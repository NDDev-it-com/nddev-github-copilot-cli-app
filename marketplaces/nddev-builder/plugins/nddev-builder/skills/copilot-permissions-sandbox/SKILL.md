---
name: copilot-permissions-sandbox
description: Create or review GitHub Copilot CLI approval, permissions-config.json, sandbox, and managed launch posture for NDDev full-auto and safe profiles.
---

# Copilot Permissions And Sandbox

Use this skill when changing approval prompts, tool/path/URL permissions,
sandbox settings, or launch arguments.

## Native Surface

Read
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md)
for the official settings and permissions surfaces. The setting
`permissions.disableBypassPermissionsMode` is the documented deny-bypass
control. `--allow-all` only combines the documented tool, path, and URL
allow-all approvals; it is not the whole runtime posture.

## Module Contract

- `full-auto` is the default trusted-target profile. Its exact setting bundle
  and launch bundle are code-owned by `profiles/full-auto/` and the validator.
- `safe` is the conservative deny-bypass plus sandbox profile. It must not add
  allow-all flags.
- User launch args that override managed permissions, model, agent, MCP,
  worktree, remote, sandbox, or tool scope are rejected by the launcher.
- Do not invent a boolean memory setting. Copilot owns runtime memory and the
  documented permission kind `memory`.

## Validation Workflow

Run the public validator and an isolated target lifecycle smoke from
[`../../references/public-validation-workflows.md`](../../references/public-validation-workflows.md).
Treat a drift or unsupported-key failure as a contract bug.
