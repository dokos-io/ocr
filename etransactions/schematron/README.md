# Bundled schematron stylesheets

Compiled XSLT 2.0 stylesheets run via saxonche (`etransactions.schematron`).

The FNFE-MPE builds below come from the **Schematrons FR CTC v1.4.0** package
(XP Z12-012 V1.4.0, 2026-06-30).

| File | Rules | Source |
|---|---|---|
| `Factur-X_1.07.2_BASIC.xsl` | Factur-X 1.07.2 BASIC (CII) | FNFE-MPE Factur-X package (not in the reform set; unchanged) |
| `Factur-X_1.09.2_EXTENDED.xslt` (+ `Factur-X_EXTENDED_codedb.xml`) | Factur-X 1.09.2 EXTENDED (CII) | FNFE-MPE Schematrons FR CTC v1.4.0 |
| `EN16931-CII-validation.xslt` | EN16931 (CII) | FNFE-MPE Schematrons FR CTC v1.4.0 (CEN/TC434) |
| `EXTENDED-CTC-FR-CII.xslt` | EXTENDED-CTC-FR profile (CII) | FNFE-MPE Schematrons FR CTC v1.4.0 |
| `BR-FR-Flux2-Schematron-CII_WARNING.xslt` | French CTC reform rules (CII), non-blocking WARNING build | FNFE-MPE Schematrons FR CTC v1.4.0 |
| `XRechnung-CII-validation.xsl` | XRechnung CIUS (CII) | KoSIT xrechnung-schematron |
| `EN16931-UBL-validation.xslt` | EN16931 core (UBL) | FNFE-MPE Schematrons FR CTC v1.4.0 (CEN/TC434) |
| `PEPPOL-EN16931-UBL.xslt` | Peppol BIS Billing 3.0 CIUS (UBL) | OpenPeppol peppol-bis-invoice-3, compiled build from phax/phive-rules |
| `EXTENDED-CTC-FR-UBL.xslt` / `BR-FR-Flux2-Schematron-UBL_WARNING.xslt` | EXTENDED-CTC-FR profile / French reform rules (UBL) | FNFE-MPE v1.4.0 (bundled for completeness; the generator emits CTC-FR as CII, so these are currently unused) |

The EN16931 and FNFE schematrons are licensed Apache 2.0 / EUPL v1.2; the Peppol
BIS rules are © OpenPeppol AISBL. The CTC-FR profile now validates against its
dedicated `EXTENDED-CTC-FR-CII.xslt` (which natively accepts the cpro.gouv.fr
guideline). The French reform rules (`BR-FR-Flux2`) run in the non-blocking
WARNING build as a local pre-flight for the Extended / CTC-FR CII profiles; the
accredited platform remains authoritative and applies the fatal French rules on
submit.
