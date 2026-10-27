Cross-provider regression acceptance
===================================

Release: 19.0.1.1.1, 2026-10-27.

Method
------
Replace only the HTTP request boundary with synthetic DeepSeek Chat Completions,
OpenAI Responses, Gemini generateContent and Claude Messages responses. Production
request adaptation, response parsing, business validation, repair limits and usage
accounting remain active. No credentials or external model requests are used.

New coverage: 12 test groups, 190 provider/scenario combinations
------------------------------------------------------------
* Purchase reference used as material in each prose field: bounded repair and
  usage for all rounds. Legitimate purchase references remain accepted.
* Internal identifiers/field names, incorrect local dates, invented numeric facts,
  missing coverage and unsupported evidence references: reject repeated bad drafts.
* Known versus unknown coverage, final shortage remedies, overlapping shortages,
  simulated versus recorded allocations and wrong narrative language.
* Evidence completion prohibits further tool calls on all four providers.
* Automatic candidates: reject invented/reordered plans, duplicate/unknown facts,
  arbitrary model prose and contextually invalid verification targets.
* Automatic narrative rendering matches across providers in English, Chinese and
  French; empty verification targets are omitted and inputs remain unchanged.
* Dormant manual interpretation preserves exact facts and unknown coverage.
  Its existing INTERPRETATION_ENABLED=False gate is NOT changed by this release.
* Truncation, refusal and invalid JSON are rejected in all three AI workflows.
* Missing usage stays unknown; malformed native content retains known usage;
  invalid cache/thinking counts cannot silently become an understated total.

Defects reproduced and corrected
-------------------------------
OpenAI/Gemini/Claude previously could continue tools after all evidence was read;
they now stop with a format error, as DeepSeek already did. Malformed native
Gemini/Claude content previously became a generic interruption before metering;
it now produces a rejected envelope with valid usage retained. Invalid Claude
cache counts previously could leave a non-cache subtotal looking complete; the
total is now unknown while other known rounds remain available.

Limits
------
These are protocol and historical-regression simulations, not live provider
acceptance or proof of arbitrary natural-language correctness. Shared review
progress, handoff copy, permissions, business writes and deterministic calculation
code are unchanged. No UI/installation/stress campaigns were repeated. Existing
affected AI tests and the repository's automatic CI are the regression checks.
External model API requests: 0. External model API tokens: 0.
