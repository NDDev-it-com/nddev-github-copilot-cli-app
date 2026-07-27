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
- Setup operations are intent-specific: install does not replace managed
  targets, switch requires a current clean managed target, and migrate requires
  legacy-managed state.
- Mutations and managed launch share a target-internal persistent lifecycle
  lock file held with nonblocking `fcntl.flock`, bounded backup rotation,
  postcondition checks, and rollback on failure.
- Restore removes known managed paths absent from the validated backup while
  preserving unrelated unmanaged files.
- Managed launch keeps the lifecycle lock through child completion, protects
  the lock parent from ordinary child unlink cleanup, and revalidates the
  target-owned executable fingerprint with `O_NOFOLLOW` fd evidence immediately
  before `Popen`.
- Runtime handoff is a write-protected verified path, not portable fd
  execution. Without a sandbox it does not claim resistance to deliberate
  same-UID chmod or rename attacks.
- The builder capability is installed through local native GitHub Copilot CLI
  marketplace commands in an isolated target home/cache.
