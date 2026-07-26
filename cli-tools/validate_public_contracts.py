#!/usr/bin/env python3
"""Validate nddev-github-copilot-cli-app public contracts without side effects."""

from __future__ import annotations

import json
import re
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
    "installer_url": "https://gh.io/copilot-install",
    "installer_sha256": "cd45508981a9baee5fb8f5e38495d315758cd7fea4a715b53a9f26c12544dc95",
    "installer_size": 6922,
    "checksums_sha256": "60cc71c48eb6df4380799af868035a78ae45128d725cbc4e2f91a09666505d37",
    "checksums_size": 1740,
}
EXPECTED_SETUP_IDS = ["safe", "balanced", "full-auto"]
EXPECTED_MANAGED_FILES = [
    "settings.json",
    "permissions-config.json",
    "copilot-instructions.md",
    "instructions/nddev-builder.instructions.md",
    "mcp-config.json",
]
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
EXPECTED_SUPPORTED_PLATFORMS = ["macos", "linux", "linuxmusl"]
EXPECTED_BLOCKED_FLAGS = [
    "--add-dir",
    "--add-github-mcp-tool",
    "--add-github-mcp-toolset",
    "--additional-mcp-config",
    "--agent",
    "--allow-all",
    "--allow-all-mcp-server-instructions",
    "--allow-all-paths",
    "--allow-all-tools",
    "--allow-all-urls",
    "--allow-tool",
    "--allow-url",
    "--autopilot",
    "--available-tools",
    "--bash-env",
    "--config-dir",
    "--connect",
    "--context",
    "--deny-tool",
    "--deny-url",
    "--disable-builtin-mcps",
    "--disable-mcp-server",
    "--disallow-temp-dir",
    "--effort",
    "--enable-all-github-mcp-tools",
    "--enable-memory",
    "--max-autopilot-continues",
    "--mode",
    "--model",
    "--plan",
    "--reasoning-effort",
    "--resume",
    "--worktree",
    "--yolo",
    "-C",
    "-w",
]
PLACEHOLDER_MARKER = "skele" + "ton"


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
    require(
        contract.get("version_ref") == "build/version.json", "contract version_ref mismatch", errors
    )
    require(
        contract.get("manifest_ref") == "build/manifest.json",
        "contract manifest_ref mismatch",
        errors,
    )
    require(PLACEHOLDER_MARKER not in contract, "contract contains placeholder marker", errors)
    require(
        build.get("copilot_cli_tested") == OFFICIAL["version"], "tested version mismatch", errors
    )
    require(
        build.get("copilot_cli_release_tag") == OFFICIAL["release_tag"],
        "release tag mismatch",
        errors,
    )
    require(
        build.get("copilot_cli_release_published_at") == OFFICIAL["published_at"],
        "release date mismatch",
        errors,
    )
    require(build.get("command") == OFFICIAL["command"], "command mismatch", errors)
    require(build.get("installer_url") == OFFICIAL["installer_url"], "installer URL mismatch", errors)
    require(
        build.get("installer_sha256") == OFFICIAL["installer_sha256"],
        "installer SHA256 mismatch",
        errors,
    )
    release = baseline.get("release")
    installer = baseline.get("installer")
    runtime_baseline = baseline.get("runtime")
    require(isinstance(release, dict), "baseline release missing", errors)
    require(isinstance(installer, dict), "baseline installer missing", errors)
    require(isinstance(runtime_baseline, dict), "baseline runtime missing", errors)
    if isinstance(release, dict):
        require(
            release.get("tag") == build.get("copilot_cli_release_tag"),
            "baseline release tag mismatch",
            errors,
        )
        require(
            release.get("published_at") == build.get("copilot_cli_release_published_at"),
            "baseline release date mismatch",
            errors,
        )
        checksums = release.get("checksums")
        require(isinstance(checksums, dict), "baseline checksums missing", errors)
        if isinstance(checksums, dict):
            require(
                checksums.get("sha256") == OFFICIAL["checksums_sha256"],
                "baseline checksums SHA256 mismatch",
                errors,
            )
            require(
                checksums.get("size") == OFFICIAL["checksums_size"],
                "baseline checksums size mismatch",
                errors,
            )
    if isinstance(installer, dict):
        require(installer.get("url") == OFFICIAL["installer_url"], "baseline installer URL mismatch", errors)
        require(
            installer.get("sha256") == OFFICIAL["installer_sha256"],
            "baseline installer SHA256 mismatch",
            errors,
        )
        require(installer.get("size") == OFFICIAL["installer_size"], "baseline installer size mismatch", errors)
    if isinstance(runtime_baseline, dict):
        require(runtime_baseline.get("version") == build.get("copilot_cli_tested"), "baseline runtime version mismatch", errors)
        require(runtime_baseline.get("command") == build.get("command"), "baseline command mismatch", errors)
    for owner, runtime in (
        ("manifest", manifest.get("runtime_compatibility")),
        ("contract", contract.get("runtime_compatibility")),
    ):
        require(isinstance(runtime, dict), f"{owner} runtime_compatibility missing", errors)
        if isinstance(runtime, dict):
            require(
                runtime.get("tested_version") == build.get("copilot_cli_tested"),
                f"{owner} tested version mismatch",
                errors,
            )
            require(
                runtime.get("release_tag") == build.get("copilot_cli_release_tag"),
                f"{owner} release tag mismatch",
                errors,
            )
            require(
                runtime.get("baseline_ref") == build.get("runtime_baseline_ref"),
                f"{owner} baseline ref mismatch",
                errors,
            )


