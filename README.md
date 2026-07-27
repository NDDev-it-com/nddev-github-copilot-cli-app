# nddev-github-copilot-cli-app

Target-explicit NDDev setup manager for GitHub Copilot CLI.

This module manages an isolated Copilot home selected with `--target`. It
never defaults to the caller's live `~/.copilot`, does not expand `~`, and does
not read or modify live authentication state.

## Runtime Baseline

- Command: `copilot`
- Tested release: `github/copilot-cli` `v1.0.75`
- Installer channel: `https://gh.io/copilot-install`
- Config root: `COPILOT_HOME`
- Cache root: `COPILOT_CACHE_HOME`
- Supported by this module: macOS and Ubuntu 26.04
- Unsupported by this module: Windows, linux-musl, and non-Ubuntu Linux

The immutable installer, checksum, and release asset baseline is owned by
`references/copilot-cli-baseline.json`; do not copy those pins into skills or
handwritten workflow notes.

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
python3 cli-tools/nddev_github_copilot_cli.py launch --target /absolute/copilot-home -- --help
```

`nddev-builder` is the only content setup. `full-auto` is the default
permission profile, and `safe` is available through `--profile safe`.
`install` only accepts an absent or unmanaged eligible target, `switch` only
accepts a current clean managed target, and `migrate` only accepts an actual
legacy-managed target.

## Profiles

`full-auto` is for explicitly trusted targets. The manager-owned launch posture
is stored in `profiles/full-auto/profile.json`; the profile settings live in
`profiles/full-auto/settings.json`. The settings disable ask-user prompts,
remote sessions, remote export, auto-update, plaintext token storage, sandbox
credential injection, and keychain access, while keeping tool search and
autopilot behavior enabled as declared by the profile. It intentionally does
not set `permissions.disableBypassPermissionsMode`.

`safe` keeps remote sessions and remote export off, enables the documented
sandbox controls, disables sandbox bypass, disables sandbox git/gh credential
injection, disables local-network sandbox access, and sets
`permissions.disableBypassPermissionsMode` to `disable`. It does not use
allow-all launch flags.

There is no middle permission profile and no public boolean memory setting.
Copilot CLI owns runtime memory state and exposes `memory` as a permission kind.

## Native Builder

The public builder toolkit is a native local marketplace plugin:

- Marketplace source: `marketplaces/nddev-builder`
- Marketplace manifest: `marketplaces/nddev-builder/.github/plugin/marketplace.json`
- Plugin source: `marketplaces/nddev-builder/plugins/nddev-builder`
- Plugin spec: `nddev-builder@nddev-builder`
- Installed cache: `COPILOT_HOME/installed-plugins/nddev-builder/nddev-builder`

`install-builder` runs target-owned `bin/copilot` with isolated `COPILOT_HOME`
and `COPILOT_CACHE_HOME`, stripped authentication environment variables,
`COPILOT_OFFLINE=true`, a deterministic system `PATH`, and a target-owned `gh`
blocker before invoking native `copilot plugin marketplace add` and
`copilot plugin install`.

The plugin ships a routed Agent Skills toolkit for Copilot CLI configuration,
profiles, permissions, sandbox, custom agents, skills, instructions, plugins,
marketplace, hooks, MCP, installation lifecycle, and release-readiness review.

## Safety Model

- Explicit absolute `--target` is required for every target operation.
- Target symlinks and managed symlinks/hard links fail closed.
- Existing managed targets must be current-user-owned private directories.
- New target parents are created with mode `0700` and checked before mutation.
- Group/world-writable ancestors are rejected unless they are sticky, preserving
  valid private targets under `/tmp`.
- The lifecycle lock is target-internal; missing target creation uses a short
  bootstrap lock under a validated private parent.
- Backup roots remain target-bound sibling paths under a validated private
  parent; precreated symlinks and unsafe pools fail closed.
- Managed files are written as owner-only regular files.
- Backups are marker-bound to the canonical target and rotate through ten
  slots.
- Mutations snapshot managed bytes and restore them on failure.
- Restore removes every known managed path that is absent from the validated
  backup while preserving unrelated unmanaged files.
- Unmanaged files and unmanaged settings keys are preserved.
- Legacy managed state is read only for status, migrate, restore, and remove;
  launch is denied until migration succeeds.
- Launch requires a clean current managed target, current pinned software, and
  a current native builder plugin installation.
- Launch holds the lifecycle lock from preflight through child completion and
  cleanup, so lifecycle mutations are denied while the child is running.
- Launch revalidates the target-owned executable inode and digest after
  building argv/env and before starting the child.
- Launch rejects caller flags that override manager-owned profile, permissions,
  sandbox, remote, worktree, model, agent, MCP, or tool scope.

## Public Validation

```bash
python3 -m py_compile cli-tools/nddev_github_copilot_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_github_copilot_cli.py list --json
git diff --check
```

The public validator includes non-live adversarial smokes for unsafe target
modes, precreated symlink lock and backup paths, external marker preservation,
valid private targets under sticky `/tmp`, fake `PATH` interpreter/tool
injection, launch-held lifecycle locking, and launch executable revalidation.
They also cover setup operation intent and restore removal of retired managed
projection files.
