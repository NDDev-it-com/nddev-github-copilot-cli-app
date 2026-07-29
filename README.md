# nddev-github-copilot-cli-app

Target-explicit NDDev setup manager for GitHub Copilot CLI.

This module manages an isolated Copilot home selected with `--target`. It
never defaults to the caller's live `~/.copilot`, does not expand `~`, and does
not read or modify live authentication state.

## Runtime Baseline

Current runtime pins, install provenance, platform support, command names, and
native discovery paths are owned by `build/version.json`,
`build/manifest.json`, `config/nddev-contract.json`, and
`references/copilot-cli-baseline.json`. Use `list --json`, `status --json`,
`software-status --json`, and `builder-status --json` for machine-readable
state instead of copying current values into handwritten notes.

## Usage

```bash
python3 cli-tools/nddev_github_copilot_cli.py plan --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py install --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py update --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py switch --profile safe --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py launch --target /absolute/copilot-home -- --help
```

Run `python3 cli-tools/nddev_github_copilot_cli.py --help` for the current
command grammar. Use `list --json`, `status --json`, `software-status --json`,
and `builder-status --json` for machine-readable state.
Use `software-remove --target <absolute-target>` to remove only manager-owned
Copilot CLI software artifacts while preserving setup, auth, and unrelated
target state.

`nddev-builder` is the only content setup. `full-auto` is the default
permission profile, and `safe` is available through `--profile safe`.
`install` only accepts an absent or unmanaged eligible target, `update`
refreshes the current setup/profile selection, `switch` only accepts a current
clean managed target, and `migrate` only accepts an actual legacy-managed target.
`plan` reports `current` with no command for an already-current clean target;
actionable plans report the executable `install`, `switch`, or `migrate`
command.

## Profiles

`full-auto` is for explicitly trusted targets. `safe` is the conservative
profile. Their exact native settings, permission bundles, and launch posture are
owned by `profiles/<profile>/`, `build/manifest.json`, and
`config/nddev-contract.json`; inspect `list --json` for the current public
profile inventory.

There is no middle permission profile and no public boolean memory setting.
Copilot CLI owns runtime memory state and exposes `memory` as a permission kind.

## Native Builder

The public builder toolkit is installed through native local marketplace
support. Source and installed locations, plugin identifiers, native command
shape, and isolation mechanics are owned by `build/manifest.json`,
`config/nddev-contract.json`, `setups/nddev-builder/setup.json`, and
`cli-tools/nddev_github_copilot_cli.py`.

The plugin ships a routed Agent Skills toolkit. Its exact skill and native
surface inventory is owned by `marketplaces/nddev-builder/`.

## Safety Model

The manager requires an explicit absolute `--target`, rejects unsafe ownership,
linkage, lifecycle, and backup state, and preserves unrelated runtime-owned
files. Exact managed paths, stamp contents, backup envelopes, transaction
steps, launch overrides, environment handoff, and lock mechanics are owned by
`cli-tools/nddev_github_copilot_cli.py` and summarized in
`config/nddev-contract.json`.

Managed mutations are transactional at the public boundary: when a fallible
write path fails before completion, the manager restores the prior managed
objects, bytes, modes, mtimes, digests, or absence before surfacing the error.
Launch requires a clean current managed target plus current target-owned software and native
builder state. It does not claim resistance to deliberate same-UID tampering
outside the documented no-sandbox boundary.

## Public Validation

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_github_copilot_cli.py list --json
python3 cli-tools/nddev_github_copilot_cli.py --help
git diff --check
```

The public validator parses the public contracts and non-live manager surfaces,
checks release/archive closure, and runs public adversarial smokes without
network or live Copilot state. The exact validator inventory is owned by
`cli-tools/validate_public_contracts.py`.
