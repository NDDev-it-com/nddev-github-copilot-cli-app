# Public Validation Workflows

Run these checks from the `nddev-github-copilot-cli-app` module root. They are
public, deterministic, and do not require live Copilot authentication.

## Static Public Contract

```bash
python3 -m py_compile cli-tools/nddev_github_copilot_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_github_copilot_cli.py list --json
git diff --check
```

The public contract validator includes isolated launch smokes for
target-internal lifecycle lock retention and executable fingerprint
revalidation. They mock process boundaries in-process and do not invoke live
Copilot software.

## Isolated Target Smoke

Use a temporary parent with mode `0700`. This smoke exercises target
transaction logic without running live software install or native plugin
installation.

```bash
tmp="$(mktemp -d)"
chmod 700 "$tmp"
python3 cli-tools/nddev_github_copilot_cli.py plan --target "$tmp/copilot" --json
python3 cli-tools/nddev_github_copilot_cli.py install --target "$tmp/copilot" --json
python3 cli-tools/nddev_github_copilot_cli.py status --target "$tmp/copilot" --json
python3 cli-tools/nddev_github_copilot_cli.py builder-status --target "$tmp/copilot" --json
python3 cli-tools/nddev_github_copilot_cli.py remove --target "$tmp/copilot" --json
```

## Native Builder Proof

Run this only against an isolated target that already has the target-owned,
pinned Copilot CLI installed by this manager:

```bash
python3 cli-tools/nddev_github_copilot_cli.py install-builder --target /absolute/copilot-home --json
python3 cli-tools/nddev_github_copilot_cli.py builder-status --target /absolute/copilot-home --json
```

The manager invokes native `copilot plugin marketplace add` and
`copilot plugin install` with isolated `COPILOT_HOME` and `COPILOT_CACHE_HOME`.

## Out Of Scope For Public Module

Private root validation, fixtures, benchmarks, memories, evidence generation,
registry pinning, CI execution, pushes, and tags are owned outside this public
module.
