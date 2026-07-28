# nddev-github-copilot-cli-app Agent Rules

Work only inside this public module unless the user explicitly changes scope.
Repository artifacts are English.

## Ownership

- Public manager: `cli-tools/nddev_github_copilot_cli.py`.
- Public contract: `config/nddev-contract.json`.
- Public build metadata: `build/manifest.json` and `build/version.json`.
- Runtime baseline pins: `references/copilot-cli-baseline.json`.
- Content setup: `setups/nddev-builder/`.
- Permission profiles: `profiles/full-auto/` and `profiles/safe/`.
- Native builder marketplace: `marketplaces/nddev-builder/`.

Do not add private validation, fixtures, benchmark data, operational memories,
runtime logs, generated evidence, credentials, live `~/.copilot` state, root
harness files, registry updates, CI changes, pushes, or tags here.

## Product Boundary

The module supports macOS arm64/x64 and Ubuntu glibc arm64/x64 only. GitHub's
official Copilot CLI docs publish generic Linux support and no Ubuntu version
floor, so this module must not invent one. Windows, linux-musl, non-Ubuntu
Linux, unsupported architectures, middle permission profiles, exception
language, manual runtime-owned plugin projections, and undocumented Copilot CLI
settings are out of scope.

Use the setup/profile model: `nddev-builder` owns content, while `full-auto`
and `safe` own permission posture. Keep future setup switching orthogonal to
future profile switching.

## Builder Toolkit

The managed builder is a native local Copilot CLI marketplace plugin under
`marketplaces/nddev-builder/`. Keep the entry `nddev-builder` skill as a
router and put detailed guidance in focused skills or one-hop references.

Point to code-owned facts for volatile versions, pins, launch flags, profile
lists, managed path enumerations, and command grammar. Do not duplicate those
facts in skills beyond narrow examples.

## Validation

Before committing public module changes, run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_github_copilot_cli.py list --json
python3 cli-tools/nddev_github_copilot_cli.py --help
git diff --check
```

Do not run live software install, native builder install, CI, push, or tag
unless the user explicitly approves that later phase.
