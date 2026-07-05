# Bundled schematron stylesheets

Compiled XSLT 2.0 stylesheets run via saxonche (`etransactions.schematron`).

| File | Rules | Source |
|---|---|---|
| `Factur-X_1.07.2_BASIC.xsl` / `Factur-X_1.07.2_EXTENDED.xsl` | Factur-X 1.07.2 (CII) | FNFE-MPE Factur-X package |
| `EN16931-CII-validation-preprocessed.xsl` | EN16931 (CII) | ConnectingEurope eInvoicing-EN16931 |
| `XRechnung-CII-validation.xsl` | XRechnung CIUS (CII) | KoSIT xrechnung-schematron |
| `EN16931-UBL-validation.xslt` | EN16931 core (UBL) | CEN/TC434, compiled build from phax/phive-rules (openpeppol 2026.5) |
| `PEPPOL-EN16931-UBL.xslt` | Peppol BIS Billing 3.0 CIUS (UBL) | OpenPeppol peppol-bis-invoice-3, compiled build from phax/phive-rules (openpeppol 2026.5) |

The EN16931 schematrons are licensed EUPL v1.2 (CEF/ConnectingEurope);
the Peppol BIS rules are © OpenPeppol AISBL. The French CTC-FR (cpro.gouv.fr)
schematron is not bundled — CTC-FR documents are validated against the
EXTENDED sheet locally, and the accredited platform applies the French CDV
rules on submit.
