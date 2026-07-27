#!/usr/bin/env python3
"""Transactional setup manager for an explicit GitHub Copilot CLI home."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
MARKETPLACE_ROOT = ROOT / "marketplaces" / "nddev-builder"
BUILDER_ROOT = MARKETPLACE_ROOT / "plugins" / "nddev-builder"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-github-copilot-cli-app"
COMMAND_NAME = "copilot"
STAMP_NAME = "NDDEV-GITHUB-COPILOT-CLI-SETUP.json"
BACKUP_POOL_NAME = "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json"
BACKUP_NAME = "NDDEV-GITHUB-COPILOT-CLI-BACKUP.json"
BASELINE_REF = ROOT / "references" / "copilot-cli-baseline.json"
TARGET_LOCK_NAME = ".nddev-github-copilot-cli.lock"
TESTED_VERSION = "1.0.75"
RELEASE_TAG = "v1.0.75"
STAMP_SCHEMA = 2
LEGACY_STAMP_SCHEMA = 1
DEFAULT_SETUP_ID = "nddev-builder"
DEFAULT_PROFILE_ID = "full-auto"
BUILDER_MARKETPLACE_NAME = "nddev-builder"
BUILDER_PLUGIN_NAME = "nddev-builder"
BUILDER_PLUGIN_SPEC = "nddev-builder@nddev-builder"
BUILDER_INSTALLED_ROOT = Path("installed-plugins") / BUILDER_MARKETPLACE_NAME / BUILDER_PLUGIN_NAME
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
INSTALLER_MAX_BYTES = 128 * 1024
CHECKSUMS_MAX_BYTES = 256 * 1024
SOFTWARE_FILE_MAX_BYTES = 256 * 1024 * 1024
INSTALL_TIMEOUT_SECONDS = 900
PROBE_TIMEOUT_SECONDS = 30
PROCESS_TIMEOUT_SECONDS = 120
PROCESS_OUTPUT_MAX_BYTES = 256 * 1024
BUILDER_TREE_MAX_BYTES = 8 * 1024 * 1024
BUILDER_TREE_MAX_FILES = 256
DETERMINISTIC_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
BASH_CANDIDATES = (Path("/bin/bash"), Path("/usr/bin/bash"))
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PROFILE_ID_PATTERN = SETUP_ID_PATTERN
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
MANAGED_SETTINGS_KEYS = (
    "askUser",
    "autoUpdate",
    "autoUpdatesChannel",
    "disabledSkills",
    "enabledPlugins",
    "extraKnownMarketplaces",
    "hooks",
    "ide",
    "includeCoAuthoredBy",
    "keepAlive",
    "permissions",
    "remote",
    "remoteExport",
    "sandbox",
    "shellShortcut",
    "stayInAutopilot",
    "storeTokenPlaintext",
    "toolSearch",
)
SETUP_MANAGED_FILES = [
    "copilot-instructions.md",
    "instructions/nddev-builder.instructions.md",
    "mcp-config.json",
]
PROFILE_MANAGED_FILES = [
    "settings.json",
    "permissions-config.json",
]
CATALOG_MANAGED_FILES = [
    *PROFILE_MANAGED_FILES,
    *SETUP_MANAGED_FILES,
]
CURRENT_MANAGED_PATHS = (
    Path("settings.json"),
    Path("permissions-config.json"),
    Path("copilot-instructions.md"),
    Path("instructions") / "nddev-builder.instructions.md",
    Path("mcp-config.json"),
    Path(STAMP_NAME),
)
LEGACY_MANAGED_PATHS = (
    Path("settings.json"),
    Path("permissions-config.json"),
    Path("copilot-instructions.md"),
    Path("instructions") / "nddev-builder.instructions.md",
    Path("mcp-config.json"),
    Path("plugins") / "nddev-builder" / "plugin.json",
    Path("plugins") / "nddev-builder" / "skills" / "nddev-builder" / "SKILL.md",
    Path("plugins") / "nddev-builder" / "agents" / "nddev-builder.agent.md",
    Path("plugins") / "nddev-builder" / "hooks.json",
    Path("skills") / "nddev-builder" / "SKILL.md",
    Path("agents") / "nddev-builder.agent.md",
    Path("hooks") / "nddev-builder.json",
    Path(STAMP_NAME),
)
MANAGED_PATHS = CURRENT_MANAGED_PATHS
ALL_KNOWN_MANAGED_PATHS = tuple(dict.fromkeys((*CURRENT_MANAGED_PATHS, *LEGACY_MANAGED_PATHS)))
STAMP_KEYS_V2 = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "profile_id",
    "canonical_target",
    "managed_files",
    "builder_native_plugin",
    "launch_args",
}
STAMP_KEYS_V1 = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
    "launch_args",
}
BACKUP_KEYS_V2 = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "source_profile_id",
    "managed_files",
    "created_at",
}
BACKUP_KEYS_V1 = BACKUP_KEYS_V2 - {"source_profile_id"}
BACKUP_POOL_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
}
TOKEN_ENV_NAMES = {
    "COPILOT_ACCESS_TOKEN",
    "COPILOT_GITHUB_TOKEN",
    "GITHUB_COPILOT_API_TOKEN",
    "GITHUB_COPILOT_GIT_TOKEN",
    "GITHUB_COPILOT_OIDC_MCP_TOKEN",
    "GH_TOKEN",
    "GITHUB_COPILOT_TOKEN",
    "GITHUB_TOKEN",
    "SSH_ASKPASS",
    "SSH_AUTH_SOCK",
    "GIT_ASKPASS",
}
TARGET_SCOPE_FLAGS = {
    "--add-dir",
    "--add-github-mcp-tool",
    "--add-github-mcp-toolset",
    "-C",
    "--config-dir",
    "--additional-mcp-config",
    "--agent",
    "--allow-all",
    "--allow-all-mcp-server-instructions",
    "--allow-all-tools",
    "--allow-all-paths",
    "--allow-all-urls",
    "--allow-tool",
    "--allow-url",
    "--ask-user",
    "--deny-tool",
    "--deny-url",
    "--available-tools",
    "--bash-env",
    "--connect",
    "--context",
    "--disable-builtin-mcps",
    "--disable-mcp-server",
    "--disallow-temp-dir",
    "--effort",
    "--enable-all-github-mcp-tools",
    "--enable-memory",
    "--mode",
    "--model",
    "--no-ask-user",
    "--no-remote",
    "--no-remote-export",
    "--no-sandbox",
    "--autopilot",
    "--max-autopilot-continues",
    "--plan",
    "--reasoning-effort",
    "--remote",
    "--remote-export",
    "--resume",
    "--sandbox",
    "--worktree",
    "-w",
    "--yolo",
}
EXPECTED_BUILDER_SKILLS = (
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
)
EXPECTED_BUILDER_REFERENCES = (
    Path("references/native-paths-and-schemas.md"),
    Path("references/public-validation-workflows.md"),
)


class CopilotCliSetupError(Exception):
    """A safe user-facing lifecycle failure."""


class ConcurrentTargetChange(CopilotCliSetupError):
    """A fail-closed target race."""


class RuntimeValidationError(CopilotCliSetupError):
    """Structured target-owned Copilot CLI runtime validation failure."""

    def __init__(self, message: str, *, code: str, repairable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.repairable = repairable


@dataclass
class DirectoryTransaction:
    created: list[Path]

    def cleanup(self) -> None:
        for path in reversed(self.created):
            with contextlib.suppress(OSError):
                path.rmdir()


@dataclass
class DirectoryLock:
    path: Path
    identity: tuple[int, int]


@dataclass
class FileSnapshot:
    exists: bool
    data: bytes | None = None
    mode: int | None = None


def fail(message: str) -> NoReturn:
    raise CopilotCliSetupError(message)


def fail_concurrent(message: str) -> NoReturn:
    raise ConcurrentTargetChange(message)


def runtime_fail(message: str, *, code: str, repairable: bool) -> NoReturn:
    raise RuntimeValidationError(message, code=code, repairable=repairable)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file_bounded(path: Path, *, max_bytes: int, label: str) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            digest.update(chunk)
    return digest.hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def current_owner() -> int | None:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return None
    return int(geteuid())


def require_current_owner(info: os.stat_result, label: str) -> None:
    owner = current_owner()
    if owner is not None and owner_of(info) != owner:
        fail(f"{label} must be owned by the current user")


def require_trusted_executable(candidates: tuple[Path, ...], label: str) -> Path:
    current_uid = current_owner()
    last_error = f"{label} is missing"
    for path in candidates:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            last_error = f"{label} must not be a symlink: {path}"
            continue
        if not stat.S_ISREG(info.st_mode):
            last_error = f"{label} must be a regular file: {path}"
            continue
        if stat.S_IMODE(info.st_mode) & 0o022:
            last_error = f"{label} must not be group- or world-writable: {path}"
            continue
        owner = owner_of(info)
        if owner not in {0, current_uid}:
            last_error = f"{label} has an untrusted owner: {path}"
            continue
        if not os.access(path, os.X_OK):
            last_error = f"{label} is not executable: {path}"
            continue
        return path
    fail(last_error)


def is_owner_only_file(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    if current_owner() is not None and owner_of(info) != current_owner():
        return False
    return True


def is_owner_private_directory(info: os.stat_result) -> bool:
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        return False
    if current_owner() is not None and owner_of(info) != current_owner():
        return False
    return True


def lstat_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def stat_existing(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    return info


def require_directory(path: Path, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    require_current_owner(info, label)
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    return info


def require_private_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    if not is_owner_private_directory(info):
        fail(f"{label} must be owned by the current user with mode 0700")
    return info


def require_safe_target_parent(path: Path, label: str) -> Path:
    parent_info = require_private_directory(path, label)
    del parent_info
    resolved = path.resolve(strict=True)
    current = resolved.parent
    while True:
        info = stat_existing(current, f"{label} ancestor {current}")
        if info is None or not stat.S_ISDIR(info.st_mode):
            fail(f"{label} ancestor must be a real directory: {current}")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022 and (mode & stat.S_ISVTX) == 0:
            fail(f"{label} ancestor is group- or world-writable without sticky bit: {current}")
        if current == current.parent:
            return resolved
        current = current.parent


def require_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    require_current_owner(info, label)
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    if owner_only and not is_owner_only_file(info):
        fail(f"{label} must be owned by the current user with mode 0600")
    if info.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    return info


def read_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> tuple[bytes, os.stat_result]:
    before = require_regular_file(path, label, owner_only=owner_only, max_bytes=max_bytes)
    if before.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            fail_concurrent(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            fail(f"{label} changed to an unsafe file")
        if owner_only and not is_owner_only_file(opened):
            fail(f"{label} must be owned by the current user with mode 0600")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, owner_only=owner_only, max_bytes=max_bytes)
    expected = identity_of(before)
    if identity_of(after) != expected or identity_of(final) != expected:
        fail_concurrent(f"{label} changed while it was being read")
    return b"".join(chunks), final


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def load_json_object(path: Path, label: str, *, owner_only: bool = False) -> dict[str, Any]:
    content, _ = read_regular_file(path, label, owner_only=owner_only, max_bytes=METADATA_MAX_BYTES)
    return parse_json_object(content, label)


def read_url_bounded(url: str, *, max_bytes: int, label: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        fail(f"{label} must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": PRODUCT_NAME})
    try:
        response_context = urllib.request.urlopen(request, timeout=PROCESS_TIMEOUT_SECONDS)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"{label} download failed: {exc}")
    with response_context as response:
        content_length = response.headers.get("Content-Length")
        if content_length is None:
            fail(f"{label} Content-Length is missing")
        try:
            declared = int(content_length)
        except ValueError:
            fail(f"{label} Content-Length is invalid")
        if declared > max_bytes:
            fail(f"{label} Content-Length is too large")
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fail(f"{label} exceeds the {max_bytes}-byte size limit")
                chunks.append(chunk)
        except (TimeoutError, OSError) as exc:
            fail(f"{label} download failed: {exc}")
        if total != declared:
            fail(f"{label} download size does not match Content-Length")
        return b"".join(chunks)


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(
            f"{label} has invalid keys "
            f"(missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def validate_profile_id(profile_id: str) -> None:
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        fail(f"invalid profile id: {profile_id!r}")


def managed_settings_view(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings[key] for key in MANAGED_SETTINGS_KEYS if key in settings}


def merge_settings(
    existing: dict[str, Any] | None, setup_settings: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if existing is not None:
        for key, value in existing.items():
            if key not in MANAGED_SETTINGS_KEYS:
                result[key] = value
    result.update(managed_settings_view(setup_settings))
    return result


def managed_digest(relative: Path, content: bytes) -> str:
    if relative == Path("settings.json"):
        settings = parse_json_object(content, str(relative))
        return sha256_bytes(canonical_json(managed_settings_view(settings)))
    return sha256_bytes(content)


def validate_common_settings(settings: dict[str, Any], label: str) -> None:
    required = {
        "askUser",
        "autoUpdate",
        "autoUpdatesChannel",
        "remote",
        "remoteExport",
        "storeTokenPlaintext",
        "keepAlive",
        "sandbox",
        "stayInAutopilot",
        "toolSearch",
        "disabledSkills",
        "enabledPlugins",
        "extraKnownMarketplaces",
    }
    if not required.issubset(settings):
        fail(f"{label} is missing required settings keys")
    if "memory" in settings:
        fail(f"{label} must not define undocumented memory settings")
    if settings["askUser"] is not False and settings["askUser"] is not True:
        fail(f"{label} askUser must be a boolean")
    if settings["autoUpdate"] is not False:
        fail(f"{label} must keep autoUpdate disabled")
    if settings["autoUpdatesChannel"] != "stable":
        fail(f"{label} must use the stable update channel")
    if settings["remote"] != "off" or settings["remoteExport"] is not False:
        fail(f"{label} must keep remote sessions disabled")
    if settings["storeTokenPlaintext"] is not False:
        fail(f"{label} must not allow plaintext token storage")
    if settings["keepAlive"] != "off":
        fail(f"{label} keepAlive must be off")
    if settings["toolSearch"] is not True:
        fail(f"{label} must keep documented toolSearch enabled")
    if not isinstance(settings["disabledSkills"], list) or not all(
        isinstance(item, str) for item in settings["disabledSkills"]
    ):
        fail(f"{label} disabledSkills must be a string array")
    sandbox = settings.get("sandbox")
    if not isinstance(sandbox, dict):
        fail(f"{label} has invalid sandbox settings")
    for key in ("enabled", "allowBypass", "gitAuth", "ghAuth"):
        if not isinstance(sandbox.get(key), bool):
            fail(f"{label} sandbox.{key} must be a boolean")
    if sandbox.get("gitAuth") is not False or sandbox.get("ghAuth") is not False:
        fail(f"{label} must not inject git or gh credentials into the sandbox")
    seatbelt = (
        sandbox.get("userPolicy", {}).get("seatbelt", {})
        if isinstance(sandbox.get("userPolicy"), dict)
        else {}
    )
    if seatbelt.get("keychainAccess") is not False:
        fail(f"{label} must not grant macOS keychain access to the sandbox")
    if not isinstance(settings.get("stayInAutopilot"), bool):
        fail(f"{label} stayInAutopilot must be a boolean")
    if not isinstance(settings.get("enabledPlugins"), dict):
        fail(f"{label} enabledPlugins must be an object")
    if not isinstance(settings.get("extraKnownMarketplaces"), dict):
        fail(f"{label} extraKnownMarketplaces must be an object")


def validate_profile_settings(profile_id: str, settings: dict[str, Any], label: str) -> None:
    validate_common_settings(settings, label)
    sandbox = settings["sandbox"]
    if profile_id == "full-auto":
        if settings["askUser"] is not False:
            fail(f"{label} full-auto must disable askUser")
        if settings["stayInAutopilot"] is not True:
            fail(f"{label} full-auto must stay in autopilot")
        if sandbox.get("enabled") is not False:
            fail(f"{label} full-auto must not enable sandbox")
        if sandbox.get("allowBypass") is not True:
            fail(f"{label} full-auto sandbox bypass setting must remain true")
        if "permissions" in settings:
            fail(f"{label} full-auto must not disable bypass permissions mode")
    elif profile_id == "safe":
        if settings["askUser"] is not True:
            fail(f"{label} safe must keep askUser enabled")
        if settings["stayInAutopilot"] is not False:
            fail(f"{label} safe must not stay in autopilot")
        if sandbox.get("enabled") is not True:
            fail(f"{label} safe must enable sandbox")
        if sandbox.get("allowBypass") is not False:
            fail(f"{label} safe must disable sandbox bypass")
        network = sandbox.get("userPolicy", {}).get("network", {})
        if not isinstance(network, dict):
            fail(f"{label} safe sandbox network policy must be an object")
        if network.get("allowLocalNetwork") is not False:
            fail(f"{label} safe must not allow local network access in sandbox")
        permissions = settings.get("permissions")
        if not isinstance(permissions, dict):
            fail(f"{label} safe must define permissions")
        if permissions.get("disableBypassPermissionsMode") != "disable":
            fail(f"{label} safe must disable bypass permissions mode")
    else:
        fail(f"unknown profile: {profile_id}")


def validate_permissions_config(value: dict[str, Any], label: str) -> None:
    require_exact_keys(value, {"locations"}, label)
    if not isinstance(value["locations"], dict):
        fail(f"{label} locations must be an object")


def validate_setup_metadata(metadata: dict[str, Any], setup_id: str) -> None:
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "managed_files",
            "builder_marketplace",
            "builder_plugin",
            "builder_default_on",
        },
        f"setup {setup_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"setup {setup_id} metadata has unsupported schema")
    if metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity mismatch")
    if metadata["managed_files"] != SETUP_MANAGED_FILES:
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_marketplace"] != "marketplaces/nddev-builder":
        fail(f"setup {setup_id} has invalid builder marketplace")
    if metadata["builder_plugin"] != BUILDER_PLUGIN_SPEC:
        fail(f"setup {setup_id} has invalid builder plugin spec")
    if metadata["builder_default_on"] is not True:
        fail(f"setup {setup_id} must enable the builder by default")


def validate_profile_metadata(metadata: dict[str, Any], profile_id: str) -> None:
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "managed_files",
            "default",
            "launch_args",
        },
        f"profile {profile_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"profile {profile_id} metadata has unsupported schema")
    if metadata["id"] != profile_id:
        fail(f"profile {profile_id} metadata identity mismatch")
    if metadata["managed_files"] != PROFILE_MANAGED_FILES:
        fail(f"profile {profile_id} managed file declaration is invalid")
    if not isinstance(metadata["default"], bool):
        fail(f"profile {profile_id} default must be a boolean")
    if not isinstance(metadata["launch_args"], list) or not all(
        isinstance(item, str) for item in metadata["launch_args"]
    ):
        fail(f"profile {profile_id} launch_args must be a string array")
    if profile_id == "full-auto":
        expected = [
            "--allow-all",
            "--mode=autopilot",
            "--no-ask-user",
            "--no-remote",
            "--no-remote-export",
            "--enable-all-github-mcp-tools",
            "--allow-all-mcp-server-instructions",
        ]
        if metadata["launch_args"] != expected:
            fail("full-auto launch args do not match the documented native bundle")
    elif profile_id == "safe":
        if any(arg.startswith("--allow") or arg in {"--yolo", "--mode=autopilot"} for arg in metadata["launch_args"]):
            fail("safe launch args must not contain allow-all or autopilot flags")
    else:
        fail(f"unknown profile: {profile_id}")


def render_setup(
    setup_id: str,
    profile_id: str,
    *,
    existing_settings: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[Path, bytes]]:
    validate_setup_id(setup_id)
    validate_profile_id(profile_id)
    setup_root = CATALOG_ROOT / setup_id
    profile_root = PROFILE_ROOT / profile_id
    setup_info = stat_existing(setup_root, f"setup {setup_id}")
    if setup_info is None or not stat.S_ISDIR(setup_info.st_mode):
        fail(f"unknown setup: {setup_id}")
    profile_info = stat_existing(profile_root, f"profile {profile_id}")
    if profile_info is None or not stat.S_ISDIR(profile_info.st_mode):
        fail(f"unknown profile: {profile_id}")
    metadata = load_json_object(setup_root / "setup.json", f"setup {setup_id} metadata")
    validate_setup_metadata(metadata, setup_id)
    profile = load_json_object(profile_root / "profile.json", f"profile {profile_id} metadata")
    validate_profile_metadata(profile, profile_id)
    settings = load_json_object(profile_root / "settings.json", f"profile {profile_id}/settings.json")
    validate_profile_settings(profile_id, settings, f"profile {profile_id}/settings.json")
    permissions = load_json_object(
        profile_root / "permissions-config.json",
        f"profile {profile_id}/permissions-config.json",
    )
    validate_permissions_config(permissions, f"profile {profile_id}/permissions-config.json")
    instructions, _ = read_regular_file(
        setup_root / "copilot-instructions.md",
        f"setup {setup_id}/copilot-instructions.md",
    )
    modular_instructions, _ = read_regular_file(
        setup_root / "instructions" / "nddev-builder.instructions.md",
        f"setup {setup_id}/instructions/nddev-builder.instructions.md",
    )
    mcp_config = load_json_object(setup_root / "mcp-config.json", f"setup {setup_id}/mcp-config.json")
    require_exact_keys(mcp_config, {"mcpServers"}, f"setup {setup_id}/mcp-config.json")
    if not isinstance(mcp_config["mcpServers"], dict):
        fail(f"setup {setup_id}/mcp-config.json mcpServers must be an object")
    desired: dict[Path, bytes] = {
        Path("settings.json"): canonical_json(merge_settings(existing_settings, settings)),
        Path("permissions-config.json"): canonical_json(permissions),
        Path("copilot-instructions.md"): instructions,
        Path("instructions") / "nddev-builder.instructions.md": modular_instructions,
        Path("mcp-config.json"): canonical_json(mcp_config),
    }
    stamp = build_stamp(setup_id, profile_id, desired, profile["launch_args"])
    desired[Path(STAMP_NAME)] = canonical_json(stamp)
    return metadata, desired


def build_stamp(
    setup_id: str, profile_id: str, desired: dict[Path, bytes], launch_args: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": "",
        "managed_files": {
            str(relative): managed_digest(relative, content)
            for relative, content in desired.items()
            if relative != Path(STAMP_NAME)
        },
        "builder_native_plugin": {
            "marketplace": BUILDER_MARKETPLACE_NAME,
            "marketplace_path": "marketplaces/nddev-builder",
            "plugin": BUILDER_PLUGIN_NAME,
            "plugin_spec": BUILDER_PLUGIN_SPEC,
            "installed_root": str(BUILDER_INSTALLED_ROOT),
        },
        "launch_args": launch_args,
    }


def bind_stamp(stamp: dict[str, Any], canonical_target: Path) -> dict[str, Any]:
    bound = dict(stamp)
    bound["canonical_target"] = str(canonical_target)
    return bound


def list_setups() -> list[dict[str, Any]]:
    setups: list[dict[str, Any]] = []
    for path in sorted(CATALOG_ROOT.iterdir()):
        info = stat_existing(path, f"setup {path.name}")
        if info is None or not stat.S_ISDIR(info.st_mode):
            continue
        metadata = load_json_object(path / "setup.json", f"setup {path.name} metadata")
        validate_setup_metadata(metadata, path.name)
        setups.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "builder_default_on": metadata["builder_default_on"],
                "builder_plugin": metadata["builder_plugin"],
            }
        )
    return setups


def list_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for path in sorted(PROFILE_ROOT.iterdir()):
        info = stat_existing(path, f"profile {path.name}")
        if info is None or not stat.S_ISDIR(info.st_mode):
            continue
        metadata = load_json_object(path / "profile.json", f"profile {path.name} metadata")
        validate_profile_metadata(metadata, path.name)
        profiles.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "default": metadata["default"],
                "launch_args": metadata["launch_args"],
            }
        )
    return profiles


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-github-copilot-cli-backups"


def backup_pool_marker(pool: Path) -> Path:
    return pool / BACKUP_POOL_NAME


def lock_path(target: Path) -> Path:
    return target / TARGET_LOCK_NAME


def bootstrap_lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-github-copilot-cli.bootstrap.lock"


def acquire_directory_lock(path: Path, label: str) -> DirectoryLock:
    try:
        os.mkdir(path, OWNER_DIRECTORY_MODE)
    except FileExistsError:
        fail(f"{label} is locked: {path}")
    except BaseException:
        fail(f"{label} is locked: {path}")
    try:
        path.chmod(OWNER_DIRECTORY_MODE)
        info = stat_existing(path, label)
        if info is None:
            fail_concurrent(f"{label} disappeared after creation")
        require_current_owner(info, label)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail_concurrent(f"{label} changed after creation")
        return DirectoryLock(path=path, identity=identity_of(info))
    except BaseException:
        with contextlib.suppress(OSError):
            path.rmdir()
        raise


def release_directory_lock(lock: DirectoryLock, label: str) -> None:
    info = stat_existing(lock.path, label)
    if info is None:
        fail_concurrent(f"{label} disappeared before release")
    require_current_owner(info, label)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail_concurrent(f"{label} changed to an unsafe path before release")
    if identity_of(info) != lock.identity:
        fail_concurrent(f"{label} identity changed before release")
    lock.path.rmdir()


def ensure_directory_chain(path: Path, transaction: DirectoryTransaction, label: str) -> None:
    missing: list[Path] = []
    current = path
    while True:
        info = stat_existing(current, label)
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                fail(f"{label} must be a directory")
            break
        missing.append(current)
        parent = current.parent
        if parent == current:
            fail(f"{label} parent is missing")
        current = parent
    for directory in reversed(missing):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE)
        directory.chmod(OWNER_DIRECTORY_MODE)
        transaction.created.append(directory)


@contextlib.contextmanager
def target_lock(target: Path, *, create_parent: bool = False) -> Iterator[DirectoryTransaction]:
    transaction = DirectoryTransaction([])
    lifecycle_lock: DirectoryLock | None = None
    bootstrap_lock: DirectoryLock | None = None
    if create_parent:
        ensure_directory_chain(target.parent, transaction, "target parent")
    else:
        require_directory(target.parent, "target parent")
    parent_info = require_private_directory(target.parent, "target parent")
    if stat.S_IMODE(parent_info.st_mode) & 0o022:
        transaction.cleanup()
        fail("target parent must not be group- or world-writable")
    require_safe_target_parent(target.parent, "target parent")
    target_info = stat_existing(target, "target")
    if target_info is None:
        if not create_parent:
            transaction.cleanup()
            fail("target is missing")
        try:
            bootstrap_lock = acquire_directory_lock(bootstrap_lock_path(target), "target bootstrap lock")
            try:
                target_info = stat_existing(target, "target")
                if target_info is None:
                    ensure_target_directory(target, transaction)
                else:
                    require_current_owner(target_info, "target")
                    if not stat.S_ISDIR(target_info.st_mode):
                        fail("target must be a real directory")
                    if not is_owner_private_directory(target_info):
                        fail("target must be owned by the current user with mode 0700")
                lifecycle_lock = acquire_directory_lock(lock_path(target), "target lifecycle lock")
            finally:
                if bootstrap_lock is not None:
                    release_directory_lock(bootstrap_lock, "target bootstrap lock")
                    bootstrap_lock = None
        except BaseException:
            if lifecycle_lock is not None:
                with contextlib.suppress(CopilotCliSetupError, OSError):
                    release_directory_lock(lifecycle_lock, "target lifecycle lock")
                lifecycle_lock = None
            transaction.cleanup()
            raise
    else:
        require_current_owner(target_info, "target")
        if not stat.S_ISDIR(target_info.st_mode):
            transaction.cleanup()
            fail("target must be a real directory")
        if not is_owner_private_directory(target_info):
            transaction.cleanup()
            fail("target must be owned by the current user with mode 0700")
        lifecycle_lock = acquire_directory_lock(lock_path(target), "target lifecycle lock")
    failed = False
    try:
        yield transaction
    except BaseException:
        failed = True
        raise
    finally:
        if lifecycle_lock is not None:
            try:
                release_directory_lock(lifecycle_lock, "target lifecycle lock")
            except BaseException:
                if not failed:
                    raise
        if failed:
            transaction.cleanup()


def require_explicit_absolute_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("an explicit --target absolute path is required")
    target = Path(raw_target)
    if not target.is_absolute():
        fail("--target must be an absolute path")
    try:
        info = target.lstat()
    except FileNotFoundError:
        return target
    if stat.S_ISLNK(info.st_mode):
        fail("--target must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        fail("--target must be a directory")
    require_current_owner(info, "target")
    return target.resolve()


def ensure_target_directory(
    target: Path, transaction: DirectoryTransaction | None = None
) -> Path:
    if lstat_exists(target):
        info = require_directory(target, "target")
        if not is_owner_private_directory(info):
            fail("target must be owned by the current user with mode 0700")
        return target.resolve()
    parent = target.parent
    require_directory(parent, "target parent")
    target.mkdir(mode=OWNER_DIRECTORY_MODE)
    target.chmod(OWNER_DIRECTORY_MODE)
    if transaction is not None:
        transaction.created.append(target)
    return target.resolve()


def any_managed_path_exists(target: Path) -> bool:
    return any(
        lstat_exists(target / relative)
        for relative in ALL_KNOWN_MANAGED_PATHS
    )


def ensure_real_parent(path: Path, target: Path) -> None:
    try:
        relative_parent = path.relative_to(target).parent
    except ValueError:
        fail(f"managed path escaped target: {path}")
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_existing(current, f"managed directory {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            current.chmod(OWNER_DIRECTORY_MODE)
            continue
        require_current_owner(info, f"managed directory {current}")
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent is not a directory: {current}")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"managed parent must be private: {current}")


def load_stamp(target: Path) -> tuple[dict[str, Any], bool] | None:
    stamp = target / STAMP_NAME
    if not lstat_exists(stamp):
        return None
    value = load_json_object(stamp, "setup stamp", owner_only=True)
    schema_version = value.get("schema_version")
    if schema_version == STAMP_SCHEMA:
        require_exact_keys(value, STAMP_KEYS_V2, "setup stamp")
    elif schema_version == LEGACY_STAMP_SCHEMA:
        require_exact_keys(value, STAMP_KEYS_V1, "legacy setup stamp")
    else:
        fail("setup stamp has unsupported schema")
    if value["product_name"] != PRODUCT_NAME:
        fail("setup stamp belongs to another product")
    if schema_version == STAMP_SCHEMA and value["build_version"] != VERSION:
        fail("setup stamp build version mismatch")
    if value["canonical_target"] != str(target):
        fail("setup stamp is bound to a different canonical target")
    if not isinstance(value["managed_files"], dict):
        fail("setup stamp managed_files must be an object")
    if not isinstance(value["launch_args"], list) or not all(
        isinstance(item, str) for item in value["launch_args"]
    ):
        fail("setup stamp launch_args must be a string array")
    validate_setup_id(value["setup_id"])
    if schema_version == STAMP_SCHEMA:
        validate_profile_id(value["profile_id"])
        if not isinstance(value["builder_native_plugin"], dict):
            fail("setup stamp builder_native_plugin must be an object")
    return value, schema_version == LEGACY_STAMP_SCHEMA


def validate_managed_files(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    expected = stamp["managed_files"]
    ordered = [relative for relative in MANAGED_PATHS if str(relative) in expected]
    ordered.extend(
        Path(raw_relative)
        for raw_relative in sorted(set(expected) - {str(item) for item in ordered})
    )
    for relative in ordered:
        expected_digest = expected[str(relative)]
        if relative.is_absolute() or ".." in relative.parts:
            fail("setup stamp contains an unsafe managed path")
        content, _ = read_regular_file(
            target / relative, f"managed file {relative}", owner_only=True
        )
        actual_digest = managed_digest(relative, content)
        if actual_digest != expected_digest:
            drift.append(str(relative))
    if drift:
        fail(f"managed target drift detected: {', '.join(sorted(drift))}")
    return sorted(expected)


def inspect_target(target: Path) -> dict[str, Any]:
    if not lstat_exists(target):
        return {"state": "missing", "target": str(target)}
    target_info = require_directory(target, "target")
    if not is_owner_private_directory(target_info):
        fail("target must be owned by the current user with mode 0700")
    stamp_result = load_stamp(target)
    if stamp_result is None:
        if any_managed_path_exists(target):
            fail("unmanaged target contains nddev-managed paths")
        return {"state": "unmanaged", "target": str(target)}
    stamp, legacy = stamp_result
    managed_files = validate_managed_files(target, stamp)
    if legacy:
        return {
            "state": "legacy-managed",
            "target": str(target),
            "setup_id": stamp["setup_id"],
            "profile_id": None,
            "build_version": stamp["build_version"],
            "legacy_schema": stamp["schema_version"],
            "managed_files": managed_files,
            "builder_projection": stamp["builder_projection"],
            "launch_args": stamp["launch_args"],
            "launch_supported": False,
        }
    return {
        "state": "managed",
        "target": str(target),
        "setup_id": stamp["setup_id"],
        "profile_id": stamp["profile_id"],
        "build_version": stamp["build_version"],
        "managed_files": managed_files,
        "builder_native_plugin": stamp["builder_native_plugin"],
        "launch_args": stamp["launch_args"],
        "launch_supported": True,
    }


def read_existing_settings_if_managed(target: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("state") not in {"managed", "legacy-managed"}:
        return None
    return load_json_object(target / "settings.json", "existing settings.json", owner_only=True)


def managed_paths_from_state(state: dict[str, Any] | None = None) -> tuple[Path, ...]:
    if state and isinstance(state.get("managed_files"), list):
        paths = [Path(raw) for raw in state["managed_files"]]
        paths.append(Path(STAMP_NAME))
        return tuple(dict.fromkeys(paths))
    return MANAGED_PATHS


def current_managed_snapshot(
    target: Path, paths: tuple[Path, ...] = MANAGED_PATHS
) -> dict[Path, bytes | None]:
    snapshot: dict[Path, bytes | None] = {}
    for relative in paths:
        path = target / relative
        if lstat_exists(path):
            content, _ = read_regular_file(path, f"managed file {relative}", owner_only=True)
            snapshot[relative] = content
        else:
            snapshot[relative] = None
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[Path, bytes | None]) -> None:
    paths = tuple(snapshot)
    for relative in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        path = target / relative
        if lstat_exists(path):
            path.unlink()
    for relative, content in snapshot.items():
        if content is None:
            continue
        path = target / relative
        ensure_real_parent(path, target)
        temporary = path.with_name(f".{path.name}.restore.tmp.{os.getpid()}.{time.time_ns()}")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
        path.chmod(OWNER_FILE_MODE)
    prune_empty_managed_dirs(target, paths)


def write_owner_file_replace(path: Path, content: bytes, target: Path, label: str) -> None:
    ensure_real_parent(path, target)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    os.replace(temporary, path)
    try:
        final = require_regular_file(path, label, owner_only=True)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    if stat.S_IMODE(final.st_mode) != OWNER_FILE_MODE:
        path.chmod(OWNER_FILE_MODE)


def remove_private_tree(path: Path, label: str) -> None:
    info = require_private_directory(path, label)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private")
    shutil.rmtree(path)


def prune_empty_managed_dirs(target: Path, paths: tuple[Path, ...] = MANAGED_PATHS) -> None:
    candidates = sorted(
        {(target / relative).parent for relative in paths},
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in candidates:
        while directory != target and lstat_exists(directory):
            info = stat_existing(directory, f"managed directory {directory}")
            if info is None or not stat.S_ISDIR(info.st_mode):
                break
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent


def replace_managed_state(
    target: Path,
    desired: dict[Path, bytes | None],
    expected: dict[str, Any],
) -> None:
    del expected
    for relative, content in desired.items():
        path = target / relative
        if relative.is_absolute() or ".." in relative.parts:
            fail(f"unsafe managed path: {relative}")
        if content is None:
            if lstat_exists(path):
                require_regular_file(path, f"managed file {relative}", owner_only=True)
                path.unlink()
            continue
        ensure_real_parent(path, target)
        require_existing = None
        if lstat_exists(path):
            require_existing = require_regular_file(
                path, f"managed file {relative}", owner_only=True
            )
        del require_existing
        temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
            raise
        temporary.chmod(OWNER_FILE_MODE)
        os.replace(temporary, path)
        path.chmod(OWNER_FILE_MODE)
    prune_empty_managed_dirs(target, tuple(desired))


def changed_paths(target: Path, desired: dict[Path, bytes | None]) -> list[str]:
    changed: list[str] = []
    for relative, content in desired.items():
        path = target / relative
        if content is None:
            if lstat_exists(path):
                changed.append(str(relative))
            continue
        if not lstat_exists(path):
            changed.append(str(relative))
            continue
        actual, _ = read_regular_file(path, f"managed file {relative}", owner_only=True)
        if actual != content:
            changed.append(str(relative))
    return sorted(changed)


def create_backup(target: Path, state: dict[str, Any]) -> int:
    pool = ensure_backup_pool(target)
    for slot in sorted(backup_slots_for_rotation(target, pool), reverse=True):
        current = pool / str(slot)
        if slot == 9:
            # The slot was just validated as a target-bound manager backup.
            remove_private_tree(current, f"backup slot {slot}")
        else:
            os.replace(current, pool / str(slot + 1))
    slot_dir = pool / "0"
    slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    managed_files = list(state["managed_files"])
    for raw_relative in [*managed_files, STAMP_NAME]:
        relative = Path(raw_relative)
        content, _ = read_regular_file(
            target / relative, f"managed file {relative}", owner_only=True
        )
        destination = slot_dir / relative
        ensure_real_parent(destination, slot_dir)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        destination.chmod(OWNER_FILE_MODE)
    envelope = {
        "schema_version": 2,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": 0,
        "canonical_target": str(target),
        "source_setup_id": state["setup_id"],
        "source_profile_id": state.get("profile_id"),
        "managed_files": managed_files,
        "created_at": int(time.time()),
    }
    envelope_path = slot_dir / BACKUP_NAME
    fd = os.open(envelope_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_json(envelope))
    refresh_backup_slot_numbers(target, pool)
    return 0


def validate_backup_pool_marker(target: Path, pool: Path) -> None:
    marker = load_json_object(
        backup_pool_marker(pool),
        "backup pool marker",
        owner_only=True,
    )
    require_exact_keys(marker, BACKUP_POOL_KEYS, "backup pool marker")
    if marker["schema_version"] != 1:
        fail("backup pool marker has unsupported schema")
    if marker["product_name"] != PRODUCT_NAME:
        fail("backup pool marker belongs to another product")
    if marker["build_version"] != VERSION and marker["build_version"] != "0.1.0":
        fail("backup pool marker build version mismatch")
    if marker["canonical_target"] != str(target):
        fail("backup pool is bound to a different canonical target")


def write_backup_pool_marker(target: Path, pool: Path) -> None:
    marker = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
    }
    marker_path = backup_pool_marker(pool)
    fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_json(marker))


def ensure_backup_pool(target: Path) -> Path:
    pool = backup_pool(target)
    info = stat_existing(pool, "backup pool")
    if info is None:
        require_private_directory(target.parent, "backup pool parent")
        require_safe_target_parent(target.parent, "backup pool parent")
        pool.mkdir(mode=OWNER_DIRECTORY_MODE)
        pool.chmod(OWNER_DIRECTORY_MODE)
        write_backup_pool_marker(target, pool)
        return pool
    require_current_owner(info, "backup pool")
    if not stat.S_ISDIR(info.st_mode):
        fail("backup pool must be a directory")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("backup pool must be private")
    require_safe_target_parent(target.parent, "backup pool parent")
    validate_backup_pool_marker(target, pool)
    return pool


def require_backup_pool(target: Path) -> Path:
    pool = backup_pool(target)
    require_safe_target_parent(target.parent, "backup pool parent")
    require_private_directory(pool, "backup pool")
    validate_backup_pool_marker(target, pool)
    return pool


def validate_backup_envelope(
    target: Path,
    envelope: dict[str, Any],
    label: str,
    *,
    expected_slot: int | None,
) -> None:
    schema_version = envelope.get("schema_version")
    if schema_version == 2:
        require_exact_keys(envelope, BACKUP_KEYS_V2, label)
    elif schema_version == 1:
        require_exact_keys(envelope, BACKUP_KEYS_V1, label)
    else:
        fail(f"{label} has unsupported schema")
    if envelope["product_name"] != PRODUCT_NAME:
        fail("backup belongs to another product")
    if schema_version == 2 and envelope["build_version"] != VERSION:
        fail("backup build version mismatch")
    if envelope["canonical_target"] != str(target):
        fail("backup belongs to a different canonical target")
    slot = envelope["slot"]
    if not isinstance(slot, int) or slot < 0 or slot > 9:
        fail(f"{label} slot is invalid")
    if expected_slot is not None and slot != expected_slot:
        fail(f"{label} slot identity mismatch")
    if not isinstance(envelope["source_setup_id"], str):
        fail(f"{label} source_setup_id must be a string")
    validate_setup_id(envelope["source_setup_id"])
    if schema_version == 2 and envelope["source_profile_id"] is not None:
        if not isinstance(envelope["source_profile_id"], str):
            fail(f"{label} source_profile_id must be a string or null")
        validate_profile_id(envelope["source_profile_id"])
    managed_files = envelope["managed_files"]
    if not isinstance(managed_files, list) or not all(
        isinstance(item, str) for item in managed_files
    ):
        fail(f"{label} managed_files must be a string array")
    if len(managed_files) != len(set(managed_files)):
        fail(f"{label} managed_files must be unique")
    if not isinstance(envelope["created_at"], int):
        fail(f"{label} created_at must be an integer")
    for raw_relative in managed_files:
        relative = Path(raw_relative)
        if relative.is_absolute() or ".." in relative.parts or relative == Path(STAMP_NAME):
            fail(f"{label} contains an unsafe managed path")


def load_backup_envelope(
    target: Path,
    slot_dir: Path,
    slot: int,
    *,
    expected_slot: int | None,
) -> dict[str, Any]:
    require_private_directory(slot_dir, f"backup slot {slot}")
    envelope = load_json_object(
        slot_dir / BACKUP_NAME,
        f"backup slot {slot} envelope",
        owner_only=True,
    )
    validate_backup_envelope(
        target,
        envelope,
        f"backup slot {slot} envelope",
        expected_slot=expected_slot,
    )
    return envelope


def backup_slots_for_rotation(target: Path, pool: Path) -> list[int]:
    slots: list[int] = []
    for child in pool.iterdir():
        if child.name == BACKUP_POOL_NAME:
            continue
        if not child.name.isdigit():
            fail("backup pool contains an unmanaged path")
        slot = int(child.name)
        if slot < 0 or slot > 9:
            fail("backup pool contains a slot outside the 0-9 rotation window")
        load_backup_envelope(target, child, slot, expected_slot=slot)
        slots.append(slot)
    return sorted(set(slots))


def refresh_backup_slot_numbers(target: Path, pool: Path) -> None:
    for slot in range(10):
        slot_dir = pool / str(slot)
        if not lstat_exists(slot_dir):
            continue
        envelope = load_backup_envelope(target, slot_dir, slot, expected_slot=None)
        envelope["slot"] = slot
        envelope_path = slot_dir / BACKUP_NAME
        write_owner_file_replace(
            envelope_path,
            canonical_json(envelope),
            slot_dir,
            f"backup slot {slot} envelope",
        )


def load_backup(target: Path, slot: int) -> tuple[dict[str, Any], dict[Path, bytes]]:
    if slot < 0 or slot > 9:
        fail("--backup must be between 0 and 9")
    pool = require_backup_pool(target)
    slot_dir = pool / str(slot)
    envelope = load_backup_envelope(target, slot_dir, slot, expected_slot=slot)
    files: dict[Path, bytes] = {}
    for raw_relative in [*envelope["managed_files"], STAMP_NAME]:
        relative = Path(raw_relative)
        if relative.is_absolute() or ".." in relative.parts:
            fail("backup envelope contains an unsafe managed path")
        content, _ = read_regular_file(
            slot_dir / relative, f"backup file {relative}", owner_only=True
        )
        files[relative] = content
    return envelope, files


def mutate_setup(target: Path, setup_id: str, profile_id: str, operation: str) -> dict[str, Any]:
    with target_lock(target, create_parent=True) as directory_transaction:
        canonical_target = ensure_target_directory(target, directory_transaction)
        state = inspect_target(canonical_target)
        if state["state"] == "unmanaged" and any_managed_path_exists(canonical_target):
            fail("unmanaged target contains nddev-managed paths")
        if state["state"] == "legacy-managed" and operation != "migrate":
            fail("target is legacy-managed; run migrate before install, switch, or launch")
        existing_settings = read_existing_settings_if_managed(canonical_target, state)
        metadata, desired = render_setup(
            setup_id, profile_id, existing_settings=existing_settings
        )
        stamp = bind_stamp(
            parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
        )
        desired[Path(STAMP_NAME)] = canonical_json(stamp)
        if state["state"] == "legacy-managed" and operation == "migrate":
            for relative in managed_paths_from_state(state):
                desired.setdefault(relative, None)
        changed = changed_paths(canonical_target, desired)
        backup_slot: int | None = None
        snapshot_paths = tuple(dict.fromkeys((*managed_paths_from_state(state), *MANAGED_PATHS)))
        snapshot = current_managed_snapshot(canonical_target, snapshot_paths)
        try:
            if state["state"] in {"managed", "legacy-managed"} and changed:
                backup_slot = create_backup(canonical_target, state)
            if changed:
                replace_managed_state(canonical_target, desired, stamp)
            post = inspect_target(canonical_target)
        except BaseException:
            restore_snapshot(canonical_target, snapshot)
            raise
    return {
        "ok": True,
        "operation": operation,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "description": metadata["description"],
        "target": str(canonical_target),
        "changed": changed,
        "backup_slot": backup_slot,
        "state": post["state"],
    }


def plan_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    state = inspect_target(canonical_target)
    existing_settings = read_existing_settings_if_managed(canonical_target, state)
    _metadata, desired = render_setup(setup_id, profile_id, existing_settings=existing_settings)
    if state["state"] == "managed":
        stamp = bind_stamp(
            parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
        )
        desired[Path(STAMP_NAME)] = canonical_json(stamp)
        changed = changed_paths(canonical_target, desired)
        operation = (
            "switch"
            if state.get("setup_id") != setup_id or state.get("profile_id") != profile_id
            else "install"
        )
        backup_required = bool(changed)
    elif state["state"] == "legacy-managed":
        for relative in managed_paths_from_state(state):
            desired.setdefault(relative, None)
        changed = changed_paths(canonical_target, desired)
        operation = "migrate"
        backup_required = bool(changed)
    else:
        changed = sorted(str(path) for path in desired)
        operation = "install"
        backup_required = False
    return {
        "ok": True,
        "operation": operation,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "target": str(canonical_target),
        "state": state["state"],
        "mutates": False,
        "backup_required": backup_required,
        "changed": changed,
    }


def remove_setup(target: Path) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    with target_lock(canonical_target, create_parent=False):
        state = inspect_target(canonical_target)
        if state["state"] not in {"managed", "legacy-managed"}:
            fail("target is not managed by nddev-github-copilot-cli-app")
        paths = managed_paths_from_state(state)
        snapshot = current_managed_snapshot(canonical_target, paths)
        desired = {relative: None for relative in paths}
        try:
            backup_slot = create_backup(canonical_target, state)
            replace_managed_state(canonical_target, desired, {})
        except BaseException:
            restore_snapshot(canonical_target, snapshot)
            raise
    return {
        "ok": True,
        "operation": "remove",
        "target": str(canonical_target),
        "removed_setup_id": state["setup_id"],
        "removed_profile_id": state.get("profile_id"),
        "backup_slot": backup_slot,
    }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    with target_lock(canonical_target, create_parent=False):
        state = inspect_target(canonical_target)
        if state["state"] not in {"managed", "legacy-managed"}:
            fail("target is not managed by nddev-github-copilot-cli-app")
        envelope, desired = load_backup(canonical_target, slot)
        paths = tuple(dict.fromkeys((*managed_paths_from_state(state), *tuple(desired))))
        snapshot = current_managed_snapshot(canonical_target, paths)
        try:
            replace_managed_state(canonical_target, desired, {})
            post = inspect_target(canonical_target)
        except BaseException:
            restore_snapshot(canonical_target, snapshot)
            raise
    return {
        "ok": True,
        "operation": "restore",
        "target": str(canonical_target),
        "setup_id": post["setup_id"],
        "profile_id": post.get("profile_id"),
        "restored_from_slot": slot,
        "restored_source_setup_id": envelope["source_setup_id"],
        "restored_source_profile_id": envelope.get("source_profile_id"),
    }


def load_baseline() -> dict[str, Any]:
    return load_json_object(BASELINE_REF, "Copilot CLI baseline")


def installer_source(baseline: dict[str, Any]) -> tuple[str, str, int]:
    installer = baseline["installer"]
    return str(installer["url"]), str(installer["sha256"]), int(installer["size"])


def checksums_source(baseline: dict[str, Any]) -> tuple[str, str, int]:
    checksums = baseline["release"]["checksums"]
    return str(checksums["url"]), str(checksums["sha256"]), int(checksums["size"])


def linux_os_release() -> dict[str, str]:
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        result: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            result[key] = value
        return result
    fail("unsupported Linux distribution: /etc/os-release is missing")


def detect_platform_asset() -> tuple[str, dict[str, Any]]:
    baseline = load_baseline()
    system = sys.platform
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        fail(f"unsupported architecture for Copilot CLI install: {platform.machine()}")
    if system == "darwin":
        asset_name = f"copilot-darwin-{arch}.tar.gz"
    elif system.startswith("linux"):
        libc_name = platform.libc_ver()[0].lower()
        if libc_name == "musl":
            fail("unsupported platform for Copilot CLI install: linux musl")
        release = linux_os_release()
        if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "26.04":
            fail("unsupported Linux distribution for Copilot CLI install: Ubuntu 26.04 required")
        asset_name = f"copilot-linux-{arch}.tar.gz"
    else:
        fail(f"unsupported platform for Copilot CLI install: {system}")
    assets = baseline.get("assets")
    if not isinstance(assets, dict) or asset_name not in assets:
        fail(f"baseline does not declare asset {asset_name}")
    asset = assets[asset_name]
    if not isinstance(asset, dict):
        fail(f"baseline asset {asset_name} must be an object")
    return asset_name, asset


def parse_checksums(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"Copilot CLI checksums are not UTF-8: {exc}")
    checksums: dict[str, str] = {}
    for index, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        parts = raw.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            fail(f"Copilot CLI checksums line {index} is invalid")
        name = parts[1]
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            fail(f"Copilot CLI checksums line {index} has an unsafe filename")
        checksums[name] = parts[0].lower()
    return checksums


def verify_release_metadata(baseline: dict[str, Any], asset_name: str, asset: dict[str, Any]) -> dict[str, Any]:
    checksums_url, expected_checksums_sha, expected_checksums_size = checksums_source(baseline)
    checksums_bytes = read_url_bounded(
        checksums_url,
        max_bytes=CHECKSUMS_MAX_BYTES,
        label="Copilot CLI SHA256SUMS.txt",
    )
    if len(checksums_bytes) != expected_checksums_size:
        fail("Copilot CLI checksums size does not match the pinned baseline")
    if sha256_bytes(checksums_bytes) != expected_checksums_sha:
        fail("Copilot CLI checksums SHA256 does not match the pinned baseline")
    parsed = parse_checksums(checksums_bytes)
    assets = baseline["assets"]
    url = str(asset["browser_download_url"])
    expected_size = int(asset["size"])
    expected_sha = str(asset["sha256"])
    for expected_name, expected_asset in assets.items():
        if parsed.get(expected_name) != expected_asset["sha256"]:
            fail(f"Copilot CLI checksums do not match pinned asset {expected_name}")
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme != "https":
        fail("Copilot CLI artifact URL must use HTTPS")
    if parsed_url.netloc.lower() != "github.com" or not parsed_url.path.startswith("/github/copilot-cli/releases/download/"):
        fail("Copilot CLI artifact URL must point at the official GitHub Copilot CLI release")
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": PRODUCT_NAME})
    try:
        response_context = urllib.request.urlopen(request, timeout=PROCESS_TIMEOUT_SECONDS)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"Copilot CLI artifact HEAD failed: {exc}")
    with response_context as response:
        content_length = response.headers.get("Content-Length")
        if content_length is None:
            fail("Copilot CLI artifact Content-Length is missing")
        try:
            declared = int(content_length)
        except ValueError:
            fail("Copilot CLI artifact Content-Length is invalid")
        if declared != expected_size:
            fail("Copilot CLI artifact Content-Length does not match the pinned baseline")
    return {
        "checksums": {
            "url": checksums_url,
            "sha256": expected_checksums_sha,
            "size": expected_checksums_size,
        },
        "asset": {
            "name": asset_name,
            "url": url,
            "sha256": expected_sha,
            "size": expected_size,
        },
        "artifact_verification": {"size_verified": True, "sha256_verified": False, "method": "head"},
    }


def software_manifest_path(target: Path) -> Path:
    return target / "software" / "copilot-cli.json"


def copilot_executable(target: Path) -> Path:
    return target / "bin" / COMMAND_NAME


def runtime_lstat(path: Path, target: Path, label: str, *, repairable: bool) -> os.stat_result:
    if target not in path.parents and path != target:
        runtime_fail(f"{label} escaped managed target", code="escaped_target", repairable=False)
    try:
        info = path.lstat()
    except FileNotFoundError:
        runtime_fail(f"{label} is missing", code=f"{label_slug(label)}_missing", repairable=repairable)
    try:
        require_current_owner(info, label)
    except CopilotCliSetupError as exc:
        runtime_fail(str(exc), code=f"{label_slug(label)}_owner", repairable=False)
    return info


def label_slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def runtime_private_directory(path: Path, target: Path, label: str, *, repairable: bool) -> os.stat_result:
    info = runtime_lstat(path, target, label, repairable=repairable)
    if stat.S_ISLNK(info.st_mode):
        runtime_fail(f"{label} must not be a symlink", code=f"{label_slug(label)}_symlink", repairable=False)
    if not stat.S_ISDIR(info.st_mode):
        runtime_fail(f"{label} must be a directory", code=f"{label_slug(label)}_type", repairable=False)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        runtime_fail(f"{label} must be private", code=f"{label_slug(label)}_mode", repairable=False)
    return info


def runtime_regular_file(path: Path, target: Path, label: str, *, repairable: bool) -> os.stat_result:
    info = runtime_lstat(path, target, label, repairable=repairable)
    if stat.S_ISLNK(info.st_mode):
        runtime_fail(f"{label} must not be a symlink", code=f"{label_slug(label)}_symlink", repairable=False)
    if not stat.S_ISREG(info.st_mode):
        runtime_fail(f"{label} must be a regular file", code=f"{label_slug(label)}_type", repairable=False)
    if info.st_nlink != 1:
        runtime_fail(f"{label} must not have hard-link aliases", code=f"{label_slug(label)}_hardlink", repairable=False)
    return info


def sha256_runtime_regular_file(
    path: Path,
    target: Path,
    label: str,
    info: os.stat_result,
    *,
    max_bytes: int,
) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        runtime_fail(f"{label} could not be opened safely: {exc}", code=f"{label_slug(label)}_open", repairable=False)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(info):
            fail_concurrent(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            runtime_fail(f"{label} changed to an unsafe file", code=f"{label_slug(label)}_type", repairable=False)
        try:
            require_current_owner(opened, label)
        except CopilotCliSetupError as exc:
            runtime_fail(str(exc), code=f"{label_slug(label)}_owner", repairable=False)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                runtime_fail(f"{label} exceeds the {max_bytes}-byte size limit", code=f"{label_slug(label)}_size", repairable=False)
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = runtime_regular_file(path, target, label, repairable=False)
    if identity_of(after) != identity_of(info) or identity_of(final) != identity_of(info):
        fail_concurrent(f"{label} changed while it was being read")
    return digest.hexdigest()


def current_software_metadata(target: Path) -> dict[str, Any]:
    runtime_private_directory(target, target, "target", repairable=False)
    executable = copilot_executable(target)
    manifest_path = software_manifest_path(target)
    binary_info = runtime_regular_file(executable, target, "Copilot CLI executable", repairable=True)
    if stat.S_IMODE(binary_info.st_mode) != OWNER_DIRECTORY_MODE or not os.access(executable, os.X_OK):
        runtime_fail("Copilot CLI executable mode is unsafe", code="copilot_executable_mode", repairable=False)
    receipt_info = runtime_regular_file(manifest_path, target, "software receipt", repairable=True)
    if not is_owner_only_file(receipt_info):
        runtime_fail("software receipt mode is unsafe", code="software_receipt_mode", repairable=False)
    try:
        receipt = load_json_object(manifest_path, "software receipt", owner_only=True)
    except CopilotCliSetupError as exc:
        runtime_fail(str(exc), code="software_receipt_invalid", repairable=True)
    baseline = load_baseline()
    expected_common = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "version": TESTED_VERSION,
        "release_tag": RELEASE_TAG,
        "command": COMMAND_NAME,
        "installer": baseline["installer"],
        "release": baseline["release"],
    }
    for key, expected in expected_common.items():
        if receipt.get(key) != expected:
            runtime_fail(f"software receipt {key} does not match the baseline", code=f"software_receipt_{key}", repairable=True)
    artifact = receipt.get("artifact")
    asset_name, asset = detect_platform_asset()
    expected_artifact = {
        "name": asset_name,
        "url": asset["browser_download_url"],
        "sha256": asset["sha256"],
        "size": asset["size"],
    }
    if artifact != expected_artifact:
        runtime_fail("software receipt artifact does not match the baseline", code="software_receipt_artifact", repairable=True)
    binary_sha = sha256_runtime_regular_file(
        executable,
        target,
        "Copilot CLI executable",
        binary_info,
        max_bytes=SOFTWARE_FILE_MAX_BYTES,
    )
    if receipt.get("binary_sha256") != binary_sha:
        runtime_fail("software receipt binary SHA256 does not match target executable", code="software_receipt_binary_sha256", repairable=True)
    if receipt.get("binary_size") != binary_info.st_size:
        runtime_fail("software receipt binary size does not match target executable", code="software_receipt_binary_size", repairable=True)
    return {
        "version": receipt["version"],
        "release_tag": receipt["release_tag"],
        "asset": receipt["artifact"],
        "checksums": receipt["checksums"],
        "artifact_verification": receipt["artifact_verification"],
        "executable": f"bin/{COMMAND_NAME}",
        "binary": {
            "size": binary_info.st_size,
            "sha256": binary_sha,
            "mode": f"{stat.S_IMODE(binary_info.st_mode):04o}",
            "identity": {
                "device": binary_info.st_dev,
                "inode": binary_info.st_ino,
            },
        },
        "receipt_sha256": sha256_file_bounded(manifest_path, max_bytes=METADATA_MAX_BYTES, label="software receipt"),
    }


def require_launch_executable_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before.get("binary") != after.get("binary"):
        fail_concurrent("Copilot CLI executable changed before launch")


def software_status(target: Path) -> dict[str, Any]:
    if not lstat_exists(target):
        return {
            "ok": True,
            "state": "absent",
            "installed": False,
            "current": False,
            "target": str(target),
            "version": None,
            "executable": None,
        }
    canonical_target = require_explicit_absolute_target(str(target))
    runtime_private_directory(canonical_target, canonical_target, "target", repairable=False)
    if not lstat_exists(copilot_executable(canonical_target)) and not lstat_exists(software_manifest_path(canonical_target)):
        return {
            "ok": True,
            "state": "absent",
            "installed": False,
            "current": False,
            "target": str(canonical_target),
            "version": None,
            "executable": str(copilot_executable(canonical_target)),
        }
    try:
        metadata = current_software_metadata(canonical_target)
    except RuntimeValidationError as exc:
        return {
            "ok": True,
            "state": "partial",
            "installed": False,
            "current": False,
            "target": str(canonical_target),
            "version": None,
            "executable": str(copilot_executable(canonical_target)),
            "error": str(exc),
            "code": exc.code,
            "repairable": exc.repairable,
        }
    return {
        "ok": True,
        "state": "installed",
        "installed": True,
        "current": True,
        "target": str(canonical_target),
        "version": metadata["version"],
        "release_tag": metadata["release_tag"],
        "executable": str(copilot_executable(canonical_target)),
        "asset": metadata["asset"]["name"],
        "binary_sha256": metadata["binary"]["sha256"],
    }


def sanitized_subprocess_env(home: Path, cache: Path, tmp: Path) -> dict[str, str]:
    env: dict[str, str] = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "COPILOT_HOME": str(home / ".copilot"),
        "COPILOT_CACHE_HOME": str(cache),
        "COPILOT_AUTO_UPDATE": "false",
        "TMPDIR": str(tmp),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(cache / "xdg-cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "PATH": DETERMINISTIC_PATH,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    for name in TOKEN_ENV_NAMES:
        env.pop(name, None)
    return env


def write_stage_installer(stage: Path, data: bytes) -> Path:
    installer = stage / "install.sh"
    fd = os.open(installer, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    installer.chmod(0o700)
    return installer


def run_stage_version_probe(prefix: Path, stage_home: Path, timeout: int) -> None:
    executable = prefix / "bin" / COMMAND_NAME
    env = sanitized_subprocess_env(stage_home, stage_home / "cache", stage_home / "tmp")
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            cwd=stage_home,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        fail(f"stage Copilot CLI version probe command is missing: {exc}")
    except subprocess.TimeoutExpired:
        fail("stage Copilot CLI version probe timed out")
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        fail(f"stage Copilot CLI version probe failed: {output.strip()}")
    if TESTED_VERSION not in output:
        fail("stage Copilot CLI version probe did not report the pinned version")


def install_software_to_stage(stage: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    installer_url, expected_installer_sha, expected_installer_size = installer_source(baseline)
    installer_bytes = read_url_bounded(
        installer_url, max_bytes=INSTALLER_MAX_BYTES, label="Copilot CLI installer"
    )
    if len(installer_bytes) != expected_installer_size:
        fail("Copilot CLI installer size does not match the pinned baseline")
    if sha256_bytes(installer_bytes) != expected_installer_sha:
        fail("Copilot CLI installer SHA256 does not match the pinned baseline")
    asset_name, asset = detect_platform_asset()
    release_metadata = verify_release_metadata(baseline, asset_name, asset)
    stage_home = stage / "home"
    stage_prefix = stage / "prefix"
    stage_tmp = stage / "tmp"
    for directory in (stage_home, stage_prefix, stage_tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE)
    installer_path = write_stage_installer(stage, installer_bytes)
    env = sanitized_subprocess_env(stage_home, stage_home / "cache", stage_tmp)
    env["VERSION"] = TESTED_VERSION
    env["PREFIX"] = str(stage_prefix)
    env["NDDEV_COPILOT_EXPECTED_ASSET_SHA256"] = release_metadata["asset"]["sha256"]
    env["NDDEV_COPILOT_EXPECTED_ASSET_SIZE"] = str(release_metadata["asset"]["size"])
    try:
        completed = subprocess.run(
            [str(require_trusted_executable(BASH_CANDIDATES, "bash")), str(installer_path)],
            cwd=stage,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=INSTALL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        fail(f"Copilot CLI installer shell is missing: {exc}")
    except subprocess.TimeoutExpired:
        fail("Copilot CLI installer timed out in isolated staging home")
    output = completed.stdout + completed.stderr
    if len(output.encode("utf-8")) > PROCESS_OUTPUT_MAX_BYTES:
        fail("Copilot CLI installer output exceeded the size limit")
    if completed.returncode != 0:
        fail(f"Copilot CLI installer failed in isolated staging home: {output.strip()}")
    if release_metadata["asset"]["url"] not in output:
        fail("Copilot CLI installer output did not confirm the pinned artifact URL")
    if "Checksum validated" not in output:
        fail("Copilot CLI installer output did not confirm checksum validation")
    run_stage_version_probe(stage_prefix, stage_home, PROBE_TIMEOUT_SECONDS)
    staged_binary = stage_prefix / "bin" / COMMAND_NAME
    binary_info = require_regular_file(
        staged_binary,
        "staged Copilot CLI executable",
        max_bytes=SOFTWARE_FILE_MAX_BYTES,
    )
    if not os.access(staged_binary, os.X_OK):
        fail("staged Copilot CLI executable is not executable")
    return {
        "stage_prefix": stage_prefix,
        "staged_binary": staged_binary,
        "binary_sha256": sha256_file_bounded(staged_binary, max_bytes=SOFTWARE_FILE_MAX_BYTES, label="staged Copilot CLI executable"),
        "binary_size": binary_info.st_size,
        "installer": {"url": baseline["installer"]["url"], "sha256": expected_installer_sha, "size": expected_installer_size},
        "release": baseline["release"],
        "checksums": release_metadata["checksums"],
        "artifact": release_metadata["asset"],
        "artifact_verification": release_metadata["artifact_verification"],
        "installer_output_sha256": sha256_bytes(output.encode("utf-8")),
    }


def capture_file_snapshot(path: Path, label: str) -> FileSnapshot:
    if not lstat_exists(path):
        return FileSnapshot(exists=False)
    data, info = read_regular_file(path, label, owner_only=True, max_bytes=SOFTWARE_FILE_MAX_BYTES)
    return FileSnapshot(exists=True, data=data, mode=stat.S_IMODE(info.st_mode))


def restore_file_snapshot(path: Path, snapshot: FileSnapshot, target: Path) -> None:
    if not snapshot.exists:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    if snapshot.data is None or snapshot.mode is None:
        fail("software rollback snapshot is invalid")
    ensure_real_parent(path, target)
    temporary = path.with_name(f".{path.name}.rollback.tmp.{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, snapshot.mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(snapshot.data)
    os.replace(temporary, path)
    path.chmod(snapshot.mode)


def prune_empty_software_dirs(target: Path) -> None:
    for directory in (target / "software", target / "bin"):
        with contextlib.suppress(OSError):
            directory.rmdir()


def write_software_receipt(target: Path, install_result: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "version": TESTED_VERSION,
        "release_tag": RELEASE_TAG,
        "command": COMMAND_NAME,
        "installer": load_baseline()["installer"],
        "release": load_baseline()["release"],
        "checksums": install_result["checksums"],
        "artifact": install_result["artifact"],
        "artifact_verification": install_result["artifact_verification"],
        "binary_sha256": install_result["binary_sha256"],
        "binary_size": install_result["binary_size"],
        "installer_output_sha256": install_result["installer_output_sha256"],
    }
    return receipt


def persist_stage_software(target: Path, install_result: dict[str, Any]) -> None:
    executable = copilot_executable(target)
    receipt_path = software_manifest_path(target)
    ensure_real_parent(executable, target)
    ensure_real_parent(receipt_path, target)
    executable_snapshot = capture_file_snapshot(executable, "Copilot CLI executable")
    receipt_snapshot = capture_file_snapshot(receipt_path, "software receipt")
    try:
        temporary = executable.with_name(f".{executable.name}.install.tmp.{os.getpid()}.{time.time_ns()}")
        shutil.copy2(install_result["staged_binary"], temporary)
        temporary.chmod(0o700)
        os.replace(temporary, executable)
        receipt = write_software_receipt(target, install_result)
        temporary_receipt = receipt_path.with_name(f".{receipt_path.name}.install.tmp.{os.getpid()}.{time.time_ns()}")
        fd = os.open(temporary_receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_json(receipt))
        os.replace(temporary_receipt, receipt_path)
        receipt_path.chmod(OWNER_FILE_MODE)
        current_software_metadata(target)
    except BaseException:
        restore_file_snapshot(executable, executable_snapshot, target)
        restore_file_snapshot(receipt_path, receipt_snapshot, target)
        prune_empty_software_dirs(target)
        raise


def software_plan(target: Path) -> dict[str, Any]:
    status = software_status(target)
    action = "none"
    if status["state"] == "absent":
        action = "install"
    elif status["state"] == "partial":
        action = "repair" if status.get("repairable") else "blocked"
    return {"ok": True, "target": str(target), "mutates": False, "action": action, "software": status}


def install_or_update_cli(target: Path, *, operation: str) -> dict[str, Any]:
    create_parent = operation == "software-install"
    if operation == "software-update" and not lstat_exists(target):
        fail("Copilot CLI software is not installed; run software-install")
    with target_lock(target, create_parent=create_parent) as directory_transaction:
        canonical_target = (
            ensure_target_directory(target, directory_transaction)
            if create_parent
            else require_explicit_absolute_target(str(target))
        )
        status = software_status(canonical_target)
        if operation == "software-install":
            if status["state"] == "installed":
                return {"ok": True, "operation": operation, "changed": False, "target": str(canonical_target), "software": status}
            if status["state"] == "partial":
                fail("Copilot CLI software is partial; run software-update to repair it")
        else:
            if status["state"] == "installed":
                return {"ok": True, "operation": operation, "changed": False, "target": str(canonical_target), "software": status}
            if status["state"] == "absent":
                fail("Copilot CLI software is not installed; run software-install")
            if status["state"] == "partial" and not status.get("repairable"):
                fail(status.get("error", "Copilot CLI software is unsafe"))
        baseline = load_baseline()
        stage = Path(
            tempfile.mkdtemp(
                dir=canonical_target.parent,
                prefix=f".{canonical_target.name}.nddev-copilot-cli-stage.",
            )
        )
        stage.chmod(OWNER_DIRECTORY_MODE)
        try:
            install_result = install_software_to_stage(stage, baseline)
            persist_stage_software(canonical_target, install_result)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        new_status = software_status(canonical_target)
    return {
        "ok": True,
        "operation": operation,
        "changed": True,
        "target": str(canonical_target),
        "software": new_status,
    }


def collect_regular_tree(root: Path, label: str) -> dict[Path, bytes]:
    info = stat_existing(root, label)
    if info is None or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} is missing")
    files: dict[Path, bytes] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            fail(f"{label} contains unsupported generated state: {relative}")
        item_info = stat_existing(path, f"{label} {relative}")
        if item_info is None:
            continue
        if stat.S_ISDIR(item_info.st_mode):
            continue
        content, _ = read_regular_file(path, f"{label} {relative}")
        total += len(content)
        if len(files) >= BUILDER_TREE_MAX_FILES:
            fail(f"{label} exceeds the {BUILDER_TREE_MAX_FILES}-file limit")
        if total > BUILDER_TREE_MAX_BYTES:
            fail(f"{label} exceeds the {BUILDER_TREE_MAX_BYTES}-byte limit")
        files[relative] = content
    return files


def validate_markdown_links(root: Path, path: Path, label: str) -> None:
    content, _ = read_regular_file(path, label)
    text = content.decode("utf-8")
    for raw_target in MARKDOWN_LINK_PATTERN.findall(text):
        target = raw_target.split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
            continue
        linked = (path.parent / target).resolve()
        try:
            linked.relative_to(root.resolve())
        except ValueError:
            fail(f"{label} contains an escaped markdown link: {raw_target}")
        if not lstat_exists(linked):
            fail(f"{label} references a missing path: {raw_target}")


def validate_skill_file(path: Path, expected_name: str, label: str) -> str:
    content, _ = read_regular_file(path, label)
    text = content.decode("utf-8")
    if not text.startswith("---\n"):
        fail(f"{label} must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail(f"{label} frontmatter is not closed")
    frontmatter = text[4:end]
    if f"name: {expected_name}" not in frontmatter:
        fail(f"{label} name must be {expected_name}")
    if "description:" not in frontmatter:
        fail(f"{label} must define a description")
    validate_markdown_links(BUILDER_ROOT, path, label)
    return text


def validate_agent_file(path: Path, label: str) -> None:
    content, _ = read_regular_file(path, label)
    text = content.decode("utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        fail(f"{label} must contain YAML frontmatter")
    for key in ("name:", "description:"):
        if key not in text:
            fail(f"{label} must define {key.rstrip(':')}")
    validate_markdown_links(BUILDER_ROOT, path, label)


def validate_builder_toolkit_source() -> dict[Path, bytes]:
    marketplace = load_json_object(
        MARKETPLACE_ROOT / ".github" / "plugin" / "marketplace.json",
        "builder marketplace manifest",
    )
    require_exact_keys(
        marketplace,
        {"name", "owner", "metadata", "plugins"},
        "builder marketplace manifest",
    )
    if marketplace["name"] != BUILDER_MARKETPLACE_NAME:
        fail("builder marketplace name mismatch")
    if not isinstance(marketplace["plugins"], list) or len(marketplace["plugins"]) != 1:
        fail("builder marketplace must contain exactly one plugin")
    plugin_entry = marketplace["plugins"][0]
    if not isinstance(plugin_entry, dict):
        fail("builder marketplace plugin entry must be an object")
    if plugin_entry.get("name") != BUILDER_PLUGIN_NAME:
        fail("builder marketplace plugin name mismatch")
    if plugin_entry.get("source") != "plugins/nddev-builder":
        fail("builder marketplace plugin source mismatch")
    if plugin_entry.get("version") != VERSION:
        fail("builder marketplace plugin version mismatch")
    if plugin_entry.get("strict") is not True:
        fail("builder marketplace entry must use strict validation")

    plugin = load_json_object(BUILDER_ROOT / "plugin.json", "builder plugin manifest")
    require_exact_keys(
        plugin,
        {
            "name",
            "description",
            "version",
            "author",
            "license",
            "keywords",
            "category",
            "tags",
            "agents",
            "skills",
            "hooks",
            "mcpServers",
        },
        "builder plugin manifest",
    )
    if plugin["name"] != BUILDER_PLUGIN_NAME:
        fail("builder plugin name mismatch")
    if plugin["version"] != VERSION:
        fail("builder plugin version mismatch")
    if plugin["agents"] != "agents/" or plugin["skills"] != "skills/":
        fail("builder plugin component paths are invalid")
    if plugin["hooks"] != "hooks.json" or plugin["mcpServers"] != ".mcp.json":
        fail("builder plugin hook or MCP paths are invalid")

    hooks = load_json_object(BUILDER_ROOT / "hooks.json", "builder hooks")
    require_exact_keys(hooks, {"version", "hooks"}, "builder hooks")
    if hooks["version"] != 1 or not isinstance(hooks["hooks"], dict):
        fail("builder hooks must use Copilot hooks schema version 1")
    mcp = load_json_object(BUILDER_ROOT / ".mcp.json", "builder MCP config")
    require_exact_keys(mcp, {"mcpServers"}, "builder MCP config")
    if not isinstance(mcp["mcpServers"], dict):
        fail("builder MCP config mcpServers must be an object")
    validate_agent_file(
        BUILDER_ROOT / "agents" / "nddev-builder.agent.md",
        "builder nddev-builder agent",
    )
    skill_root = BUILDER_ROOT / "skills"
    actual_skills = sorted(
        path.name
        for path in skill_root.iterdir()
        if path.is_dir()
    )
    if actual_skills != sorted(EXPECTED_BUILDER_SKILLS):
        fail("builder skill set does not match the public toolkit contract")
    for skill_dir in sorted(skill_root.iterdir()):
        info = stat_existing(skill_dir, f"builder skill {skill_dir.name}")
        if info is None or not stat.S_ISDIR(info.st_mode):
            continue
        validate_skill_file(
            skill_dir / "SKILL.md",
            skill_dir.name,
            f"builder skill {skill_dir.name}",
        )
    for relative in EXPECTED_BUILDER_REFERENCES:
        read_regular_file(BUILDER_ROOT / relative, f"builder reference {relative}")
        validate_markdown_links(
            BUILDER_ROOT,
            BUILDER_ROOT / relative,
            f"builder reference {relative}",
        )
    return collect_regular_tree(BUILDER_ROOT, "builder plugin source")


def installed_builder_root(target: Path) -> Path:
    return target / BUILDER_INSTALLED_ROOT


def builder_status(target: Path) -> dict[str, Any]:
    source_files = validate_builder_toolkit_source()
    if not lstat_exists(target):
        return {
            "ok": True,
            "target": str(target),
            "installed": False,
            "current": False,
            "state": "absent",
            "plugin": BUILDER_PLUGIN_SPEC,
        }
    canonical_target = require_explicit_absolute_target(str(target))
    root = installed_builder_root(canonical_target)
    if not lstat_exists(root):
        return {
            "ok": True,
            "target": str(canonical_target),
            "installed": False,
            "current": False,
            "state": "missing",
            "plugin": BUILDER_PLUGIN_SPEC,
        }
    try:
        installed_files = collect_regular_tree(root, "installed builder plugin")
    except CopilotCliSetupError as exc:
        return {
            "ok": True,
            "target": str(canonical_target),
            "installed": False,
            "current": False,
            "state": "partial",
            "plugin": BUILDER_PLUGIN_SPEC,
            "error": str(exc),
        }
    missing = sorted(str(path) for path in set(source_files) - set(installed_files))
    drift = sorted(
        str(path)
        for path, content in source_files.items()
        if installed_files.get(path) != content
    )
    current = not missing and not drift
    return {
        "ok": True,
        "target": str(canonical_target),
        "installed": True,
        "current": current,
        "state": "installed" if current else "drift",
        "plugin": BUILDER_PLUGIN_SPEC,
        "installed_root": str(root),
        "missing": missing,
        "drift": drift,
    }


def write_gh_blocker(directory: Path) -> Path:
    directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    directory.chmod(OWNER_DIRECTORY_MODE)
    blocker = directory / "gh"
    script = b"#!/bin/sh\nexit 127\n"
    if lstat_exists(blocker):
        content, info = read_regular_file(blocker, "gh fallback blocker")
        if content != script:
            fail("gh fallback blocker path is not owned by this manager")
        if stat.S_IMODE(info.st_mode) != 0o700:
            blocker.chmod(0o700)
        return directory
    fd = os.open(blocker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(script)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            blocker.unlink()
        raise
    blocker.chmod(0o700)
    return directory


def native_builder_environment(target: Path) -> dict[str, str]:
    env = isolated_child_environment(target)
    runtime = target / "runtime"
    gh_config = runtime / "gh-config"
    no_ambient_bin = write_gh_blocker(runtime / "no-ambient-bin")
    gh_config.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    gh_config.chmod(OWNER_DIRECTORY_MODE)
    env["GH_CONFIG_DIR"] = str(gh_config)
    env["GITHUB_CONFIG_DIR"] = str(gh_config)
    env["COPILOT_OFFLINE"] = "true"
    env["PATH"] = f"{no_ambient_bin}{os.pathsep}{env['PATH']}"
    for name in TOKEN_ENV_NAMES:
        env.pop(name, None)
    return env


def run_native_builder_command(target: Path, argv: list[str]) -> str:
    executable = copilot_executable(target)
    try:
        completed = subprocess.run(
            [str(executable), *argv],
            cwd=target,
            env=native_builder_environment(target),
            text=True,
            capture_output=True,
            check=False,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        fail(f"target-owned Copilot CLI is missing: {exc}")
    except subprocess.TimeoutExpired:
        fail(f"Copilot CLI native builder command timed out: {' '.join(argv)}")
    output = completed.stdout + completed.stderr
    if len(output.encode("utf-8")) > PROCESS_OUTPUT_MAX_BYTES:
        fail("Copilot CLI native builder command output exceeded the size limit")
    if completed.returncode != 0:
        fail(f"Copilot CLI native builder command failed: {output.strip()}")
    return output


def remove_builder_paths_created_by_failed_install(target: Path, had_builder: bool) -> None:
    if had_builder:
        return
    for relative in (
        Path("installed-plugins") / BUILDER_MARKETPLACE_NAME,
        Path("plugin-data") / BUILDER_MARKETPLACE_NAME,
    ):
        path = target / relative
        info = stat_existing(path, f"builder rollback path {relative}")
        if info is None:
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"builder rollback path is not a directory: {relative}")
        shutil.rmtree(path)


def install_builder(target: Path) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    with target_lock(canonical_target, create_parent=False):
        state = inspect_target(canonical_target)
        if state["state"] == "legacy-managed":
            fail("target is legacy-managed; run migrate before installing builder")
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        status = software_status(canonical_target)
        if not status["installed"] or not status["current"]:
            fail("Copilot CLI is not installed at the tested version in this target")
        current = builder_status(canonical_target)
        if current["current"]:
            return {
                "ok": True,
                "operation": "install-builder",
                "changed": False,
                "target": str(canonical_target),
                "builder": current,
            }
        if current["state"] not in {"missing", "absent"}:
            fail("builder plugin cache is not current; remove it before reinstalling")
        managed_snapshot = current_managed_snapshot(canonical_target, MANAGED_PATHS)
        had_builder = lstat_exists(installed_builder_root(canonical_target))
        try:
            run_native_builder_command(
                canonical_target,
                ["plugin", "marketplace", "add", str(MARKETPLACE_ROOT)],
            )
            run_native_builder_command(
                canonical_target,
                ["plugin", "install", BUILDER_PLUGIN_SPEC],
            )
            restore_snapshot(canonical_target, managed_snapshot)
            installed = builder_status(canonical_target)
            if not installed["current"]:
                fail("native builder plugin install did not produce the expected toolkit")
        except BaseException:
            restore_snapshot(canonical_target, managed_snapshot)
            remove_builder_paths_created_by_failed_install(canonical_target, had_builder)
            raise
    return {
        "ok": True,
        "operation": "install-builder",
        "changed": True,
        "target": str(canonical_target),
        "builder": installed,
    }


def isolated_child_environment(target: Path) -> dict[str, str]:
    home = target / "home"
    cache = target / "cache"
    runtime = target / "runtime"
    tmp = runtime / "tmp"
    for directory in (home, cache, runtime, tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
        directory.chmod(OWNER_DIRECTORY_MODE)
    env: dict[str, str] = {}
    for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "COPILOT_HOME": str(target),
            "COPILOT_CACHE_HOME": str(cache),
            "COPILOT_AUTO_UPDATE": "false",
            "TMPDIR": str(tmp),
            "XDG_CONFIG_HOME": str(runtime / "xdg-config"),
            "XDG_CACHE_HOME": str(cache / "xdg-cache"),
            "XDG_STATE_HOME": str(runtime / "xdg-state"),
            "GH_CONFIG_DIR": str(runtime / "gh-config"),
            "GITHUB_CONFIG_DIR": str(runtime / "gh-config"),
            "PATH": DETERMINISTIC_PATH,
        }
    )
    (runtime / "gh-config").mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    (runtime / "gh-config").chmod(OWNER_DIRECTORY_MODE)
    no_ambient_bin = write_gh_blocker(runtime / "no-ambient-bin")
    env["PATH"] = f"{no_ambient_bin}{os.pathsep}{env['PATH']}"
    for name in TOKEN_ENV_NAMES:
        env.pop(name, None)
    return env


def child_args_use_target_scope_overrides(child_args: list[str]) -> str | None:
    for index, arg in enumerate(child_args):
        if arg == "--":
            continue
        if arg in TARGET_SCOPE_FLAGS:
            return arg
        for flag in ("-C", "-w"):
            if arg.startswith(flag) and arg != flag:
                return flag
        for flag in TARGET_SCOPE_FLAGS:
            if arg.startswith(f"{flag}="):
                return flag
        if index > 0 and child_args[index - 1] in TARGET_SCOPE_FLAGS:
            return child_args[index - 1]
    return None


def launch_copilot(target: Path, args: list[str]) -> int:
    override = child_args_use_target_scope_overrides(args)
    if override is not None:
        fail(f"{override} is managed by the target launch environment")
    canonical_target = require_explicit_absolute_target(str(target))
    with target_lock(canonical_target, create_parent=False):
        state = inspect_target(canonical_target)
        if state["state"] == "legacy-managed":
            fail("target is legacy-managed; run migrate before launch")
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        status = software_status(canonical_target)
        if not status["installed"] or not status["current"]:
            fail("Copilot CLI is not installed at the tested version in this target")
        software_before = current_software_metadata(canonical_target)
        builder = builder_status(canonical_target)
        if not builder["current"]:
            fail("nddev-builder native plugin is not installed; run install-builder")
        executable = copilot_executable(canonical_target)
        child_args = list(state["launch_args"]) + args
        child_env = isolated_child_environment(canonical_target)
        software_after = current_software_metadata(canonical_target)
        require_launch_executable_unchanged(software_before, software_after)
        completed = subprocess.run(
            [str(executable), *child_args],
            cwd=canonical_target,
            env=child_env,
            check=False,
            timeout=None,
        )
        return int(completed.returncode)


def print_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print JSON output")


def add_target_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="explicit absolute Copilot CLI home")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list available setups and profiles")
    add_json_argument(list_parser)

    for name in ("status", "software-plan", "software-status", "builder-status"):
        command_parser = subparsers.add_parser(name, help=f"{name} for a target")
        add_target_argument(command_parser)
        add_json_argument(command_parser)

    for name in ("plan", "install", "switch", "migrate"):
        command_parser = subparsers.add_parser(name, help=f"{name} a setup")
        command_parser.add_argument("--setup", default=DEFAULT_SETUP_ID, help="setup id")
        command_parser.add_argument(
            "--profile", default=DEFAULT_PROFILE_ID, help="permission profile id"
        )
        add_target_argument(command_parser)
        add_json_argument(command_parser)

    restore_parser = subparsers.add_parser("restore", help="restore a target-bound backup")
    restore_parser.add_argument("--backup", type=int, required=True, help="backup slot 0..9")
    add_target_argument(restore_parser)
    add_json_argument(restore_parser)

    remove_parser = subparsers.add_parser("remove", help="remove nddev-managed setup files")
    add_target_argument(remove_parser)
    add_json_argument(remove_parser)

    for name in ("software-install", "software-update"):
        command_parser = subparsers.add_parser(name, help=f"{name} exact tested Copilot CLI")
        add_target_argument(command_parser)
        add_json_argument(command_parser)

    install_builder_parser = subparsers.add_parser(
        "install-builder", help="install the native nddev-builder plugin"
    )
    add_target_argument(install_builder_parser)
    add_json_argument(install_builder_parser)

    launch_parser = subparsers.add_parser("launch", help="launch target-owned Copilot CLI")
    add_target_argument(launch_parser)
    add_json_argument(launch_parser)
    launch_parser.add_argument("copilot_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def error_result(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"ok": False, "error": message}, indent=2, sort_keys=True))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def run(args: argparse.Namespace) -> int:
    if args.command == "list":
        print_payload(
            {"ok": True, "setups": list_setups(), "profiles": list_profiles()},
            json_output=args.json,
        )
        return 0
    if args.command == "status":
        target = require_explicit_absolute_target(args.target)
        print_payload({"ok": True, **inspect_target(target)}, json_output=args.json)
        return 0
    if args.command == "software-status":
        target = require_explicit_absolute_target(args.target)
        print_payload(software_status(target), json_output=args.json)
        return 0
    if args.command == "software-plan":
        target = require_explicit_absolute_target(args.target)
        print_payload(software_plan(target), json_output=args.json)
        return 0
    if args.command == "builder-status":
        target = require_explicit_absolute_target(args.target)
        print_payload(builder_status(target), json_output=args.json)
        return 0
    if args.command == "plan":
        target = require_explicit_absolute_target(args.target)
        print_payload(plan_setup(target, args.setup, args.profile), json_output=args.json)
        return 0
    if args.command in {"install", "switch", "migrate"}:
        target = require_explicit_absolute_target(args.target)
        print_payload(
            mutate_setup(target, args.setup, args.profile, args.command),
            json_output=args.json,
        )
        return 0
    if args.command == "restore":
        target = require_explicit_absolute_target(args.target)
        print_payload(restore_backup(target, args.backup), json_output=args.json)
        return 0
    if args.command == "remove":
        target = require_explicit_absolute_target(args.target)
        print_payload(remove_setup(target), json_output=args.json)
        return 0
    if args.command == "software-install":
        target = require_explicit_absolute_target(args.target)
        print_payload(install_or_update_cli(target, operation="software-install"), json_output=args.json)
        return 0
    if args.command == "software-update":
        target = require_explicit_absolute_target(args.target)
        print_payload(install_or_update_cli(target, operation="software-update"), json_output=args.json)
        return 0
    if args.command == "install-builder":
        target = require_explicit_absolute_target(args.target)
        print_payload(install_builder(target), json_output=args.json)
        return 0
    if args.command == "launch":
        target = require_explicit_absolute_target(args.target)
        copilot_args = list(args.copilot_args)
        if copilot_args and copilot_args[0] == "--":
            copilot_args = copilot_args[1:]
        return launch_copilot(target, copilot_args)
    fail(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        return run(args)
    except CopilotCliSetupError as exc:
        json_output = "--json" in (argv if argv is not None else sys.argv[1:])
        return error_result(str(exc), json_output=json_output)


if __name__ == "__main__":
    raise SystemExit(main())
