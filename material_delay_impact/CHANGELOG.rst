Changelog
=========

19.0.1.1.0 (2026-10-27)
----------------------
* Add visible first-use setup guidance and actionable, localized API error help.
* Separate saved, connection-tested and capability-tested configuration states;
  invalidate old validation after a save, model/key change or removal.
* Add model presets and an explicitly unverified manual-model option.
* Add native Gemini and Claude transports alongside existing DeepSeek/OpenAI.
  New provider support is simulated-test coverage, not live-provider acceptance.
* Meter connection/capability checks, recommendations and manual explanations,
  including known usage on failure, Claude cache tokens and Gemini thinking tokens.
* Preserve local calculations, shared reviews and existing business permissions.

19.0.1.0.2 (2026-10-21)
----------------------
* Keep material identity in AI drafting and review; reject a purchase reference used as a material name.
* Aggregate provider token usage across analysis tool, generation and repair rounds.
* Preserve known usage on failure and cached results; missing usage is unknown, not zero.
* Leave material calculations, business writes, permissions and recommendation selection unchanged.

19.0.1.0.1 (2026-10-21)
----------------------
* Use HTML entities for store-page separators to avoid encoding artifacts.
* Remove the duplicate cover and replace narrow screenshots with desktop captures.
* Show genuine DeepSeek analysis and AI-selected decision evidence using synthetic data.
* Keep business logic, permissions, calculations and provider request behavior unchanged.

19.0.1.0.0 (2026-10-20)
----------------------
* Initial store release for Odoo 19, with Windows and Linux acceptance records.
