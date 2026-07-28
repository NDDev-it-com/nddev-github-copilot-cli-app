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
python3 cli-tools/nddev_github_copilot_cli.py list
python3 cli-tools/nddev_github_copilot_cli.py plan --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py install --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py switch --profile safe --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py migrate --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py restore --backup 0 --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py remove --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-plan --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-status --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-install --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-update --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py install-builder --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py builder-status --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py launch --target /absolute/copilot-home --workspace /absolute/project -- --help
```

`nddev-builder` is the only content setup. `full-auto` is the default
permission profile, and `safe` is available through `--profile safe`.
`install` only accepts an absent or unmanaged eligible target, `switch` only
accepts a current clean managed target, and `migrate` only accepts an actual
legacy-managed target.
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

The plugin ships a routed Agent Skills toolkit for Copilot CLI configuration,
profiles, permissions, sandbox, custom agents, skills, instructions, plugins,
marketplace, hooks, MCP, installation lifecycle, and release-readiness review.

## Safety Model

- Explicit absolute `--target` is required for every target operation.
- Target symlinks and managed symlinks/hard links fail closed.
- Existing managed targets must be current-user-owned private directories.
- New targets are created and checked fail-closed before mutation.
- Unsafe ancestors, symlinked lifecycle state, and unsafe backup pools fail
  closed while valid private targets under sticky system temp roots remain
  supported.
- Lifecycle operations use manager-owned exclusion across mutation and managed
  launch; implementation mechanics are owned by
  `cli-tools/nddev_github_copilot_cli.py` and summarized in
  `config/nddev-contract.json`.
- Backup roots remain target-bound and marker-bound.
- Managed files are written as owner-only regular files.
- Mutations snapshot managed bytes and restore them on failure.
- Restore removes every known managed path that is absent from the validated
  backup while preserving unrelated unmanaged files.
- Unmanaged files and unmanaged settings keys are preserved.
- Legacy managed state is read only for status, migrate, restore, and remove;
  launch is denied until migration succeeds.
- Launch requires a clean current managed target, current pinned software, and
  a current native builder plugin installation.
- Launch keeps lifecycle mutations denied while the child is running and keeps
  native runtime state writable. `--target` owns Copilot home/config/runtime
  state; `--workspace` or the caller cwd owns project context. Exact
  environment, path, and handoff mechanics are owned by the manager and public
  contract.
- Launch is a write-protected verified-path handoff, not a portable fd
  execution guarantee. Without a sandbox it does not claim resistance to
  deliberate same-UID tampering outside the documented boundary.
- Launch rejects caller flags that override manager-owned profile, permissions,
  sandbox, remote, worktree, model, agent, MCP, or tool scope.

## Public Validation

```bash
python3 -m py_compile cli-tools/nddev_github_copilot_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_github_copilot_cli.py list --json
git diff --check
```

The public validator parses the public contracts and non-live manager surfaces,
checks release/archive closure, and runs public adversarial smokes without
network or live Copilot state. The exact validator inventory is owned by
`cli-tools/validate_public_contracts.py`.
