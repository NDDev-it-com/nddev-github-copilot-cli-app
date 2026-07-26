#!/usr/bin/env python3
"""Validate nddev-github-copilot-cli-app public contracts without side effects."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
OFFICIAL = {
    "version": "1.0.75",
    "release_tag": "v1.0.75",
    "published_at": "2026-07-24T19:54:03Z",
    "command": "copilot",
    "npm_package": "@github/copilot",
}
EXPECTED_SETUP_IDS = ["safe", "balanced", "full-auto"]
EXPECTED_LAUNCH_ARGS = {
    "safe": ["--no-remote", "--no-remote-export", "--disallow-temp-dir"],
    "balanced": [
        "--no-remote",
        "--no-remote-export",
        "--disallow-temp-dir",
        "--allow-tool=read,write",
        "--allow-tool=shell(git:*)",
        "--deny-tool=shell(git push)",
        "--deny-tool=shell(rm:*)",
    ],
    "full-auto": ["--allow-all"],
}
PLACEHOLDER_MARKER = "skele" + "ton"
OLD_EXT_MARKERS = ("gh" + "-copilot", "gh" + " copilot")


def read_json(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain a JSON object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_versions(errors: list[str]) -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = read_json("build/version.json")
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    baseline = read_json("references/copilot-cli-baseline.json")
    require(SEMVER.fullmatch(version) is not None, "VERSION is not SemVer", errors)
    require(version != "0.0.0", "VERSION must not be placeholder 0.0.0", errors)
    require(build.get("schema_version") == 2, "build/version.json schema mismatch", errors)
    require(manifest.get("schema_version") == 2, "build/manifest.json schema mismatch", errors)
    require(contract.get("contract_version") == 2, "contract version mismatch", errors)
    require(build.get("build_version") == version, "build version mismatch", errors)
    require(manifest.get("build_version") == version, "manifest version mismatch", errors)
    require(contract.get("version_ref") == "build/version.json", "contract version_ref mismatch", errors)
    require(contract.get("manifest_ref") == "build/manifest.json", "contract manifest_ref mismatch", errors)
    require(PLACEHOLDER_MARKER not in contract, "contract contains placeholder marker", errors)
    require(build.get("copilot_cli_tested") == OFFICIAL["version"], "tested version mismatch", errors)
    require(build.get("copilot_cli_release_tag") == OFFICIAL["release_tag"], "release tag mismatch", errors)
    require(build.get("copilot_cli_release_published_at") == OFFICIAL["published_at"], "release date mismatch", errors)
    require(build.get("command") == OFFICIAL["command"], "command mismatch", errors)
    require(build.get("npm_package") == OFFICIAL["npm_package"], "package mismatch", errors)
    release = baseline.get("release")
    npm = baseline.get("npm")
    require(isinstance(release, dict), "baseline release missing", errors)
    require(isinstance(npm, dict), "baseline npm missing", errors)
    if isinstance(release, dict):
        require(release.get("tag") == build.get("copilot_cli_release_tag"), "baseline release tag mismatch", errors)
        require(release.get("published_at") == build.get("copilot_cli_release_published_at"), "baseline release date mismatch", errors)
    if isinstance(npm, dict):
        require(npm.get("package") == build.get("npm_package"), "baseline package mismatch", errors)
        require(npm.get("version") == build.get("copilot_cli_tested"), "baseline package version mismatch", errors)
        require(npm.get("binary") == build.get("command"), "baseline command mismatch", errors)
    for owner, runtime in (("manifest", manifest.get("runtime_compatibility")), ("contract", contract.get("runtime_compatibility"))):
        require(isinstance(runtime, dict), f"{owner} runtime_compatibility missing", errors)
        if isinstance(runtime, dict):
            require(runtime.get("tested_version") == build.get("copilot_cli_tested"), f"{owner} tested version mismatch", errors)
            require(runtime.get("npm_package") == build.get("npm_package"), f"{owner} package mismatch", errors)
            require(runtime.get("release_tag") == build.get("copilot_cli_release_tag"), f"{owner} release tag mismatch", errors)
            require(runtime.get("baseline_ref") == build.get("runtime_baseline_ref"), f"{owner} baseline ref mismatch", errors)


def validate_assets(errors: list[str]) -> None:
    baseline = read_json("references/copilot-cli-baseline.json")
    assets = baseline.get("assets")
    require(isinstance(assets, dict), "baseline assets missing", errors)
    expected = {
        "copilot-darwin-arm64.tar.gz": "a5ede0d96dbb6cfff8bed0f6872ac3eb05bf0a4ed342d44a0a6548cb242713c2",
        "copilot-darwin-x64.tar.gz": "e8078d57accc7eabbb29565a2f4c217723acfb7c7a2563ed6cac41c45eb29acf",
        "copilot-linux-arm64.tar.gz": "0911f12dd816f612d27c4a360d4f00b62d933845a98d6c913e8d7400a69c6809",
        "copilot-linux-x64.tar.gz": "d304ef66c0c1d2de7d736b3653b36557e80b4f40a0bf8c4a71e7215f3aff7441",
        "copilot-linuxmusl-arm64.tar.gz": "9b790f9b5be01f662743646fcdd47fa61024e0377e3edf23e381df784f8cb01d",
        "copilot-linuxmusl-x64.tar.gz": "56228153a79f4ea69450ce4e5a9ff122b30d4307e90b2300b4b5208ffc649f08",
        "copilot-win32-arm64.zip": "d9c3b7e0e22ba2929ff53cae8fd9fb1990e8d63c8507266b19ffecf9a3ae9d87",
        "copilot-win32-x64.zip": "18a8d469d30930cb9da5625dfaf3e261f0cd25442bfdb6754382c443bed42643",
        "github-copilot-1.0.75.tgz": "b1c9b9e94cb7fd383a87a2793ce9cc7be0640c4ce685685a587df557f57ffe75",
    }
    if isinstance(assets, dict):
        for name, digest in expected.items():
            asset = assets.get(name)
            require(isinstance(asset, dict), f"asset missing: {name}", errors)
            if isinstance(asset, dict):
                require(asset.get("sha256") == digest, f"asset digest mismatch: {name}", errors)
                require(
                    asset.get("browser_download_url") == f"https://github.com/github/copilot-cli/releases/download/v1.0.75/{name}",
                    f"asset URL mismatch: {name}",
                    errors,
                )


def validate_setups(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    require(manifest.get("setup_ids") == EXPECTED_SETUP_IDS, "manifest setup ids mismatch", errors)
    setup_system = contract.get("setup_system")
    require(isinstance(setup_system, dict), "contract setup_system missing", errors)
    if isinstance(setup_system, dict):
        require(setup_system.get("setup_ids") == EXPECTED_SETUP_IDS, "contract setup ids mismatch", errors)
        require(setup_system.get("builder_default_on") is True, "builder default mismatch", errors)
    for setup_id in EXPECTED_SETUP_IDS:
        metadata = read_json(f"setups/{setup_id}/setup.json")
        settings = read_json(f"setups/{setup_id}/settings.json")
        permissions = read_json(f"setups/{setup_id}/permissions-config.json")
        require(metadata.get("id") == setup_id, f"{setup_id} id mismatch", errors)
        require(metadata.get("launch_args") == EXPECTED_LAUNCH_ARGS[setup_id], f"{setup_id} launch args mismatch", errors)
        require(metadata.get("builder_default_on") is True, f"{setup_id} builder not default-on", errors)
        require(metadata.get("builder_projection") == "native-plugin-plus-user-files", f"{setup_id} builder projection mismatch", errors)
        require(settings.get("remote") == "off", f"{setup_id} remote must be off", errors)
        require(settings.get("remoteExport") is False, f"{setup_id} remote export must be off", errors)
        require(settings.get("storeTokenPlaintext") is False, f"{setup_id} plaintext token storage must be off", errors)
        require(settings.get("enabledPlugins") == {"nddev-builder": True}, f"{setup_id} builder plugin must be enabled", errors)
        require(settings.get("extraKnownMarketplaces") == {}, f"{setup_id} marketplace must be empty", errors)
        require(permissions.get("locations") == {}, f"{setup_id} permissions locations mismatch", errors)


def validate_builder(errors: list[str]) -> None:
    build = read_json("build/version.json")
    contract = read_json("config/nddev-contract.json")
    plugin = read_json("plugins/nddev-builder/plugin.json")
    builder = contract.get("builder_capability")
    require(plugin.get("name") == "nddev-builder", "builder name mismatch", errors)
    require(plugin.get("version") == build.get("nddev_builder_plugin_version"), "builder version mismatch", errors)
    require(plugin.get("skills") == "skills", "builder skills path mismatch", errors)
    require(plugin.get("agents") == "agents", "builder agents path mismatch", errors)
    require(plugin.get("hooks") == "hooks.json", "builder hooks path mismatch", errors)
    require(isinstance(builder, dict), "contract builder missing", errors)
    if isinstance(builder, dict):
        require(builder.get("projection") == "copilot-native-plugin-user-files", "builder projection mismatch", errors)
        require(builder.get("default_on") is True, "builder default_on mismatch", errors)
        require(builder.get("marketplace") is None, "builder marketplace must be null", errors)
    for relative in (
        "plugins/nddev-builder/plugin.json",
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "plugins/nddev-builder/agents/nddev-builder.agent.md",
        "plugins/nddev-builder/hooks.json",
    ):
        require((ROOT / relative).is_file(), f"missing builder native file: {relative}", errors)


def validate_absent_retired_markers(errors: list[str]) -> None:
    own_path = Path(__file__).resolve()
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.resolve() == own_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if PLACEHOLDER_MARKER in text:
            errors.append(f"placeholder marker found in {path.relative_to(ROOT)}")
        for marker in OLD_EXT_MARKERS:
            if marker in text:
                errors.append(f"retired extension marker found in {path.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    try:
        validate_versions(errors)
        validate_assets(errors)
        validate_setups(errors)
        validate_builder(errors)
        validate_absent_retired_markers(errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