def validate_assets(errors: list[str]) -> None:
    baseline = read_json("references/copilot-cli-baseline.json")
    assets = baseline.get("assets")
    require(isinstance(assets, dict), "baseline assets missing", errors)
    expected = {
        "copilot-darwin-arm64.tar.gz": (
            "a5ede0d96dbb6cfff8bed0f6872ac3eb05bf0a4ed342d44a0a6548cb242713c2",
            94014855,
        ),
        "copilot-darwin-x64.tar.gz": (
            "e8078d57accc7eabbb29565a2f4c217723acfb7c7a2563ed6cac41c45eb29acf",
            105156970,
        ),
        "copilot-linux-arm64.tar.gz": (
            "0911f12dd816f612d27c4a360d4f00b62d933845a98d6c913e8d7400a69c6809",
            106111479,
        ),
        "copilot-linux-x64.tar.gz": (
            "d304ef66c0c1d2de7d736b3653b36557e80b4f40a0bf8c4a71e7215f3aff7441",
            105262977,
        ),
        "copilot-linuxmusl-arm64.tar.gz": (
            "9b790f9b5be01f662743646fcdd47fa61024e0377e3edf23e381df784f8cb01d",
            99411680,
        ),
        "copilot-linuxmusl-x64.tar.gz": (
            "56228153a79f4ea69450ce4e5a9ff122b30d4307e90b2300b4b5208ffc649f08",
            102519573,
        ),
    }
    if isinstance(assets, dict):
        require(set(assets) == set(expected), "baseline asset set mismatch", errors)
        for name, (digest, size) in expected.items():
            asset = assets.get(name)
            require(isinstance(asset, dict), f"asset missing: {name}", errors)
            if isinstance(asset, dict):
                require(asset.get("sha256") == digest, f"asset digest mismatch: {name}", errors)
                require(asset.get("size") == size, f"asset size mismatch: {name}", errors)
                require(
                    asset.get("browser_download_url")
                    == f"https://github.com/github/copilot-cli/releases/download/v1.0.75/{name}",
                    f"asset URL mismatch: {name}",
                    errors,
                )


