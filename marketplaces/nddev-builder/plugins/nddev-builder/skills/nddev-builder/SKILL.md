---
name: nddev-builder
description: Route GitHub Copilot CLI setup-module authoring and review to focused NDDev builder skills for native configuration, permissions, agents, skills, plugins, hooks, MCP, lifecycle, and validation work.
---

# NDDev Builder Router

Use this entry skill for GitHub Copilot CLI setup-module work. Load only the
focused skill needed for the current surface, then load its referenced files
only when the task needs the extra detail.

## Routing

- Profile or settings work: use `copilot-configuration-profile`.
- Permission, approval, sandbox, and launch posture work: use
  `copilot-permissions-sandbox`.
- Custom agent or subagent work: use `copilot-agents-subagents`.
- Agent Skill or instruction work: use `copilot-skills-instructions`.
- Native plugin and local marketplace work: use `copilot-plugins-marketplace`.
- Hook work: use `copilot-hooks`.
- MCP work: use `copilot-mcp`.
- Installer, target lifecycle, migration, rollback, and launch work: use
  `copilot-installation-lifecycle`.
- Creator, checker, and release-readiness review: use
  `copilot-creator-checker-release`.

## Ground Rules

Keep public module changes inside this repository. Do not add private tests,
fixtures, memories, evidence bundles, root harness instructions, credentials,
runtime logs, generated caches, unsupported profiles, exception language,
unsupported platforms, or undocumented Copilot CLI switches.

For volatile values, point to the code owners:

- Manager behavior and command grammar:
  `cli-tools/nddev_github_copilot_cli.py`.
- Public contract and lifecycle surface:
  `config/nddev-contract.json`.
- Build metadata:
  `build/version.json`.
- Release and artifact baseline:
  `references/copilot-cli-baseline.json`.

For native path and schema reminders, read
[`references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md).
For executable public checks, read
[`references/public-validation-workflows.md`](../../references/public-validation-workflows.md).
