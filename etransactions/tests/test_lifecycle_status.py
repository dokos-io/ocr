# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee import lifecycle_status as ls


class TestLifecycleStatus(UnitTestCase):
	"""Pure-logic tests for the canonical lifecycle status registry and mappings.

	No database access — safe and fast to run in isolation.
	"""

	def test_every_status_has_required_fields(self):
		for status, vals in ls.STATUSES.items():
			self.assertIn(status, ls.LABELS, f"missing label for {status}")
			self.assertTrue(vals.get("mdt105"), f"missing MDT-105 for {status}")

	def test_superpdp_roundtrip(self):
		# Only statuses with a SuperPDP code round-trip through the fr: codes.
		for status, vals in ls.STATUSES.items():
			code = vals.get("superpdp")
			if not code:
				continue
			self.assertEqual(ls.to_superpdp_code(status), code)
			self.assertEqual(ls.from_superpdp_code(code), status)

	def test_unsupported_superpdp_status_raises(self):
		# "refused" has no SuperPDP code yet and must raise rather than guess.
		self.assertIsNone(ls.STATUSES["refused"]["superpdp"])
		with self.assertRaises(Exception):
			ls.to_superpdp_code("refused")

	def test_cdar_roundtrip(self):
		for status in ls.STATUSES:
			mdt105, _mdt88 = ls.to_cdar_codes(status)
			self.assertEqual(ls.from_cdar_code(mdt105), status)

	def test_mdt105_codes_unique(self):
		codes = [v["mdt105"] for v in ls.STATUSES.values()]
		self.assertEqual(len(codes), len(set(codes)), "MDT-105 codes must be unique")

	def test_manual_statuses_partitioned_by_side(self):
		purchase = set(ls.manual_statuses("purchase"))
		sale = set(ls.manual_statuses("sale"))
		self.assertIn("refused", purchase)
		self.assertIn("payment_received", sale)
		self.assertFalse(purchase & sale, "a status cannot be manual for both sides")

	def test_warning_statuses(self):
		self.assertTrue(ls.is_warning("refused"))
		self.assertTrue(ls.is_warning("dispute"))
		self.assertFalse(ls.is_warning("approved"))


