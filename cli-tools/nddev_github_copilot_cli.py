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
BUILDER_ROOT = ROOT / "plugins" / "nddev-builder"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-github-copilot-cli-app"
COMMAND_NAME = "copilot"
STAMP_NAME = "NDDEV-GITHUB-COPILOT-CLI-SETUP.json"
BACKUP_POOL_NAME = "NDDEV-GITHUB-COPILOT-CLI-BACKUPS.json"
BACKUP_NAME = "NDDEV-GITHUB-COPILOT-CLI-BACKUP.json"
BASELINE_REF = ROOT / "references" / "copilot-cli-baseline.json"
TESTED_VERSION = "1.0.75"
RELEASE_TAG = "v1.0.75"
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
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
MANAGED_SETTINGS_KEYS = (
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
CATALOG_MANAGED_FILES = [
    "settings.json",
    "permissions-config.json",
    "copilot-instructions.md",
    "instructions/nddev-builder.instructions.md",
    "mcp-config.json",
]
BUILDER_SOURCE_FILES = (
    (Path("plugin.json"), Path("plugins") / "nddev-builder" / "plugin.json"),
    (
        Path("skills") / "nddev-builder" / "SKILL.md",
        Path("plugins") / "nddev-builder" / "skills" / "nddev-builder" / "SKILL.md",
    ),
    (
        Path("agents") / "nddev-builder.agent.md",
        Path("plugins") / "nddev-builder" / "agents" / "nddev-builder.agent.md",
    ),
    (Path("hooks.json"), Path("plugins") / "nddev-builder" / "hooks.json"),
    (
        Path("skills") / "nddev-builder" / "SKILL.md",
        Path("skills") / "nddev-builder" / "SKILL.md",
    ),
    (
        Path("agents") / "nddev-builder.agent.md",
        Path("agents") / "nddev-builder.agent.md",
    ),
    (Path("hooks.json"), Path("hooks") / "nddev-builder.json"),
)
MANAGED_PATHS = (
    Path("settings.json"),
    Path("permissions-config.json"),
    Path("copilot-instructions.md"),
    Path("instructions") / "nddev-builder.instructions.md",
    Path("mcp-config.json"),
    *(target for _, target in BUILDER_SOURCE_FILES),
    Path(STAMP_NAME),
)
STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
    "launch_args",
}
BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "managed_files",
    "created_at",
}
BACKUP_POOL_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
}
TOKEN_ENV_NAMES = {
    "COPILOT_ACCESS_TOKEN",
    "COPILOT_GITHUB_TOKEN",
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
    "--autopilot",
    "--max-autopilot-continues",
    "--plan",
    "--reasoning-effort",
    "--resume",
    "--worktree",
    "-w",
    "--yolo",
}


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


def require_regular_file(path: Path, label: str, *, owner_only: bool = False) -> os.stat_result:
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
    if info.st_size > MANAGED_PAYLOAD_MAX_BYTES:
        fail(f"{label} exceeds the {MANAGED_PAYLOAD_MAX_BYTES}-byte size limit")
    return info


def read_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> tuple[bytes, os.stat_result]:
    before = require_regular_file(path, label, owner_only=owner_only)
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
    final = require_regular_file(path, label, owner_only=owner_only)
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


def read_path_bounded(path: Path, *, max_bytes: int, label: str) -> bytes:
    info = require_regular_file(path, label)
    if info.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    data, _ = read_regular_file(path, label, max_bytes=max_bytes)
    return data


def test_override_enabled() -> bool:
    return os.environ.get("NDDEV_COPILOT_CLI_ALLOW_TEST_INSTALLER") == "1"


def read_url_bounded(url: str, *, max_bytes: int, label: str) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in ("", "file"):
        if not test_override_enabled():
            fail(f"{label} fixture override is disabled")
        path = Path(urllib.request.url2pathname(parsed.path) if parsed.scheme else url)
        if not path.is_absolute():
            fail(f"{label} fixture path must be absolute")
        return read_path_bounded(path, max_bytes=max_bytes, label=label)
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


def env_timeout_seconds(name: str, default: int, label: str) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not test_override_enabled():
        fail(f"{label} timeout override is disabled")
    try:
        value = int(raw)
    except ValueError:
        fail(f"{label} timeout override is invalid")
    if value <= 0:
        fail(f"{label} timeout override must be positive")
    return value


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


