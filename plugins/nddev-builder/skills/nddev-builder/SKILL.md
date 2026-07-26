---
name: nddev-builder
description: Build and review native GitHub Copilot CLI configuration, plugin, skill, agent, and hook artifacts for NDDev setup modules.
---

# NDDev Builder for GitHub Copilot CLI

Use current GitHub Copilot CLI surfaces only:

- user settings in `settings.json`;
- user permissions in `permissions-config.json`;
- user instructions in `copilot-instructions.md`;
- skills under `skills/`;
- agents under `agents/`;
- hooks under `hooks/`;
- native plugins with `plugin.json`, `skills`, `agents`, and `hooks.json`.

Do not assume any marketplace install flow unless a current official GitHub
Copilot CLI source proves it. For this module, the marketplace field is null
and the builder is projected as local native files.

Keep auth and provider credentials outside generated artifacts.
