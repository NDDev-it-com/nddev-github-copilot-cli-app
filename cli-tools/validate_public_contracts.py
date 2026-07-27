#!/usr/bin/env python3
"""Validate nddev-github-copilot-cli-app public contracts without side effects."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "cli-tools" / "nddev_github_copilot_cli.py"
BUILDER_ROOT = ROOT / "marketplaces" / "nddev-builder" / "plugins" / "nddev-builder"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
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
EXPECTED_SETUP_IDS = ["nddev-builder"]
EXPECTED_PROFILE_IDS = ["full-auto", "safe"]
EXPECTED_SETUP_MANAGED_FILES = [
    "copilot-instructions.md",
    "instructions/nddev-builder.instructions.md",
    "mcp-config.json",
]
EXPECTED_PROFILE_MANAGED_FILES = ["settings.json", "permissions-config.json"]
EXPECTED_CURRENT_MANAGED_FILES = [
    "settings.json",
    "permissions-config.json",
    "copilot-instructions.md",
    "instructions/nddev-builder.instructions.md",
    "mcp-config.json",
    "NDDEV-GITHUB-COPILOT-CLI-SETUP.json",
]
EXPECTED_FULL_AUTO_LAUNCH_ARGS = [
    "--allow-all",
    "--mode=autopilot",
    "--no-ask-user",
    "--no-remote",
    "--no-remote-export",
    "--enable-all-github-mcp-tools",
    "--allow-all-mcp-server-instructions",
]
EXPECTED_SAFE_LAUNCH_ARGS = ["--no-remote", "--no-remote-export", "--disallow-temp-dir"]
EXPECTED_BUILDER_SKILLS = [
    "nddev-builder",
    "copilot-configuration-profile",
    "copilot-permissions-sandbox",
    "copilot-agents-subagents",
    "copilot-skills-instructions",
    "copilot-plugins-marketplace",
    "copilot-hooks",
    "copilot-mcp",
    "copilot-installation-lifecycle",
    "copilot-creator-checker-release",
]
EXPECTED_BUILDER_REFERENCES = [
    "references/native-paths-and-schemas.md",
    "references/public-validation-workflows.md",
]
EXPECTED_SUPPORTED_PLATFORMS = ["macos", "ubuntu-26.04"]
EXPECTED_UNSUPPORTED_PLATFORMS = ["windows", "linux-musl", "non-ubuntu-linux"]
EXPECTED_ASSETS = {
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
}
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
    "--ask-user",
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
    "--no-ask-user",
    "--no-remote",
    "--no-remote-export",
    "--no-sandbox",
    "--plan",
    "--reasoning-effort",
    "--remote",
    "--remote-export",
    "--resume",
    "--sandbox",
    "--worktree",
    "--yolo",
    "-C",
    "-w",
]
EXPECTED_ARCHIVE_RELEASE_PATHS = [
    "README.md",
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "SECURITY.md",
    ".github",
    "build",
    "cli-tools",
    "config",
    "marketplaces",
    "profiles",
    "references",
    "setups",
]
EXPECTED_RUNTIME_RELEASE_PATHS = [
    "README.md",
    "LICENSE",
    "VERSION",
    "build",
    "cli-tools",
    "config",
    "marketplaces",
    "profiles",
    "references",
    "setups",
]
FORBIDDEN_RELEASE_PATHS = {"plugins"}
EXPECTED_OPERATION_INTENT = {
    "install": "absent-or-unmanaged-target-only",
    "switch": "current-clean-schema-target-only",
    "migrate": "legacy-managed-target-only",
}
PLACEHOLDER_MARKER = "skele" + "ton"
FORBIDDEN_MANAGER_SOURCE_PATTERNS = [
    "ALLOW_TEST",
    "ALLOW_TEST_INSTALLER",
    "FAKE_COPILOT",
    "fixture override",
    "fixture path",
    "test_override",
    "env_timeout_seconds",
    "NDDEV_COPILOT_CLI_INSTALLER_URL",
    "NDDEV_COPILOT_CLI_INSTALLER_SHA256",
    "NDDEV_COPILOT_CLI_INSTALLER_SIZE",
    "NDDEV_COPILOT_CLI_CHECKSUMS_URL",
    "NDDEV_COPILOT_CLI_CHECKSUMS_SHA256",
    "NDDEV_COPILOT_CLI_CHECKSUMS_SIZE",
    "NDDEV_COPILOT_CLI_ASSET_URL",
    "NDDEV_COPILOT_CLI_ASSET_SHA256",
    "NDDEV_COPILOT_CLI_ASSET_SIZE",
    "NDDEV_COPILOT_CLI_INSTALL_TIMEOUT_SECONDS",
    "NDDEV_COPILOT_CLI_PROBE_TIMEOUT_SECONDS",
]
BUILDER_DOC_RUNTIME_LITERAL_PATTERNS = [
    r"\b0\.[1-9][0-9]*\.[0-9A-Za-z.+-]+\b",
    r"\b[1-9][0-9]*\.[0-9]+\.[0-9A-Za-z.+-]+\b",
    r"\bv[0-9]+\.[0-9]+\.[0-9A-Za-z.+-]+\b",
    r"\b20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]+Z\b",
    r"https://gh\.io/copilot-install",
    r"github/copilot-cli/releases",
]


def read_json(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain a JSON object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_manager() -> Any:
    spec = importlib.util.spec_from_file_location("nddev_github_copilot_cli", MANAGER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load manager module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_versions(errors: list[str]) -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = read_json("build/version.json")
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    baseline = read_json("references/copilot-cli-baseline.json")
    require(SEMVER.fullmatch(version) is not None, "VERSION is not SemVer", errors)
    require(build.get("schema_version") == 2, "build/version.json schema mismatch", errors)
    require(manifest.get("schema_version") == 2, "build/manifest.json schema mismatch", errors)
    require(contract.get("contract_version") == 3, "contract version mismatch", errors)
    require(build.get("build_version") == version, "build version mismatch", errors)
    require(manifest.get("build_version") == version, "manifest version mismatch", errors)
    require(
        build.get("nddev_builder_plugin_version") == version,
        "builder plugin version must track build version",
        errors,
    )
    require(contract.get("version_ref") == "build/version.json", "contract version_ref mismatch", errors)
    require(contract.get("manifest_ref") == "build/manifest.json", "contract manifest_ref mismatch", errors)
    require(PLACEHOLDER_MARKER not in json.dumps(contract), "contract contains placeholder marker", errors)
    require(build.get("copilot_cli_tested") == OFFICIAL["version"], "tested version mismatch", errors)
    require(build.get("copilot_cli_release_tag") == OFFICIAL["release_tag"], "release tag mismatch", errors)
    require(build.get("copilot_cli_release_published_at") == OFFICIAL["published_at"], "release date mismatch", errors)
    require(build.get("command") == OFFICIAL["command"], "command mismatch", errors)
    require(build.get("installer_url") == OFFICIAL["installer_url"], "installer URL mismatch", errors)
    require(build.get("installer_sha256") == OFFICIAL["installer_sha256"], "installer SHA256 mismatch", errors)
    release = baseline.get("release")
    installer = baseline.get("installer")
    runtime_baseline = baseline.get("runtime")
    require(isinstance(release, dict), "baseline release missing", errors)
    require(isinstance(installer, dict), "baseline installer missing", errors)
    require(isinstance(runtime_baseline, dict), "baseline runtime missing", errors)
    if isinstance(release, dict):
        require(release.get("tag") == build.get("copilot_cli_release_tag"), "baseline release tag mismatch", errors)
        require(release.get("published_at") == build.get("copilot_cli_release_published_at"), "baseline release date mismatch", errors)
        checksums = release.get("checksums")
        require(isinstance(checksums, dict), "baseline checksums missing", errors)
        if isinstance(checksums, dict):
            require(checksums.get("sha256") == OFFICIAL["checksums_sha256"], "baseline checksums SHA256 mismatch", errors)
            require(checksums.get("size") == OFFICIAL["checksums_size"], "baseline checksums size mismatch", errors)
    if isinstance(installer, dict):
        require(installer.get("url") == OFFICIAL["installer_url"], "baseline installer URL mismatch", errors)
        require(installer.get("sha256") == OFFICIAL["installer_sha256"], "baseline installer SHA256 mismatch", errors)
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
            require(runtime.get("tested_version") == build.get("copilot_cli_tested"), f"{owner} tested version mismatch", errors)
            require(runtime.get("release_tag") == build.get("copilot_cli_release_tag"), f"{owner} release tag mismatch", errors)
            require(runtime.get("baseline_ref") == build.get("runtime_baseline_ref"), f"{owner} baseline ref mismatch", errors)


def validate_assets(errors: list[str]) -> None:
    baseline = read_json("references/copilot-cli-baseline.json")
    assets = baseline.get("assets")
    require(isinstance(assets, dict), "baseline assets missing", errors)
    if isinstance(assets, dict):
        require(set(assets) == set(EXPECTED_ASSETS), "baseline asset set mismatch", errors)
        for name, (digest, size) in EXPECTED_ASSETS.items():
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
    support = baseline.get("platform_support")
    require(isinstance(support, dict), "platform support missing", errors)
    if isinstance(support, dict):
        require(support.get("supported") == EXPECTED_SUPPORTED_PLATFORMS, "platform supported list mismatch", errors)
        require(support.get("unsupported") == EXPECTED_UNSUPPORTED_PLATFORMS, "platform unsupported list mismatch", errors)


def validate_lifecycle_contracts(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    for owner, runtime in (
        ("manifest", manifest.get("runtime_launch")),
        ("contract", contract.get("runtime_launch")),
    ):
        require(isinstance(runtime, dict), f"{owner} runtime_launch missing", errors)
        if isinstance(runtime, dict):
            require(runtime.get("command") == "<absolute-target>/bin/copilot", f"{owner} launch command mismatch", errors)
            require(runtime.get("executable_source") == "validated-target-owned-github-release-asset", f"{owner} executable source mismatch", errors)
            require(runtime.get("token_environment_inheritance") == "stripped", f"{owner} token inheritance mismatch", errors)
            require(runtime.get("environment_inheritance") == "minimal-locale-and-terminal-allowlist", f"{owner} environment inheritance mismatch", errors)
            require(runtime.get("ambient_gh_fallback") == "blocked", f"{owner} gh fallback policy mismatch", errors)
            require(
                runtime.get("preflight_lock")
                == "exclusive target-internal lifecycle lock held through child completion and cleanup",
                f"{owner} launch lock scope mismatch",
                errors,
            )
            require(runtime.get("lock_released_before_child") is False, f"{owner} lock release contract mismatch", errors)
            require(runtime.get("lock_held_through_child_completion") is True, f"{owner} child lock contract mismatch", errors)
            require(
                runtime.get("executable_revalidation")
                == "target-owned executable inode and sha256 rechecked after argv/env construction before child exec",
                f"{owner} executable revalidation mismatch",
                errors,
            )
            require(
                runtime.get("lifecycle_mutations_blocked_while_launch_running") is True,
                f"{owner} launch mutation lock mismatch",
                errors,
            )
            require(runtime.get("requires_current_builder_plugin") is True, f"{owner} builder launch preflight mismatch", errors)
            require(runtime.get("blocks_user_managed_flags") == EXPECTED_BLOCKED_FLAGS, f"{owner} blocked launch flags mismatch", errors)
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
        require(safety.get("backup_pool_marker") == "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json", "backup pool marker mismatch", errors)
        require(safety.get("preexisting_backup_pool_collision") == "fail-closed-no-delete", "backup collision policy mismatch", errors)
        require(
            safety.get("restore_absent_managed_paths")
            == "remove-all-known-managed-paths-absent-from-validated-backup",
            "restore absent managed paths policy mismatch",
            errors,
        )
    transaction = manifest.get("transaction_policy")
    require(isinstance(transaction, dict), "manifest transaction_policy missing", errors)
    if isinstance(transaction, dict):
        require(transaction.get("lock") == "target-internal lifecycle directory", "transaction lock policy mismatch", errors)
        require(transaction.get("lock_path") == "<target>/.nddev-github-copilot-cli.lock", "transaction lock path mismatch", errors)
        require(
            transaction.get("new_target_bootstrap_lock")
            == "<target-parent>/.<target-name>.nddev-github-copilot-cli.bootstrap.lock",
            "transaction bootstrap lock path mismatch",
            errors,
        )
        require(transaction.get("private_current_user_parent_required") is True, "transaction parent privacy mismatch", errors)
        require(transaction.get("dangling_symlinks_fail_closed") is True, "transaction dangling symlink policy mismatch", errors)
        require(transaction.get("backup_pool_marker") == "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json", "transaction backup marker mismatch", errors)
        require(transaction.get("rollback_snapshot") == "managed bytes restored with 0600 managed-file modes", "transaction rollback snapshot mismatch", errors)
        require(
            transaction.get("restore_absent_managed_paths")
            == "remove-all-known-managed-paths-absent-from-validated-backup",
            "transaction restore absent managed paths mismatch",
            errors,
        )
    for owner, software in (
        ("manifest", manifest.get("software_install")),
        ("contract", contract.get("software_install")),
    ):
        require(isinstance(software, dict), f"{owner} software_install missing", errors)
        if isinstance(software, dict):
            require(software.get("supported_platforms") == EXPECTED_SUPPORTED_PLATFORMS, f"{owner} software platforms mismatch", errors)
            require(software.get("unsupported_platforms") == EXPECTED_UNSUPPORTED_PLATFORMS, f"{owner} unsupported platforms mismatch", errors)
            require(software.get("update_precondition") == "installed-or-safe-repairable-partial-target", f"{owner} update precondition mismatch", errors)
            require(software.get("absent_update_policy") == "domain-failure-install-first-zero-artifacts", f"{owner} absent update policy mismatch", errors)
            require(software.get("stage_policy") == "unique-private-mkdtemp-under-target-parent", f"{owner} stage policy mismatch", errors)


def validate_settings_common(profile_id: str, settings: dict[str, Any], errors: list[str]) -> None:
    require("memory" not in settings, f"{profile_id} must not define memory settings", errors)
    require(settings.get("autoUpdate") is False, f"{profile_id} autoUpdate must be false", errors)
    require(settings.get("autoUpdatesChannel") == "stable", f"{profile_id} update channel mismatch", errors)
    require(settings.get("remote") == "off", f"{profile_id} remote must be off", errors)
    require(settings.get("remoteExport") is False, f"{profile_id} remoteExport must be false", errors)
    require(settings.get("storeTokenPlaintext") is False, f"{profile_id} plaintext token storage must be false", errors)
    require(settings.get("toolSearch") is True, f"{profile_id} toolSearch must be true", errors)
    require(settings.get("disabledSkills") == [], f"{profile_id} disabledSkills mismatch", errors)
    require(settings.get("keepAlive") == "off", f"{profile_id} keepAlive mismatch", errors)
    require(settings.get("enabledPlugins") == {"nddev-builder@nddev-builder": True}, f"{profile_id} enabledPlugins mismatch", errors)
    require(settings.get("extraKnownMarketplaces") == {}, f"{profile_id} extraKnownMarketplaces mismatch", errors)
    sandbox = settings.get("sandbox")
    require(isinstance(sandbox, dict), f"{profile_id} sandbox missing", errors)
    if isinstance(sandbox, dict):
        require(sandbox.get("gitAuth") is False, f"{profile_id} sandbox gitAuth must be false", errors)
        require(sandbox.get("ghAuth") is False, f"{profile_id} sandbox ghAuth must be false", errors)
        seatbelt = sandbox.get("userPolicy", {}).get("seatbelt", {}) if isinstance(sandbox.get("userPolicy"), dict) else {}
        require(seatbelt.get("keychainAccess") is False, f"{profile_id} sandbox keychain access must be false", errors)


def validate_setups_and_profiles(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    require(manifest.get("setup_ids") == EXPECTED_SETUP_IDS, "manifest setup ids mismatch", errors)
    require(manifest.get("profile_ids") == EXPECTED_PROFILE_IDS, "manifest profile ids mismatch", errors)
    require(manifest.get("default_setup") == "nddev-builder", "manifest default setup mismatch", errors)
    require(manifest.get("default_profile") == "full-auto", "manifest default profile mismatch", errors)
    require(manifest.get("operation_intent") == EXPECTED_OPERATION_INTENT, "manifest operation intent mismatch", errors)
    require(manifest.get("managed_files") == EXPECTED_CURRENT_MANAGED_FILES, "manifest managed files mismatch", errors)
    managed_state = contract.get("managed_state")
    setup_system = contract.get("setup_system")
    require(isinstance(managed_state, dict), "contract managed_state missing", errors)
    require(isinstance(setup_system, dict), "contract setup_system missing", errors)
    if isinstance(managed_state, dict):
        require(managed_state.get("stamp_schema") == 2, "stamp schema mismatch", errors)
        require(managed_state.get("legacy_stamp_schema") == 1, "legacy stamp schema mismatch", errors)
        require(managed_state.get("managed_files") == EXPECTED_CURRENT_MANAGED_FILES[:-1], "contract managed files mismatch", errors)
        require(managed_state.get("legacy_state_policy") == "status-migrate-restore-remove-only-no-launch", "legacy state policy mismatch", errors)
    if isinstance(setup_system, dict):
        require(setup_system.get("setup_ids") == EXPECTED_SETUP_IDS, "contract setup ids mismatch", errors)
        require(setup_system.get("profile_ids") == EXPECTED_PROFILE_IDS, "contract profile ids mismatch", errors)
        require(setup_system.get("operation_intent") == EXPECTED_OPERATION_INTENT, "contract operation intent mismatch", errors)
        require(setup_system.get("default_profile") == "full-auto", "contract default profile mismatch", errors)
        require(setup_system.get("builder_default_on") is True, "builder default mismatch", errors)
    setup = read_json("setups/nddev-builder/setup.json")
    require(setup.get("id") == "nddev-builder", "setup id mismatch", errors)
    require(setup.get("managed_files") == EXPECTED_SETUP_MANAGED_FILES, "setup managed files mismatch", errors)
    require(setup.get("builder_marketplace") == "marketplaces/nddev-builder", "setup marketplace mismatch", errors)
    require(setup.get("builder_plugin") == "nddev-builder@nddev-builder", "setup builder plugin mismatch", errors)
    require(setup.get("builder_default_on") is True, "setup builder default mismatch", errors)
    for relative in EXPECTED_SETUP_MANAGED_FILES:
        require((ROOT / "setups" / "nddev-builder" / relative).is_file(), f"setup file missing: {relative}", errors)
    for profile_id in EXPECTED_PROFILE_IDS:
        profile = read_json(f"profiles/{profile_id}/profile.json")
        settings = read_json(f"profiles/{profile_id}/settings.json")
        permissions = read_json(f"profiles/{profile_id}/permissions-config.json")
        require(profile.get("id") == profile_id, f"{profile_id} id mismatch", errors)
        require(profile.get("managed_files") == EXPECTED_PROFILE_MANAGED_FILES, f"{profile_id} managed files mismatch", errors)
        require(permissions == {"locations": {}}, f"{profile_id} permissions-config mismatch", errors)
        validate_settings_common(profile_id, settings, errors)
        if profile_id == "full-auto":
            require(profile.get("default") is True, "full-auto must be default", errors)
            require(profile.get("launch_args") == EXPECTED_FULL_AUTO_LAUNCH_ARGS, "full-auto launch args mismatch", errors)
            require(settings.get("askUser") is False, "full-auto askUser mismatch", errors)
            require(settings.get("stayInAutopilot") is True, "full-auto autopilot mismatch", errors)
            require("permissions" not in settings, "full-auto must not disable bypass permissions mode", errors)
            sandbox = settings.get("sandbox", {})
            require(sandbox.get("enabled") is False, "full-auto sandbox enabled mismatch", errors)
            require(sandbox.get("allowBypass") is True, "full-auto sandbox bypass mismatch", errors)
        if profile_id == "safe":
            require(profile.get("default") is False, "safe default mismatch", errors)
            require(profile.get("launch_args") == EXPECTED_SAFE_LAUNCH_ARGS, "safe launch args mismatch", errors)
            require(settings.get("askUser") is True, "safe askUser mismatch", errors)
            require(settings.get("stayInAutopilot") is False, "safe autopilot mismatch", errors)
            sandbox = settings.get("sandbox", {})
            require(sandbox.get("enabled") is True, "safe sandbox enabled mismatch", errors)
            require(sandbox.get("allowBypass") is False, "safe sandbox bypass mismatch", errors)
            network = sandbox.get("userPolicy", {}).get("network", {}) if isinstance(sandbox.get("userPolicy"), dict) else {}
            require(network.get("allowLocalNetwork") is False, "safe local network mismatch", errors)
            require(settings.get("permissions") == {"disableBypassPermissionsMode": "disable"}, "safe deny-bypass mismatch", errors)
            require(not any(arg.startswith("--allow") or arg in {"--allow-all", "--yolo", "--mode=autopilot"} for arg in profile.get("launch_args", [])), "safe must not use allow-all launch flags", errors)


def validate_markdown_links(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(BUILDER_ROOT.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)} has escaped markdown link: {raw_target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)} references missing path: {raw_target}")


def validate_skill_file(path: Path, expected_name: str, entry_text: list[str], errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"{path.relative_to(ROOT)} missing frontmatter", errors)
    end = text.find("\n---\n", 4)
    require(end != -1, f"{path.relative_to(ROOT)} frontmatter not closed", errors)
    frontmatter = text[4:end] if end != -1 else ""
    require(f"name: {expected_name}" in frontmatter, f"{expected_name} skill name mismatch", errors)
    require("description:" in frontmatter, f"{expected_name} skill description missing", errors)
    require(SKILL_NAME.fullmatch(expected_name) is not None, f"{expected_name} invalid skill name", errors)
    if expected_name == "nddev-builder":
        entry_text.append(text)
    validate_markdown_links(path, errors)


def validate_builder(errors: list[str]) -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = read_json("build/version.json")
    contract = read_json("config/nddev-contract.json")
    manifest = read_json("build/manifest.json")
    marketplace = read_json("marketplaces/nddev-builder/.github/plugin/marketplace.json")
    plugin = read_json("marketplaces/nddev-builder/plugins/nddev-builder/plugin.json")
    hooks = read_json("marketplaces/nddev-builder/plugins/nddev-builder/hooks.json")
    mcp = read_json("marketplaces/nddev-builder/plugins/nddev-builder/.mcp.json")
    builder = contract.get("builder_capability")
    manifest_builder = manifest.get("builder_capability")
    require(isinstance(builder, dict), "contract builder missing", errors)
    require(isinstance(manifest_builder, dict), "manifest builder missing", errors)
    for owner, value in (("contract", builder), ("manifest", manifest_builder)):
        if isinstance(value, dict):
            require(value.get("mode") == "copilot-native-local-marketplace-install", f"{owner} builder mode mismatch", errors)
            require(value.get("source_root") == "marketplaces/nddev-builder", f"{owner} builder source root mismatch", errors)
            require(value.get("plugin_spec") == "nddev-builder@nddev-builder", f"{owner} builder spec mismatch", errors)
            require(value.get("installed_root") == "installed-plugins/nddev-builder/nddev-builder", f"{owner} builder installed root mismatch", errors)
            require(value.get("manual_runtime_projection") is False, f"{owner} builder manual projection mismatch", errors)
            require(value.get("default_on") is True, f"{owner} builder default_on mismatch", errors)
    require(marketplace.get("name") == "nddev-builder", "marketplace name mismatch", errors)
    require(isinstance(marketplace.get("owner"), dict), "marketplace owner missing", errors)
    require(marketplace.get("metadata", {}).get("version") == build.get("nddev_builder_plugin_version"), "marketplace version mismatch", errors)
    require(marketplace.get("metadata", {}).get("version") == version, "marketplace version must match VERSION", errors)
    plugins = marketplace.get("plugins")
    require(isinstance(plugins, list) and len(plugins) == 1, "marketplace must contain one plugin", errors)
    if isinstance(plugins, list) and plugins:
        entry = plugins[0]
        require(isinstance(entry, dict), "marketplace plugin entry must be object", errors)
        if isinstance(entry, dict):
            require(entry.get("name") == "nddev-builder", "marketplace plugin name mismatch", errors)
            require(entry.get("source") == "plugins/nddev-builder", "marketplace plugin source mismatch", errors)
            require(entry.get("version") == build.get("nddev_builder_plugin_version"), "marketplace plugin version mismatch", errors)
            require(entry.get("version") == version, "marketplace plugin version must match VERSION", errors)
            require(entry.get("strict") is True, "marketplace strict flag mismatch", errors)
    require("schema_version" not in plugin, "plugin.json must not use schema_version", errors)
    require("strict" not in plugin, "plugin.json strict belongs to marketplace entries", errors)
    require(plugin.get("name") == "nddev-builder", "builder plugin name mismatch", errors)
    require(plugin.get("version") == build.get("nddev_builder_plugin_version"), "builder plugin version mismatch", errors)
    require(plugin.get("version") == version, "builder plugin version must match VERSION", errors)
    require(plugin.get("skills") == "skills/", "builder skills path mismatch", errors)
    require(plugin.get("agents") == "agents/", "builder agents path mismatch", errors)
    require(plugin.get("hooks") == "hooks.json", "builder hooks path mismatch", errors)
    require(plugin.get("mcpServers") == ".mcp.json", "builder MCP path mismatch", errors)
    require(mcp == {"mcpServers": {}}, "builder MCP config mismatch", errors)
    require(hooks.get("version") == 1, "builder hooks schema mismatch", errors)
    require(isinstance(hooks.get("hooks"), dict), "builder hooks object missing", errors)
    if isinstance(hooks.get("hooks"), dict):
        require("agentStop" in hooks["hooks"], "builder agentStop hook missing", errors)
    agent_path = BUILDER_ROOT / "agents" / "nddev-builder.agent.md"
    require(agent_path.is_file(), "builder agent missing", errors)
    if agent_path.is_file():
        agent_text = agent_path.read_text(encoding="utf-8")
        require(agent_text.startswith("---\n"), "builder agent frontmatter missing", errors)
        require("description:" in agent_text, "builder agent description missing", errors)
        validate_markdown_links(agent_path, errors)
    skill_root = BUILDER_ROOT / "skills"
    actual_skills = sorted(path.name for path in skill_root.iterdir() if path.is_dir())
    require(actual_skills == sorted(EXPECTED_BUILDER_SKILLS), "builder skill set mismatch", errors)
    entry_text: list[str] = []
    for skill in EXPECTED_BUILDER_SKILLS:
        validate_skill_file(skill_root / skill / "SKILL.md", skill, entry_text, errors)
    if entry_text:
        for skill in EXPECTED_BUILDER_SKILLS:
            require(skill in entry_text[0], f"entry skill does not route to {skill}", errors)
    for relative in EXPECTED_BUILDER_REFERENCES:
        path = BUILDER_ROOT / relative
        require(path.is_file(), f"builder reference missing: {relative}", errors)
        if path.is_file():
            validate_markdown_links(path, errors)
    require(not (ROOT / "plugins").exists(), "legacy public plugins/ tree must be removed", errors)


def validate_builder_docs_have_no_runtime_literals(errors: list[str]) -> None:
    docs: list[Path] = []
    docs.extend(sorted((BUILDER_ROOT / "skills").glob("*/SKILL.md")))
    docs.extend(sorted((BUILDER_ROOT / "references").glob("*.md")))
    docs.extend(sorted((BUILDER_ROOT / "agents").glob("*.md")))
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for pattern in BUILDER_DOC_RUNTIME_LITERAL_PATTERNS:
            if re.search(pattern, text):
                errors.append(
                    f"builder doc duplicates volatile release/runtime literal: {path.relative_to(ROOT)}"
                )


def release_workflow_paths(name: str, errors: list[str]) -> list[str]:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^      {re.escape(name)}: >-\n((?:        .+\n?)+)", text, flags=re.MULTILINE)
    if match is None:
        errors.append(f"release workflow missing {name}")
        return []
    values: list[str] = []
    for line in match.group(1).splitlines():
        values.extend(line.split())
    return values


def release_root_for_reference(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    path = raw.split(":", 1)[0]
    if path.startswith("<") or path.startswith("http://") or path.startswith("https://"):
        return None
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if not relative.parts:
        return None
    return relative.parts[0]


def contract_release_roots(manifest: dict[str, Any], contract: dict[str, Any]) -> set[str]:
    roots = {"build", "cli-tools", "config", "references"}
    for raw in (
        manifest.get("source_root"),
        manifest.get("profile_root"),
        manifest.get("runtime_compatibility", {}).get("baseline_ref"),
        manifest.get("runtime_compatibility", {}).get("version_ref"),
        manifest.get("builder_capability", {}).get("source_root"),
        manifest.get("builder_capability", {}).get("marketplace_manifest"),
        manifest.get("builder_capability", {}).get("plugin_root"),
        manifest.get("builder_capability", {}).get("plugin_manifest"),
        contract.get("manifest_ref"),
        contract.get("version_ref"),
        contract.get("setup_system", {}).get("catalog_root"),
        contract.get("setup_system", {}).get("profile_root"),
        contract.get("runtime_compatibility", {}).get("baseline_ref"),
        contract.get("runtime_compatibility", {}).get("version_ref"),
        contract.get("builder_capability", {}).get("source_root"),
        contract.get("builder_capability", {}).get("marketplace_manifest"),
        contract.get("builder_capability", {}).get("plugin_root"),
        contract.get("builder_capability", {}).get("manifest"),
    ):
        root = release_root_for_reference(raw)
        if root is not None:
            roots.add(root)
    for profile in manifest.get("permission_policy", {}).get("profiles", {}).values():
        if isinstance(profile, dict):
            for key in ("settings_ref", "permissions_ref", "launch_args_ref"):
                root = release_root_for_reference(profile.get(key))
                if root is not None:
                    roots.add(root)
    for profile in contract.get("permission_profiles", {}).values():
        if isinstance(profile, dict):
            for key in ("settings_ref", "permissions_ref", "profile_ref"):
                root = release_root_for_reference(profile.get(key))
                if root is not None:
                    roots.add(root)
    return roots


def validate_release_paths(errors: list[str]) -> None:
    manifest = read_json("build/manifest.json")
    contract = read_json("config/nddev-contract.json")
    archive_paths = release_workflow_paths("archive_paths", errors)
    runtime_paths = release_workflow_paths("runtime_paths", errors)
    require(archive_paths == EXPECTED_ARCHIVE_RELEASE_PATHS, "release archive paths mismatch", errors)
    require(runtime_paths == EXPECTED_RUNTIME_RELEASE_PATHS, "release runtime paths mismatch", errors)
    for owner, values in (("archive_paths", archive_paths), ("runtime_paths", runtime_paths)):
        for raw in values:
            relative = Path(raw)
            require(not relative.is_absolute(), f"{owner} contains absolute path: {raw}", errors)
            require(".." not in relative.parts, f"{owner} contains parent traversal: {raw}", errors)
            require((ROOT / relative).exists(), f"{owner} path does not exist: {raw}", errors)
            require(raw not in FORBIDDEN_RELEASE_PATHS, f"{owner} contains obsolete root: {raw}", errors)
        for forbidden in FORBIDDEN_RELEASE_PATHS:
            require(forbidden not in values, f"{owner} must not package obsolete {forbidden}/", errors)
    for root in sorted(contract_release_roots(manifest, contract)):
        require(root in archive_paths, f"archive_paths missing contract root: {root}", errors)
        require(root in runtime_paths, f"runtime_paths missing contract root: {root}", errors)
        require((ROOT / root).exists(), f"contract root does not exist: {root}", errors)


def validate_manager_contract(errors: list[str]) -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manager_source = MANAGER_PATH.read_text(encoding="utf-8")
    for pattern in FORBIDDEN_MANAGER_SOURCE_PATTERNS:
        require(pattern not in manager_source, f"manager exposes forbidden test switch: {pattern}", errors)
    try:
        manager = load_manager()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"manager import failed: {exc}")
        return
    require(manager.VERSION == version, "manager VERSION mismatch", errors)
    require(manager.STAMP_SCHEMA == 2, "manager stamp schema mismatch", errors)
    require(manager.DEFAULT_SETUP_ID == "nddev-builder", "manager default setup mismatch", errors)
    require(manager.DEFAULT_PROFILE_ID == "full-auto", "manager default profile mismatch", errors)
    require(list(manager.SETUP_MANAGED_FILES) == EXPECTED_SETUP_MANAGED_FILES, "manager setup managed files mismatch", errors)
    require(list(manager.PROFILE_MANAGED_FILES) == EXPECTED_PROFILE_MANAGED_FILES, "manager profile managed files mismatch", errors)
    require(sorted(manager.EXPECTED_BUILDER_SKILLS) == sorted(EXPECTED_BUILDER_SKILLS), "manager builder skills mismatch", errors)
    require(sorted(manager.TARGET_SCOPE_FLAGS) == sorted(EXPECTED_BLOCKED_FLAGS), "manager target override flags mismatch", errors)
    for argv in (
        ["list", "--json"],
        ["plan", "--target", "/tmp/nddev-copilot"],
        ["install", "--target", "/tmp/nddev-copilot", "--profile", "safe"],
        ["migrate", "--target", "/tmp/nddev-copilot"],
        ["builder-status", "--target", "/tmp/nddev-copilot", "--json"],
        ["install-builder", "--target", "/tmp/nddev-copilot", "--json"],
        ["launch", "--target", "/tmp/nddev-copilot", "--", "--help"],
    ):
        try:
            manager.parse_args(list(argv))
        except SystemExit as exc:
            errors.append(f"manager parse_args rejected {argv}: {exc}")


def make_temp_base() -> Path:
    root = Path("/tmp") if Path("/tmp").exists() else Path(tempfile.gettempdir())
    base = Path(tempfile.mkdtemp(prefix="nddev-copilot-public-smoke.", dir=root))
    base.chmod(0o700)
    return base


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def owner_file(path: Path, content: str) -> None:
    owner_bytes(path, content.encode("utf-8"))


def owner_bytes(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def expect_manager_error(errors: list[str], label: str, fn: Any) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ in {"CopilotCliSetupError", "ConcurrentTargetChange"}:
            return
        errors.append(f"{label} raised unexpected error type: {exc}")
        return
    errors.append(f"{label} did not fail closed")


def expect_manager_error_contains(errors: list[str], label: str, fragment: str, fn: Any) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ not in {"CopilotCliSetupError", "ConcurrentTargetChange"}:
            errors.append(f"{label} raised unexpected error type: {exc}")
            return
        require(fragment in str(exc), f"{label} error message mismatch: {exc}", errors)
        return
    errors.append(f"{label} did not fail closed")


def write_legacy_target(manager: Any, target: Path) -> None:
    private_dir(target)
    settings = b"{}\n"
    instructions = b"legacy instructions\n"
    owner_bytes(target / "settings.json", settings)
    owner_bytes(target / "copilot-instructions.md", instructions)
    stamp = {
        "schema_version": manager.LEGACY_STAMP_SCHEMA,
        "product_name": manager.PRODUCT_NAME,
        "build_version": "0.1.0",
        "setup_id": "nddev-builder",
        "canonical_target": str(target.resolve()),
        "managed_files": {
            "settings.json": manager.managed_digest(Path("settings.json"), settings),
            "copilot-instructions.md": manager.managed_digest(Path("copilot-instructions.md"), instructions),
        },
        "builder_projection": {},
        "launch_args": [],
    }
    owner_bytes(target / manager.STAMP_NAME, manager.canonical_json(stamp))


def fake_current_software_metadata(manager: Any, *, inode: int = 1, digest: str | None = None) -> dict[str, Any]:
    return {
        "version": manager.TESTED_VERSION,
        "release_tag": manager.RELEASE_TAG,
        "asset": {"name": "copilot-test.tar.gz"},
        "checksums": {},
        "artifact_verification": {"size_verified": True, "sha256_verified": True},
        "executable": f"bin/{manager.COMMAND_NAME}",
        "binary": {
            "size": 1,
            "sha256": digest or ("0" * 64),
            "mode": "0700",
            "identity": {"device": 1, "inode": inode},
        },
        "receipt_sha256": "1" * 64,
    }


def patch_launch_preconditions(manager: Any, *, changing_metadata: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    originals = {
        "software_status": manager.software_status,
        "current_software_metadata": manager.current_software_metadata,
        "builder_status": manager.builder_status,
        "subprocess_run": manager.subprocess.run,
    }
    calls = {"metadata": 0}

    def software_status(_target: Path) -> dict[str, Any]:
        return {
            "ok": True,
            "state": "installed",
            "installed": True,
            "current": True,
            "target": str(_target),
            "version": manager.TESTED_VERSION,
            "executable": str(manager.copilot_executable(_target)),
        }

    def current_software_metadata(_target: Path) -> dict[str, Any]:
        calls["metadata"] += 1
        inode = calls["metadata"] if changing_metadata else 1
        digest = f"{calls['metadata']:064x}" if changing_metadata else None
        return fake_current_software_metadata(manager, inode=inode, digest=digest)

    def builder_status(_target: Path) -> dict[str, Any]:
        return {
            "ok": True,
            "target": str(_target),
            "installed": True,
            "current": True,
            "state": "installed",
            "plugin": manager.BUILDER_PLUGIN_SPEC,
        }

    manager.software_status = software_status
    manager.current_software_metadata = current_software_metadata
    manager.builder_status = builder_status
    return originals, calls


def restore_launch_preconditions(manager: Any, originals: dict[str, Any]) -> None:
    manager.software_status = originals["software_status"]
    manager.current_software_metadata = originals["current_software_metadata"]
    manager.builder_status = originals["builder_status"]
    manager.subprocess.run = originals["subprocess_run"]


def validate_adversarial_smokes(errors: list[str]) -> None:
    try:
        manager = load_manager()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"manager import failed for adversarial smokes: {exc}")
        return

    base = make_temp_base()
    try:
        parent = private_dir(base / "mode-parent")
        target = private_dir(parent / "copilot")
        target.chmod(0o777)
        expect_manager_error(errors, "0777 target status", lambda: manager.inspect_target(target))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "lock-parent")
        target = private_dir(parent / "copilot")
        external = private_dir(base / "external-lock")
        marker = external / "marker.txt"
        owner_file(marker, "preserve\n")
        os.symlink(external, manager.lock_path(target))
        expect_manager_error(
            errors,
            "precreated symlink lock path",
            lambda: manager.mutate_setup(target, "nddev-builder", "full-auto", "install"),
        )
        require(marker.read_text(encoding="utf-8") == "preserve\n", "external lock marker changed", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "bootstrap-lock-parent")
        target = parent / "copilot"
        external = private_dir(base / "external-bootstrap-lock")
        marker = external / "marker.txt"
        owner_file(marker, "preserve\n")
        os.symlink(external, manager.bootstrap_lock_path(target))
        expect_manager_error(
            errors,
            "precreated symlink bootstrap lock path",
            lambda: manager.mutate_setup(target, "nddev-builder", "full-auto", "install"),
        )
        require(marker.read_text(encoding="utf-8") == "preserve\n", "external bootstrap lock marker changed", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "backup-symlink-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        external = private_dir(base / "external-backup")
        marker = external / "marker.txt"
        owner_file(marker, "preserve\n")
        os.symlink(external, manager.backup_pool(target.resolve()))
        expect_manager_error(
            errors,
            "precreated symlink backup pool",
            lambda: manager.mutate_setup(target.resolve(), "nddev-builder", "safe", "switch"),
        )
        require(marker.read_text(encoding="utf-8") == "preserve\n", "external backup marker changed", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "backup-slot-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        pool = manager.ensure_backup_pool(target.resolve())
        external = private_dir(base / "external-slot")
        marker = external / "marker.txt"
        owner_file(marker, "preserve\n")
        os.symlink(external, pool / "0")
        expect_manager_error(
            errors,
            "precreated symlink backup slot",
            lambda: manager.mutate_setup(target.resolve(), "nddev-builder", "safe", "switch"),
        )
        require(marker.read_text(encoding="utf-8") == "preserve\n", "external slot marker changed", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "sticky-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        state = manager.inspect_target(target.resolve())
        require(state.get("state") == "managed", "sticky-temp managed target failed", errors)
        manager.remove_setup(target.resolve())
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "operation-intent-parent")
        missing_switch = parent / "missing-switch"
        expect_manager_error_contains(
            errors,
            "switch missing target",
            "switch requires a current clean managed target",
            lambda: manager.mutate_setup(missing_switch, "nddev-builder", "safe", "switch"),
        )
        require(not missing_switch.exists(), "switch created a missing target", errors)
        missing_migrate = parent / "missing-migrate"
        expect_manager_error_contains(
            errors,
            "migrate missing target",
            "migrate requires a legacy-managed target",
            lambda: manager.mutate_setup(missing_migrate, "nddev-builder", "full-auto", "migrate"),
        )
        require(not missing_migrate.exists(), "migrate created a missing target", errors)

        unmanaged = private_dir(parent / "unmanaged")
        unmanaged_marker = unmanaged / "marker.txt"
        owner_file(unmanaged_marker, "preserve\n")
        expect_manager_error_contains(
            errors,
            "switch unmanaged target",
            "switch requires a current clean managed target",
            lambda: manager.mutate_setup(unmanaged, "nddev-builder", "safe", "switch"),
        )
        expect_manager_error_contains(
            errors,
            "migrate unmanaged target",
            "migrate requires a legacy-managed target",
            lambda: manager.mutate_setup(unmanaged, "nddev-builder", "full-auto", "migrate"),
        )
        require(unmanaged_marker.read_text(encoding="utf-8") == "preserve\n", "invalid operation changed unmanaged marker", errors)
        require(not (unmanaged / manager.STAMP_NAME).exists(), "invalid operation stamped unmanaged target", errors)

        managed = parent / "managed"
        manager.mutate_setup(managed, "nddev-builder", "full-auto", "install")
        expect_manager_error_contains(
            errors,
            "install managed target",
            "install requires an absent or unmanaged target",
            lambda: manager.mutate_setup(managed.resolve(), "nddev-builder", "safe", "install"),
        )
        expect_manager_error_contains(
            errors,
            "migrate current target",
            "migrate requires a legacy-managed target",
            lambda: manager.mutate_setup(managed.resolve(), "nddev-builder", "full-auto", "migrate"),
        )
        state = manager.inspect_target(managed.resolve())
        require(state.get("profile_id") == "full-auto", "invalid operation changed managed profile", errors)

        legacy = parent / "legacy"
        write_legacy_target(manager, legacy)
        expect_manager_error_contains(
            errors,
            "install legacy target",
            "install requires an absent or unmanaged target",
            lambda: manager.mutate_setup(legacy.resolve(), "nddev-builder", "full-auto", "install"),
        )
        migrated = manager.mutate_setup(legacy.resolve(), "nddev-builder", "full-auto", "migrate")
        require(migrated.get("state") == "managed", "migrate did not convert legacy target", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "restore-retired-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        canonical_target = target.resolve()
        stale = canonical_target / "plugins" / "nddev-builder" / "plugin.json"
        manager.ensure_real_parent(stale, canonical_target)
        owner_file(stale, "retired managed projection\n")
        unrelated = canonical_target / "unmanaged-note.txt"
        owner_file(unrelated, "preserve\n")
        manager.mutate_setup(canonical_target, "nddev-builder", "safe", "switch")
        require(stale.exists(), "setup switch removed stale projection before restore smoke", errors)
        restored = manager.restore_backup(canonical_target, 0)
        require(restored.get("profile_id") == "full-auto", "restore did not restore backed up profile", errors)
        require(not stale.exists(), "restore preserved retired managed projection", errors)
        require(unrelated.read_text(encoding="utf-8") == "preserve\n", "restore changed unrelated unmanaged file", errors)
        post = manager.inspect_target(canonical_target)
        require(post.get("state") == "managed", "post-restore target is not clean managed", errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    old_path = os.environ.get("PATH")
    try:
        fake_bin = private_dir(base / "fake-bin")
        for name in ("bash", "gh"):
            tool = fake_bin / name
            owner_file(tool, "#!/usr/bin/env sh\nexit 88\n")
            tool.chmod(0o700)
        os.environ["PATH"] = str(fake_bin)
        env = manager.sanitized_subprocess_env(base / "home", base / "cache", base / "tmp")
        require(env.get("PATH") == manager.DETERMINISTIC_PATH, "sanitized env inherited fake PATH", errors)
        target = private_dir(base / "env-target")
        child_env = manager.isolated_child_environment(target)
        require(str(fake_bin) not in child_env.get("PATH", ""), "launch env inherited fake PATH", errors)
        first_path = child_env.get("PATH", "").split(os.pathsep)[0]
        require(first_path.endswith("no-ambient-bin"), "launch env did not prepend gh blocker", errors)
        require((Path(first_path) / "gh").is_file(), "gh blocker missing", errors)
        bash = manager.require_trusted_executable(manager.BASH_CANDIDATES, "bash")
        require(bash.parent != fake_bin, "trusted bash resolved from fake PATH", errors)
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "launch-lock-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        originals, calls = patch_launch_preconditions(manager)
        mutation_blocked = {"value": False}

        class Completed:
            returncode = 37

        def fake_run(argv: list[str], *, cwd: Path, env: dict[str, str], check: bool, timeout: Any) -> Completed:
            require(calls["metadata"] >= 2, "launch did not revalidate executable before child", errors)
            require(manager.lock_path(cwd).exists(), "launch lifecycle lock missing during child", errors)
            require(env.get("COPILOT_HOME") == str(cwd), "launch COPILOT_HOME escaped target", errors)
            path_parts = env.get("PATH", "").split(os.pathsep)
            require(path_parts[0] == str(cwd / "runtime" / "no-ambient-bin"), "launch env gh blocker escaped target", errors)
            require(os.pathsep.join(path_parts[1:]) == manager.DETERMINISTIC_PATH, "launch env inherited ambient PATH", errors)
            try:
                manager.mutate_setup(cwd, "nddev-builder", "safe", "switch")
            except Exception as exc:  # noqa: BLE001
                if exc.__class__.__name__ in {"CopilotCliSetupError", "ConcurrentTargetChange"} and "locked" in str(exc):
                    mutation_blocked["value"] = True
                else:
                    errors.append(f"launch concurrent mutation raised unexpected error: {exc}")
            else:
                errors.append("launch concurrent mutation was not blocked")
            require(argv[0] == str(manager.copilot_executable(cwd)), "launch executable argv escaped target", errors)
            require(check is False and timeout is None, "launch child subprocess posture mismatch", errors)
            return Completed()

        manager.subprocess.run = fake_run
        try:
            code = manager.launch_copilot(target.resolve(), ["--version"])
            require(code == 37, "launch did not forward child exit code", errors)
            require(mutation_blocked["value"], "launch did not block concurrent lifecycle mutation", errors)
            state = manager.inspect_target(target.resolve())
            require(state.get("profile_id") == "full-auto", "blocked launch mutation changed profile", errors)
            require(not manager.lock_path(target.resolve()).exists(), "launch lifecycle lock was not released", errors)
        finally:
            restore_launch_preconditions(manager, originals)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base = make_temp_base()
    try:
        parent = private_dir(base / "launch-revalidate-parent")
        target = parent / "copilot"
        manager.mutate_setup(target, "nddev-builder", "full-auto", "install")
        originals, _calls = patch_launch_preconditions(manager, changing_metadata=True)
        run_called = {"value": False}

        def fake_run_changed(*_args: Any, **_kwargs: Any) -> Any:
            run_called["value"] = True
            raise AssertionError("subprocess must not run after executable fingerprint drift")

        manager.subprocess.run = fake_run_changed
        try:
            expect_manager_error(
                errors,
                "launch executable revalidation",
                lambda: manager.launch_copilot(target.resolve(), ["--version"]),
            )
            require(not run_called["value"], "launch ran child after executable fingerprint drift", errors)
        finally:
            restore_launch_preconditions(manager, originals)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def validate_absent_retired_markers(errors: list[str]) -> None:
    own_path = Path(__file__).resolve()
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.resolve() == own_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PLACEHOLDER_MARKER in text.lower():
            errors.append(f"placeholder marker found in {path.relative_to(ROOT)}")
        if "memory.enabled" in text:
            errors.append(f"undocumented memory.enabled found in {path.relative_to(ROOT)}")
    for retired in ("setups/safe/settings.json", "setups/full-auto/settings.json", "setups/balanced/settings.json"):
        require(not (ROOT / retired).exists(), f"retired setup path still exists: {retired}", errors)


def main() -> int:
    errors: list[str] = []
    try:
        validate_versions(errors)
        validate_assets(errors)
        validate_lifecycle_contracts(errors)
        validate_setups_and_profiles(errors)
        validate_builder(errors)
        validate_builder_docs_have_no_runtime_literals(errors)
        validate_release_paths(errors)
        validate_manager_contract(errors)
        validate_adversarial_smokes(errors)
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
