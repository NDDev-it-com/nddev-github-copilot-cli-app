# Security Policy

## Supported surface

Security reporting covers the setup catalog, lifecycle CLI, public contracts,
documentation, native GitHub Copilot CLI builder projection, and GitHub
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
- Mutations and managed launch share a target-internal lifecycle lock, bounded
  backup rotation, postcondition checks, and rollback on failure.
- Managed launch keeps the lifecycle lock through child completion and
  revalidates the target-owned executable fingerprint immediately before the
  child starts.
- The builder capability is installed through local native GitHub Copilot CLI
  marketplace commands in an isolated target home/cache.
