---
name: copilot-plugins-marketplace
description: Create or review native GitHub Copilot CLI plugin and marketplace artifacts, including isolated local marketplace installation for the NDDev builder plugin.
---

# Copilot Plugins And Marketplace

Use this skill for `marketplace.json`, `plugin.json`, plugin component paths,
and native installation behavior.

## Native Surface

Read
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md)
for the official marketplace and plugin manifest locations and fields. Local
marketplaces are registered with `copilot plugin marketplace add SOURCE`, and
marketplace plugins install as `plugin@marketplace`.

## Module Contract

- Public source root: `marketplaces/nddev-builder/`.
- Marketplace manifest:
  `marketplaces/nddev-builder/.github/plugin/marketplace.json`.
- Plugin source:
  `marketplaces/nddev-builder/plugins/nddev-builder/`.
- Installed target cache:
  `COPILOT_HOME/installed-plugins/nddev-builder/nddev-builder/`.
- Installation must run target-owned `bin/copilot` with isolated
  `COPILOT_HOME`, isolated `COPILOT_CACHE_HOME`, stripped auth env, and blocked
  ambient `gh` fallback.

Do not manually copy plugin files into runtime-owned installed plugin caches.
Do not add a fake marketplace or unsupported schema fields.

## Validation Workflow

Use `builder-status` to compare the installed native plugin cache with the
public source. Use `install-builder` only against an isolated target that has
the pinned target-owned Copilot CLI installed.
