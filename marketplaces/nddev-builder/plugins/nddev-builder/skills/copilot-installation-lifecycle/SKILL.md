---
name: copilot-installation-lifecycle
description: Create or review target-explicit GitHub Copilot CLI installation, setup lifecycle, migration, restore, and launch behavior for the NDDev module.
---

# Copilot Installation And Lifecycle

Use this skill for software install, setup install/switch/migrate/remove,
backup/restore, builder installation, status, and launch work.

## Manager Surface

The public manager is `cli-tools/nddev_github_copilot_cli.py`.
Use its `parse_args` as the command grammar owner. Do not duplicate command
enumerations in docs except as examples.

The target must be explicit and absolute. The manager never defaults to live
`~/.copilot`, never expands `~`, and preserves unmanaged target files. Legacy
managed state may be inspected, migrated, restored, or removed, but it must not
launch.

## Native Install Boundary

Software install uses the official GitHub Copilot CLI installer and release
assets pinned by `references/copilot-cli-baseline.json`.
Do not copy the pin values into skills.

Builder install must use native `copilot plugin marketplace add` and
`copilot plugin install` inside the target-owned home/cache with stripped auth
environment and blocked ambient `gh` lookup.

## Validation Workflow

Use the public workflows in
[`../../references/public-validation-workflows.md`](../../references/public-validation-workflows.md).
Do not run live software install, CI, push, or tag from this skill.