def validate_settings(settings: dict[str, Any], label: str) -> None:
    required = {
        "remote",
        "remoteExport",
        "storeTokenPlaintext",
        "shellShortcut",
        "keepAlive",
        "sandbox",
        "stayInAutopilot",
        "includeCoAuthoredBy",
        "ide",
        "toolSearch",
        "disabledSkills",
        "enabledPlugins",
        "extraKnownMarketplaces",
    }
    if not required.issubset(settings):
        fail(f"{label} is missing required settings keys")
    if settings["remote"] != "off" or settings["remoteExport"] is not False:
        fail(f"{label} must keep remote sessions disabled")
    if settings["storeTokenPlaintext"] is not False:
        fail(f"{label} must not allow plaintext token storage")
    sandbox = settings.get("sandbox")
    if not isinstance(sandbox, dict):
        fail(f"{label} has invalid sandbox settings")
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
            "builder_projection",
            "builder_default_on",
            "launch_args",
        },
        f"setup {setup_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"setup {setup_id} metadata has unsupported schema")
    if metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity mismatch")
    if metadata["managed_files"] != CATALOG_MANAGED_FILES:
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_projection"] != "native-plugin-plus-user-files":
        fail(f"setup {setup_id} has invalid builder projection")
    if metadata["builder_default_on"] is not True:
        fail(f"setup {setup_id} must enable the builder by default")
    if not isinstance(metadata["launch_args"], list) or not all(
        isinstance(item, str) for item in metadata["launch_args"]
    ):
        fail(f"setup {setup_id} launch_args must be a string array")


def render_builder_files() -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    for source_relative, target_relative in BUILDER_SOURCE_FILES:
        source = BUILDER_ROOT / source_relative
        content, _ = read_regular_file(source, f"builder source {source_relative}")
        files[target_relative] = content
    return files


def render_setup(
    setup_id: str,
    *,
    existing_settings: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[Path, bytes]]:
    validate_setup_id(setup_id)
    setup_root = CATALOG_ROOT / setup_id
    setup_info = stat_existing(setup_root, f"setup {setup_id}")
    if setup_info is None or not stat.S_ISDIR(setup_info.st_mode):
        fail(f"unknown setup: {setup_id}")
    metadata = load_json_object(setup_root / "setup.json", f"setup {setup_id} metadata")
    validate_setup_metadata(metadata, setup_id)
    settings = load_json_object(setup_root / "settings.json", f"setup {setup_id}/settings.json")
    validate_settings(settings, f"setup {setup_id}/settings.json")
    permissions = load_json_object(
        setup_root / "permissions-config.json",
        f"setup {setup_id}/permissions-config.json",
    )
    validate_permissions_config(permissions, f"setup {setup_id}/permissions-config.json")
    instructions, _ = read_regular_file(
        setup_root / "copilot-instructions.md",
        f"setup {setup_id}/copilot-instructions.md",
    )
    modular_instructions, _ = read_regular_file(
        setup_root / "instructions" / "nddev-builder.instructions.md",
        f"setup {setup_id}/instructions/nddev-builder.instructions.md",
    )
    desired: dict[Path, bytes] = {
        Path("settings.json"): canonical_json(merge_settings(existing_settings, settings)),
        Path("permissions-config.json"): canonical_json(permissions),
        Path("copilot-instructions.md"): instructions,
        Path("instructions") / "nddev-builder.instructions.md": modular_instructions,
        Path("mcp-config.json"): canonical_json({"mcpServers": {}}),
    }
    desired.update(render_builder_files())
    stamp = build_stamp(setup_id, desired, metadata["launch_args"])
    desired[Path(STAMP_NAME)] = canonical_json(stamp)
    return metadata, desired


def build_stamp(
    setup_id: str, desired: dict[Path, bytes], launch_args: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": "",
        "managed_files": {
            str(relative): managed_digest(relative, content)
            for relative, content in desired.items()
            if relative != Path(STAMP_NAME)
        },
        "builder_projection": "copilot-native-plugin-user-files",
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
                "launch_args": metadata["launch_args"],
            }
        )
    return setups


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-github-copilot-cli-backups"


def backup_pool_marker(pool: Path) -> Path:
    return pool / BACKUP_POOL_NAME


def lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-github-copilot-cli.lock"


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
    if create_parent:
        ensure_directory_chain(target.parent, transaction, "target parent")
    else:
        require_directory(target.parent, "target parent")
    parent_info = require_private_directory(target.parent, "target parent")
    if stat.S_IMODE(parent_info.st_mode) & 0o022:
        transaction.cleanup()
        fail("target parent must not be group- or world-writable")
    path = lock_path(target)
    try:
        os.mkdir(path, OWNER_DIRECTORY_MODE)
    except FileExistsError:
        transaction.cleanup()
        fail(f"target is locked: {path}")
    except BaseException:
        transaction.cleanup()
        fail(f"target is locked: {path}")
    failed = False
    try:
        yield transaction
    except BaseException:
        failed = True
        raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.rmdir()
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
        for relative in MANAGED_PATHS
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


def load_stamp(target: Path) -> dict[str, Any] | None:
    stamp = target / STAMP_NAME
    if not lstat_exists(stamp):
        return None
    value = load_json_object(stamp, "setup stamp", owner_only=True)
    require_exact_keys(value, STAMP_KEYS, "setup stamp")
    if value["schema_version"] != 1:
        fail("setup stamp has unsupported schema")
    if value["product_name"] != PRODUCT_NAME:
        fail("setup stamp belongs to another product")
    if value["build_version"] != VERSION:
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
    return value


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
    stamp = load_stamp(target)
    if stamp is None:
        if any_managed_path_exists(target):
            fail("unmanaged target contains nddev-managed paths")
        return {"state": "unmanaged", "target": str(target)}
    managed_files = validate_managed_files(target, stamp)
    return {
        "state": "managed",
        "target": str(target),
        "setup_id": stamp["setup_id"],
        "build_version": stamp["build_version"],
        "managed_files": managed_files,
        "builder_projection": stamp["builder_projection"],
        "launch_args": stamp["launch_args"],
    }


def read_existing_settings_if_managed(target: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("state") != "managed":
        return None
    return load_json_object(target / "settings.json", "existing settings.json", owner_only=True)


def current_managed_snapshot(target: Path) -> dict[Path, bytes | None]:
    snapshot: dict[Path, bytes | None] = {}
    for relative in MANAGED_PATHS:
        path = target / relative
        if lstat_exists(path):
            content, _ = read_regular_file(path, f"managed file {relative}", owner_only=True)
            snapshot[relative] = content
        else:
            snapshot[relative] = None
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[Path, bytes | None]) -> None:
    for relative in sorted(MANAGED_PATHS, key=lambda item: len(item.parts), reverse=True):
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
    prune_empty_managed_dirs(target)


def prune_empty_managed_dirs(target: Path) -> None:
    candidates = sorted(
        {(target / relative).parent for relative in MANAGED_PATHS},
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
    prune_empty_managed_dirs(target)


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
            shutil.rmtree(current)
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
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": 0,
        "canonical_target": str(target),
        "source_setup_id": state["setup_id"],
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
    if marker["build_version"] != VERSION:
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
        pool.mkdir(mode=OWNER_DIRECTORY_MODE)
        pool.chmod(OWNER_DIRECTORY_MODE)
        write_backup_pool_marker(target, pool)
        return pool
    require_current_owner(info, "backup pool")
    if not stat.S_ISDIR(info.st_mode):
        fail("backup pool must be a directory")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("backup pool must be private")
    validate_backup_pool_marker(target, pool)
    return pool


def require_backup_pool(target: Path) -> Path:
    pool = backup_pool(target)
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
    require_exact_keys(envelope, BACKUP_KEYS, label)
    if envelope["schema_version"] != 1:
        fail(f"{label} has unsupported schema")
    if envelope["product_name"] != PRODUCT_NAME:
        fail("backup belongs to another product")
    if envelope["build_version"] != VERSION:
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
        envelope_path.write_bytes(canonical_json(envelope))
        envelope_path.chmod(OWNER_FILE_MODE)


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


def mutate_setup(target: Path, setup_id: str, operation: str) -> dict[str, Any]:
    with target_lock(target, create_parent=True) as directory_transaction:
        canonical_target = ensure_target_directory(target, directory_transaction)
        state = inspect_target(canonical_target)
        if state["state"] == "unmanaged" and any_managed_path_exists(canonical_target):
            fail("unmanaged target contains nddev-managed paths")
        existing_settings = read_existing_settings_if_managed(canonical_target, state)
        metadata, desired = render_setup(setup_id, existing_settings=existing_settings)
        stamp = bind_stamp(
            parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
        )
        desired[Path(STAMP_NAME)] = canonical_json(stamp)
        changed = changed_paths(canonical_target, desired)
        backup_slot: int | None = None
        snapshot = current_managed_snapshot(canonical_target)
        try:
            if state["state"] == "managed" and changed:
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
        "description": metadata["description"],
        "target": str(canonical_target),
        "changed": changed,
        "backup_slot": backup_slot,
        "state": post["state"],
    }