class TestLifecycleTransitions(UnitTestCase):
	"""The state machine that keeps the reported timeline coherent.

	Pure logic: the state dict is handed in, so no database is involved.
	"""

	def _state(self, purchase=None, sale=None, refused=False, cancelled=False):
		return {
			"purchase": purchase,
			"sale": sale,
			"purchase_at": None,
			"sale_at": None,
			"refused": refused,
			"cancelled": cancelled,
			"latest": purchase or sale,
			"latest_at": None,
		}

	def _allowed(self, status, **state):
		self.assertIsNone(
			ls.transition_error(self._state(**state), status),
			f"{status} should be allowed from {state}",
		)

	def _blocked(self, status, **state):
		error = ls.transition_error(self._state(**state), status)
		self.assertTrue(error, f"{status} should be blocked from {state}")
		return error

	# ------------------------------------------------------------------
	# Graph integrity
	# ------------------------------------------------------------------
	def test_graph_only_references_known_statuses(self):
		for status, successors in ls.TRANSITIONS.items():
			self.assertIn(status, ls.STATUSES, f"unknown status {status} in TRANSITIONS")
			for successor in successors:
				self.assertIn(successor, ls.STATUSES, f"unknown successor {successor} of {status}")

	def test_every_status_has_a_transition_row(self):
		self.assertEqual(set(ls.TRANSITIONS), set(ls.STATUSES))

	def test_terminal_statuses_have_no_successor(self):
		for status in ls.TERMINAL:
			self.assertFalse(ls.TRANSITIONS[status], f"{status} must be a sink")

	def test_transitions_never_cross_axes(self):
		# The two axes advance independently; a purchase status can only be followed by
		# another purchase status, and likewise for the sale side.
		for status, successors in ls.TRANSITIONS.items():
			side = ls.side_of(status)
			if not side:
				continue
			for successor in successors:
				self.assertEqual(
					ls.side_of(successor), side, f"{status} -> {successor} crosses axes"
				)

	def test_side_of_covers_every_status(self):
		for status in ls.STATUSES:
			side = ls.side_of(status)
			self.assertIn(side, ("purchase", "sale", None))
		self.assertIsNone(ls.side_of("cancelled"), "cancellation belongs to no axis")

	# ------------------------------------------------------------------
	# Case 1 — contradictory events
	# ------------------------------------------------------------------
	def test_nothing_can_be_reported_after_a_refusal(self):
		error = self._blocked("approved", purchase="refused", refused=True)
		self.assertIn("refus", error.lower())
		for status in ("in_hand", "dispute", "payment_sent", "refused"):
			self._blocked(status, purchase="refused", refused=True)

	def test_a_refused_invoice_can_still_be_cancelled(self):
		# Otherwise the guided cancellation flow would leave the invoice stuck.
		self._allowed("cancelled", purchase="refused", refused=True)

	def test_nothing_can_be_reported_after_a_cancellation(self):
		for status in ("approved", "dispute", "payment_sent", "cancelled"):
			self._blocked(status, cancelled=True)

	def test_a_refusal_on_one_axis_freezes_the_other(self):
		# A buyer refusing an invoice we issued must stop us reporting on the sale side.
		self._blocked("payment_received", purchase="refused", refused=True)

	# ------------------------------------------------------------------
	# Case 2 — duplicated events
	# ------------------------------------------------------------------
	def test_a_one_shot_status_cannot_be_reported_twice(self):
		for status in ("in_hand", "approved"):
			self._blocked(status, purchase=status)
		self._blocked("completed", sale="completed")

	def test_receipt_cannot_be_reported_again_later(self):
		self._blocked("in_hand", purchase="approved")

	def test_repeatable_statuses_may_be_reported_again(self):
		# Partial payments and successive disputes each carry new data.
		self._allowed("payment_sent", purchase="payment_sent")
		self._allowed("payment_received", sale="payment_received")
		self._allowed("dispute", purchase="dispute")
		self._allowed("partially_approved", purchase="partially_approved")
		self._allowed("suspended", purchase="suspended")

	# ------------------------------------------------------------------
	# Deliberately permissive edges
	# ------------------------------------------------------------------
	def test_an_invoice_can_be_refused_after_being_approved(self):
		# auto_send_approved reports 'Approved' on submission, often before anyone has
		# checked the invoice — the user must keep a way out.
		self._allowed("refused", purchase="approved")
		self._allowed("dispute", purchase="approved")

	def test_a_dispute_can_be_resolved_either_way(self):
		self._allowed("approved", purchase="dispute")
		self._allowed("refused", purchase="dispute")

	def test_a_paid_invoice_cannot_be_refused(self):
		self._blocked("refused", purchase="payment_sent")
		self._allowed("dispute", purchase="payment_sent")

	def test_receipt_is_not_a_prerequisite(self):
		# Nothing forces 'In Hand' to be reported first.
		for status in ls.manual_statuses("purchase"):
			self._allowed(status)

	def test_the_two_axes_are_independent(self):
		self._allowed("approved", sale="completed")
		self._allowed("completed", purchase="approved")

	def test_an_unknown_status_is_rejected(self):
		self._blocked("teleported")

	# ------------------------------------------------------------------
	# allowed_next
	# ------------------------------------------------------------------
	def test_allowed_next_on_an_empty_axis_offers_the_whole_side(self):
		self.assertEqual(ls.allowed_next(None, "purchase"), set(ls.manual_statuses("purchase")))
		self.assertEqual(ls.allowed_next(None, "sale"), set(ls.manual_statuses("sale")))

	def test_allowed_next_includes_repeatable_statuses(self):
		self.assertIn("payment_sent", ls.allowed_next("payment_sent", "purchase"))
		self.assertNotIn("approved", ls.allowed_next("approved", "purchase"))

	def test_allowed_next_is_empty_after_a_refusal(self):
		self.assertEqual(ls.allowed_next("refused", "purchase"), set())


