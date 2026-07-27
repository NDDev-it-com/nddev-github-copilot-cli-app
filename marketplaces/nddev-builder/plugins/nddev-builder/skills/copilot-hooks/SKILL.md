---
name: copilot-hooks
description: Create or review GitHub Copilot CLI hook configuration for the NDDev builder plugin using the documented hooks version 1 schema.
---

# Copilot Hooks

Use this skill for hook configuration and hook review.

## Native Surface

Hooks use JSON with top-level `version: 1` and `hooks` keyed by event name.
Command, HTTP, and prompt hook entries have event-specific support and failure
semantics. User hooks live under `COPILOT_HOME/hooks/`, repository hooks under
`.github/hooks/`, inline hooks under settings files, and plugin hooks in a
plugin's `hooks.json` or `hooks/hooks.json`.

See
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md)
for the path summary and official-source pointers.

## Builder Practice

- Keep plugin hooks deterministic and low impact.
- Prefer `command` hooks that do not depend on repository-relative private
  paths.
- Do not send secrets, transcripts, or live credentials to HTTP hooks.
- Do not rely on Windows-only PowerShell behavior; Windows is outside this
  module's support boundary.

## Validation Workflow

Run `python3 cli-tools/validate_public_contracts.py`; it validates hook schema
version and plugin manifest wiring. Native execution proof belongs in an
isolated target, not in live `~/.copilot`.