def plan_setup(target: Path, setup_id: str) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    state = inspect_target(canonical_target)
    existing_settings = read_existing_settings_if_managed(canonical_target, state)
    _metadata, desired = render_setup(setup_id, existing_settings=existing_settings)
    if state["state"] == "managed":
        stamp = bind_stamp(
            parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
        )
        desired[Path(STAMP_NAME)] = canonical_json(stamp)
        changed = changed_paths(canonical_target, desired)
        operation = "switch" if state.get("setup_id") != setup_id else "install"
        backup_required = bool(changed)
    else:
        changed = sorted(str(path) for path in desired)
        operation = "install"
        backup_required = False
    return {
        "ok": True,
        "operation": operation,
        "setup_id": setup_id,
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
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        snapshot = current_managed_snapshot(canonical_target)
        desired = {relative: None for relative in MANAGED_PATHS}
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
        "backup_slot": backup_slot,
    }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    canonical_target = require_explicit_absolute_target(str(target))
    with target_lock(canonical_target, create_parent=False):
        state = inspect_target(canonical_target)
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        envelope, desired = load_backup(canonical_target, slot)
        snapshot = current_managed_snapshot(canonical_target)
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
        "restored_from_slot": slot,
        "restored_source_setup_id": envelope["source_setup_id"],
    }


def load_baseline() -> dict[str, Any]:
    return load_json_object(BASELINE_REF, "Copilot CLI baseline")


def installer_source(baseline: dict[str, Any]) -> tuple[str, str, int]:
    installer = baseline["installer"]
    official_url = installer["url"]
    official_sha256 = installer["sha256"]
    official_size = int(installer["size"])
    url = os.environ.get("NDDEV_COPILOT_CLI_INSTALLER_URL", official_url)
    sha256 = os.environ.get("NDDEV_COPILOT_CLI_INSTALLER_SHA256", official_sha256)
    size = int(os.environ.get("NDDEV_COPILOT_CLI_INSTALLER_SIZE", str(official_size)))
    if (url != official_url or sha256 != official_sha256 or size != official_size) and not test_override_enabled():
        fail("unofficial Copilot CLI installer override is disabled")
    return url, sha256, size


def checksums_source(baseline: dict[str, Any]) -> tuple[str, str, int]:
    checksums = baseline["release"]["checksums"]
    official_url = checksums["url"]
    official_sha256 = checksums["sha256"]
    official_size = int(checksums["size"])
    url = os.environ.get("NDDEV_COPILOT_CLI_CHECKSUMS_URL", official_url)
    sha256 = os.environ.get("NDDEV_COPILOT_CLI_CHECKSUMS_SHA256", official_sha256)
    size = int(os.environ.get("NDDEV_COPILOT_CLI_CHECKSUMS_SIZE", str(official_size)))
    if (url != official_url or sha256 != official_sha256 or size != official_size) and not test_override_enabled():
        fail("unofficial Copilot CLI checksums override is disabled")
    return url, sha256, size


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
        family = "linuxmusl" if libc_name == "musl" else "linux"
        asset_name = f"copilot-{family}-{arch}.tar.gz"
    elif system.startswith("win"):
        asset_name = f"copilot-win32-{arch}.zip"
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
    override_url = os.environ.get("NDDEV_COPILOT_CLI_ASSET_URL")
    override_sha = os.environ.get("NDDEV_COPILOT_CLI_ASSET_SHA256")
    override_size = os.environ.get("NDDEV_COPILOT_CLI_ASSET_SIZE")
    if any(value is not None for value in (override_url, override_sha, override_size)):
        if not test_override_enabled():
            fail("unofficial Copilot CLI asset override is disabled")
        if override_url is None or override_sha is None or override_size is None:
            fail("Copilot CLI asset test override must include URL, SHA256, and size")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", override_sha):
            fail("Copilot CLI asset test override SHA256 is invalid")
        try:
            expected_size = int(override_size)
        except ValueError:
            fail("Copilot CLI asset test override size is invalid")
        if expected_size <= 0:
            fail("Copilot CLI asset test override size must be positive")
        url = override_url
        expected_sha = override_sha.lower()
    if test_override_enabled():
        if parsed.get(asset_name) != expected_sha:
            fail(f"Copilot CLI checksums do not match selected asset {asset_name}")
    else:
        for expected_name, expected_asset in assets.items():
            if parsed.get(expected_name) != expected_asset["sha256"]:
                fail(f"Copilot CLI checksums do not match pinned asset {expected_name}")
    if override_url is not None:
        url = override_url
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme in ("", "file"):
        if not test_override_enabled():
            fail("Copilot CLI artifact fixture override is disabled")
        path = Path(urllib.request.url2pathname(parsed_url.path) if parsed_url.scheme else url)
        if not path.is_absolute():
            fail("Copilot CLI artifact fixture path must be absolute")
        info = require_regular_file(path, "Copilot CLI artifact fixture")
        if info.st_size != expected_size:
            fail("Copilot CLI artifact fixture size does not match the pinned baseline")
        if sha256_file_bounded(path, max_bytes=expected_size + 1, label="Copilot CLI artifact fixture") != expected_sha:
            fail("Copilot CLI artifact fixture SHA256 does not match the pinned baseline")
        method = "file"
    else:
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
        method = "head"
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
        "artifact_verification": {"size_verified": True, "sha256_verified": method == "file", "method": method},
    }


