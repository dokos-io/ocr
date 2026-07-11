"""Test-only redirection of the PA clients to a Microcks mock server.

The three Plateforme Agréée clients (SuperPDP, AFNOR/Custom, Esalink) and the
Esalink partner Customer API all build their request URLs as ``base_url + path``.
For end-to-end integration tests we run a Microcks instance seeded with the mock
OpenAPI specs under ``etransactions/components/mocks`` and point every client at
it by returning a Microcks base URL here.

Microcks serves a REST mock at ``{microcks_url}/rest/{Title}/{Version}`` and
dispatches on the operation path from the spec — so the base URL below plus the
path each client appends (``/oauth2/token``, ``/v1/flows``, ``/v1/customerPA`` …)
must resolve to a mocked operation. The ``Title`` (spaces → ``+``) and ``Version``
values here therefore have to match ``info.title`` / ``info.version`` in the
corresponding mock spec.

This module is inert unless ``microcks_url`` is set in ``site_config`` (only the
test site / CI set it), so production always talks to the real platform URLs.
"""

import frappe

# service kind → "{Title}/{Version}" segment of the Microcks mock URL.
# Keep these in lockstep with info.title/info.version in components/mocks/*.yaml.
_MICROCKS_SERVICES = {
	"SuperPDP": "SuperPDP+PA+API/1.0.0",
	"Custom": "AFNOR+PA+API/1.0.0",
	"Esalink": "Esalink+PA+API/1.0.0",
	"EsalinkPartner": "Esalink+Customer+API/1.0.0",
}


def microcks_base_url(kind: str) -> str | None:
	"""Base URL of the Microcks mock for a PA service ``kind``, or ``None``.

	Returns a URL only when ``microcks_url`` is configured in ``site_config``;
	otherwise ``None`` so callers fall back to the real platform base URL.
	``kind`` is one of the keys of :data:`_MICROCKS_SERVICES`.
	"""
	root = frappe.conf.get("microcks_url")
	if not root:
		return None
	service = _MICROCKS_SERVICES.get(kind)
	if not service:
		return None
	return f"{root.rstrip('/')}/rest/{service}"
