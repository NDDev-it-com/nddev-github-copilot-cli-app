---
name: copilot-configuration-profile
description: Create or review GitHub Copilot CLI settings.json/profile artifacts for this NDDev module while preserving the setup/profile separation and code-owned volatile contracts.
---

# Copilot Configuration And Profiles

Use this skill when changing `settings.json`, profile metadata, or the
orthogonal setup/profile model.

## Native Surface

Read
[`../../references/native-paths-and-schemas.md`](../../references/native-paths-and-schemas.md)
for the current native user, repository, and plugin paths. User settings are
JSONC in `settings.json` under `COPILOT_HOME`; this module writes regular JSON
for deterministic validation.

## Module Surface

- Content setup: `setups/nddev-builder/`.
- Permission profiles: `profiles/full-auto/` and `profiles/safe/`.
- The manager combines setup files and profile files at install, switch, and
  migrate time.
- Existing unmanaged keys in a managed target's `settings.json` are preserved
  unless their key is owned by the manager.

Do not add another setup or profile unless the public contract is updated in
the same module commit and the code validator is updated to enforce it. Do not
add a middle permission profile without an exact native Copilot CLI meaning.

## Validation Workflow

After changes, run the public checks in
[`../../references/public-validation-workflows.md`](../../references/public-validation-workflows.md).
Use `cli-tools/nddev_github_copilot_cli.py list --json` to confirm the public
setup/profile catalog shape instead of copying catalog facts into docs.
