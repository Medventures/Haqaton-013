# Targeted implementation references

Controller fetched official OpenAI Structured Outputs supported schemas on 2026-09-30:
https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas
Use a root object, required properties and additionalProperties:false; optional values nullable. The SDK structured parser handles schema conversion; server code still validates quote provenance, IDs and populated paths. Do not change configured model or API credentials. Prefer mocked transport for tests.

Official PDF references fetched:
https://docs.reportlab.com/reportlab/userguide/ch3_fonts/
https://docs.reportlab.com/reportlab/userguide/ch5_platypus/
Local bundled font source: /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf and DejaVuSans-Bold.ttf; distribution license at /usr/share/doc/fonts-dejavu-core/copyright. Tools pdftoppm and nginx are installed. No Docker daemon currently available.

Disposable PostgreSQL16 server: Unix socket /tmp/medhub-p0-postgres.BJdoUn, port55432, user mephirious. Requires escalated socket access; no TCP listener. Database medhub_p0_task1_20260930 already migrated in Task1 tests; use a new dedicated DB for destructive round trips. Main owns cleanup.
