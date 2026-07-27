# Changelog

All notable changes to `nddev-github-copilot-cli-app` are documented here.

## [0.2.0] - 2026-07-27

- Replaced setup variants with one `nddev-builder` content setup and
  orthogonal `full-auto` and `safe` permission profiles.
- Switched builder provisioning to a native local Copilot CLI marketplace and
  plugin install flow.
- Added a routed public Agent Skills builder toolkit covering every supported
  Copilot CLI native surface.
- Removed Windows, linux-musl, non-Ubuntu Linux, middle permission profiles,
  manual runtime-owned builder projections, exception language, and
  undocumented memory toggles from the public contract.
- Hardened target, lock, backup, launch environment, and builder install
  isolation checks, with public adversarial non-live smokes.

## [0.1.0] - 2026-07-26

- Initial target-explicit GitHub Copilot CLI setup manager.
- Initial setup variants for the current CLI launch flags, settings,
  permissions, and instructions surfaces.
- Default-on local native `nddev-builder` plugin files with skills, agents,
  and hooks.
- Public contract validator and shared public CI callers.