def software_manifest_path(target: Path) -> Path:
    return target / "software" / "copilot-cli.json"


def copilot_executable(target: Path) -> Path:
    suffix = ".exe" if sys.platform.startswith("win") else ""
    return target / "bin" / f"{COMMAND_NAME}{suffix}"


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
    if artifact != expected_artifact and not test_override_enabled():
        runtime_fail("software receipt artifact does not match the baseline", code="software_receipt_artifact", repairable=True)
    binary_sha = sha256_file_bounded(executable, max_bytes=SOFTWARE_FILE_MAX_BYTES, label="Copilot CLI executable")
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
        },
        "receipt_sha256": sha256_file_bounded(manifest_path, max_bytes=METADATA_MAX_BYTES, label="software receipt"),
    }


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
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"):
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
    install_timeout = env_timeout_seconds(
        "NDDEV_COPILOT_CLI_INSTALL_TIMEOUT_SECONDS",
        INSTALL_TIMEOUT_SECONDS,
        "Copilot CLI installer",
    )
    probe_timeout = env_timeout_seconds(
        "NDDEV_COPILOT_CLI_PROBE_TIMEOUT_SECONDS",
        PROBE_TIMEOUT_SECONDS,
        "Copilot CLI version probe",
    )
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
            ["bash", str(installer_path)],
            cwd=stage,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=install_timeout,
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
    run_stage_version_probe(stage_prefix, stage_home, probe_timeout)
    staged_binary = stage_prefix / "bin" / COMMAND_NAME
    binary_info = require_regular_file(staged_binary, "staged Copilot CLI executable")
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


def isolated_child_environment(target: Path) -> dict[str, str]:
    home = target / "home"
    cache = target / "cache"
    runtime = target / "runtime"
    tmp = runtime / "tmp"
    for directory in (home, cache, runtime, tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
        directory.chmod(OWNER_DIRECTORY_MODE)
    env: dict[str, str] = {}
    for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    if test_override_enabled():
        for name in ("FAKE_COPILOT_CAPTURE", "FAKE_COPILOT_EXIT"):
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
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
    )
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
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        status = software_status(canonical_target)
        if not status["installed"] or not status["current"]:
            fail("Copilot CLI is not installed at the tested version in this target")
        executable = copilot_executable(canonical_target)
        child_args = list(state["launch_args"]) + args
        child_env = isolated_child_environment(canonical_target)
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

    list_parser = subparsers.add_parser("list", help="list available setup variants")
    add_json_argument(list_parser)

    for name in ("status", "software-plan", "software-status"):
        command_parser = subparsers.add_parser(name, help=f"{name} for a target")
        add_target_argument(command_parser)
        add_json_argument(command_parser)

    for name in ("plan", "install", "switch"):
        command_parser = subparsers.add_parser(name, help=f"{name} a setup")
        command_parser.add_argument("--setup", required=True, help="setup id")
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
        print_payload({"ok": True, "setups": list_setups()}, json_output=args.json)
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
    if args.command == "plan":
        target = require_explicit_absolute_target(args.target)
        print_payload(plan_setup(target, args.setup), json_output=args.json)
        return 0
    if args.command in {"install", "switch"}:
        target = require_explicit_absolute_target(args.target)
        print_payload(mutate_setup(target, args.setup, args.command), json_output=args.json)
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
