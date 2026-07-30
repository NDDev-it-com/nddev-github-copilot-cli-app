#!/usr/bin/env python3
"""Validate static public artifacts for nddev-github-copilot-cli-app."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
SETUPS = ["nddev-builder"]
PROFILES = ["full-auto", "safe"]
SUPPORTED = ["macos-arm64", "macos-x64", "ubuntu-glibc-arm64", "ubuntu-glibc-x64"]
UNSUPPORTED = ["windows", "non-ubuntu-linux", "linux-musl", "unsupported-architecture"]
REQUIRED_WORKFLOWS = {
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
}


def read_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_versions() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = read_json("build/version.json")
    manifest = read_json("build/manifest.json")
    baseline = read_json("references/copilot-cli-baseline.json")
    contract = read_json("config/nddev-contract.json")
    require(bool(SEMVER.fullmatch(version)), "VERSION must be semantic")
    require(build.get("build_version") == version, "build version mismatch")
    require(manifest.get("build_version") == version, "manifest version mismatch")
    require(
        build.get("nddev_builder_plugin_version") == version,
        "builder plugin version mismatch",
    )
    tested = build.get("copilot_cli_tested")
    require(tested == baseline["runtime"]["version"], "runtime baseline mismatch")
    require(
        contract["runtime_compatibility"]["tested_version"] == tested,
        "contract runtime mismatch",
    )
    require(
        manifest["runtime_compatibility"]["tested_version"] == tested,
        "manifest runtime mismatch",
    )
    require(contract.get("version_ref") == "build/version.json", "version_ref mismatch")
    require(contract.get("manifest_ref") == "build/manifest.json", "manifest_ref mismatch")
    return manifest, contract, baseline


def validate_catalog(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    require(manifest.get("setup_ids") == SETUPS, "manifest setup ids mismatch")
    require(manifest.get("profile_ids") == PROFILES, "manifest profile ids mismatch")
    require(contract["setup_system"]["setup_ids"] == SETUPS, "contract setup ids mismatch")
    require(contract["setup_system"]["profile_ids"] == PROFILES, "contract profile ids mismatch")
    require(set(contract["permission_profiles"]) == set(PROFILES), "profile policy mismatch")
    setup = read_json("setups/nddev-builder/setup.json")
    require(setup.get("id") == "nddev-builder", "setup id mismatch")
    setup_source_paths = {
        relative
        for relative in setup.get("managed_files", [])
        if (ROOT / "setups/nddev-builder" / relative).is_file()
    }
    profile_source_paths = {
        name
        for profile_id in PROFILES
        for name in ("settings.json", "permissions-config.json")
        if (ROOT / "profiles" / profile_id / name).is_file()
    }
    for profile_id in PROFILES:
        profile = read_json(f"profiles/{profile_id}/profile.json")
        require(profile.get("id") == profile_id, f"profile id mismatch: {profile_id}")
        for name in ("settings.json", "permissions-config.json"):
            read_json(f"profiles/{profile_id}/{name}")
    managed = manifest.get("managed_files")
    require(isinstance(managed, list) and len(managed) == len(set(managed)), "managed files invalid")
    require(set(managed) == setup_source_paths | profile_source_paths
            | {contract["managed_state"]["stamp_file"]},
            "managed file projection mismatch")


def validate_marketplace(version: str) -> None:
    marketplace = read_json("marketplaces/nddev-builder/.github/plugin/marketplace.json")
    plugin = read_json("marketplaces/nddev-builder/plugins/nddev-builder/plugin.json")
    require(marketplace.get("name") == "nddev-builder", "marketplace name mismatch")
    entries = marketplace.get("plugins")
    require(isinstance(entries, list) and len(entries) == 1, "marketplace plugin list invalid")
    entry = entries[0]
    require(entry.get("name") == "nddev-builder", "marketplace plugin id mismatch")
    require(entry.get("version") == version, "marketplace plugin version mismatch")
    require(entry.get("source") in {"plugins/nddev-builder", "./plugins/nddev-builder"},
            "marketplace source mismatch")
    require(plugin.get("name") == "nddev-builder", "plugin name mismatch")
    require(plugin.get("version") == version, "plugin version mismatch")
    for key in ("agents", "skills"):
        relative = plugin.get(key)
        require(isinstance(relative, str) and relative, f"plugin {key} missing")
        require((ROOT / "marketplaces/nddev-builder/plugins/nddev-builder" / relative).is_dir(),
                f"missing plugin path {relative}")
    read_json("marketplaces/nddev-builder/plugins/nddev-builder/.mcp.json")
    read_json("marketplaces/nddev-builder/plugins/nddev-builder/hooks.json")


def validate_runtime_integrity(baseline: dict[str, Any]) -> None:
    assets = baseline.get("assets")
    host_assets = baseline["platform_support"]["host_assets"]
    require(baseline["platform_support"]["supported"] == SUPPORTED, "supported hosts mismatch")
    require(baseline["platform_support"]["unsupported"] == UNSUPPORTED, "unsupported hosts mismatch")
    require(isinstance(assets, dict), "runtime assets missing")
    require(set(assets) == set(host_assets.values()), "product asset scope mismatch")
    for host, name in host_assets.items():
        require(host in SUPPORTED, f"unexpected supported host {host}")
        asset = assets[name]
        digest = asset.get("sha256")
        require(isinstance(digest, str) and len(digest) == 64, f"invalid digest for {name}")
        int(digest, 16)
        require(asset.get("size", 0) > 0, f"invalid size for {name}")
def validate_static_source() -> None:
    manager_path = ROOT / "cli-tools/nddev_github_copilot_cli.py"
    source = manager_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(manager_path))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    require({"parse_args", "main"} <= functions, "manager parse_args/main missing")
    for marker in (
        "NDDEV_GITHUB_COPILOT_CLI_TEST",
        "BOOTSTRAP_ROOT_OVERRIDE",
        "TEST_INSTALLER",
        "FAIL_AFTER",
    ):
        require(marker not in source, f"public manager contains test marker {marker}")


def validate_release_surface(manifest: dict[str, Any]) -> None:
    for name in REQUIRED_WORKFLOWS:
        require((ROOT / ".github/workflows" / name).is_file(), f"missing workflow {name}")
    for relative in ("AGENTS.md", "README.md", "LICENSE", "VERSION", "build", "cli-tools",
                     "config", "marketplaces", "profiles", "references", "setups"):
        require((ROOT / relative).exists(), f"missing release path {relative}")
    bridge_root = ROOT / ".claude"
    bridge = bridge_root / "CLAUDE.md"
    require(stat.S_ISDIR(bridge_root.lstat().st_mode), "Claude bridge root must be a directory")
    require(sorted(path.name for path in bridge_root.iterdir()) == ["CLAUDE.md"],
            "Claude bridge directory must contain only CLAUDE.md")
    require(stat.S_ISREG(bridge.lstat().st_mode), "Claude bridge must be a regular file")
    require(bridge.read_bytes() == b"@../AGENTS.md\n", "Claude bridge mismatch")
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    require(hashlib.sha256(manifest_bytes).hexdigest(), "manifest digest failed")


def main() -> int:
    try:
        manifest, contract, baseline = validate_versions()
        validate_catalog(manifest, contract)
        validate_marketplace((ROOT / "VERSION").read_text(encoding="utf-8").strip())
        validate_runtime_integrity(baseline)
        validate_static_source()
        validate_release_surface(manifest)
    except Exception as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