class TestSupportedLifecycleStatuses(UnitTestCase):
	"""The Report Status buttons: what the platform carries AND the state allows."""

	def _call(self, platform_type="Esalink", einvoice_type="Incoming", **state):
		from types import SimpleNamespace
		from unittest.mock import patch

		from etransactions.etransactions.doctype.einvoice.einvoice import (
			get_supported_lifecycle_statuses,
		)

		doc = SimpleNamespace(einvoice_type=einvoice_type, company="_Test Company")
		doc.check_permission = lambda perm: None
		platform = SimpleNamespace(platform_type=platform_type) if platform_type else None
		current = {
			"purchase": None, "sale": None, "purchase_at": None, "sale_at": None,
			"refused": False, "cancelled": False, "latest": None, "latest_at": None,
		}
		current.update(state)
		with (
			patch("frappe.get_doc", return_value=doc),
			patch(
				"etransactions.plateforme_agreee.session.get_platform_for_company",
				return_value=platform,
			),
			patch(
				"etransactions.etransactions.doctype.einvoice_event.einvoice_event.current_lifecycle_state",
				return_value=current,
			),
		):
			return get_supported_lifecycle_statuses("EINV-1")

	def _offered(self, **kwargs):
		return {s["status"] for s in self._call(**kwargs)["statuses"]}

	def test_superpdp_filters_to_fr_codes(self):
		offered = self._offered(platform_type="SuperPDP")
		# Statuses without a native fr: code must not be offered on SuperPDP.
		self.assertNotIn("refused", offered)
		self.assertNotIn("suspended", offered)
		self.assertIn("dispute", offered)
		self.assertEqual(
			offered,
			{
				k
				for k in ls.manual_statuses("purchase")
				if ls.STATUSES[k].get("superpdp")
			},
		)

	def test_cdar_platforms_carry_every_status_of_the_side(self):
		for platform_type in ("Esalink", "Custom", None):
			self.assertEqual(
				self._offered(platform_type=platform_type), set(ls.manual_statuses("purchase"))
			)

	def test_only_our_own_side_is_offered(self):
		# We report the buyer's statuses on an invoice we received, the seller's on one
		# we issued — never the counterparty's.
		self.assertEqual(
			self._offered(einvoice_type="Outgoing"), set(ls.manual_statuses("sale"))
		)

	def test_an_already_reported_status_is_no_longer_offered(self):
		offered = self._offered(purchase="in_hand")
		self.assertNotIn("in_hand", offered)
		self.assertIn("approved", offered)

	def test_a_refused_invoice_offers_nothing_and_explains_why(self):
		result = self._call(purchase="refused", refused=True)
		self.assertEqual(result["statuses"], [])
		self.assertTrue(result["blocked_reason"])

	def test_button_metadata_comes_from_the_server(self):
		# The client no longer keeps its own copy of the registry.
		by_status = {s["status"]: s for s in self._call()["statuses"]}
		self.assertTrue(by_status["refused"]["confirm"])
		self.assertTrue(by_status["refused"]["reason"])
		self.assertTrue(by_status["refused"]["confirm_message"])
		self.assertFalse(by_status["approved"]["reason"])
		self.assertFalse(by_status["approved"]["confirm"])
		self.assertEqual(by_status["approved"]["label"], ls.label("approved"))

	def test_current_state_is_reported_for_the_ui(self):
		state = self._call(purchase="approved", sale="completed")["state"]
		self.assertEqual(state["purchase"]["status"], "approved")
		self.assertEqual(state["purchase"]["label"], ls.label("approved"))
		self.assertEqual(state["sale"]["status"], "completed")


class TestReasonCodes(UnitTestCase):
	"""The MDT-113 reason codes and the wording served to the picker.

	Pure logic: the code lists come from the CDAR schematron (BR-FR-CDV-CL-09) and the
	wording is keyed by code, so these tests are mostly drift guards between the two.
	"""

	def _all_codes(self) -> set[str]:
		return {code for codes in ls.REASON_CODES.values() for code in codes}

	def test_every_reason_code_has_a_label(self):
		missing = self._all_codes() - set(ls.REASON_LABELS)
		self.assertFalse(missing, f"reason codes without a label: {sorted(missing)}")

	def test_every_reason_code_has_a_description(self):
		missing = self._all_codes() - set(ls.REASON_DESCRIPTIONS)
		self.assertFalse(missing, f"reason codes without a description: {sorted(missing)}")

	def test_no_orphan_reason_wording(self):
		# Wording for a code no status accepts is dead weight the schematron will never
		# validate — most likely a typo in one of the REASON_CODES lists.
		codes = self._all_codes()
		self.assertFalse(set(ls.REASON_LABELS) - codes)
		self.assertFalse(set(ls.REASON_DESCRIPTIONS) - codes)

	def test_reason_code_options_preserve_the_schematron_list(self):
		# Membership and order stay derived from REASON_CODES: the picker can never offer
		# a code the platform would reject.
		for status, codes in ls.REASON_CODES.items():
			self.assertEqual([o["value"] for o in ls.reason_code_options(status)], codes)

	def test_reason_code_options_are_plain_strings(self):
		# The registry holds lazy translations, which cannot be serialised to JSON and
		# raise on __eq__. They must be resolved before crossing the whitelisted boundary.
		for status in ls.REASON_CODES:
			for option in ls.reason_code_options(status):
				self.assertIs(type(option["label"]), str)
				self.assertIs(type(option["description"]), str)

	def test_labels_and_confirm_messages_are_resolved_too(self):
		for status in ls.STATUSES:
			self.assertIs(type(ls.label(status)), str)
		self.assertIs(type(ls.confirm_message("refused")), str)
		self.assertIsNone(ls.confirm_message("approved"))

	def test_a_status_without_reason_codes_offers_no_options(self):
		self.assertEqual(ls.reason_code_options("approved"), [])
		self.assertEqual(ls.reason_codes("approved"), [])
		self.assertFalse(ls.reason_required("approved"))

	def test_every_status_requiring_a_reason_has_codes_for_it(self):
		for status, vals in ls.STATUSES.items():
			if vals.get("detail_required"):
				self.assertTrue(ls.reason_codes(status), f"{status} requires a reason but has no codes")

	def test_an_unknown_code_degrades_to_itself(self):
		self.assertEqual(ls.reason_label("NOT_A_CODE"), "NOT_A_CODE")
		self.assertEqual(ls.reason_description("NOT_A_CODE"), "")

	def test_all_reason_labels_covers_every_code(self):
		labels = ls.all_reason_labels()
		self.assertEqual(set(labels), set(ls.REASON_LABELS))
		self.assertTrue(all(type(v) is str for v in labels.values()))
