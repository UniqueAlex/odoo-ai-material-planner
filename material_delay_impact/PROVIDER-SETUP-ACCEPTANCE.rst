Provider setup acceptance: 19.0.1.1.0
===================================
Date: 2026-10-27

Scope
-----
Visible first-use setup, model presets/manual entry, connection/capability states,
actionable errors, native Gemini/Claude adapters and operation token accounting.
The user requested implementation and simulated verification only. No real
OpenAI, Gemini, Claude or DeepSeek request was made for this release acceptance.
Provider-billed tokens for this acceptance: 0. Synthetic fixture counters are
not real usage. DeepSeek's earlier live acceptance is historical evidence only.

Evidence
--------
* Windows: 51 focused tests, 40 passed and 11 POSIX-only tests skipped.
* Linux: the same 51 tests, 50 passed and one Windows-only test skipped.
* Tests cover native tool history/signatures, structured output, truncation,
  rejected results, error redaction, usage aggregation, encrypted storage,
  concurrent writes, scoped validation and stale-result rejection.
* Existing recommendation/manual explanation tests cover factual validation,
  unknown coverage, bounded requests and no-call behavior for covered scenarios.
* Isolated Windows Odoo 19 database upgraded successfully. Browser walkthrough
  covered first use without a key, saving, cleared secret input, consent gating,
  connection/capability state transitions, refresh, manual-model edits,
  key/network errors and normal-user guidance. Provider responses were simulated.
* RPC checks verified DeepSeek/Gemini capability flows, cached request reuse,
  administrator-only configuration and local calculation/comparison without a
  key. OpenAI/Claude setup flows were exercised in the browser with simulated
  responses. Purchase, stock, reservation and manufacturing fingerprints stayed
  unchanged through the RPC workflow.
* A narrow-window model-name truncation was corrected and the final Odoo Sass
  bundle and page were checked. Python, XML and JavaScript syntax checks passed.

Limits
------
These checks do not establish live API availability, billing, regional access,
or real-model answer quality for OpenAI, Gemini or Claude. Customers should run
connection and analysis-capability checks with their own provider account.
The capability check validates a small synthetic tool round-trip and JSON
output; it does not certify every future model answer or manual model name.
Only direct official APIs are implemented, not Azure, Vertex AI, Bedrock or
arbitrary proxy endpoints. Odoo.sh remains unvalidated.
