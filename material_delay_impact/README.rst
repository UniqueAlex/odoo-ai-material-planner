AI Material Planner
===================
Version 19.0.1.1.0. Free material-delay and allocation decision support for Odoo 19.
Technical module name: material_delay_impact (unchanged for upgrades).
Install through normal Odoo Apps from a configured custom add-ons directory.
Dependencies: purchase_stock, mrp, web; see requirements.txt for Python dependencies.
Verified configurations: native Windows 11 workers=0; Ubuntu 24.04 / official Odoo 19
Docker / PostgreSQL 16 with two HTTP workers and persistent shared storage.
Odoo.sh has not been validated. Odoo Online is unsupported.
No Enterprise-specific integration or other Odoo major version is certified.
Customer-owned AI is optional; provider charges are separate.
Direct provider integrations: DeepSeek, OpenAI Responses, Google Gemini API,
and Anthropic Claude Messages. This release's Gemini/Claude adapters and OpenAI
paths are covered by simulated protocol tests, not new live-provider acceptance.
DeepSeek has prior live acceptance. Preset models are starting configurations,
not a guarantee of account/region availability. Azure, Vertex AI, Bedrock and
arbitrary compatible proxy URLs are not included.
First-use guidance separates saved settings, connection checks and synthetic
analysis-capability verification. Saving changes clears old verification state.
Read static/description/installation.html, privacy.html and quick-start.html.
Support: aa7266901@gmail.com. License: LGPL-3; see LICENSE and COPYING.