def validate_lifecycle_contracts(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    for owner, runtime in (
        ("manifest", manifest.get("runtime_launch")),
        ("contract", contract.get("runtime_launch")),
    ):
        require(isinstance(runtime, dict), f"{owner} runtime_launch missing", errors)
        if isinstance(runtime, dict):
            require(
                runtime.get("command") == "<absolute-target>/bin/copilot",
                f"{owner} launch command mismatch",
                errors,
            )
            require(
                runtime.get("executable_source") == "validated-target-owned-github-release-asset",
                f"{owner} executable source mismatch",
                errors,
            )
            require(
                runtime.get("token_environment_inheritance") == "stripped",
                f"{owner} token inheritance mismatch",
                errors,
            )
            require(
                runtime.get("environment_inheritance")
                == "minimal-allowlist-plus-test-fixture-vars",
                f"{owner} environment inheritance mismatch",
                errors,
            )
            require(
                runtime.get("lock_released_before_child") is True,
                f"{owner} lock release contract mismatch",
                errors,
            )
            require(
                runtime.get("blocks_user_managed_flags") == EXPECTED_BLOCKED_FLAGS,
                f"{owner} blocked launch flags mismatch",
                errors,
            )
    safety = contract.get("safety")
    require(isinstance(safety, dict), "contract safety missing", errors)
    if isinstance(safety, dict):
        expected_safety = {
            "explicit_target_required": True,
            "absolute_target_required": True,
            "relative_target_rejected": True,
            "missing_target_argument_rejected": True,
            "target_symlinks_rejected": True,
            "home_expansion_rejected": True,
            "target_parent_private_required": True,
            "dangling_symlinks_fail_closed": True,
            "hardlinks_rejected": True,
            "canonical_target_binding": True,
            "preserve_existing_target_mode": True,
            "unique_transaction_directories": True,
            "created_transaction_paths_cleaned_exactly": True,
            "rollback_on_failure": True,
        }
        for key, expected in expected_safety.items():
            require(safety.get(key) is expected, f"safety {key} mismatch", errors)
        require(safety.get("default_target") is None, "default target must be null", errors)
        require(safety.get("max_backups") == 10, "max backups mismatch", errors)
        require(safety.get("new_target_mode") == "0700", "new target mode mismatch", errors)
        require(
            safety.get("backup_pool_marker") == "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json",
            "backup pool marker mismatch",
            errors,
        )
        require(
            safety.get("preexisting_backup_pool_collision") == "fail-closed-no-delete",
            "backup collision policy mismatch",
            errors,
        )
        require(
            safety.get("rollback_snapshot")
            == "managed bytes restored with 0600 managed-file modes",
            "rollback snapshot contract mismatch",
            errors,
        )
    transaction = manifest.get("transaction_policy")
    require(isinstance(transaction, dict), "manifest transaction_policy missing", errors)
    if isinstance(transaction, dict):
        require(
            transaction.get("private_current_user_parent_required") is True,
            "transaction parent privacy mismatch",
            errors,
        )
        require(
            transaction.get("dangling_symlinks_fail_closed") is True,
            "transaction dangling symlink policy mismatch",
            errors,
        )
        require(
            transaction.get("unique_stage_directories") is True,
            "transaction stage uniqueness mismatch",
            errors,
        )
        require(
            transaction.get("backup_pool_marker") == "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json",
            "transaction backup marker mismatch",
            errors,
        )
        require(
            transaction.get("preexisting_backup_pool_collision") == "fail-closed-no-delete",
            "transaction backup collision mismatch",
            errors,
        )
        require(
            transaction.get("created_transaction_paths_cleaned_exactly") is True,
            "transaction cleanup scope mismatch",
            errors,
        )
        require(
            transaction.get("rollback_snapshot")
            == "managed bytes restored with 0600 managed-file modes",
            "transaction rollback snapshot mismatch",
            errors,
        )
    for owner, software in (
        ("manifest", manifest.get("software_install")),
        ("contract", contract.get("software_install")),
    ):
        require(isinstance(software, dict), f"{owner} software_install missing", errors)
        if isinstance(software, dict):
            require(
                software.get("supported_platforms") == EXPECTED_SUPPORTED_PLATFORMS,
                f"{owner} software platforms mismatch",
                errors,
            )
            require(
                software.get("update_precondition")
                == "installed-or-safe-repairable-partial-target",
                f"{owner} update precondition mismatch",
                errors,
            )
            require(
                software.get("absent_update_policy")
                == "domain-failure-install-first-zero-artifacts",
                f"{owner} absent update policy mismatch",
                errors,
            )
            require(
                software.get("stage_policy") == "unique-private-mkdtemp-under-target-parent",
                f"{owner} stage policy mismatch",
                errors,
            )
            require(
                software.get("pre_network_preflight")
                == "target-parent-current-user-owned-mode-0700-no-follow",
                f"{owner} pre-network preflight mismatch",
                errors,
            )


def validate_setups(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    require(manifest.get("setup_ids") == EXPECTED_SETUP_IDS, "manifest setup ids mismatch", errors)
    setup_system = contract.get("setup_system")
    require(isinstance(setup_system, dict), "contract setup_system missing", errors)
    if isinstance(setup_system, dict):
        require(
            setup_system.get("setup_ids") == EXPECTED_SETUP_IDS,
            "contract setup ids mismatch",
            errors,
        )
        require(setup_system.get("builder_default_on") is True, "builder default mismatch", errors)
    for setup_id in EXPECTED_SETUP_IDS:
        metadata = read_json(f"setups/{setup_id}/setup.json")
        settings = read_json(f"setups/{setup_id}/settings.json")
        permissions = read_json(f"setups/{setup_id}/permissions-config.json")
        require(metadata.get("id") == setup_id, f"{setup_id} id mismatch", errors)
        require(
            metadata.get("managed_files") == EXPECTED_MANAGED_FILES,
            f"{setup_id} managed files mismatch",
            errors,
        )
        require(
            metadata.get("launch_args") == EXPECTED_LAUNCH_ARGS[setup_id],
            f"{setup_id} launch args mismatch",
            errors,
        )
        require(
            metadata.get("builder_default_on") is True, f"{setup_id} builder not default-on", errors
        )
        require(
            metadata.get("builder_projection") == "native-plugin-plus-user-files",
            f"{setup_id} builder projection mismatch",
            errors,
        )
        require(settings.get("remote") == "off", f"{setup_id} remote must be off", errors)
        require(
            settings.get("remoteExport") is False, f"{setup_id} remote export must be off", errors
        )
        require(
            settings.get("storeTokenPlaintext") is False,
            f"{setup_id} plaintext token storage must be off",
            errors,
        )
        require(
            settings.get("enabledPlugins") == {"nddev-builder": True},
            f"{setup_id} builder plugin must be enabled",
            errors,
        )
        require(
            settings.get("extraKnownMarketplaces") == {},
            f"{setup_id} marketplace must be empty",
            errors,
        )
        require(
            permissions.get("locations") == {}, f"{setup_id} permissions locations mismatch", errors
        )
        require(
            (ROOT / "setups" / setup_id / "instructions" / "nddev-builder.instructions.md").is_file(),
            f"{setup_id} modular instructions missing",
            errors,
        )


def validate_builder(errors: list[str]) -> None:
    build = read_json("build/version.json")
    contract = read_json("config/nddev-contract.json")
    plugin = read_json("plugins/nddev-builder/plugin.json")
    builder = contract.get("builder_capability")
    require(plugin.get("name") == "nddev-builder", "builder name mismatch", errors)
    require(
        plugin.get("version") == build.get("nddev_builder_plugin_version"),
        "builder version mismatch",
        errors,
    )
    require(plugin.get("skills") == "skills", "builder skills path mismatch", errors)
    require(plugin.get("agents") == "agents", "builder agents path mismatch", errors)
    require(plugin.get("hooks") == "hooks.json", "builder hooks path mismatch", errors)
    require(isinstance(builder, dict), "contract builder missing", errors)
    if isinstance(builder, dict):
        require(
            builder.get("projection") == "copilot-native-plugin-user-files",
            "builder projection mismatch",
            errors,
        )
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


def main() -> int:
    errors: list[str] = []
    try:
        validate_versions(errors)
        validate_assets(errors)
        validate_lifecycle_contracts(errors)
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
