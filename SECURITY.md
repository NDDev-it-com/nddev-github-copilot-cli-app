# Security Policy

## Supported surface

Security reporting covers the setup catalog, lifecycle CLI, public contracts,
documentation, native GitHub Copilot CLI builder capability, and GitHub
workflows in this repository. Only the latest numeric release is supported.

## Reporting a vulnerability

Report vulnerabilities privately through GitHub Security Advisories for
`NDDev-it-com/nddev-github-copilot-cli-app`. Do not publish credentials, tokens,
private configuration, or backup contents in an issue or pull request.

## Baseline controls

- The CLI never defaults to a live Copilot home; target operations require an
  explicit absolute `--target`.
- Managed files reject symlinks, special files, and hard-link aliases.
- Setup switching preserves unmanaged target files and co-owned settings keys.
- Backup envelopes and installed stamps are bound to the canonical target.
- Setup operations are intent-specific: install does not replace managed
  targets, switch requires a current clean managed target, and migrate requires
  legacy-managed state.
- Mutations and managed launch use manager-owned lifecycle exclusion,
  postcondition checks, and rollback on failure.
- Restore removes known managed paths absent from the validated backup while
  preserving unrelated unmanaged files.
- Managed launch keeps lifecycle mutations denied through child completion and
  revalidates the target-owned executable before handoff.
- Runtime handoff is a write-protected verified path, not portable fd
  execution. Without a sandbox it does not claim resistance to deliberate
  same-UID tampering outside the documented boundary.
- The builder capability is installed through local native GitHub Copilot CLI
  marketplace commands in an isolated target home/cache.

Implementation mechanics, exact paths, current pins, and validation coverage
are owned by `cli-tools/nddev_github_copilot_cli.py`,
`config/nddev-contract.json`, `build/manifest.json`, `build/version.json`, and
`references/copilot-cli-baseline.json`.
