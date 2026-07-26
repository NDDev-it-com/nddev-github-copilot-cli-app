# nddev-github-copilot-cli-app

Target-explicit NDDev setup manager for the current GitHub Copilot CLI.

This module manages an isolated Copilot home selected by `--target`; it never
defaults to the caller's live home directory and does not read or modify live
authentication state.

## Supported runtime baseline

- Command: `copilot`
- Tested release: `github/copilot-cli` `v1.0.75`
- Release published: `2026-07-24T19:54:03Z`
- Installer: `https://gh.io/copilot-install`
- Installer SHA-256: `cd45508981a9baee5fb8f5e38495d315758cd7fea4a715b53a9f26c12544dc95`
- Config root: `COPILOT_HOME`
- Cache root: `COPILOT_CACHE_HOME`

The full immutable installer, checksum, and release asset baseline is in
`references/copilot-cli-baseline.json`.

## Usage

```bash
python3 cli-tools/nddev_github_copilot_cli.py list
python3 cli-tools/nddev_github_copilot_cli.py plan --setup safe --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py install --setup safe --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py switch --setup balanced --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py restore --backup 0 --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py remove --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-plan --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-status --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-install --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py software-update --target /absolute/copilot-home
python3 cli-tools/nddev_github_copilot_cli.py launch --target /absolute/copilot-home -- --help
```

`software-install` verifies the pinned official installer, release checksums,
and selected release asset metadata, runs the installer only in an isolated
staging home with `VERSION=1.0.75` and `PREFIX=<stage>`, probes only the staged
binary, and persists only the target-owned `bin/copilot` plus receipt.

## Setup variants

- `safe`: remote sessions off, remote export off, temp-dir access disallowed,
  bypass disabled.
- `balanced`: safe defaults plus a bounded read/write and git allowlist with
  destructive command denials.
- `full-auto`: explicit trusted-target setup using the current `--allow-all`
  launch flag.

All variants keep `nddev-builder` default-on through local native plugin, skill,
agent, hook, and modular instruction files. Marketplace provisioning is `null`
because this manager does not have a confirmed official marketplace install
contract.

## Safety model

- explicit absolute `--target` is required for every target operation;
- target symlinks and managed symlinks/hard links fail closed;
- reads are size bounded;
- state stamps and backup envelopes bind to the canonical target;
- ten rotating target-bound backups are retained;
- unmanaged target files and co-owned settings keys are preserved;
- mutation failure rolls back the previous managed state;
- software status never executes `copilot`;
- launch uses only the target-owned `bin/copilot`;
- launcher child environment strips common GitHub/Copilot token variables.
