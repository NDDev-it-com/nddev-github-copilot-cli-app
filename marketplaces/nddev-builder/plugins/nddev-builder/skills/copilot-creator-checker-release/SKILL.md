---
name: copilot-creator-checker-release
description: Run a creator/checker/release-readiness pass for public GitHub Copilot CLI setup-module artifacts before committing or publishing.
---

# Copilot Creator, Checker, And Release Review

Use this skill before committing public setup-module changes or preparing a
release.

## Creator Pass

- Identify the native surface first: profile, permissions, agent, skill,
  plugin, marketplace, hook, MCP, installer, or lifecycle.
- Use the focused `copilot-*` skill for that surface.
- Keep every public artifact English, deterministic, and independently usable.
- Point volatile values to code-owned files instead of copying them.

## Checker Pass

- Confirm no private validation, fixtures, memories, logs, caches, or evidence
  files are present in the public module.
- Confirm no unsupported platform, middle profile, exception text, fake memory
  setting, or manual runtime-owned plugin projection is introduced.
- Confirm every relative markdown link from builder skills and references
  resolves inside the plugin.
- Confirm launch and install behavior keep target ownership, rollback, bounded
  reads, secret isolation, and fail-closed handling.

## Release Readiness

Run the public checks listed in
[`../../references/public-validation-workflows.md`](../../references/public-validation-workflows.md).
Root-private validation, registry pinning, evidence generation, CI, push, and
tags are outside this public module skill.
