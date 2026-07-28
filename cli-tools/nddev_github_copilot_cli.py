#!/usr/bin/env python3
"""Transactional setup manager for an explicit GitHub Copilot CLI home."""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
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
TRANSACTION_STASH_MARKER_NAME = ".nddev-transaction-stash.json"
BASELINE_REF = ROOT / "references" / "copilot-cli-baseline.json"
TARGET_LOCK_DIRECTORY_NAME = ".nddev-github-copilot-cli.lock"
TARGET_LOCK_FILE_NAME = "lifecycle.lock"
GLOBAL_COORDINATION_LOCK_FILE_NAME = "global.lock"
CLEANUP_NAME_COMPONENT = "nddev-github-copilot-cli.cleanup"
CLEANUP_JOURNAL_FILE_NAME = "pending.json"
CLEANUP_PROMOTION_INTENT_FILE_NAME = "promotion-intent.json"
CLEANUP_SCHEMA = 1
CLEANUP_MAX_ENTRIES = 4
CLEANUP_MAX_TREE_ENTRIES = 2048
CLEANUP_MAX_TREE_BYTES = 128 * 1024 * 1024
CLEANUP_MAX_JOURNAL_BYTES = 1024 * 1024
CLEANUP_MAX_PROMOTION_INTENT_BYTES = 2 * 1024 * 1024
RECOVERABLE_CLEANUP_SOURCE_KINDS = (
    "managed",
    "backup-pool",
    "software",
    "software-remove",
    "builder-install",
)
EXTERNAL_LOCK_SCHEMA = 1
EXTERNAL_LOCK_KIND = "external-bootstrap-lifecycle"
PRODUCT_COORDINATION_LOCK_KIND = "external-bootstrap-product"
LOCK_HELD_DIRECTORY_MODE = 0o500
TESTED_VERSION = "1.0.75"
RELEASE_TAG = "v1.0.75"
STAMP_SCHEMA = 3
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
IMMUTABLE_LAUNCH_DIRECTORIES = (Path("bin"), Path("software"))
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
STAMP_KEYS_V3 = {
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
BACKUP_SCHEMA = 3
BACKUP_KEYS_V3 = BACKUP_KEYS_V2
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


class JsonCliArgumentError(CopilotCliSetupError):
    """A parse error rendered through the JSON error boundary."""


class JsonArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, json_errors: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.json_errors = json_errors

    def error(self, message: str) -> None:
        if self.json_errors:
            raise JsonCliArgumentError(message)
        super().error(message)


class DurableReplaceError(OSError):
    """A staged durable replacement failed at a known phase."""

    def __init__(self, stage: str, original: BaseException) -> None:
        super().__init__(str(original))
        self.stage = stage
        self.original = original


class NoReplacePublicationError(DurableReplaceError):
    """A no-replace publication failed with known final-path visibility."""

    def __init__(
        self, stage: str, original: BaseException, *, final_visible: bool, temp: Path
    ) -> None:
        super().__init__(stage, original)
        self.final_visible = final_visible
        self.temp = temp


@dataclass
class DirectoryTransaction:
    created: list[Path]
    directory_snapshots: dict[Path, DirectorySnapshot] = field(default_factory=dict)

    def remember_directory(self, path: Path, label: str) -> None:
        if path in self.created or path in self.directory_snapshots:
            return
        snapshot = capture_directory_snapshot(path, label)
        if snapshot.exists:
            self.directory_snapshots[path] = snapshot

    def cleanup(self) -> None:
        cleanup_error: BaseException | None = None
        for path in reversed(self.created):
            try:
                path.rmdir()
                fsync_directory(path.parent, f"created directory cleanup parent {path.name}")
            except FileNotFoundError:
                continue
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        try:
            restore_absolute_directory_snapshots(
                self.directory_snapshots, "directory transaction cleanup"
            )
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error


@dataclass
class FileLock:
    descriptor: int
    path: Path
    identity: tuple[int, int]
    parent: Path
    parent_identity: tuple[int, int]
    created: bool
    parent_snapshot: DirectorySnapshot | None = None


@dataclass
class ExternalLifecycleLock:
    descriptor: int
    path: Path
    identity: tuple[int, int]
    parent: Path
    parent_identity: tuple[int, int]
    parent_snapshot: DirectorySnapshot
    canonical_target: Path


@dataclass
class BootstrapDirectoryLock:
    descriptor: int
    path: Path
    identity: tuple[int, int]


@dataclass
class ProductCoordinationLock:
    descriptor: int
    path: Path
    identity: tuple[int, int]
    parent: Path
    parent_identity: tuple[int, int]
    parent_snapshot: DirectorySnapshot


@dataclass
class TargetLockContext:
    target: Path
    transaction: DirectoryTransaction


@dataclass
class ProtectedDirectory:
    path: Path
    snapshot: DirectorySnapshot


@dataclass
class FileSnapshot:
    exists: bool
    data: bytes | None = None
    mode: int | None = None
    device: int | None = None
    inode: int | None = None
    mtime_ns: int | None = None


@dataclass
class DirectorySnapshot:
    exists: bool
    mode: int | None = None
    device: int | None = None
    inode: int | None = None
    mtime_ns: int | None = None
    size: int | None = None


@dataclass
class FileSetTransaction:
    root: Path
    stash_root: Path
    files: dict[Path, FileSnapshot]
    directories: dict[Path, DirectorySnapshot]
    parent_directories: dict[Path, DirectorySnapshot]


@dataclass
class BackupPoolTransaction:
    target: Path
    pool: Path
    stash_root: Path
    stashed_pool: Path | None
    parent_directories: dict[Path, DirectorySnapshot]


@dataclass
class BuilderInstallPathTransaction:
    target: Path
    stash_root: Path
    stashed_paths: dict[Path, Path]
    absent_paths: set[Path]
    parent_directories: dict[Path, DirectorySnapshot]


@dataclass
class CleanupNamespaceTransaction:
    root: Path
    namespace: Path
    snapshots: dict[Path, DirectorySnapshot]
    created_root: bool = False
    created_namespace: bool = False


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


def file_record(relative: Path, content: bytes) -> dict[str, Any]:
    return {
        "path": str(relative),
        "size": len(content),
        "sha256": sha256_bytes(content),
    }


def file_records(contents: dict[Path, bytes]) -> dict[str, dict[str, Any]]:
    return {str(relative): file_record(relative, content) for relative, content in contents.items()}


def validate_file_records(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        fail(f"{label} must be a file-record object")
    records: dict[str, dict[str, Any]] = {}
    for key, raw_record in value.items():
        if not isinstance(key, str):
            fail(f"{label} path keys must be strings")
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != key:
            fail(f"{label} contains an unsafe path")
        if not isinstance(raw_record, dict):
            fail(f"{label} record for {key} must be an object")
        require_exact_keys(raw_record, {"path", "size", "sha256"}, f"{label} record {key}")
        if raw_record["path"] != key:
            fail(f"{label} record {key} path mismatch")
        if not isinstance(raw_record["size"], int) or raw_record["size"] < 0:
            fail(f"{label} record {key} size is invalid")
        if not isinstance(raw_record["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", raw_record["sha256"]
        ):
            fail(f"{label} record {key} sha256 is invalid")
        records[key] = dict(raw_record)
    return records


def assert_file_record_matches(
    relative: Path, content: bytes, record: dict[str, Any], label: str
) -> None:
    expected = file_record(relative, content)
    if record != expected:
        fail(f"{label} file record mismatch for {relative}")


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


def path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


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


def is_owner_safe_directory(info: os.stat_result) -> bool:
    if not stat.S_ISDIR(info.st_mode):
        return False
    if current_owner() is not None and owner_of(info) != current_owner():
        return False
    return (stat.S_IMODE(info.st_mode) & 0o022) == 0


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
    try:
        initial = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    require_current_owner(initial, label)
    if stat.S_ISLNK(initial.st_mode):
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            fail(f"{label} symlink could not be resolved safely: {exc}")
        parent_info = require_directory(resolved, label)
        if not is_owner_safe_directory(parent_info):
            fail(f"{label} must be owned by the current user and not group- or world-writable")
        final = path.lstat()
        if identity_of(final) != identity_of(initial):
            fail_concurrent(f"{label} symlink changed while it was being resolved")
    else:
        if not stat.S_ISDIR(initial.st_mode):
            fail(f"{label} must be a real directory")
        if not is_owner_safe_directory(initial):
            fail(f"{label} must be owned by the current user and not group- or world-writable")
        parent_info = initial
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            fail(f"{label} could not be resolved safely: {exc}")
    del parent_info
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
    flags |= require_no_follow_flag(label)
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


def fsync_directory(path: Path, label: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def retrying_replace(source: Path, destination: Path, _label: str) -> None:
    first_error: BaseException | None = None
    for attempt in range(2):
        try:
            os.replace(source, destination)
            return
        except BaseException as exc:
            if attempt == 0:
                first_error = exc
                continue
            if first_error is not None:
                raise first_error from exc
            raise


def retrying_unlink(path: Path, label: str) -> None:
    if not lstat_exists(path):
        return
    first_error: BaseException | None = None
    for attempt in range(2):
        try:
            path.unlink()
            fsync_directory(path.parent, f"{label} parent")
            return
        except FileNotFoundError:
            fsync_directory(path.parent, f"{label} parent")
            return
        except BaseException as exc:
            if attempt == 0:
                first_error = exc
                continue
            if first_error is not None:
                raise first_error from exc
            raise


def remove_private_tree_verified(path: Path, label: str) -> None:
    if not lstat_exists(path):
        return
    parent = path.parent
    first_error: BaseException | None = None
    for attempt in range(2):
        try:
            remove_private_tree(path, label)
            fsync_directory(parent, f"{label} parent")
        except FileNotFoundError:
            fsync_directory(parent, f"{label} parent")
        except BaseException as exc:
            active_error: BaseException = exc
            if not lstat_exists(path):
                try:
                    fsync_directory(parent, f"{label} parent")
                    return
                except BaseException as fsync_exc:
                    active_error = fsync_exc
            if attempt == 0:
                first_error = active_error
                continue
            if first_error is not None:
                raise first_error from active_error
            raise
        if not lstat_exists(path):
            return
        if attempt == 0:
            first_error = CopilotCliSetupError(f"{label} cleanup left residue")
            continue
    if first_error is not None:
        raise first_error
    fail(f"{label} cleanup left residue")


def restore_file_snapshot_exact(
    path: Path,
    snapshot: FileSnapshot,
    label: str,
    *,
    max_bytes: int,
) -> None:
    if not snapshot.exists:
        if lstat_exists(path):
            require_regular_file(path, label, max_bytes=max_bytes)
            retrying_unlink(path, label)
        if lstat_exists(path):
            fail(f"{label} rollback expected absent path")
        return
    if snapshot.data is None or snapshot.mode is None or snapshot.mtime_ns is None:
        fail(f"{label} rollback snapshot is invalid")
    current = require_regular_file(path, label, max_bytes=max_bytes)
    if snapshot.device is not None and current.st_dev != snapshot.device:
        fail(f"{label} rollback device mismatch")
    if snapshot.inode is not None and current.st_ino != snapshot.inode:
        fail(f"{label} rollback inode mismatch")
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag(label)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(current):
            fail_concurrent(f"{label} changed while it was being restored")
        os.fchmod(descriptor, snapshot.mode)
        remaining = snapshot.data
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                fail(f"{label} rollback content could not be written")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    refreshed = require_regular_file(path, label, max_bytes=max_bytes)
    os.utime(path, ns=(refreshed.st_atime_ns, snapshot.mtime_ns))
    assert_file_snapshot_postcondition(path, snapshot, label)


def restore_lock_file_snapshot_if_changed(
    path: Path,
    snapshot: FileSnapshot | None,
    label: str,
) -> None:
    if snapshot is None:
        return
    current = capture_file_snapshot(
        path,
        label,
        allowed_modes={OWNER_FILE_MODE} if lstat_exists(path) else None,
    )
    if current != snapshot:
        restore_file_snapshot_exact(path, snapshot, label, max_bytes=METADATA_MAX_BYTES)


def rollback_created_lock_file(
    path: Path,
    parent_snapshot: DirectorySnapshot,
    label: str,
) -> None:
    cleanup_error: BaseException | None = None
    try:
        info = stat_existing(path, label)
        if info is not None:
            require_current_owner(info, label)
            if not stat.S_ISREG(info.st_mode):
                fail(f"{label} must be a regular file before rollback removal")
            path.unlink()
            fsync_directory(path.parent, f"{label} rollback parent")
    except BaseException as exc:
        cleanup_error = exc
    try:
        restore_directory_snapshot(path.parent, parent_snapshot, f"{label} parent")
    except BaseException as exc:
        if cleanup_error is None:
            cleanup_error = exc
    if cleanup_error is not None:
        raise cleanup_error


def rollback_lock_binding_failure(
    path: Path,
    *,
    created: bool,
    parent_snapshot: DirectorySnapshot,
    file_snapshot: FileSnapshot | None,
    label: str,
) -> None:
    cleanup_error: BaseException | None = None
    try:
        if created:
            rollback_created_lock_file(path, parent_snapshot, label)
        else:
            restore_lock_file_snapshot_if_changed(path, file_snapshot, label)
            restore_directory_snapshot(path.parent, parent_snapshot, f"{label} parent")
    except BaseException as exc:
        cleanup_error = exc
    if cleanup_error is not None:
        raise cleanup_error


def transaction_stash_root(
    root: Path,
    purpose: str,
    parent_snapshots: dict[Path, DirectorySnapshot] | None = None,
) -> Path:
    parent = root.parent
    parent_info = require_directory(parent, f"{purpose} transaction parent")
    if not is_owner_safe_directory(parent_info):
        fail(
            f"{purpose} transaction parent must be owned by the current user "
            "and not group- or world-writable"
        )
    parent_snapshot = capture_directory_snapshot(parent, f"{purpose} transaction parent")
    safe_purpose = re.sub(r"[^a-z0-9]+", "-", purpose.lower()).strip("-") or "state"
    stash = parent / f".{root.name}.nddev-{safe_purpose}.{os.getpid()}.{time.time_ns()}"
    created = False
    try:
        stash.mkdir(mode=OWNER_DIRECTORY_MODE)
        created = True
        stash.chmod(OWNER_DIRECTORY_MODE)
        marker = {
            "schema_version": 1,
            "product_name": PRODUCT_NAME,
            "stash_kind": safe_purpose,
            "root_name": root.name,
            "source_parent": cleanup_source_parent_record(root),
        }
        write_file_content_durable(
            stash / TRANSACTION_STASH_MARKER_NAME,
            canonical_json(marker),
            OWNER_FILE_MODE,
            f"{purpose} transaction stash marker",
        )
        fsync_directory(parent, f"{purpose} transaction parent")
        if parent_snapshots is not None and parent_snapshot.exists:
            parent_snapshots.setdefault(parent, parent_snapshot)
        return stash
    except BaseException:
        cleanup_error: BaseException | None = None
        if created and lstat_exists(stash):
            try:
                remove_private_tree_verified(stash, f"{purpose} transaction stash")
            except BaseException as exc:
                cleanup_error = exc
        try:
            restore_directory_snapshot(parent, parent_snapshot, f"{purpose} transaction parent")
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error
        raise


def write_file_content_durable(path: Path, content: bytes, mode: int, label: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags, mode)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    fsync_directory(path.parent, f"{label} parent")


def durable_replace_file(
    path: Path,
    content: bytes,
    mode: int,
    target: Path,
    label: str,
    *,
    marker: str = ".tmp.",
) -> None:
    ensure_real_parent(path, target)
    temporary = path.with_name(f".{path.name}{marker}{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    stage = "prepare"
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        stage = "replace"
        os.replace(temporary, path)
        stage = "parent-fsync"
        fsync_directory(path.parent, f"{label} parent")
    except BaseException:
        exc = sys.exc_info()[1]
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        if exc is not None:
            raise DurableReplaceError(stage, exc) from exc
        raise
    finally:
        if fd >= 0:
            os.close(fd)


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
        if any(
            arg.startswith("--allow") or arg in {"--yolo", "--mode=autopilot"}
            for arg in metadata["launch_args"]
        ):
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
    settings = load_json_object(
        profile_root / "settings.json", f"profile {profile_id}/settings.json"
    )
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
    mcp_config = load_json_object(
        setup_root / "mcp-config.json", f"setup {setup_id}/mcp-config.json"
    )
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
    managed_contents = {
        relative: content for relative, content in desired.items() if relative != Path(STAMP_NAME)
    }
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": "",
        "managed_files": file_records(managed_contents),
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


def lock_parent_path(target: Path) -> Path:
    return target / TARGET_LOCK_DIRECTORY_NAME


def lock_path(target: Path) -> Path:
    return lock_parent_path(target) / TARGET_LOCK_FILE_NAME


def fixed_system_temp_root() -> Path:
    try:
        root = Path("/tmp").resolve(strict=True)
    except FileNotFoundError:
        fail("fixed system temp root is missing")
    info = stat_existing(root, "fixed system temp root")
    if info is None or not stat.S_ISDIR(info.st_mode):
        fail("fixed system temp root must be a real directory")
    if (stat.S_IMODE(info.st_mode) & stat.S_ISVTX) == 0:
        fail("fixed system temp root must be sticky")
    return root


def bootstrap_root_path() -> Path:
    owner = current_owner()
    if owner is None:
        fail("external lifecycle lock requires a current user id")
    return fixed_system_temp_root() / f"{PRODUCT_NAME}.{owner}.bootstrap"


def canonical_target_digest(target: Path) -> str:
    return hashlib.sha256(f"{PRODUCT_NAME}\0{target}".encode("utf-8")).hexdigest()


def ensure_bootstrap_root() -> Path:
    root = bootstrap_root_path()
    parent = root.parent
    parent_info = stat_existing(parent, "fixed system temp root")
    parent_snapshot: DirectorySnapshot | None = None
    owner = current_owner()
    if parent_info is not None and (owner is None or owner_of(parent_info) == owner):
        parent_snapshot = capture_directory_snapshot(parent, "fixed system temp root")
    info = stat_existing(root, "external lifecycle lock root")
    created = False
    if info is None:
        try:
            root.mkdir(mode=OWNER_DIRECTORY_MODE)
            created = True
            root.chmod(OWNER_DIRECTORY_MODE)
            info = stat_existing(root, "external lifecycle lock root")
            require_current_owner(info, "external lifecycle lock root")
            if not stat.S_ISDIR(info.st_mode):
                fail("external lifecycle lock root must be a real directory")
            if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                fail(
                    "external lifecycle lock root must be owned by the current user with mode 0700"
                )
            fsync_directory(parent, "fixed system temp root")
        except FileExistsError:
            info = stat_existing(root, "external lifecycle lock root")
        except BaseException:
            cleanup_error: BaseException | None = None
            if lstat_exists(root):
                try:
                    require_private_directory(root, "external lifecycle lock root")
                    root.rmdir()
                    fsync_directory(parent, "external lifecycle lock root rollback parent")
                except BaseException as exc:
                    cleanup_error = exc
            if parent_snapshot is not None:
                try:
                    restore_directory_snapshot(parent, parent_snapshot, "fixed system temp root")
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
            if cleanup_error is not None:
                raise cleanup_error
            raise
    if created and parent_snapshot is not None:
        restore_directory_snapshot(
            parent,
            parent_snapshot,
            "fixed system temp root",
            verify_size=False,
        )
    if info is None:
        fail("external lifecycle lock root is missing")
    require_current_owner(info, "external lifecycle lock root")
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root must be owned by the current user with mode 0700")
    return root


def bootstrap_lock_path_no_create(target: Path) -> Path:
    return bootstrap_root_path() / f"{PRODUCT_NAME}.{canonical_target_digest(target)}.lock"


def bootstrap_lock_path(target: Path) -> Path:
    return ensure_bootstrap_root() / bootstrap_lock_path_no_create(target).name


def product_coordination_lock_path_no_create() -> Path:
    return bootstrap_root_path() / GLOBAL_COORDINATION_LOCK_FILE_NAME


def product_coordination_lock_path() -> Path:
    return ensure_bootstrap_root() / GLOBAL_COORDINATION_LOCK_FILE_NAME


def canonical_target_for_lifecycle_lock(target: Path) -> Path:
    if not target.is_absolute():
        fail("--target must be an absolute path")
    if target.name in {"", ".", ".."}:
        fail("--target must name a directory")
    resolved_parent = require_safe_target_parent(target.parent, "target parent")
    return resolved_parent / target.name


def product_coordination_lock_marker() -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "lock_kind": PRODUCT_COORDINATION_LOCK_KIND,
    }


def validate_product_coordination_lock_marker(raw: bytes) -> None:
    marker = parse_json_object(raw, "product coordination lock")
    require_exact_keys(
        marker,
        {"schema_version", "product_name", "lock_kind"},
        "product coordination lock",
    )
    if marker["schema_version"] != EXTERNAL_LOCK_SCHEMA:
        fail("product coordination lock has unsupported schema")
    if marker["product_name"] != PRODUCT_NAME:
        fail("product coordination lock product mismatch")
    if marker["lock_kind"] != PRODUCT_COORDINATION_LOCK_KIND:
        fail("product coordination lock kind mismatch")


def read_product_coordination_lock_marker(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, METADATA_MAX_BYTES + 1)
    if len(raw) > METADATA_MAX_BYTES:
        fail("product coordination lock exceeds the metadata size limit")
    if not raw:
        fail("product coordination lock marker is incomplete")
    validate_product_coordination_lock_marker(raw)


def open_bootstrap_directory_lock(
    root: Path,
    *,
    exclusive: bool,
    label: str,
) -> BootstrapDirectoryLock:
    before = require_private_directory(root, label)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(root, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            fail_concurrent(f"{label} changed while it was being opened")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"{label} is locked: {root}")
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail(f"{label} is locked: {root}")
            raise
        locked = os.fstat(descriptor)
        if identity_of(locked) != identity_of(opened):
            fail_concurrent(f"{label} changed while it was being locked")
        final = require_private_directory(root, label)
        if identity_of(final) != identity_of(locked):
            fail_concurrent(f"{label} changed after lock acquisition")
        return BootstrapDirectoryLock(
            descriptor=descriptor,
            path=root,
            identity=identity_of(locked),
        )
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise


def release_bootstrap_directory_lock(lock: BootstrapDirectoryLock) -> None:
    release_error: BaseException | None = None
    try:
        final = require_private_directory(lock.path, "bootstrap coordination directory")
        if identity_of(final) != lock.identity:
            fail_concurrent("bootstrap coordination directory changed before release")
    except BaseException as exc:
        release_error = exc
    try:
        fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock.descriptor)
    if release_error is not None:
        raise release_error


def is_publication_alias(path: Path, final: Path) -> bool:
    prefix = f".{final.name}.tmp."
    if path.parent != final.parent or not path.name.startswith(prefix):
        return False
    suffix = path.name[len(prefix) :]
    parts = suffix.split(".")
    return len(parts) == 2 and all(part.isdigit() for part in parts)


def recover_hardlink_publication_alias(
    path: Path,
    identity: tuple[int, int],
    label: str,
) -> None:
    alias = require_one_hardlink_publication_alias(path, identity, label)
    retrying_unlink(alias, f"{label} publication alias")
    fsync_directory(path.parent, f"{label} publication alias cleanup parent")


def require_one_hardlink_publication_alias(
    path: Path,
    identity: tuple[int, int],
    label: str,
) -> Path:
    parent = path.parent
    aliases: list[Path] = []
    unknown_aliases: list[Path] = []
    for candidate in parent.iterdir():
        if candidate == path:
            continue
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or identity_of(info) != identity:
            continue
        if is_publication_alias(candidate, path):
            aliases.append(candidate)
        else:
            unknown_aliases.append(candidate)
    if unknown_aliases:
        fail(f"{label} has an unknown hard-link alias")
    if len(aliases) != 1:
        fail(f"{label} publication alias recovery expected exactly one alias")
    return aliases[0]


def publish_lock_marker_atomic(
    path: Path,
    marker: dict[str, Any],
    label: str,
) -> tuple[int, tuple[int, int], os.stat_result, DirectorySnapshot, os.stat_result] | None:
    parent = path.parent
    parent_info = require_private_directory(parent, f"{label} parent")
    parent_snapshot = capture_directory_snapshot(parent, f"{label} parent")
    if lstat_exists(path):
        return None
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag(label)
    descriptor: int | None = None
    final_visible = False
    temp_unlinked = False
    content = canonical_json(marker)
    try:
        descriptor = os.open(temp, flags, OWNER_FILE_MODE)
        os.fchmod(descriptor, OWNER_FILE_MODE)
        remaining = content
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                fail(f"{label} marker could not be written")
            remaining = remaining[written:]
        os.fsync(descriptor)
        temp_info = require_regular_file(
            temp,
            f"{label} temp",
            owner_only=True,
            max_bytes=METADATA_MAX_BYTES,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"{label} temp is locked: {temp}")
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail(f"{label} temp is locked: {temp}")
            raise
        locked_temp = os.fstat(descriptor)
        if identity_of(locked_temp) != identity_of(temp_info):
            fail_concurrent(f"{label} temp changed while it was being locked")
        fsync_directory(parent, f"{label} temp parent")
        try:
            os.link(temp, path)
        except FileExistsError:
            retrying_unlink(temp, f"{label} temp")
            temp_unlinked = True
            os.close(descriptor)
            descriptor = None
            return None
        final_visible = True
        temp.unlink()
        temp_unlinked = True
        final = require_regular_file(path, label, owner_only=True, max_bytes=METADATA_MAX_BYTES)
        if identity_of(final) != identity_of(locked_temp):
            fail_concurrent(f"{label} changed during no-replace publication")
        if final.st_nlink != 1:
            fail(f"{label} must not have hard-link aliases")
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, METADATA_MAX_BYTES + 1)
        if raw != content:
            fail(f"{label} marker changed during no-replace publication")
        fsync_directory(parent, f"{label} publish parent")
        return descriptor, identity_of(locked_temp), parent_info, parent_snapshot, final
    except BaseException as exc:
        cleanup_error: BaseException | None = None
        if not temp_unlinked and lstat_exists(temp):
            try:
                retrying_unlink(temp, f"{label} temp")
            except BaseException as cleanup_exc:
                cleanup_error = cleanup_exc
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        try:
            fsync_directory(parent, f"{label} rollback parent")
        except BaseException as cleanup_exc:
            if cleanup_error is None:
                cleanup_error = cleanup_exc
        if not final_visible:
            try:
                restore_directory_snapshot(parent, parent_snapshot, f"{label} parent")
            except BaseException as cleanup_exc:
                if cleanup_error is None:
                    cleanup_error = cleanup_exc
        if cleanup_error is not None:
            raise cleanup_error from exc
        raise


def open_existing_product_coordination_lock(
    path: Path,
    *,
    exclusive: bool,
) -> ProductCoordinationLock:
    parent_info = require_private_directory(path.parent, "product coordination lock parent")
    parent_snapshot = capture_directory_snapshot(path.parent, "product coordination lock parent")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag("product coordination lock")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            fail("product coordination lock must not be a symlink")
        fail(f"product coordination lock could not be opened safely: {exc}")
    try:
        opened = os.fstat(descriptor)
        require_current_owner(opened, "product coordination lock")
        if not stat.S_ISREG(opened.st_mode):
            fail("product coordination lock must be a regular file")
        if opened.st_nlink not in {1, 2}:
            fail("product coordination lock must not have unbounded hard-link aliases")
        if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
            fail("product coordination lock must be owned by the current user with mode 0600")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"product coordination lock is locked: {path}")
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail(f"product coordination lock is locked: {path}")
            raise
        locked = os.fstat(descriptor)
        if identity_of(locked) != identity_of(opened):
            fail_concurrent("product coordination lock changed while it was being locked")
        if locked.st_nlink == 2:
            if not exclusive:
                require_one_hardlink_publication_alias(
                    path,
                    identity_of(locked),
                    "product coordination lock",
                )
                fail("product coordination lock publication is incomplete")
            recover_hardlink_publication_alias(
                path,
                identity_of(locked),
                "product coordination lock",
            )
            locked = os.fstat(descriptor)
        final = require_regular_file(
            path, "product coordination lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != identity_of(locked):
            fail_concurrent("product coordination lock changed while it was being opened")
        if final.st_nlink != 1 or locked.st_nlink != 1:
            fail("product coordination lock must not have hard-link aliases")
        read_product_coordination_lock_marker(descriptor)
        rebound = os.fstat(descriptor)
        if identity_of(rebound) != identity_of(locked):
            fail_concurrent("product coordination lock changed while its marker was read")
        final = require_regular_file(
            path, "product coordination lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != identity_of(locked):
            fail_concurrent("product coordination lock changed after marker validation")
        return ProductCoordinationLock(
            descriptor=descriptor,
            path=path,
            identity=identity_of(locked),
            parent=path.parent,
            parent_identity=identity_of(parent_info),
            parent_snapshot=parent_snapshot,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise


def open_product_coordination_lock(
    *,
    create: bool = True,
    exclusive: bool = True,
) -> ProductCoordinationLock | None:
    if not create:
        root = bootstrap_root_path()
        info = stat_existing(root, "external lifecycle lock root")
        if info is None:
            return None
        require_private_directory(root, "external lifecycle lock root")
        path = product_coordination_lock_path_no_create()
        if not lstat_exists(path):
            return None
        return open_existing_product_coordination_lock(path, exclusive=exclusive)

    root = ensure_bootstrap_root()
    bootstrap_lock = open_bootstrap_directory_lock(
        root,
        exclusive=True,
        label="product bootstrap handoff",
    )
    try:
        path = product_coordination_lock_path_no_create()
        if not lstat_exists(path):
            published = publish_lock_marker_atomic(
                path,
                product_coordination_lock_marker(),
                "product coordination lock",
            )
            if published is not None:
                (
                    descriptor,
                    lock_identity,
                    parent_info,
                    parent_snapshot,
                    _final,
                ) = published
                lock = ProductCoordinationLock(
                    descriptor=descriptor,
                    path=path,
                    identity=lock_identity,
                    parent=path.parent,
                    parent_identity=identity_of(parent_info),
                    parent_snapshot=parent_snapshot,
                )
            else:
                lock = open_existing_product_coordination_lock(path, exclusive=exclusive)
        else:
            lock = open_existing_product_coordination_lock(path, exclusive=exclusive)
    except BaseException:
        try:
            release_bootstrap_directory_lock(bootstrap_lock)
        except BaseException:
            pass
        raise
    try:
        release_bootstrap_directory_lock(bootstrap_lock)
    except BaseException:
        with contextlib.suppress(BaseException):
            release_product_coordination_lock(lock)
        raise
    return lock


def product_coordination_anchor_exists_no_create() -> bool:
    root = bootstrap_root_path()
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        return False
    require_private_directory(root, "external lifecycle lock root")
    return lstat_exists(product_coordination_lock_path_no_create())


def release_product_coordination_lock(lock: ProductCoordinationLock) -> None:
    release_error: BaseException | None = None
    try:
        parent_info = require_private_directory(lock.parent, "product coordination lock parent")
        if identity_of(parent_info) != lock.parent_identity:
            fail_concurrent("product coordination lock parent changed before release")
        final = require_regular_file(
            lock.path, "product coordination lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != lock.identity:
            fail_concurrent("product coordination lock changed before release")
    except BaseException as exc:
        release_error = exc
    try:
        fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock.descriptor)
    if release_error is not None:
        raise release_error


def external_lifecycle_lock_marker(canonical_target: Path) -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_SCHEMA,
        "product_name": PRODUCT_NAME,
        "lock_kind": EXTERNAL_LOCK_KIND,
        "canonical_target": str(canonical_target),
    }


def validate_external_lifecycle_lock_marker(raw: bytes, canonical_target: Path) -> None:
    marker = parse_json_object(raw, "external lifecycle lock")
    require_exact_keys(
        marker,
        {"schema_version", "product_name", "lock_kind", "canonical_target"},
        "external lifecycle lock",
    )
    if marker["schema_version"] != EXTERNAL_LOCK_SCHEMA:
        fail("external lifecycle lock has unsupported schema")
    if marker["product_name"] != PRODUCT_NAME:
        fail("external lifecycle lock product mismatch")
    if marker["lock_kind"] != EXTERNAL_LOCK_KIND:
        fail("external lifecycle lock kind mismatch")
    if marker["canonical_target"] != str(canonical_target):
        fail("external lifecycle lock target binding mismatch")


def read_external_lifecycle_lock_marker(descriptor: int, canonical_target: Path) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, METADATA_MAX_BYTES + 1)
    if len(raw) > METADATA_MAX_BYTES:
        fail("external lifecycle lock exceeds the metadata size limit")
    if not raw:
        fail("external lifecycle lock marker is incomplete")
    validate_external_lifecycle_lock_marker(raw, canonical_target)


def open_existing_external_lifecycle_lock(
    path: Path,
    canonical_target: Path,
    *,
    exclusive: bool,
) -> ExternalLifecycleLock:
    parent_info = require_private_directory(path.parent, "external lifecycle lock parent")
    parent_snapshot = capture_directory_snapshot(path.parent, "external lifecycle lock parent")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag("external lifecycle lock")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            fail("external lifecycle lock must not be a symlink")
        fail(f"external lifecycle lock could not be opened safely: {exc}")
    try:
        opened = os.fstat(descriptor)
        require_current_owner(opened, "external lifecycle lock")
        if not stat.S_ISREG(opened.st_mode):
            fail("external lifecycle lock must be a regular file")
        if opened.st_nlink not in {1, 2}:
            fail("external lifecycle lock must not have unbounded hard-link aliases")
        if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
            fail("external lifecycle lock must be owned by the current user with mode 0600")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"external lifecycle lock is locked: {path}")
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail(f"external lifecycle lock is locked: {path}")
            raise
        locked = os.fstat(descriptor)
        if identity_of(locked) != identity_of(opened):
            fail_concurrent("external lifecycle lock changed while it was being locked")
        if locked.st_nlink == 2:
            if not exclusive:
                require_one_hardlink_publication_alias(
                    path,
                    identity_of(locked),
                    "external lifecycle lock",
                )
                fail("external lifecycle lock publication is incomplete")
            recover_hardlink_publication_alias(
                path,
                identity_of(locked),
                "external lifecycle lock",
            )
            locked = os.fstat(descriptor)
        require_current_owner(locked, "external lifecycle lock")
        if not stat.S_ISREG(locked.st_mode):
            fail("external lifecycle lock must be a regular file")
        if locked.st_nlink != 1:
            fail("external lifecycle lock must not have hard-link aliases")
        if stat.S_IMODE(locked.st_mode) != OWNER_FILE_MODE:
            fail("external lifecycle lock must be owned by the current user with mode 0600")
        final = require_regular_file(
            path, "external lifecycle lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != identity_of(locked):
            fail_concurrent("external lifecycle lock changed while it was being opened")
        read_external_lifecycle_lock_marker(descriptor, canonical_target)
        rebound = os.fstat(descriptor)
        if identity_of(rebound) != identity_of(locked):
            fail_concurrent("external lifecycle lock changed while its marker was read")
        final = require_regular_file(
            path, "external lifecycle lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != identity_of(locked):
            fail_concurrent("external lifecycle lock changed after marker validation")
        return ExternalLifecycleLock(
            descriptor=descriptor,
            path=path,
            identity=identity_of(locked),
            parent=path.parent,
            parent_identity=identity_of(parent_info),
            parent_snapshot=parent_snapshot,
            canonical_target=canonical_target,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise


def open_external_lifecycle_lock(
    canonical_target: Path,
    *,
    create: bool = True,
    exclusive: bool = True,
    product_lock: ProductCoordinationLock | None = None,
) -> ExternalLifecycleLock | None:
    owned_product_lock: ProductCoordinationLock | None = None
    if create and product_lock is None:
        owned_product_lock = open_product_coordination_lock(create=True, exclusive=True)
        if owned_product_lock is None:
            fail("product coordination lock could not be acquired")
        product_lock = owned_product_lock
    try:
        if create:
            path = bootstrap_lock_path(canonical_target)
            if not lstat_exists(path):
                published = publish_lock_marker_atomic(
                    path,
                    external_lifecycle_lock_marker(canonical_target),
                    "external lifecycle lock",
                )
                if published is not None:
                    (
                        descriptor,
                        lock_identity,
                        parent_info,
                        parent_snapshot,
                        _final,
                    ) = published
                    lock = ExternalLifecycleLock(
                        descriptor=descriptor,
                        path=path,
                        identity=lock_identity,
                        parent=path.parent,
                        parent_identity=identity_of(parent_info),
                        parent_snapshot=parent_snapshot,
                        canonical_target=canonical_target,
                    )
                else:
                    lock = open_existing_external_lifecycle_lock(
                        path,
                        canonical_target,
                        exclusive=exclusive,
                    )
            else:
                lock = open_existing_external_lifecycle_lock(
                    path,
                    canonical_target,
                    exclusive=exclusive,
                )
        else:
            root = bootstrap_root_path()
            info = stat_existing(root, "external lifecycle lock root")
            if info is None:
                return None
            require_private_directory(root, "external lifecycle lock root")
            path = bootstrap_lock_path_no_create(canonical_target)
            if not lstat_exists(path):
                return None
            lock = open_existing_external_lifecycle_lock(
                path,
                canonical_target,
                exclusive=exclusive,
            )
    except BaseException:
        if owned_product_lock is not None:
            with contextlib.suppress(BaseException):
                release_product_coordination_lock(owned_product_lock)
        raise
    if owned_product_lock is not None:
        try:
            release_product_coordination_lock(owned_product_lock)
        except BaseException:
            with contextlib.suppress(BaseException):
                release_external_lifecycle_lock(lock)
            raise
    return lock


def release_external_lifecycle_lock(lock: ExternalLifecycleLock) -> None:
    release_error: BaseException | None = None
    try:
        parent_info = require_private_directory(lock.parent, "external lifecycle lock parent")
        if identity_of(parent_info) != lock.parent_identity:
            fail_concurrent("external lifecycle lock parent changed before release")
        final = require_regular_file(
            lock.path, "external lifecycle lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != lock.identity:
            fail_concurrent("external lifecycle lock changed before release")
    except BaseException as exc:
        release_error = exc
    try:
        fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock.descriptor)
    if release_error is not None:
        raise release_error


def require_owner_directory_mode(path: Path, label: str, allowed_modes: set[int]) -> os.stat_result:
    info = require_directory(path, label)
    mode = stat.S_IMODE(info.st_mode)
    if mode not in allowed_modes:
        allowed = ", ".join(f"{item:04o}" for item in sorted(allowed_modes))
        fail(f"{label} must be owned by the current user with mode {allowed}")
    return info


def require_no_follow_flag(label: str) -> int:
    flag = getattr(os, "O_NOFOLLOW", None)
    if flag is None:
        fail(f"{label} requires O_NOFOLLOW support")
    return int(flag)


def ensure_lock_parent(
    target: Path,
    transaction: DirectoryTransaction | None = None,
) -> os.stat_result:
    parent = lock_parent_path(target)
    info = stat_existing(parent, "target lifecycle lock parent")
    if info is None:
        target_info = require_owner_directory_mode(
            target,
            "target",
            {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE},
        )
        if stat.S_IMODE(target_info.st_mode) == LOCK_HELD_DIRECTORY_MODE:
            if transaction is not None:
                transaction.remember_directory(target, "target before lock parent repair")
            target.chmod(OWNER_DIRECTORY_MODE)
        if transaction is not None:
            transaction.remember_directory(target, "target before lock parent create")
        parent.mkdir(mode=OWNER_DIRECTORY_MODE)
        parent.chmod(OWNER_DIRECTORY_MODE)
        if transaction is not None:
            transaction.created.append(parent)
        info = require_owner_directory_mode(
            parent, "target lifecycle lock parent", {OWNER_DIRECTORY_MODE}
        )
        return info
    require_current_owner(info, "target lifecycle lock parent")
    if stat.S_ISLNK(info.st_mode):
        fail("target lifecycle lock parent must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        fail("target lifecycle lock parent must be a real directory")
    mode = stat.S_IMODE(info.st_mode)
    if mode not in {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE}:
        fail("target lifecycle lock parent must be private")
    if mode == LOCK_HELD_DIRECTORY_MODE and not lstat_exists(lock_path(target)):
        if transaction is not None:
            transaction.remember_directory(parent, "target lifecycle lock parent repair")
        parent.chmod(OWNER_DIRECTORY_MODE)
        info = require_owner_directory_mode(
            parent, "target lifecycle lock parent", {OWNER_DIRECTORY_MODE}
        )
    return info


def open_lock_file(target: Path, parent_info: os.stat_result) -> FileLock:
    path = lock_path(target)
    parent = lock_parent_path(target)
    parent_snapshot = capture_directory_snapshot(
        parent, "target lifecycle lock parent before lock file create"
    )
    flags = os.O_RDWR | os.O_CLOEXEC | require_no_follow_flag("target lifecycle lock")
    created = False
    restore_parent_on_failure = False
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        created = True
        restore_parent_on_failure = True
    except FileExistsError:
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                fail("target lifecycle lock must not be a symlink")
            fail(f"target lifecycle lock could not be opened safely: {exc}")
    except PermissionError:
        current = require_owner_directory_mode(
            parent,
            "target lifecycle lock parent",
            {LOCK_HELD_DIRECTORY_MODE},
        )
        if identity_of(current) != identity_of(parent_info):
            fail_concurrent("target lifecycle lock parent changed before open")
        parent.chmod(OWNER_DIRECTORY_MODE)
        parent_info = require_owner_directory_mode(
            parent, "target lifecycle lock parent", {OWNER_DIRECTORY_MODE}
        )
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
            created = True
            restore_parent_on_failure = True
        except BaseException:
            with contextlib.suppress(CopilotCliSetupError, OSError):
                restore_directory_snapshot(
                    parent,
                    parent_snapshot,
                    "target lifecycle lock parent after failed open",
                )
            raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            fail("target lifecycle lock must not be a symlink")
        fail(f"target lifecycle lock could not be opened safely: {exc}")
    try:
        if created:
            path.chmod(OWNER_FILE_MODE)
        opened = os.fstat(descriptor)
        require_current_owner(opened, "target lifecycle lock")
        if not stat.S_ISREG(opened.st_mode):
            fail("target lifecycle lock must be a regular file")
        if opened.st_nlink != 1:
            fail("target lifecycle lock must not have hard-link aliases")
        if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
            fail("target lifecycle lock must be owned by the current user with mode 0600")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"target lifecycle lock is locked: {path}")
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail(f"target lifecycle lock is locked: {path}")
            raise
        final = require_regular_file(
            path, "target lifecycle lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != identity_of(opened):
            fail_concurrent("target lifecycle lock changed while it was being opened")
        current_parent = require_owner_directory_mode(
            parent,
            "target lifecycle lock parent",
            {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE},
        )
        parent_identity = identity_of(current_parent)
        if parent_identity != identity_of(parent_info):
            fail_concurrent("target lifecycle lock parent changed while it was being opened")
        parent.chmod(LOCK_HELD_DIRECTORY_MODE)
        protected_parent = require_owner_directory_mode(
            parent,
            "target lifecycle lock parent",
            {LOCK_HELD_DIRECTORY_MODE},
        )
        if identity_of(protected_parent) != parent_identity:
            fail_concurrent("target lifecycle lock parent changed while it was being protected")
        return FileLock(
            descriptor=descriptor,
            path=path,
            identity=identity_of(opened),
            parent=parent,
            parent_identity=parent_identity,
            created=created,
            parent_snapshot=parent_snapshot if restore_parent_on_failure else None,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        cleanup_error: BaseException | None = None
        if created:
            try:
                path.unlink()
                fsync_directory(parent, "target lifecycle lock cleanup parent")
            except FileNotFoundError:
                pass
            except BaseException as exc:
                cleanup_error = exc
        if restore_parent_on_failure:
            try:
                restore_directory_snapshot(
                    parent,
                    parent_snapshot,
                    "target lifecycle lock parent after failed open",
                )
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error
        raise


def release_file_lock(lock: FileLock, *, remove_persistent: bool = False) -> None:
    release_error: BaseException | None = None
    try:
        parent = require_owner_directory_mode(
            lock.parent,
            "target lifecycle lock parent",
            {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE},
        )
        if identity_of(parent) != lock.parent_identity:
            fail_concurrent("target lifecycle lock parent changed before release")
        final = require_regular_file(
            lock.path, "target lifecycle lock", owner_only=True, max_bytes=METADATA_MAX_BYTES
        )
        if identity_of(final) != lock.identity:
            fail_concurrent("target lifecycle lock changed before release")
        if stat.S_IMODE(parent.st_mode) != OWNER_DIRECTORY_MODE:
            lock.parent.chmod(OWNER_DIRECTORY_MODE)
    except BaseException as exc:
        release_error = exc
    try:
        fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock.descriptor)
    if release_error is not None:
        raise release_error
    if remove_persistent:
        remove_error: BaseException | None = None
        try:
            lock.path.unlink()
            fsync_directory(lock.parent, "target lifecycle lock remove parent")
        except FileNotFoundError:
            pass
        except BaseException as exc:
            remove_error = exc
        if lock.parent_snapshot is not None:
            try:
                restore_directory_snapshot(
                    lock.parent,
                    lock.parent_snapshot,
                    "target lifecycle lock parent after failed lifecycle",
                )
            except BaseException as exc:
                if remove_error is None:
                    remove_error = exc
        if remove_error is not None:
            raise remove_error


def remove_persistent_lock_artifacts(target: Path) -> None:
    path = lock_path(target)
    parent = lock_parent_path(target)
    snapshots: dict[Path, DirectorySnapshot] = {}
    removed_parent = False
    try:
        info = stat_existing(path, "target lifecycle lock")
        if info is not None:
            require_current_owner(info, "target lifecycle lock")
            if stat.S_ISREG(info.st_mode):
                parent_snapshot = capture_directory_snapshot(
                    parent, "target lifecycle lock parent before remove"
                )
                if parent_snapshot.exists:
                    snapshots[parent] = parent_snapshot
                path.unlink()
                fsync_directory(parent, "target lifecycle lock remove parent")
        info = stat_existing(parent, "target lifecycle lock parent")
        if info is not None:
            require_current_owner(info, "target lifecycle lock parent")
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) == LOCK_HELD_DIRECTORY_MODE:
                    snapshots.setdefault(
                        parent,
                        capture_directory_snapshot(
                            parent, "target lifecycle lock parent before mode restore"
                        ),
                    )
                    parent.chmod(OWNER_DIRECTORY_MODE)
                target_snapshot = capture_directory_snapshot(
                    target, "target before lifecycle lock parent remove"
                )
                if target_snapshot.exists:
                    snapshots[target] = target_snapshot
                parent.rmdir()
                removed_parent = True
                fsync_directory(target, "target lifecycle lock parent remove parent")
    except BaseException:
        if removed_parent:
            snapshots.pop(parent, None)
        restore_absolute_directory_snapshots(snapshots, "target lifecycle lock cleanup")
        raise
    if removed_parent:
        snapshots.pop(parent, None)
    restore_absolute_directory_snapshots(snapshots, "target lifecycle lock cleanup")


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
        transaction.remember_directory(directory.parent, f"{label} parent before create")
        directory.mkdir(mode=OWNER_DIRECTORY_MODE)
        directory.chmod(OWNER_DIRECTORY_MODE)
        transaction.created.append(directory)


def coordinated_target_read(target: Path, reader: Callable[[Path], Any]) -> Any:
    lexical_target = require_explicit_absolute_target(str(target))
    for _attempt in range(2):
        product_lock = open_product_coordination_lock(create=False, exclusive=False)
        external_lock: ExternalLifecycleLock | None = None
        if product_lock is None:
            canonical_target = canonical_target_for_lifecycle_lock(lexical_target)
            result = reader(canonical_target)
            if not product_coordination_anchor_exists_no_create():
                return result
            continue
        try:
            canonical_target = canonical_target_for_lifecycle_lock(lexical_target)
            external_lock = open_external_lifecycle_lock(
                canonical_target,
                create=False,
                exclusive=False,
            )
            if external_lock is not None:
                release_product_coordination_lock(product_lock)
                product_lock = None
            result = reader(canonical_target)
            return result
        finally:
            release_error: BaseException | None = None
            if external_lock is not None:
                try:
                    release_external_lifecycle_lock(external_lock)
                except BaseException as exc:
                    release_error = exc
            if product_lock is not None:
                try:
                    release_product_coordination_lock(product_lock)
                except BaseException as exc:
                    if release_error is None:
                        release_error = exc
            if release_error is not None:
                raise release_error
    fail_concurrent("product coordination anchor changed during cold target read")


@contextlib.contextmanager
def target_coordination(
    target: Path,
    *,
    create_parent: bool = False,
    directory_transaction: DirectoryTransaction | None = None,
) -> Iterator[Path]:
    lexical_target = require_explicit_absolute_target(str(target))
    product_lock: ProductCoordinationLock | None = None
    external_lock: ExternalLifecycleLock | None = None
    yielded = False
    try:
        product_lock = open_product_coordination_lock(create=True, exclusive=True)
        if product_lock is None:
            fail("product coordination lock could not be acquired")
        if create_parent:
            if directory_transaction is None:
                fail("target parent creation requires a directory transaction")
            if not lstat_exists(lexical_target.parent):
                ensure_directory_chain(
                    lexical_target.parent, directory_transaction, "target parent"
                )
        canonical_target = canonical_target_for_lifecycle_lock(lexical_target)
        external_lock = open_external_lifecycle_lock(
            canonical_target,
            create=True,
            exclusive=True,
            product_lock=product_lock,
        )
        if external_lock is None:
            fail("external lifecycle lock could not be acquired")
        try:
            release_product_coordination_lock(product_lock)
        finally:
            product_lock = None
        yielded = True
        yield canonical_target
    except BaseException:
        if not yielded and create_parent and directory_transaction is not None:
            directory_transaction.cleanup()
        raise
    finally:
        release_error: BaseException | None = None
        if product_lock is not None:
            try:
                release_product_coordination_lock(product_lock)
            except BaseException as exc:
                release_error = exc
            product_lock = None
        if external_lock is not None:
            try:
                release_external_lifecycle_lock(external_lock)
            except BaseException as exc:
                if release_error is None:
                    release_error = exc
            external_lock = None
        if release_error is not None:
            raise release_error


@contextlib.contextmanager
def target_file_lock(
    target: Path,
    *,
    create_target: bool = False,
    directory_transaction: DirectoryTransaction | None = None,
) -> Iterator[DirectoryTransaction]:
    transaction = (
        directory_transaction if directory_transaction is not None else DirectoryTransaction([])
    )
    lifecycle_lock: FileLock | None = None
    failed = True
    try:
        target_info = stat_existing(target, "target")
        if target_info is None:
            if not create_target:
                failed = False
                yield transaction
                return
            target_info = stat_existing(target, "target")
            if target_info is None:
                ensure_target_directory(target, transaction)
            else:
                require_current_owner(target_info, "target")
                if not stat.S_ISDIR(target_info.st_mode):
                    fail("target must be a real directory")
                mode = stat.S_IMODE(target_info.st_mode)
                if mode not in {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE}:
                    fail("target must be owned by the current user with mode 0700")
            lock_parent = ensure_lock_parent(target, transaction)
            lifecycle_lock = open_lock_file(target, lock_parent)
        else:
            require_current_owner(target_info, "target")
            if not stat.S_ISDIR(target_info.st_mode):
                fail("target must be a real directory")
            if stat.S_IMODE(target_info.st_mode) not in {
                OWNER_DIRECTORY_MODE,
                LOCK_HELD_DIRECTORY_MODE,
            }:
                fail("target must be owned by the current user with mode 0700")
            lock_parent = ensure_lock_parent(target, transaction)
            lifecycle_lock = open_lock_file(target, lock_parent)
            if stat.S_IMODE(target_info.st_mode) == LOCK_HELD_DIRECTORY_MODE:
                transaction.remember_directory(target, "target before stale lifecycle repair")
                target.chmod(OWNER_DIRECTORY_MODE)
        failed = False
        yield transaction
    except BaseException:
        failed = True
        raise
    finally:
        release_error: BaseException | None = None
        if lifecycle_lock is not None:
            try:
                release_file_lock(
                    lifecycle_lock,
                    remove_persistent=failed and lifecycle_lock.created,
                )
            except BaseException as exc:
                if not failed:
                    release_error = exc
            lifecycle_lock = None
        if failed:
            transaction.cleanup()
        if release_error is not None:
            raise release_error


@contextlib.contextmanager
def target_lock(target: Path, *, create_parent: bool = False) -> Iterator[TargetLockContext]:
    transaction = DirectoryTransaction([])
    with target_coordination(
        target,
        create_parent=create_parent,
        directory_transaction=transaction,
    ) as canonical_target:
        with target_file_lock(
            canonical_target,
            create_target=create_parent,
            directory_transaction=transaction,
        ) as directory_transaction:
            yield TargetLockContext(target=canonical_target, transaction=directory_transaction)


def require_explicit_absolute_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("an explicit --target absolute path is required")
    target = Path(raw_target)
    if not target.is_absolute():
        fail("--target must be an absolute path")
    if target.name in {"", ".", ".."}:
        fail("--target must name a directory")
    return target


def ensure_target_directory(target: Path, transaction: DirectoryTransaction | None = None) -> Path:
    if lstat_exists(target):
        info = require_directory(target, "target")
        if not is_owner_private_directory(info):
            fail("target must be owned by the current user with mode 0700")
        return target.resolve()
    parent = target.parent
    require_directory(parent, "target parent")
    if transaction is not None:
        transaction.remember_directory(parent, "target parent before create")
    target.mkdir(mode=OWNER_DIRECTORY_MODE)
    target.chmod(OWNER_DIRECTORY_MODE)
    if transaction is not None:
        transaction.created.append(target)
    return target.resolve()


def any_managed_path_exists(target: Path) -> bool:
    return any(lstat_exists(target / relative) for relative in ALL_KNOWN_MANAGED_PATHS)


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
        require_exact_keys(value, STAMP_KEYS_V3, "setup stamp")
        validate_file_records(value["managed_files"], "setup stamp managed_files")
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


def desired_for_stamp(target: Path, stamp: dict[str, Any]) -> dict[Path, bytes]:
    existing_settings = load_json_object(
        target / "settings.json", "existing settings.json", owner_only=True
    )
    _metadata, desired = render_setup(
        stamp["setup_id"],
        stamp["profile_id"],
        existing_settings=existing_settings,
    )
    expected_stamp = bind_stamp(
        parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"),
        target,
    )
    desired[Path(STAMP_NAME)] = canonical_json(expected_stamp)
    return desired


def validate_managed_files(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    expected = stamp["managed_files"]
    if stamp.get("schema_version") == STAMP_SCHEMA:
        records = validate_file_records(expected, "setup stamp managed_files")
        desired = desired_for_stamp(target, stamp)
        expected_paths = set(records)
        desired_paths = {str(relative) for relative in desired if relative != Path(STAMP_NAME)}
        if expected_paths != desired_paths:
            fail("setup stamp managed_files do not match the canonical desired state")
        current_stamp, _ = read_regular_file(target / STAMP_NAME, "setup stamp", owner_only=True)
        if current_stamp != desired[Path(STAMP_NAME)]:
            fail("setup stamp does not match the canonical desired state")
        ordered = [relative for relative in MANAGED_PATHS if str(relative) in records]
        ordered.extend(
            Path(raw_relative)
            for raw_relative in sorted(set(records) - {str(item) for item in ordered})
        )
        for relative in ordered:
            content, _ = read_regular_file(
                target / relative, f"managed file {relative}", owner_only=True
            )
            assert_file_record_matches(
                relative,
                content,
                records[str(relative)],
                "setup stamp managed_files",
            )
            if desired[relative] != content:
                drift.append(str(relative))
    else:
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
    return sorted(str(relative) for relative in ordered)


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
    replace_managed_state(target, snapshot, snapshot, marker=".restore.tmp.")


def managed_snapshot_matches_current(target: Path, snapshot: dict[Path, bytes | None]) -> bool:
    for relative, expected in snapshot.items():
        path = target / relative
        if expected is None:
            if lstat_exists(path):
                return False
            continue
        if not lstat_exists(path):
            return False
        content, _info = read_regular_file(path, f"managed file {relative}", owner_only=True)
        if content != expected:
            return False
    return True


def restore_snapshot_if_drifted(target: Path, snapshot: dict[Path, bytes | None]) -> None:
    if managed_snapshot_matches_current(target, snapshot):
        return
    restore_snapshot(target, snapshot)


def restore_lifecycle_snapshots(
    target: Path,
    managed_snapshot: dict[Path, bytes | None],
    backup_transaction: BackupPoolTransaction | None,
) -> None:
    rollback_error: BaseException | None = None
    try:
        restore_snapshot(target, managed_snapshot)
    except BaseException as exc:
        rollback_error = exc
    if backup_transaction is not None:
        try:
            rollback_backup_pool_transaction(backup_transaction)
        except BaseException as exc:
            if rollback_error is None:
                rollback_error = exc
    if rollback_error is not None:
        raise rollback_error


def write_owner_file_replace(path: Path, content: bytes, target: Path, label: str) -> None:
    ensure_real_parent(path, target)
    if lstat_exists(path):
        require_regular_file(path, label, owner_only=True)
    relative = path.relative_to(target)
    replace_managed_state(target, {relative: content}, {relative: content})


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


def apply_managed_state(
    target: Path,
    desired: dict[Path, bytes | None],
    expected: dict[Path, bytes | None],
    *,
    marker: str = ".nddev.tmp.",
) -> FileSetTransaction:
    if expected != desired:
        fail("managed replacement expected state does not match desired state")
    transaction = begin_file_set_transaction(
        target,
        tuple(desired),
        "managed",
        allowed_modes={relative: {OWNER_FILE_MODE} for relative in desired},
    )
    try:
        for relative, content in desired.items():
            path = target / relative
            if relative.is_absolute() or ".." in relative.parts:
                fail(f"unsafe managed path: {relative}")
            if content is None:
                continue
            if lstat_exists(path):
                require_regular_file(path, f"managed file {relative}", owner_only=True)
            durable_replace_file(
                path,
                content,
                OWNER_FILE_MODE,
                target,
                f"managed file {relative}",
                marker=marker,
            )
        assert_desired_postconditions(target, expected)
        return transaction
    except BaseException:
        rollback_file_set_transaction(transaction)
        raise


def replace_managed_state(
    target: Path,
    desired: dict[Path, bytes | None],
    expected: dict[Path, bytes | None],
    *,
    marker: str = ".nddev.tmp.",
) -> None:
    transaction = apply_managed_state(target, desired, expected, marker=marker)
    try:
        commit_file_set_transaction(transaction)
    except BaseException:
        rollback_file_set_transaction(transaction)
        raise


def assert_desired_postconditions(target: Path, desired: dict[Path, bytes | None]) -> None:
    for relative, content in desired.items():
        path = target / relative
        if relative.is_absolute() or ".." in relative.parts:
            fail(f"unsafe managed postcondition path: {relative}")
        if content is None:
            if lstat_exists(path):
                fail(f"managed postcondition expected absent path: {relative}")
            continue
        actual, info = read_regular_file(
            path, f"managed postcondition file {relative}", owner_only=True
        )
        if actual != content:
            fail(f"managed postcondition content mismatch: {relative}")
        if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
            fail(f"managed postcondition mode mismatch: {relative}")


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


def begin_backup_pool_transaction(target: Path) -> BackupPoolTransaction:
    pool = backup_pool(target)
    parent_directories: dict[Path, DirectorySnapshot] = {}
    stash_root = transaction_stash_root(target, "backup-pool", parent_directories)
    stashed_pool: Path | None = None
    try:
        if lstat_exists(pool):
            require_private_directory(pool, "backup pool")
            validate_backup_pool_marker(target, pool)
            stashed_pool = stash_root / "pool"
            os.replace(pool, stashed_pool)
            fsync_directory(pool.parent, "backup pool preserve parent")
            fsync_directory(stash_root, "backup pool preserve stash")
        return BackupPoolTransaction(
            target=target,
            pool=pool,
            stash_root=stash_root,
            stashed_pool=stashed_pool,
            parent_directories=parent_directories,
        )
    except BaseException:
        transaction = BackupPoolTransaction(
            target=target,
            pool=pool,
            stash_root=stash_root,
            stashed_pool=stashed_pool,
            parent_directories=parent_directories,
        )
        rollback_backup_pool_transaction(transaction)
        raise


def rollback_backup_pool_transaction(transaction: BackupPoolTransaction) -> None:
    rollback_error: BaseException | None = None
    try:
        if lstat_exists(transaction.pool):
            remove_private_tree_verified(transaction.pool, "backup pool rollback current")
        if transaction.stashed_pool is not None:
            retrying_replace(
                transaction.stashed_pool,
                transaction.pool,
                "backup pool rollback original",
            )
            fsync_directory(transaction.pool.parent, "backup pool rollback original parent")
            validate_backup_pool_marker(transaction.target, transaction.pool)
    except BaseException as exc:
        rollback_error = exc
    try:
        remove_private_tree_verified(transaction.stash_root, "backup pool transaction stash")
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    try:
        restore_absolute_directory_snapshots(
            transaction.parent_directories, "backup pool rollback parent"
        )
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    if rollback_error is not None:
        raise rollback_error


def cleanup_root_path_no_create(target: Path) -> Path:
    return target.parent / f".{target.name}.{CLEANUP_NAME_COMPONENT}"


def cleanup_namespace_name(target: Path) -> str:
    return canonical_target_digest(target)


def cleanup_namespace_path_no_create(target: Path) -> Path:
    return cleanup_root_path_no_create(target) / cleanup_namespace_name(target)


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_namespace_path_no_create(target) / CLEANUP_JOURNAL_FILE_NAME


def cleanup_promotion_intent_path(target: Path) -> Path:
    return cleanup_namespace_path_no_create(target) / CLEANUP_PROMOTION_INTENT_FILE_NAME


def cleanup_tombstone_name(_target: Path, index: int) -> str:
    return f"entry-{index}"


def cleanup_tombstone_path(target: Path, name: str) -> Path:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        fail("cleanup journal tombstone name is unsafe")
    return cleanup_namespace_path_no_create(target) / name


def cleanup_entry_name(target: Path, index: int) -> str:
    return cleanup_tombstone_name(target, index)


def cleanup_name_prefix(target: Path) -> str:
    del target
    return "entry-"


def validate_cleanup_entry_name(target: Path, name: str) -> None:
    if not isinstance(name, str):
        fail("cleanup journal entry name must be a string")
    prefix = cleanup_name_prefix(target)
    if not name.startswith(prefix):
        fail("cleanup journal entry name is outside the manager namespace")
    suffix = name[len(prefix) :]
    if not re.fullmatch(r"[0-9]+", suffix):
        fail(f"cleanup journal entry name is invalid: {name}")


def cleanup_directory_record(path: Path, label: str, *, path_label: str) -> dict[str, Any]:
    info = require_private_directory(path, label)
    return {
        "path": path_label,
        "kind": "directory",
        "uid": owner_of(info),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "nlink": info.st_nlink,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def cleanup_source_parent_record(target: Path) -> dict[str, Any]:
    info = require_directory(target.parent, "cleanup promotion source parent")
    if not is_owner_safe_directory(info):
        fail(
            "cleanup promotion source parent must be owned by the current user "
            "and not group- or world-writable"
        )
    return {
        "path": "canonical-target-parent",
        "kind": "directory",
        "uid": owner_of(info),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def validate_cleanup_source_parent_record(target: Path, record: Any, label: str) -> None:
    if not isinstance(record, dict):
        fail(f"{label} source parent record must be an object")
    current = cleanup_source_parent_record(target)
    for key in ("path", "kind", "uid", "mode", "device", "inode"):
        if record.get(key) != current.get(key):
            fail(f"{label} source parent binding mismatch")


def cleanup_source_kind_from_stash_name(target: Path, source_name: str) -> str:
    if not isinstance(source_name, str) or source_name != Path(source_name).name:
        fail("cleanup promotion source name is unsafe")
    prefix = f".{target.name}.nddev-"
    if not source_name.startswith(prefix):
        fail("cleanup promotion source name is outside the manager namespace")
    rest = source_name[len(prefix) :]
    match = re.fullmatch(r"([a-z0-9-]+)\.([0-9]+)\.([0-9]+)", rest)
    if match is None:
        fail("cleanup promotion source name is outside the generated stash grammar")
    source_kind = match.group(1)
    if source_kind not in RECOVERABLE_CLEANUP_SOURCE_KINDS:
        fail("cleanup promotion source kind is unsupported")
    return source_kind


def validate_transaction_stash_marker(
    stash_root: Path,
    target: Path,
    source_kind: str,
    label: str,
) -> None:
    marker = load_json_object(
        stash_root / TRANSACTION_STASH_MARKER_NAME,
        f"{label} marker",
        owner_only=True,
    )
    require_exact_keys(
        marker,
        {"schema_version", "product_name", "stash_kind", "root_name", "source_parent"},
        f"{label} marker",
    )
    if marker["schema_version"] != 1:
        fail(f"{label} marker has unsupported schema")
    if marker["product_name"] != PRODUCT_NAME:
        fail(f"{label} marker belongs to another product")
    if marker["stash_kind"] != source_kind:
        fail(f"{label} marker source kind mismatch")
    if marker["root_name"] != target.name:
        fail(f"{label} marker target binding mismatch")
    validate_cleanup_source_parent_record(target, marker["source_parent"], f"{label} marker")


def validate_cleanup_source_stash(
    stash_root: Path,
    target: Path,
    source_kind: str,
    label: str,
) -> None:
    if stash_root.parent != target.parent:
        fail(f"{label} source parent binding mismatch")
    actual_kind = cleanup_source_kind_from_stash_name(target, stash_root.name)
    if actual_kind != source_kind:
        fail(f"{label} source kind mismatch")
    require_private_directory(stash_root, label)
    validate_transaction_stash_marker(stash_root, target, source_kind, label)


def recoverable_cleanup_source_stashes(target: Path) -> list[tuple[Path, str]]:
    parent_info = stat_existing(target.parent, "cleanup promotion source parent")
    if parent_info is None:
        return []
    if not stat.S_ISDIR(parent_info.st_mode):
        fail("cleanup promotion source parent must be a directory")
    if not is_owner_safe_directory(parent_info):
        fail(
            "cleanup promotion source parent must be owned by the current user "
            "and not group- or world-writable"
        )
    prefix = f".{target.name}.nddev-"
    known_manager_names = {
        backup_pool(target).name,
        cleanup_root_path_no_create(target).name,
    }
    stashes: list[tuple[Path, str]] = []
    for child in sorted(target.parent.iterdir(), key=lambda item: item.name):
        if child.name in known_manager_names:
            continue
        if not child.name.startswith(prefix):
            continue
        source_kind = cleanup_source_kind_from_stash_name(target, child.name)
        validate_cleanup_source_stash(
            child,
            target,
            source_kind,
            f"cleanup promotion orphan source {child.name}",
        )
        stashes.append((child, f"{source_kind} transaction cleanup"))
    return stashes


def cleanup_record_stable_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    stable_keys = {"path", "kind", "uid", "mode", "device", "inode"}
    return all(actual.get(key) == expected.get(key) for key in stable_keys)


def cleanup_object_record(
    root: Path, path: Path, info: os.stat_result, label: str
) -> dict[str, Any]:
    relative = "." if path == root else path.relative_to(root).as_posix()
    owner = owner_of(info)
    common: dict[str, Any] = {
        "path": relative,
        "uid": owner,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "nlink": info.st_nlink,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }
    if stat.S_ISDIR(info.st_mode):
        if not is_owner_safe_directory(info):
            fail(
                f"{label} directory {relative} must be owned by the current user and not writable by others"
            )
        common["kind"] = "directory"
        return common
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            fail(f"{label} file {relative} must not have hard-link aliases")
        content, file_info = read_regular_file(
            path,
            f"{label} file {relative}",
            owner_only=False,
            max_bytes=CLEANUP_MAX_TREE_BYTES,
        )
        mode = stat.S_IMODE(file_info.st_mode)
        if mode not in {OWNER_FILE_MODE, OWNER_DIRECTORY_MODE}:
            fail(f"{label} file {relative} has unsupported mode")
        common.update(
            {
                "kind": "regular",
                "mode": f"{mode:04o}",
                "nlink": file_info.st_nlink,
                "device": file_info.st_dev,
                "inode": file_info.st_ino,
                "size": len(content),
                "mtime_ns": file_info.st_mtime_ns,
                "sha256": sha256_bytes(content),
            }
        )
        return common
    fail(f"{label} contains unsupported path type: {relative}")


def cleanup_tree_manifest(root: Path, label: str) -> list[dict[str, Any]]:
    require_private_directory(root, label)
    paths = [root]
    paths.extend(sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()))
    if len(paths) > CLEANUP_MAX_TREE_ENTRIES:
        fail(f"{label} exceeds the cleanup entry count limit")
    records: list[dict[str, Any]] = []
    total_bytes = 0
    for path in paths:
        info = stat_existing(
            path, f"{label} path {path.relative_to(root) if path != root else '.'}"
        )
        if info is None:
            fail(f"{label} changed during cleanup journal validation")
        record = cleanup_object_record(root, path, info, label)
        if record["kind"] == "regular":
            total_bytes += int(record["size"])
            if total_bytes > CLEANUP_MAX_TREE_BYTES:
                fail(f"{label} exceeds the cleanup byte limit")
        records.append(record)
    return records


def cleanup_records_by_path(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    if len(records) > CLEANUP_MAX_TREE_ENTRIES:
        fail(f"{label} exceeds the cleanup entry count limit")
    by_path: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for record in records:
        if not isinstance(record, dict):
            fail(f"{label} contains an invalid cleanup object record")
        if record.get("kind") == "regular":
            raw_size = record.get("size")
            if not isinstance(raw_size, int) or raw_size < 0:
                fail(f"{label} contains an invalid cleanup object size")
            total_bytes += raw_size
            if total_bytes > CLEANUP_MAX_TREE_BYTES:
                fail(f"{label} exceeds the cleanup byte limit")
        raw_path = record.get("path")
        if not isinstance(raw_path, str) or raw_path in {"", ".."}:
            fail(f"{label} contains an invalid cleanup object path")
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            fail(f"{label} contains an unsafe cleanup object path")
        if raw_path in by_path:
            fail(f"{label} contains duplicate cleanup object records")
        by_path[raw_path] = record
    if "." not in by_path:
        fail(f"{label} must record the tombstone root")
    return by_path


def cleanup_current_paths(root: Path, label: str) -> set[str]:
    if not lstat_exists(root):
        return set()
    require_private_directory(root, label)
    paths = {"."}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if len(paths) >= CLEANUP_MAX_TREE_ENTRIES:
            fail(f"{label} exceeds the cleanup entry count limit")
        paths.add(relative)
    return paths


def cleanup_record_matches_path(
    root: Path,
    expected: dict[str, Any],
    label: str,
    *,
    full_directory: bool,
) -> bool:
    raw_path = expected["path"]
    path = root if raw_path == "." else root / raw_path
    info = stat_existing(path, f"{label} object {raw_path}")
    if info is None:
        return False
    actual = cleanup_object_record(root, path, info, label)
    if expected.get("kind") == "directory" and not full_directory:
        return cleanup_record_stable_matches(actual, expected)
    return actual == expected


def validate_cleanup_tree_state(
    root: Path,
    expected: list[dict[str, Any]],
    label: str,
    *,
    require_complete: bool,
) -> set[str]:
    expected_by_path = cleanup_records_by_path(expected, label)
    actual_paths = cleanup_current_paths(root, label)
    expected_paths = set(expected_by_path)
    if require_complete and actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        fail(f"{label} complete graph mismatch missing={missing} extra={extra}")
    unknown = actual_paths - expected_paths
    if unknown:
        fail(f"{label} contains unjournaled cleanup objects: {sorted(unknown)}")
    for raw_path in sorted(actual_paths, key=lambda item: (len(Path(item).parts), item)):
        expected_record = expected_by_path[raw_path]
        full_directory = require_complete or expected_record.get("kind") != "directory"
        if not cleanup_record_matches_path(
            root,
            expected_record,
            label,
            full_directory=full_directory,
        ):
            fail(f"{label} cleanup object identity changed: {raw_path}")
    return actual_paths


def drain_cleanup_tree(root: Path, expected: list[dict[str, Any]], label: str) -> None:
    actual_paths = validate_cleanup_tree_state(root, expected, label, require_complete=False)
    if not actual_paths:
        return
    expected_paths = {record["path"] for record in expected}
    if actual_paths == expected_paths:
        validate_cleanup_tree_state(root, expected, label, require_complete=True)
    records = cleanup_records_by_path(expected, label)
    for raw_path in sorted(
        actual_paths, key=lambda item: (len(Path(item).parts), item), reverse=True
    ):
        path = root if raw_path == "." else root / raw_path
        if not lstat_exists(path):
            continue
        record = records[raw_path]
        if record.get("kind") == "regular":
            if not cleanup_record_matches_path(root, record, label, full_directory=True):
                fail(f"{label} cleanup object identity changed before deletion: {raw_path}")
            retrying_unlink(path, f"{label} object {raw_path}")
        elif record.get("kind") == "directory":
            if not cleanup_record_matches_path(root, record, label, full_directory=False):
                fail(f"{label} cleanup directory identity changed before deletion: {raw_path}")
            unknown_children = [child.name for child in path.iterdir()]
            if unknown_children:
                fail(f"{label} cleanup directory is not empty before deletion: {raw_path}")
            path.rmdir()
        else:
            fail(f"{label} contains unsupported cleanup object kind: {raw_path}")
        fsync_directory(path.parent, f"{label} object {raw_path} parent")


def cleanup_journal_payload(target: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "cleanup_kind": "post-commit-recursive-cleanup",
        "canonical_target": str(target),
        "target_digest": cleanup_namespace_name(target),
        "cleanup_root": cleanup_directory_record(
            cleanup_root_path_no_create(target),
            "cleanup journal root",
            path_label=cleanup_root_path_no_create(target).name,
        ),
        "cleanup_namespace": cleanup_directory_record(
            cleanup_namespace_path_no_create(target),
            "cleanup journal namespace",
            path_label=cleanup_namespace_name(target),
        ),
        "entry_count_bound": CLEANUP_MAX_ENTRIES,
        "tree_entry_bound": CLEANUP_MAX_TREE_ENTRIES,
        "tree_byte_bound": CLEANUP_MAX_TREE_BYTES,
        "journal_byte_bound": CLEANUP_MAX_JOURNAL_BYTES,
        "entries": entries,
        "created_at": int(time.time()),
    }


def cleanup_journal_serialized_content(journal: dict[str, Any]) -> bytes:
    content = canonical_json(journal)
    if len(content) > CLEANUP_MAX_JOURNAL_BYTES:
        fail("cleanup journal exceeds the serialized byte bound")
    return content


def require_cleanup_parent(target: Path, label: str) -> os.stat_result:
    info = require_directory(target.parent, label)
    if not is_owner_safe_directory(info):
        fail(f"{label} must be owned by the current user and not group- or world-writable")
    return info


def cleanup_root_no_create(target: Path) -> Path | None:
    root = cleanup_root_path_no_create(target)
    cleanup_info = stat_existing(root, "cleanup journal root")
    if cleanup_info is None:
        return None
    require_private_directory(root, "cleanup journal root")
    return root


def cleanup_namespace_no_create(target: Path) -> Path | None:
    root = cleanup_root_no_create(target)
    if root is None:
        return None
    namespace = cleanup_namespace_path_no_create(target)
    info = stat_existing(namespace, "cleanup journal namespace")
    if info is None:
        return None
    require_private_directory(namespace, "cleanup journal namespace")
    return namespace


def cleanup_namespace_children(target: Path) -> list[Path]:
    namespace = cleanup_namespace_no_create(target)
    if namespace is None:
        return []
    return sorted(namespace.iterdir(), key=str)


def pre_intent_cleanup_namespace_state(target: Path) -> tuple[Path, Path | None] | None:
    require_cleanup_parent(target, "cleanup journal parent")
    root = cleanup_root_no_create(target)
    if root is None:
        return None
    namespace = cleanup_namespace_path_no_create(target)
    root_children = sorted(root.iterdir(), key=str)
    if not root_children:
        return root, None
    if root_children != [namespace]:
        fail("cleanup journal root contains unjournaled state")
    require_private_directory(namespace, "cleanup journal namespace")
    namespace_children = sorted(namespace.iterdir(), key=str)
    if namespace_children:
        return None
    return root, namespace


def fail_on_pre_intent_cleanup_namespace(target: Path) -> None:
    if pre_intent_cleanup_namespace_state(target) is not None:
        fail("cleanup promotion namespace requires exclusive recovery")


def recover_pre_intent_cleanup_namespace(target: Path) -> bool:
    parent_info = require_cleanup_parent(target, "cleanup journal parent")
    parent_identity = identity_of(parent_info)
    state = pre_intent_cleanup_namespace_state(target)
    if state is None:
        return False
    root, namespace = state
    if namespace is not None:
        require_private_directory(namespace, "cleanup journal pre-intent namespace")
        if any(namespace.iterdir()):
            fail("cleanup journal pre-intent namespace is not empty")
        namespace.rmdir()
        fsync_directory(root, "cleanup journal pre-intent namespace parent")
    require_private_directory(root, "cleanup journal pre-intent root")
    if any(root.iterdir()):
        fail("cleanup journal pre-intent root contains unjournaled state")
    root.rmdir()
    fsync_directory(root.parent, "cleanup journal pre-intent root parent")
    final_parent = require_cleanup_parent(target, "cleanup journal parent")
    if identity_of(final_parent) != parent_identity:
        fail_concurrent("cleanup journal parent changed during pre-intent recovery")
    return True


def cleanup_journal_publication_aliases(target: Path) -> list[Path]:
    final = cleanup_journal_path(target)
    return [
        child
        for child in cleanup_namespace_children(target)
        if child != final and is_publication_alias(child, final)
    ]


def cleanup_promotion_intent_publication_aliases(target: Path) -> list[Path]:
    final = cleanup_promotion_intent_path(target)
    return [
        child
        for child in cleanup_namespace_children(target)
        if child != final and is_publication_alias(child, final)
    ]


def remove_unpublished_publication_temps(final: Path, label: str) -> None:
    parent = final.parent
    if not lstat_exists(parent):
        return
    require_private_directory(parent, f"{label} parent")
    if lstat_exists(final):
        return
    for child in sorted(parent.iterdir(), key=str):
        if not is_publication_alias(child, final):
            continue
        info = stat_existing(child, f"{label} temp")
        if info is None:
            continue
        require_current_owner(info, f"{label} temp")
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} temp must be a regular file")
        if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
            fail(f"{label} temp must be owned by the current user with mode 0600")
        if info.st_nlink != 1:
            fail(f"{label} temp has hard-link aliases")
        retrying_unlink(child, f"{label} unpublished temp")


def validate_cleanup_journal_object_shape(
    target: Path,
    journal: dict[str, Any],
    label: str,
) -> list[dict[str, Any]]:
    require_exact_keys(
        journal,
        {
            "schema_version",
            "product_name",
            "cleanup_kind",
            "canonical_target",
            "target_digest",
            "cleanup_root",
            "cleanup_namespace",
            "entry_count_bound",
            "tree_entry_bound",
            "tree_byte_bound",
            "journal_byte_bound",
            "entries",
            "created_at",
        },
        label,
    )
    cleanup_journal_serialized_content(journal)
    if journal["schema_version"] != CLEANUP_SCHEMA:
        fail(f"{label} has unsupported schema")
    if journal["product_name"] != PRODUCT_NAME:
        fail(f"{label} belongs to another product")
    if journal["cleanup_kind"] != "post-commit-recursive-cleanup":
        fail(f"{label} kind mismatch")
    if journal["canonical_target"] != str(target):
        fail(f"{label} target binding mismatch")
    if journal["target_digest"] != cleanup_namespace_name(target):
        fail(f"{label} target digest mismatch")
    if journal["entry_count_bound"] != CLEANUP_MAX_ENTRIES:
        fail(f"{label} entry bound mismatch")
    if journal["tree_entry_bound"] != CLEANUP_MAX_TREE_ENTRIES:
        fail(f"{label} tree entry bound mismatch")
    if journal["tree_byte_bound"] != CLEANUP_MAX_TREE_BYTES:
        fail(f"{label} tree byte bound mismatch")
    if journal["journal_byte_bound"] != CLEANUP_MAX_JOURNAL_BYTES:
        fail(f"{label} serialized byte bound mismatch")
    for record_field, path, path_label in (
        (
            "cleanup_root",
            cleanup_root_path_no_create(target),
            cleanup_root_path_no_create(target).name,
        ),
        (
            "cleanup_namespace",
            cleanup_namespace_path_no_create(target),
            cleanup_namespace_name(target),
        ),
    ):
        recorded_directory = journal[record_field]
        if not isinstance(recorded_directory, dict):
            fail(f"{label} {record_field} record must be an object")
        current_directory = cleanup_directory_record(
            path,
            f"{label} {record_field}",
            path_label=path_label,
        )
        for key in ("path", "kind", "uid", "mode", "device", "inode"):
            if recorded_directory.get(key) != current_directory.get(key):
                fail(f"{label} {record_field} binding mismatch")
    entries = journal["entries"]
    if not isinstance(entries, list) or len(entries) > CLEANUP_MAX_ENTRIES:
        fail(f"{label} entries are invalid")
    declared_names: set[str] = set()
    typed_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail(f"{label} entry must be an object")
        require_exact_keys(entry, {"name", "label", "tree"}, f"{label} entry {index}")
        name = entry["name"]
        validate_cleanup_entry_name(target, name)
        if name in declared_names:
            fail(f"{label} contains duplicate entries")
        declared_names.add(name)
        if cleanup_entry_name(target, index) != name:
            fail(f"{label} entry order mismatch")
        if not isinstance(entry["label"], str) or not entry["label"]:
            fail(f"{label} entry label must be a non-empty string")
        if not isinstance(entry["tree"], list):
            fail(f"{label} entry tree must be a list")
        typed_entries.append(entry)
    return typed_entries


def publish_cleanup_journal_atomic(target: Path, journal: dict[str, Any]) -> None:
    path = cleanup_journal_path(target)
    parent = cleanup_namespace_path_no_create(target)
    require_private_directory(parent, "cleanup journal namespace")
    if lstat_exists(path):
        fail("cleanup journal is already pending")
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag("cleanup journal")
    descriptor: int | None = None
    final_visible = False
    temp_unlinked = False
    content = cleanup_journal_serialized_content(journal)
    stage = "prepare"
    try:
        descriptor = os.open(temp, flags, OWNER_FILE_MODE)
        os.fchmod(descriptor, OWNER_FILE_MODE)
        remaining = content
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                fail("cleanup journal could not be written")
            remaining = remaining[written:]
        os.fsync(descriptor)
        stage = "temp-parent-fsync"
        fsync_directory(parent, "cleanup journal temp parent")
        stage = "publish"
        os.link(temp, path)
        final_visible = True
        stage = "temp-unlink"
        temp.unlink()
        temp_unlinked = True
        stage = "parent-fsync"
        fsync_directory(parent, "cleanup journal publish parent")
    except BaseException:
        exc = sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        if not final_visible and not temp_unlinked and lstat_exists(temp):
            try:
                retrying_unlink(temp, "cleanup journal temp")
            except BaseException as cleanup_exc:
                cleanup_error = cleanup_exc
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if cleanup_error is not None:
            raise cleanup_error
        if exc is not None:
            raise NoReplacePublicationError(
                stage, exc, final_visible=final_visible, temp=temp
            ) from exc
        raise
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def cleanup_promotion_intent_serialized_content(intent: dict[str, Any]) -> bytes:
    content = canonical_json(intent)
    if len(content) > CLEANUP_MAX_PROMOTION_INTENT_BYTES:
        fail("cleanup promotion intent exceeds the serialized byte bound")
    return content


def cleanup_promotion_intent_payload(
    target: Path,
    moves: list[dict[str, Any]],
    journal: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "cleanup_kind": "pre-journal-promotion-recovery",
        "canonical_target": str(target),
        "target_digest": cleanup_namespace_name(target),
        "cleanup_root": cleanup_directory_record(
            cleanup_root_path_no_create(target),
            "cleanup promotion intent root",
            path_label=cleanup_root_path_no_create(target).name,
        ),
        "cleanup_namespace": cleanup_directory_record(
            cleanup_namespace_path_no_create(target),
            "cleanup promotion intent namespace",
            path_label=cleanup_namespace_name(target),
        ),
        "source_parent": cleanup_source_parent_record(target),
        "entry_count_bound": CLEANUP_MAX_ENTRIES,
        "tree_entry_bound": CLEANUP_MAX_TREE_ENTRIES,
        "tree_byte_bound": CLEANUP_MAX_TREE_BYTES,
        "journal_byte_bound": CLEANUP_MAX_JOURNAL_BYTES,
        "promotion_intent_byte_bound": CLEANUP_MAX_PROMOTION_INTENT_BYTES,
        "moves": moves,
        "journal": journal,
        "created_at": int(time.time()),
    }


def publish_cleanup_promotion_intent_atomic(target: Path, intent: dict[str, Any]) -> None:
    path = cleanup_promotion_intent_path(target)
    parent = cleanup_namespace_path_no_create(target)
    require_private_directory(parent, "cleanup promotion intent namespace")
    if lstat_exists(path):
        fail("cleanup promotion intent is already pending")
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag("cleanup promotion intent")
    descriptor: int | None = None
    final_visible = False
    temp_unlinked = False
    content = cleanup_promotion_intent_serialized_content(intent)
    stage = "prepare"
    try:
        descriptor = os.open(temp, flags, OWNER_FILE_MODE)
        os.fchmod(descriptor, OWNER_FILE_MODE)
        remaining = content
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                fail("cleanup promotion intent could not be written")
            remaining = remaining[written:]
        os.fsync(descriptor)
        stage = "temp-parent-fsync"
        fsync_directory(parent, "cleanup promotion intent temp parent")
        stage = "publish"
        os.link(temp, path)
        final_visible = True
        stage = "temp-unlink"
        temp.unlink()
        temp_unlinked = True
        stage = "parent-fsync"
        fsync_directory(parent, "cleanup promotion intent publish parent")
    except BaseException:
        exc = sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        if not final_visible and not temp_unlinked and lstat_exists(temp):
            try:
                retrying_unlink(temp, "cleanup promotion intent temp")
            except BaseException as cleanup_exc:
                cleanup_error = cleanup_exc
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if cleanup_error is not None:
            raise cleanup_error
        if exc is not None:
            raise NoReplacePublicationError(
                stage,
                exc,
                final_visible=final_visible,
                temp=temp,
            ) from exc
        raise
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def open_cleanup_promotion_intent(
    target: Path,
    *,
    recover_publication_alias: bool,
) -> dict[str, Any] | None:
    namespace = cleanup_namespace_no_create(target)
    if namespace is None:
        return None
    path = cleanup_promotion_intent_path(target)
    aliases = cleanup_promotion_intent_publication_aliases(target)
    info = stat_existing(path, "cleanup promotion intent")
    if info is None:
        if aliases:
            fail("cleanup promotion intent publication is incomplete")
        return None
    require_current_owner(info, "cleanup promotion intent")
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup promotion intent must be a regular file")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("cleanup promotion intent must be owned by the current user with mode 0600")
    if info.st_nlink == 2 and recover_publication_alias:
        alias = require_one_hardlink_publication_alias(
            path,
            identity_of(info),
            "cleanup promotion intent",
        )
        retrying_unlink(alias, "cleanup promotion intent publication alias")
        fsync_directory(namespace, "cleanup promotion intent publication alias cleanup parent")
        info = require_regular_file(
            path,
            "cleanup promotion intent",
            owner_only=True,
            max_bytes=CLEANUP_MAX_PROMOTION_INTENT_BYTES,
        )
        aliases = cleanup_promotion_intent_publication_aliases(target)
    if info.st_nlink != 1:
        fail("cleanup promotion intent publication is incomplete")
    if aliases:
        fail("cleanup promotion intent namespace contains incomplete publication aliases")
    content, final_info = read_regular_file(
        path,
        "cleanup promotion intent",
        owner_only=True,
        max_bytes=CLEANUP_MAX_PROMOTION_INTENT_BYTES,
    )
    if identity_of(final_info) != identity_of(info):
        fail_concurrent("cleanup promotion intent changed while it was being read")
    return parse_json_object(content, "cleanup promotion intent")


def validate_cleanup_promotion_intent(
    target: Path,
    *,
    recover_publication_alias: bool = False,
) -> dict[str, Any] | None:
    intent = open_cleanup_promotion_intent(
        target,
        recover_publication_alias=recover_publication_alias,
    )
    if intent is None:
        return None
    require_exact_keys(
        intent,
        {
            "schema_version",
            "product_name",
            "cleanup_kind",
            "canonical_target",
            "target_digest",
            "cleanup_root",
            "cleanup_namespace",
            "source_parent",
            "entry_count_bound",
            "tree_entry_bound",
            "tree_byte_bound",
            "journal_byte_bound",
            "promotion_intent_byte_bound",
            "moves",
            "journal",
            "created_at",
        },
        "cleanup promotion intent",
    )
    cleanup_promotion_intent_serialized_content(intent)
    if intent["schema_version"] != CLEANUP_SCHEMA:
        fail("cleanup promotion intent has unsupported schema")
    if intent["product_name"] != PRODUCT_NAME:
        fail("cleanup promotion intent belongs to another product")
    if intent["cleanup_kind"] != "pre-journal-promotion-recovery":
        fail("cleanup promotion intent kind mismatch")
    if intent["canonical_target"] != str(target):
        fail("cleanup promotion intent target binding mismatch")
    if intent["target_digest"] != cleanup_namespace_name(target):
        fail("cleanup promotion intent target digest mismatch")
    if intent["entry_count_bound"] != CLEANUP_MAX_ENTRIES:
        fail("cleanup promotion intent entry bound mismatch")
    if intent["tree_entry_bound"] != CLEANUP_MAX_TREE_ENTRIES:
        fail("cleanup promotion intent tree entry bound mismatch")
    if intent["tree_byte_bound"] != CLEANUP_MAX_TREE_BYTES:
        fail("cleanup promotion intent tree byte bound mismatch")
    if intent["journal_byte_bound"] != CLEANUP_MAX_JOURNAL_BYTES:
        fail("cleanup promotion intent journal byte bound mismatch")
    if intent["promotion_intent_byte_bound"] != CLEANUP_MAX_PROMOTION_INTENT_BYTES:
        fail("cleanup promotion intent serialized byte bound mismatch")
    for record_field, path, path_label in (
        (
            "cleanup_root",
            cleanup_root_path_no_create(target),
            cleanup_root_path_no_create(target).name,
        ),
        (
            "cleanup_namespace",
            cleanup_namespace_path_no_create(target),
            cleanup_namespace_name(target),
        ),
    ):
        recorded_directory = intent[record_field]
        if not isinstance(recorded_directory, dict):
            fail(f"cleanup promotion intent {record_field} record must be an object")
        current_directory = cleanup_directory_record(
            path,
            f"cleanup promotion intent {record_field}",
            path_label=path_label,
        )
        for key in ("path", "kind", "uid", "mode", "device", "inode"):
            if recorded_directory.get(key) != current_directory.get(key):
                fail(f"cleanup promotion intent {record_field} binding mismatch")
    validate_cleanup_source_parent_record(
        target,
        intent["source_parent"],
        "cleanup promotion intent",
    )
    journal = intent["journal"]
    if not isinstance(journal, dict):
        fail("cleanup promotion intent journal must be an object")
    entries = validate_cleanup_journal_object_shape(
        target,
        journal,
        "cleanup promotion intent journal",
    )
    moves = intent["moves"]
    if not isinstance(moves, list) or len(moves) != len(entries):
        fail("cleanup promotion intent moves are invalid")
    declared_names: set[str] = set()
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            fail("cleanup promotion intent move must be an object")
        require_exact_keys(
            move,
            {"name", "source_anchor", "source_name", "source_kind", "label"},
            f"cleanup promotion intent move {index}",
        )
        name = move["name"]
        source_name = move["source_name"]
        source_kind = move["source_kind"]
        if name != entries[index]["name"] or cleanup_entry_name(target, index) != name:
            fail("cleanup promotion intent move order mismatch")
        if name in declared_names:
            fail("cleanup promotion intent contains duplicate moves")
        declared_names.add(name)
        if move["source_anchor"] != "canonical-target-parent":
            fail("cleanup promotion intent source anchor mismatch")
        if not isinstance(source_kind, str):
            fail("cleanup promotion intent source kind must be a string")
        if cleanup_source_kind_from_stash_name(target, source_name) != source_kind:
            fail("cleanup promotion intent source kind mismatch")
        if move["label"] != entries[index]["label"]:
            fail("cleanup promotion intent label mismatch")
        source = target.parent / source_name
        tombstone = cleanup_tombstone_path(target, name)
        source_exists = lstat_exists(source)
        tombstone_exists = lstat_exists(tombstone)
        if source_exists and tombstone_exists:
            fail("cleanup promotion intent source and tombstone both exist")
        if not source_exists and not tombstone_exists:
            fail("cleanup promotion intent source and tombstone are both missing")
        tree = entries[index]["tree"]
        if source_exists:
            validate_cleanup_source_stash(
                source,
                target,
                source_kind,
                f"cleanup promotion intent source {source_name}",
            )
            validate_cleanup_tree_state(
                source,
                tree,
                f"cleanup promotion intent source {source_name}",
                require_complete=True,
            )
        if tombstone_exists:
            validate_cleanup_tree_state(
                tombstone,
                tree,
                f"cleanup promotion intent tombstone {name}",
                require_complete=True,
            )
    allowed = {
        cleanup_promotion_intent_path(target).name,
        cleanup_journal_path(target).name,
        *declared_names,
    }
    allowed.update(child.name for child in cleanup_promotion_intent_publication_aliases(target))
    allowed.update(child.name for child in cleanup_journal_publication_aliases(target))
    unknown = [
        child.name
        for child in cleanup_namespace_children(target)
        if child.name not in allowed
        and not is_publication_alias(child, cleanup_promotion_intent_path(target))
        and not is_publication_alias(child, cleanup_journal_path(target))
    ]
    if unknown:
        fail(f"cleanup promotion intent contains unjournaled state: {sorted(unknown)}")
    return intent


def remove_cleanup_promotion_intent(target: Path) -> None:
    path = cleanup_promotion_intent_path(target)
    if lstat_exists(path):
        retrying_unlink(path, "cleanup promotion intent")
    for alias in cleanup_promotion_intent_publication_aliases(target):
        retrying_unlink(alias, "cleanup promotion intent publication alias")


def recover_orphan_cleanup_sources(target: Path) -> bool:
    stashes = recoverable_cleanup_source_stashes(target)
    if not stashes:
        return False
    promote_transaction_stashes_to_cleanup(
        target,
        stashes,
        recover_existing=False,
    )
    return True


def recover_cleanup_promotion_intent(
    target: Path,
    *,
    recover_orphan_sources: bool = True,
) -> bool:
    remove_unpublished_publication_temps(
        cleanup_promotion_intent_path(target),
        "cleanup promotion intent",
    )
    intent = validate_cleanup_promotion_intent(target, recover_publication_alias=True)
    if intent is None:
        if recover_orphan_sources:
            if recover_orphan_cleanup_sources(target):
                return True
        if recover_pre_intent_cleanup_namespace(target):
            return True
        return False
    journal_path = cleanup_journal_path(target)
    if lstat_exists(journal_path):
        if (
            validate_cleanup_journal(
                target,
                recover_publication_alias=True,
                allow_promotion_intent=True,
            )
            is None
        ):
            fail("cleanup journal final publication is missing")
        remove_cleanup_promotion_intent(target)
        return True
    journal = intent["journal"]
    entries = validate_cleanup_journal_object_shape(
        target,
        journal,
        "cleanup promotion intent journal",
    )
    moves = intent["moves"]
    namespace = cleanup_namespace_path_no_create(target)
    for index, move in enumerate(moves):
        entry = entries[index]
        source = target.parent / move["source_name"]
        tombstone = cleanup_tombstone_path(target, move["name"])
        source_exists = lstat_exists(source)
        tombstone_exists = lstat_exists(tombstone)
        if source_exists and tombstone_exists:
            fail("cleanup promotion recovery source and tombstone both exist")
        if source_exists:
            validate_cleanup_source_stash(
                source,
                target,
                move["source_kind"],
                f"cleanup promotion recovery source {move['source_name']}",
            )
            validate_cleanup_tree_state(
                source,
                entry["tree"],
                f"cleanup promotion recovery source {move['source_name']}",
                require_complete=True,
            )
            retrying_replace(source, tombstone, f"cleanup promotion recovery {move['name']}")
            fsync_directory(source.parent, f"cleanup promotion recovery source parent {move['name']}")
            fsync_directory(namespace, f"cleanup promotion recovery namespace {move['name']}")
        elif not tombstone_exists:
            fail("cleanup promotion recovery source and tombstone are both missing")
        validate_cleanup_tree_state(
            tombstone,
            entry["tree"],
            f"cleanup promotion recovery tombstone {move['name']}",
            require_complete=True,
        )
    remove_unpublished_publication_temps(cleanup_journal_path(target), "cleanup journal")
    try:
        publish_cleanup_journal_atomic(target, journal)
    except NoReplacePublicationError as exc:
        if not exc.final_visible:
            raise
        if (
            validate_cleanup_journal(
                target,
                recover_publication_alias=True,
                allow_promotion_intent=True,
            )
            is None
        ):
            fail("cleanup journal final publication is missing")
    if (
        validate_cleanup_journal(
            target,
            recover_publication_alias=True,
            allow_promotion_intent=True,
        )
        is None
    ):
        fail("cleanup journal final publication is missing")
    remove_cleanup_promotion_intent(target)
    return True


def open_cleanup_journal(
    target: Path,
    *,
    recover_publication_alias: bool,
) -> dict[str, Any] | None:
    namespace = cleanup_namespace_no_create(target)
    if namespace is None:
        return None
    path = cleanup_journal_path(target)
    aliases = cleanup_journal_publication_aliases(target)
    info = stat_existing(path, "cleanup journal")
    if info is None:
        if aliases or any(child.name != path.name for child in cleanup_namespace_children(target)):
            fail("cleanup journal namespace contains incomplete pending state")
        return None
    require_current_owner(info, "cleanup journal")
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup journal must be a regular file")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("cleanup journal must be owned by the current user with mode 0600")
    if info.st_nlink == 2 and recover_publication_alias:
        alias = require_one_hardlink_publication_alias(path, identity_of(info), "cleanup journal")
        retrying_unlink(alias, "cleanup journal publication alias")
        fsync_directory(namespace, "cleanup journal publication alias cleanup parent")
        info = require_regular_file(
            path,
            "cleanup journal",
            owner_only=True,
            max_bytes=CLEANUP_MAX_JOURNAL_BYTES,
        )
        aliases = cleanup_journal_publication_aliases(target)
    if info.st_nlink != 1:
        fail("cleanup journal publication is incomplete")
    if aliases:
        fail("cleanup journal namespace contains incomplete publication aliases")
    content, final_info = read_regular_file(
        path,
        "cleanup journal",
        owner_only=True,
        max_bytes=CLEANUP_MAX_JOURNAL_BYTES,
    )
    if identity_of(final_info) != identity_of(info):
        fail_concurrent("cleanup journal changed while it was being read")
    return parse_json_object(content, "cleanup journal")


def validate_cleanup_journal(
    target: Path,
    *,
    recover_publication_alias: bool = False,
    allow_promotion_intent: bool = False,
) -> dict[str, Any] | None:
    journal = open_cleanup_journal(target, recover_publication_alias=recover_publication_alias)
    if journal is None:
        return None
    require_exact_keys(
        journal,
        {
            "schema_version",
            "product_name",
            "cleanup_kind",
            "canonical_target",
            "target_digest",
            "cleanup_root",
            "cleanup_namespace",
            "entry_count_bound",
            "tree_entry_bound",
            "tree_byte_bound",
            "journal_byte_bound",
            "entries",
            "created_at",
        },
        "cleanup journal",
    )
    cleanup_journal_serialized_content(journal)
    if journal["schema_version"] != CLEANUP_SCHEMA:
        fail("cleanup journal has unsupported schema")
    if journal["product_name"] != PRODUCT_NAME:
        fail("cleanup journal belongs to another product")
    if journal["cleanup_kind"] != "post-commit-recursive-cleanup":
        fail("cleanup journal kind mismatch")
    if journal["canonical_target"] != str(target):
        fail("cleanup journal target binding mismatch")
    if journal["target_digest"] != cleanup_namespace_name(target):
        fail("cleanup journal target digest mismatch")
    if journal["entry_count_bound"] != CLEANUP_MAX_ENTRIES:
        fail("cleanup journal entry bound mismatch")
    if journal["tree_entry_bound"] != CLEANUP_MAX_TREE_ENTRIES:
        fail("cleanup journal tree entry bound mismatch")
    if journal["tree_byte_bound"] != CLEANUP_MAX_TREE_BYTES:
        fail("cleanup journal tree byte bound mismatch")
    if journal["journal_byte_bound"] != CLEANUP_MAX_JOURNAL_BYTES:
        fail("cleanup journal serialized byte bound mismatch")
    for record_field, path, path_label in (
        (
            "cleanup_root",
            cleanup_root_path_no_create(target),
            cleanup_root_path_no_create(target).name,
        ),
        (
            "cleanup_namespace",
            cleanup_namespace_path_no_create(target),
            cleanup_namespace_name(target),
        ),
    ):
        recorded_directory = journal[record_field]
        if not isinstance(recorded_directory, dict):
            fail(f"cleanup journal {record_field} record must be an object")
        current_directory = cleanup_directory_record(
            path,
            f"cleanup journal {record_field}",
            path_label=path_label,
        )
        for key in ("path", "kind", "uid", "mode", "device", "inode"):
            if recorded_directory.get(key) != current_directory.get(key):
                fail(f"cleanup journal {record_field} binding mismatch")
    entries = journal["entries"]
    if not isinstance(entries, list) or len(entries) > CLEANUP_MAX_ENTRIES:
        fail("cleanup journal entries are invalid")
    declared_names: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("cleanup journal entry must be an object")
        require_exact_keys(entry, {"name", "label", "tree"}, f"cleanup journal entry {index}")
        name = entry["name"]
        validate_cleanup_entry_name(target, name)
        if name in declared_names:
            fail("cleanup journal contains duplicate entries")
        declared_names.add(name)
        if cleanup_entry_name(target, index) != name:
            fail("cleanup journal entry order mismatch")
        if not isinstance(entry["label"], str) or not entry["label"]:
            fail("cleanup journal entry label must be a non-empty string")
        tree = entry["tree"]
        if not isinstance(tree, list):
            fail("cleanup journal entry tree must be a list")
        tombstone = cleanup_tombstone_path(target, name)
        if lstat_exists(tombstone):
            validate_cleanup_tree_state(
                tombstone,
                tree,
                f"cleanup journal entry {name}",
                require_complete=False,
            )
    allowed = {cleanup_journal_path(target).name, *declared_names}
    allowed.update(child.name for child in cleanup_journal_publication_aliases(target))
    if allow_promotion_intent:
        allowed.add(cleanup_promotion_intent_path(target).name)
        allowed.update(
            child.name for child in cleanup_promotion_intent_publication_aliases(target)
        )
    unknown = [
        child.name
        for child in cleanup_namespace_children(target)
        if child.name not in allowed
        and not is_publication_alias(child, cleanup_journal_path(target))
    ]
    if unknown:
        fail(f"cleanup journal contains unjournaled state: {sorted(unknown)}")
    return journal


def cleanup_pending_status(target: Path) -> dict[str, Any]:
    return cleanup_pending_status_with_recovery(target, recover_publication_alias=False)


def cleanup_pending_status_for_mutation(target: Path) -> dict[str, Any]:
    return cleanup_pending_status_with_recovery(target, recover_publication_alias=True)


def cleanup_pending_status_with_recovery(
    target: Path,
    *,
    recover_publication_alias: bool,
) -> dict[str, Any]:
    if recover_publication_alias:
        recover_cleanup_promotion_intent(target)
    else:
        fail_on_pre_intent_cleanup_namespace(target)
        if recoverable_cleanup_source_stashes(target):
            fail("cleanup promotion source stashes require exclusive recovery")
    journal = validate_cleanup_journal(
        target,
        recover_publication_alias=recover_publication_alias,
    )
    if journal is None:
        return {"cleanup_pending": False}
    remaining = 0
    for entry in journal["entries"]:
        if lstat_exists(cleanup_tombstone_path(target, entry["name"])):
            remaining += 1
    return {
        "cleanup_pending": True,
        "cleanup": {
            "kind": journal["cleanup_kind"],
            "entries": len(journal["entries"]),
            "remaining_entries": remaining,
            "entry_count_bound": CLEANUP_MAX_ENTRIES,
            "journal_byte_bound": CLEANUP_MAX_JOURNAL_BYTES,
        },
    }


def rollback_cleanup_namespace_transaction(transaction: CleanupNamespaceTransaction) -> None:
    cleanup_error: BaseException | None = None
    try:
        if transaction.created_namespace and lstat_exists(transaction.namespace):
            require_private_directory(transaction.namespace, "cleanup journal namespace rollback")
            transaction.namespace.rmdir()
            fsync_directory(transaction.root, "cleanup journal namespace rollback parent")
        if transaction.created_root and lstat_exists(transaction.root):
            require_private_directory(transaction.root, "cleanup journal root rollback")
            transaction.root.rmdir()
            fsync_directory(transaction.root.parent, "cleanup journal root rollback parent")
    except BaseException as exc:
        cleanup_error = exc
    try:
        restore_absolute_directory_snapshots(
            transaction.snapshots,
            "cleanup journal namespace rollback",
        )
    except BaseException as exc:
        if cleanup_error is None:
            cleanup_error = exc
    if cleanup_error is not None:
        raise cleanup_error


def begin_cleanup_namespace_transaction(target: Path) -> CleanupNamespaceTransaction:
    cleanup_parent = target.parent
    require_cleanup_parent(target, "cleanup journal parent")
    cleanup_root = cleanup_root_path_no_create(target)
    namespace = cleanup_namespace_path_no_create(target)
    snapshots: dict[Path, DirectorySnapshot] = {
        cleanup_parent: capture_directory_snapshot(
            cleanup_parent, "cleanup parent before namespace create"
        ),
        cleanup_root: capture_directory_snapshot(
            cleanup_root, "cleanup root before namespace create"
        ),
        namespace: capture_directory_snapshot(
            namespace, "cleanup namespace before namespace create"
        ),
    }
    transaction = CleanupNamespaceTransaction(
        root=cleanup_root,
        namespace=namespace,
        snapshots=snapshots,
    )
    try:
        root_info = stat_existing(cleanup_root, "cleanup journal root")
        if root_info is None:
            cleanup_root.mkdir(mode=OWNER_DIRECTORY_MODE)
            transaction.created_root = True
            cleanup_root.chmod(OWNER_DIRECTORY_MODE)
            fsync_directory(cleanup_parent, "cleanup journal root parent")
        else:
            require_private_directory(cleanup_root, "cleanup journal root")
        namespace_info = stat_existing(namespace, "cleanup journal namespace")
        if namespace_info is None:
            namespace.mkdir(mode=OWNER_DIRECTORY_MODE)
            transaction.created_namespace = True
            namespace.chmod(OWNER_DIRECTORY_MODE)
            fsync_directory(cleanup_root, "cleanup journal namespace parent")
        else:
            require_private_directory(namespace, "cleanup journal namespace")
        return transaction
    except BaseException:
        rollback_cleanup_namespace_transaction(transaction)
        raise


def promote_transaction_stashes_to_cleanup(
    target: Path,
    transactions: list[tuple[Path, str]],
    *,
    recover_existing: bool = False,
) -> None:
    stashes = [
        (stash_root, label) for stash_root, label in transactions if lstat_exists(stash_root)
    ]
    if not stashes:
        return
    if len(stashes) > CLEANUP_MAX_ENTRIES:
        fail("cleanup journal entry count exceeds the declared bound")
    if recover_existing:
        recover_cleanup_promotion_intent(target, recover_orphan_sources=True)
    if validate_cleanup_journal(target, recover_publication_alias=True) is not None:
        fail("cleanup journal is already pending")
    namespace_transaction = begin_cleanup_namespace_transaction(target)
    namespace = namespace_transaction.namespace
    children = cleanup_namespace_children(target)
    if children:
        fail("cleanup journal namespace already contains pending state")
    moved: list[tuple[Path, Path, str]] = []
    intent_published = False
    try:
        entries: list[dict[str, Any]] = []
        moves: list[dict[str, Any]] = []
        for index, (stash_root, label) in enumerate(stashes):
            require_private_directory(stash_root, label)
            name = cleanup_entry_name(target, index)
            source_kind = cleanup_source_kind_from_stash_name(target, stash_root.name)
            validate_cleanup_source_stash(stash_root, target, source_kind, label)
            entries.append(
                {
                    "name": name,
                    "label": label,
                    "tree": cleanup_tree_manifest(stash_root, f"{label} cleanup journal entry"),
                }
            )
            moves.append(
                {
                    "name": name,
                    "source_anchor": "canonical-target-parent",
                    "source_name": stash_root.name,
                    "source_kind": source_kind,
                    "label": label,
                }
            )
        journal = cleanup_journal_payload(target, entries)
        cleanup_journal_serialized_content(journal)
        intent = cleanup_promotion_intent_payload(target, moves, journal)
        cleanup_promotion_intent_serialized_content(intent)
        try:
            publish_cleanup_promotion_intent_atomic(target, intent)
        except NoReplacePublicationError as exc:
            if not exc.final_visible:
                raise
            intent_published = True
            if validate_cleanup_promotion_intent(
                target,
                recover_publication_alias=True,
            ) is None:
                fail("cleanup promotion intent final publication is missing")
        else:
            intent_published = True
        for index, (stash_root, label) in enumerate(stashes):
            name = cleanup_entry_name(target, index)
            destination = cleanup_tombstone_path(target, name)
            retrying_replace(stash_root, destination, f"{label} cleanup journal promote")
            moved.append((stash_root, destination, label))
            fsync_directory(stash_root.parent, f"{label} cleanup journal source parent")
            fsync_directory(namespace, f"{label} cleanup journal namespace")
            validate_cleanup_tree_state(
                destination,
                entries[index]["tree"],
                f"{label} cleanup journal entry",
                require_complete=True,
            )
        publish_cleanup_journal_atomic(target, journal)
        validate_cleanup_journal(
            target,
            recover_publication_alias=True,
            allow_promotion_intent=True,
        )
        remove_cleanup_promotion_intent(target)
    except NoReplacePublicationError as exc:
        if exc.final_visible:
            raise
        rollback_error: BaseException | None = None
        for stash_root, destination, label in reversed(moved):
            if lstat_exists(destination) and not lstat_exists(stash_root):
                try:
                    retrying_replace(destination, stash_root, f"{label} cleanup journal rollback")
                    fsync_directory(
                        stash_root.parent, f"{label} cleanup journal rollback source parent"
                    )
                    fsync_directory(namespace, f"{label} cleanup journal rollback namespace")
                except BaseException as restore_exc:
                    if rollback_error is None:
                        rollback_error = restore_exc
        for child in cleanup_namespace_children(target):
            if is_publication_alias(child, cleanup_journal_path(target)) or is_publication_alias(
                child,
                cleanup_promotion_intent_path(target),
            ):
                with contextlib.suppress(BaseException):
                    retrying_unlink(child, "cleanup journal unpublished alias")
        if intent_published and lstat_exists(cleanup_promotion_intent_path(target)):
            try:
                retrying_unlink(
                    cleanup_promotion_intent_path(target),
                    "cleanup promotion intent rollback",
                )
            except BaseException as restore_exc:
                if rollback_error is None:
                    rollback_error = restore_exc
        try:
            rollback_cleanup_namespace_transaction(namespace_transaction)
        except BaseException as restore_exc:
            if rollback_error is None:
                rollback_error = restore_exc
        if rollback_error is not None:
            raise rollback_error from exc
        raise
    except BaseException as exc:
        rollback_error: BaseException | None = None
        if not lstat_exists(cleanup_journal_path(target)):
            for stash_root, destination, label in reversed(moved):
                if lstat_exists(destination) and not lstat_exists(stash_root):
                    try:
                        retrying_replace(
                            destination, stash_root, f"{label} cleanup journal rollback"
                        )
                        fsync_directory(
                            stash_root.parent, f"{label} cleanup journal rollback source parent"
                        )
                        fsync_directory(namespace, f"{label} cleanup journal rollback namespace")
                    except BaseException as restore_exc:
                        if rollback_error is None:
                            rollback_error = restore_exc
            for child in cleanup_namespace_children(target):
                if is_publication_alias(
                    child,
                    cleanup_journal_path(target),
                ) or is_publication_alias(child, cleanup_promotion_intent_path(target)):
                    with contextlib.suppress(BaseException):
                        retrying_unlink(child, "cleanup journal unpublished alias")
            if intent_published and lstat_exists(cleanup_promotion_intent_path(target)):
                try:
                    retrying_unlink(
                        cleanup_promotion_intent_path(target),
                        "cleanup promotion intent rollback",
                    )
                except BaseException as restore_exc:
                    if rollback_error is None:
                        rollback_error = restore_exc
            try:
                rollback_cleanup_namespace_transaction(namespace_transaction)
            except BaseException as restore_exc:
                if rollback_error is None:
                    rollback_error = restore_exc
        else:
            raise NoReplacePublicationError(
                "validate",
                exc,
                final_visible=True,
                temp=cleanup_journal_path(target),
            ) from exc
        if rollback_error is not None:
            raise rollback_error from exc
        raise


def drain_cleanup_journal(target: Path, *, fail_on_error: bool) -> bool:
    try:
        recover_cleanup_promotion_intent(target)
        journal = validate_cleanup_journal(target, recover_publication_alias=True)
        if journal is None:
            return False
        for entry in journal["entries"]:
            name = entry["name"]
            tombstone = cleanup_tombstone_path(target, name)
            if lstat_exists(tombstone):
                drain_cleanup_tree(tombstone, entry["tree"], f"cleanup journal entry {name}")
        validate_cleanup_journal(target, recover_publication_alias=True)
        for entry in journal["entries"]:
            if lstat_exists(cleanup_tombstone_path(target, entry["name"])):
                fail("cleanup journal entry remained after drain")
        journal_path = cleanup_journal_path(target)
        if lstat_exists(journal_path):
            try:
                journal_path.unlink()
                fsync_directory(journal_path.parent, "cleanup journal remove parent")
            except BaseException:
                if not lstat_exists(journal_path):
                    with contextlib.suppress(BaseException):
                        publish_cleanup_journal_atomic(target, journal)
                raise
        recover_pre_intent_cleanup_namespace(target)
        return False
    except BaseException:
        if fail_on_error:
            raise
        return True


def drain_cleanup_before_mutation(target: Path) -> None:
    drain_cleanup_journal(target, fail_on_error=True)


def drain_cleanup_before_internal_target_lock(target: Path) -> None:
    try:
        with target_coordination(target) as canonical_target:
            drain_cleanup_before_mutation(canonical_target)
    except CopilotCliSetupError as exc:
        if "target parent is missing" in str(exc):
            return
        raise


def commit_transaction_stashes_to_cleanup(
    target: Path, transactions: list[tuple[Path, str]]
) -> bool:
    try:
        promote_transaction_stashes_to_cleanup(target, transactions)
    except NoReplacePublicationError as exc:
        if exc.final_visible:
            recover_cleanup_promotion_intent(target)
            if validate_cleanup_journal(target, recover_publication_alias=True) is None:
                fail("cleanup journal final publication is missing")
            return True
        raise
    return drain_cleanup_journal(target, fail_on_error=False)


def retire_transaction_stash_for_cleanup(stash_root: Path, label: str) -> Path:
    if not lstat_exists(stash_root):
        fail(f"{label} is missing before cleanup")
    parent = stash_root.parent
    cleanup_root = stash_root.with_name(
        f".{stash_root.name}.cleanup.{os.getpid()}.{time.time_ns()}"
    )
    try:
        retrying_replace(stash_root, cleanup_root, f"{label} cleanup retire")
        fsync_directory(parent, f"{label} cleanup retire parent")
        return cleanup_root
    except BaseException as exc:
        rollback_error: BaseException | None = None
        if lstat_exists(cleanup_root) and not lstat_exists(stash_root):
            try:
                retrying_replace(cleanup_root, stash_root, f"{label} cleanup retire rollback")
                fsync_directory(parent, f"{label} cleanup retire rollback parent")
            except BaseException as restore_exc:
                rollback_error = restore_exc
        if rollback_error is not None:
            raise rollback_error from exc
        raise


def commit_transaction_stash(stash_root: Path, label: str) -> None:
    cleanup_root = retire_transaction_stash_for_cleanup(stash_root, label)
    try:
        remove_private_tree_verified(cleanup_root, f"{label} cleanup")
    except BaseException:
        if lstat_exists(cleanup_root) and not lstat_exists(stash_root):
            retrying_replace(cleanup_root, stash_root, f"{label} cleanup rollback")
            fsync_directory(stash_root.parent, f"{label} cleanup rollback parent")
        raise


def commit_lifecycle_transactions(
    target: Path,
    managed_transaction: FileSetTransaction | None,
    backup_transaction: BackupPoolTransaction | None,
) -> bool:
    transactions: list[tuple[Path, str]] = []
    if managed_transaction is not None:
        transactions.append((managed_transaction.stash_root, "transaction stash"))
    if backup_transaction is not None:
        transactions.append((backup_transaction.stash_root, "backup pool transaction stash"))
    return commit_transaction_stashes_to_cleanup(target, transactions)


def commit_backup_pool_transaction(transaction: BackupPoolTransaction) -> bool:
    return commit_transaction_stashes_to_cleanup(
        transaction.target,
        [(transaction.stash_root, "backup pool transaction stash")],
    )


def copy_backup_slot(source: Path, destination: Path, label: str) -> None:
    require_private_directory(source, label)
    if lstat_exists(destination):
        fail(f"{label} destination already exists")
    shutil.copytree(source, destination, copy_function=shutil.copy2, symlinks=False)
    for path in destination.rglob("*"):
        info = stat_existing(path, f"{label} copied path {path.relative_to(destination)}")
        if info is None:
            continue
        if stat.S_ISDIR(info.st_mode):
            path.chmod(OWNER_DIRECTORY_MODE)
        elif stat.S_ISREG(info.st_mode):
            path.chmod(OWNER_FILE_MODE)
        else:
            fail(f"{label} copied unsupported path")
    destination.chmod(OWNER_DIRECTORY_MODE)
    fsync_directory(destination.parent, f"{label} destination parent")


def assert_backup_pool_has_no_residue(pool: Path) -> None:
    if not lstat_exists(pool):
        return
    residue_markers = (
        ".backup.tmp.",
        ".restore.tmp.",
        ".rollback.tmp.",
        ".install.tmp.",
        ".nddev-backup-pool.",
    )
    for path in pool.rglob("*"):
        if any(marker in path.name for marker in residue_markers):
            fail(f"backup pool contains transaction residue: {path.relative_to(pool)}")


def assert_no_transaction_residue(
    root: Path,
    label: str,
    *,
    allowed_roots: tuple[Path, ...] = (),
) -> None:
    if not lstat_exists(root):
        return
    residue_markers = (
        ".nddev-managed.",
        ".nddev-software.",
        ".nddev-software-remove.",
        ".nddev-backup-pool.",
        ".nddev-copilot-cli-stage.",
        ".nddev.tmp.",
        ".restore.tmp.",
        ".rollback.tmp.",
        ".install.tmp.",
        ".backup.tmp.",
    )
    for path in root.rglob("*"):
        if any(path == allowed or path_is_relative_to(path, allowed) for allowed in allowed_roots):
            continue
        if any(marker in path.name for marker in residue_markers):
            fail(f"{label} contains transaction residue: {path.relative_to(root)}")


def apply_backup(target: Path, state: dict[str, Any]) -> tuple[int, BackupPoolTransaction]:
    transaction = begin_backup_pool_transaction(target)
    pool = transaction.pool
    previous_pool = transaction.stashed_pool
    try:
        if lstat_exists(pool):
            fail("backup pool transaction current path already exists")
        pool.mkdir(mode=OWNER_DIRECTORY_MODE)
        pool.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(pool.parent, "backup pool")
        write_backup_pool_marker(target, pool)
        if previous_pool is not None:
            for slot in sorted(backup_slots_for_rotation(target, previous_pool), reverse=True):
                if slot == 9:
                    continue
                copy_backup_slot(
                    previous_pool / str(slot),
                    pool / str(slot + 1),
                    f"backup slot {slot}",
                )
        slot_dir = pool / "0"
        slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
        slot_dir.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(pool, "backup pool")
        backup_records: dict[str, dict[str, Any]] = {}
        managed_files = list(state["managed_files"])
        for raw_relative in [*managed_files, STAMP_NAME]:
            relative = Path(raw_relative)
            content, _ = read_regular_file(
                target / relative, f"managed file {relative}", owner_only=True
            )
            backup_records[str(relative)] = file_record(relative, content)
            destination = slot_dir / relative
            durable_replace_file(
                destination,
                content,
                OWNER_FILE_MODE,
                slot_dir,
                f"backup file {relative}",
                marker=".backup.tmp.",
            )
        envelope = {
            "schema_version": BACKUP_SCHEMA,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "slot": 0,
            "canonical_target": str(target),
            "source_setup_id": state["setup_id"],
            "source_profile_id": state.get("profile_id"),
            "managed_files": backup_records,
            "created_at": int(time.time()),
        }
        envelope_path = slot_dir / BACKUP_NAME
        durable_replace_file(
            envelope_path,
            canonical_json(envelope),
            OWNER_FILE_MODE,
            slot_dir,
            "backup slot 0 envelope",
            marker=".backup.tmp.",
        )
        refresh_backup_slot_numbers(target, pool)
        assert_backup_pool_has_no_residue(pool)
        load_backup(target, 0)
        return 0, transaction
    except BaseException:
        rollback_backup_pool_transaction(transaction)
        raise


def create_backup(target: Path, state: dict[str, Any]) -> int:
    slot, transaction = apply_backup(target, state)
    try:
        commit_backup_pool_transaction(transaction)
        assert_no_transaction_residue(target.parent, "backup parent")
    except BaseException:
        rollback_backup_pool_transaction(transaction)
        raise
    return slot


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
    durable_replace_file(
        marker_path,
        canonical_json(marker),
        OWNER_FILE_MODE,
        pool,
        "backup pool marker",
        marker=".backup.tmp.",
    )


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
    if schema_version != BACKUP_SCHEMA:
        fail(f"{label} has unsupported schema")
    require_exact_keys(envelope, BACKUP_KEYS_V3, label)
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
    if envelope["source_profile_id"] is not None:
        if not isinstance(envelope["source_profile_id"], str):
            fail(f"{label} source_profile_id must be a string or null")
        validate_profile_id(envelope["source_profile_id"])
    managed_files = envelope["managed_files"]
    records = validate_file_records(managed_files, f"{label} managed_files")
    if not isinstance(envelope["created_at"], int):
        fail(f"{label} created_at must be an integer")
    if str(Path(STAMP_NAME)) not in records:
        fail(f"{label} must include the setup stamp")
    for raw_relative in records:
        relative = Path(raw_relative)
        if relative.is_absolute() or ".." in relative.parts:
            fail(f"{label} contains an unsafe managed path")
        if relative not in ALL_KNOWN_MANAGED_PATHS:
            fail(f"{label} contains a path outside the managed backup envelope")


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
    records = validate_file_records(envelope["managed_files"], f"backup slot {slot} managed_files")
    allowed_files = {Path(BACKUP_NAME), *(Path(raw) for raw in records)}
    allowed_directories: set[Path] = {Path(".")}
    for relative in allowed_files:
        parent = relative.parent
        while parent != Path("."):
            allowed_directories.add(parent)
            parent = parent.parent
    physical_files: set[Path] = set()
    physical_directories: set[Path] = {Path(".")}
    for path in sorted(slot_dir.rglob("*")):
        relative = path.relative_to(slot_dir)
        info = stat_existing(path, f"backup slot {slot} physical path {relative}")
        if info is None:
            continue
        if stat.S_ISDIR(info.st_mode):
            physical_directories.add(relative)
            if relative not in allowed_directories:
                fail(f"backup slot {slot} contains an unexpected directory: {relative}")
        elif stat.S_ISREG(info.st_mode):
            physical_files.add(relative)
            if relative not in allowed_files:
                fail(f"backup slot {slot} contains an unexpected file: {relative}")
            if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
                fail(f"backup slot {slot} file mode mismatch: {relative}")
        else:
            fail(f"backup slot {slot} contains an unsupported path: {relative}")
    if physical_files != allowed_files:
        missing = sorted(str(path) for path in allowed_files - physical_files)
        extra = sorted(str(path) for path in physical_files - allowed_files)
        fail(f"backup slot {slot} physical payload mismatch missing={missing} extra={extra}")
    if not allowed_directories.issubset(physical_directories):
        missing_dirs = sorted(str(path) for path in allowed_directories - physical_directories)
        fail(f"backup slot {slot} physical directory mismatch missing={missing_dirs}")
    for raw_relative, record in records.items():
        relative = Path(raw_relative)
        if relative.is_absolute() or ".." in relative.parts:
            fail("backup envelope contains an unsafe managed path")
        content, _ = read_regular_file(
            slot_dir / relative, f"backup file {relative}", owner_only=True
        )
        assert_file_record_matches(relative, content, record, f"backup slot {slot}")
        files[relative] = content
    return envelope, files


def require_mutation_intent(operation: str, state: dict[str, Any]) -> None:
    state_name = state["state"]
    if operation == "install":
        if state_name == "managed":
            fail("install requires an absent or unmanaged target; use switch for a managed target")
        if state_name == "legacy-managed":
            fail(
                "install requires an absent or unmanaged target; run migrate for a legacy-managed target"
            )
        if state_name not in {"missing", "unmanaged"}:
            fail("install requires an absent or unmanaged target")
        return
    if operation == "switch":
        if state_name != "managed":
            fail("switch requires a current clean managed target")
        return
    if operation == "update":
        if state_name != "managed":
            fail("update requires a current clean managed target")
        return
    if operation == "migrate":
        if state_name != "legacy-managed":
            fail("migrate requires a legacy-managed target")
        return
    fail(f"unsupported setup operation: {operation}")


def desired_restore_state(files: dict[Path, bytes]) -> dict[Path, bytes | None]:
    desired: dict[Path, bytes | None] = dict(files)
    for relative in ALL_KNOWN_MANAGED_PATHS:
        desired.setdefault(relative, None)
    return desired


def plan_setup_mutation(
    canonical_target: Path,
    setup_id: str,
    profile_id: str,
    operation: str,
) -> dict[str, Any]:
    state = inspect_target(canonical_target)
    if state["state"] == "unmanaged" and any_managed_path_exists(canonical_target):
        fail("unmanaged target contains nddev-managed paths")
    require_mutation_intent(operation, state)
    effective_setup_id = state["setup_id"] if operation == "update" else setup_id
    effective_profile_id = state["profile_id"] if operation == "update" else profile_id
    existing_settings = read_existing_settings_if_managed(canonical_target, state)
    metadata, desired = render_setup(
        effective_setup_id,
        effective_profile_id,
        existing_settings=existing_settings,
    )
    stamp = bind_stamp(
        parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
    )
    desired[Path(STAMP_NAME)] = canonical_json(stamp)
    if state["state"] == "legacy-managed" and operation == "migrate":
        for relative in managed_paths_from_state(state):
            desired.setdefault(relative, None)
    return {
        "state": state,
        "effective_setup_id": effective_setup_id,
        "effective_profile_id": effective_profile_id,
        "metadata": metadata,
        "desired": desired,
        "changed": changed_paths(canonical_target, desired),
    }


def setup_mutation_result(
    canonical_target: Path,
    operation: str,
    plan: dict[str, Any],
    *,
    backup_slot: int | None,
    post_state: str,
    cleanup_pending: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": operation,
        "setup_id": plan["effective_setup_id"],
        "profile_id": plan["effective_profile_id"],
        "description": plan["metadata"]["description"],
        "target": str(canonical_target),
        "changed": plan["changed"],
        "backup_slot": backup_slot,
        "state": post_state,
        "cleanup_pending": cleanup_pending,
    }


def current_setup_noop_result(
    target: Path,
    setup_id: str,
    profile_id: str,
    operation: str,
) -> dict[str, Any] | None:
    if operation not in {"switch", "update"}:
        return None

    def read_noop(canonical_target: Path) -> dict[str, Any] | None:
        cleanup = cleanup_pending_status_for_mutation(canonical_target)
        if cleanup["cleanup_pending"]:
            return None
        plan = plan_setup_mutation(canonical_target, setup_id, profile_id, operation)
        if plan["changed"]:
            return None
        return setup_mutation_result(
            canonical_target,
            operation,
            plan,
            backup_slot=None,
            post_state=plan["state"]["state"],
        )

    with target_coordination(target) as canonical_target:
        return read_noop(canonical_target)


def mutate_setup(target: Path, setup_id: str, profile_id: str, operation: str) -> dict[str, Any]:
    if operation not in {"install", "switch", "update", "migrate"}:
        require_mutation_intent(operation, {"state": "missing"})
    noop = current_setup_noop_result(target, setup_id, profile_id, operation)
    if noop is not None:
        return noop
    create_parent = operation == "install"
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=create_parent) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        plan = plan_setup_mutation(canonical_target, setup_id, profile_id, operation)
        state = plan["state"]
        desired = plan["desired"]
        changed = plan["changed"]
        backup_slot: int | None = None
        managed_transaction: FileSetTransaction | None = None
        backup_transaction: BackupPoolTransaction | None = None
        cleanup_pending = False
        try:
            if state["state"] in {"managed", "legacy-managed"} and changed:
                backup_slot, backup_transaction = apply_backup(canonical_target, state)
            if changed:
                managed_transaction = apply_managed_state(canonical_target, desired, desired)
            post = inspect_target(canonical_target)
            cleanup_pending = commit_lifecycle_transactions(
                canonical_target,
                managed_transaction,
                backup_transaction,
            )
            managed_transaction = None
            backup_transaction = None
            if not cleanup_pending:
                assert_no_transaction_residue(canonical_target.parent, "setup lifecycle parent")
        except BaseException:
            rollback_error: BaseException | None = None
            if managed_transaction is not None:
                try:
                    rollback_file_set_transaction(managed_transaction)
                except BaseException as exc:
                    rollback_error = exc
            if backup_transaction is not None:
                try:
                    rollback_backup_pool_transaction(backup_transaction)
                except BaseException as exc:
                    if rollback_error is None:
                        rollback_error = exc
            if rollback_error is not None:
                raise rollback_error
            raise
    plan["changed"] = changed
    return setup_mutation_result(
        canonical_target,
        operation,
        plan,
        backup_slot=backup_slot,
        post_state=post["state"],
        cleanup_pending=cleanup_pending,
    )


def plan_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    def read_plan(canonical_target: Path) -> dict[str, Any]:
        cleanup = cleanup_pending_status(canonical_target)
        state = inspect_target(canonical_target)
        existing_settings = read_existing_settings_if_managed(canonical_target, state)
        _metadata, desired = render_setup(
            setup_id,
            profile_id,
            existing_settings=existing_settings,
        )
        if state["state"] == "managed":
            stamp = bind_stamp(
                parse_json_object(desired[Path(STAMP_NAME)], "desired stamp"), canonical_target
            )
            desired[Path(STAMP_NAME)] = canonical_json(stamp)
            changed = changed_paths(canonical_target, desired)
            operation = (
                "switch"
                if state.get("setup_id") != setup_id or state.get("profile_id") != profile_id
                else "current"
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
        result = {
            "ok": True,
            "operation": operation,
            "command": operation if operation in {"install", "switch", "migrate"} else None,
            "setup_id": setup_id,
            "profile_id": profile_id,
            "target": str(canonical_target),
            "state": state["state"],
            "mutates": False,
            "backup_required": backup_required,
            "changed": changed,
        }
        result.update(cleanup)
        return result

    return coordinated_target_read(target, read_plan)


def remove_setup(target: Path) -> dict[str, Any]:
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=False) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        state = inspect_target(canonical_target)
        if state["state"] not in {"managed", "legacy-managed"}:
            fail("target is not managed by nddev-github-copilot-cli-app")
        paths = managed_paths_from_state(state)
        desired = {relative: None for relative in paths}
        changed = changed_paths(canonical_target, desired)
        managed_transaction: FileSetTransaction | None = None
        backup_transaction: BackupPoolTransaction | None = None
        cleanup_pending = False
        try:
            if changed:
                backup_slot, backup_transaction = apply_backup(canonical_target, state)
            else:
                backup_slot = None
            if changed:
                managed_transaction = apply_managed_state(canonical_target, desired, desired)
            cleanup_pending = commit_lifecycle_transactions(
                canonical_target,
                managed_transaction,
                backup_transaction,
            )
            managed_transaction = None
            backup_transaction = None
            if not cleanup_pending:
                assert_no_transaction_residue(canonical_target.parent, "setup remove parent")
        except BaseException:
            rollback_error: BaseException | None = None
            if managed_transaction is not None:
                try:
                    rollback_file_set_transaction(managed_transaction)
                except BaseException as exc:
                    rollback_error = exc
            if backup_transaction is not None:
                try:
                    rollback_backup_pool_transaction(backup_transaction)
                except BaseException as exc:
                    if rollback_error is None:
                        rollback_error = exc
            if rollback_error is not None:
                raise rollback_error
            raise
    return {
        "ok": True,
        "operation": "remove",
        "target": str(canonical_target),
        "removed_setup_id": state["setup_id"],
        "removed_profile_id": state.get("profile_id"),
        "backup_slot": backup_slot,
        "changed": changed,
        "cleanup_pending": cleanup_pending,
    }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=False) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        state = inspect_target(canonical_target)
        if state["state"] not in {"managed", "legacy-managed"}:
            fail("target is not managed by nddev-github-copilot-cli-app")
        envelope, files = load_backup(canonical_target, slot)
        desired = desired_restore_state(files)
        changed = changed_paths(canonical_target, desired)
        managed_transaction: FileSetTransaction | None = None
        cleanup_pending = False
        try:
            if changed:
                managed_transaction = apply_managed_state(
                    canonical_target,
                    desired,
                    desired,
                    marker=".restore.tmp.",
                )
            post = inspect_target(canonical_target)
            if managed_transaction is not None:
                cleanup_pending = commit_lifecycle_transactions(
                    canonical_target,
                    managed_transaction,
                    None,
                )
                managed_transaction = None
            if not cleanup_pending:
                assert_no_transaction_residue(canonical_target.parent, "setup restore parent")
        except BaseException:
            if managed_transaction is not None:
                rollback_file_set_transaction(managed_transaction)
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
        "changed": changed,
        "cleanup_pending": cleanup_pending,
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


def detect_supported_host(baseline: dict[str, Any]) -> dict[str, Any]:
    system = sys.platform
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        fail(f"unsupported architecture for Copilot CLI install: {platform.machine()}")
    if system == "darwin":
        host_id = f"macos-{arch}"
    elif system.startswith("linux"):
        libc_name = platform.libc_ver()[0].lower()
        if libc_name == "musl":
            fail("unsupported platform for Copilot CLI install: linux musl")
        if libc_name != "glibc":
            fail("unsupported platform for Copilot CLI install: linux glibc required")
        release = linux_os_release()
        if release.get("ID") != "ubuntu":
            fail("unsupported Linux distribution for Copilot CLI install: Ubuntu glibc required")
        host_id = f"ubuntu-glibc-{arch}"
    else:
        fail(f"unsupported platform for Copilot CLI install: {system}")
    support = baseline.get("platform_support")
    if not isinstance(support, dict):
        fail("baseline platform support must be an object")
    host_assets = support.get("host_assets")
    if not isinstance(host_assets, dict):
        fail("baseline platform host_assets must be an object")
    asset_name = host_assets.get(host_id)
    if not isinstance(asset_name, str):
        fail(f"baseline does not declare supported host {host_id}")
    assets = baseline.get("assets")
    if not isinstance(assets, dict) or asset_name not in assets:
        fail(f"baseline does not declare asset {asset_name}")
    asset = assets[asset_name]
    if not isinstance(asset, dict):
        fail(f"baseline asset {asset_name} must be an object")
    return {
        "host_id": host_id,
        "asset_name": asset_name,
        "asset": asset,
        "system": system,
        "architecture": arch,
    }


def detect_platform_asset(baseline: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    selected = detect_supported_host(load_baseline() if baseline is None else baseline)
    return str(selected["asset_name"]), selected["asset"]


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


def verify_release_metadata(
    baseline: dict[str, Any], asset_name: str, asset: dict[str, Any]
) -> dict[str, Any]:
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
    if parsed_url.netloc.lower() != "github.com" or not parsed_url.path.startswith(
        "/github/copilot-cli/releases/download/"
    ):
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
        "artifact_verification": {
            "size_verified": True,
            "sha256_verified": False,
            "method": "head",
        },
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
        runtime_fail(
            f"{label} is missing", code=f"{label_slug(label)}_missing", repairable=repairable
        )
    try:
        require_current_owner(info, label)
    except CopilotCliSetupError as exc:
        runtime_fail(str(exc), code=f"{label_slug(label)}_owner", repairable=False)
    return info


def label_slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def runtime_private_directory(
    path: Path, target: Path, label: str, *, repairable: bool
) -> os.stat_result:
    info = runtime_lstat(path, target, label, repairable=repairable)
    if stat.S_ISLNK(info.st_mode):
        runtime_fail(
            f"{label} must not be a symlink", code=f"{label_slug(label)}_symlink", repairable=False
        )
    if not stat.S_ISDIR(info.st_mode):
        runtime_fail(
            f"{label} must be a directory", code=f"{label_slug(label)}_type", repairable=False
        )
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        runtime_fail(f"{label} must be private", code=f"{label_slug(label)}_mode", repairable=False)
    return info


def create_or_require_private_runtime_directory(
    target: Path,
    relative: Path,
    label: str,
) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        fail(f"{label} path is outside the managed target")
    target_info = runtime_private_directory(target, target, "target", repairable=False)
    try:
        target_resolved = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        fail(f"target could not be resolved safely: {exc}")
    current = target
    for index, part in enumerate(relative.parts):
        if part in {"", ".", ".."}:
            fail(f"{label} path is outside the managed target")
        component = current / part
        component_label = label if index == len(relative.parts) - 1 else f"{label} parent"
        parent_info = runtime_private_directory(
            current,
            target,
            f"{component_label} parent directory",
            repairable=False,
        )
        info = stat_existing(component, component_label)
        if info is None:
            created = False
            try:
                component.mkdir(mode=OWNER_DIRECTORY_MODE)
                created = True
                component.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(current, f"{component_label} parent")
            except BaseException:
                cleanup_error: BaseException | None = None
                if created and lstat_exists(component):
                    try:
                        current_info = stat_existing(component, component_label)
                        if (
                            current_info is not None
                            and stat.S_ISDIR(current_info.st_mode)
                            and owner_of(current_info) == current_owner()
                        ):
                            component.rmdir()
                            fsync_directory(current, f"{component_label} rollback parent")
                    except BaseException as exc:
                        cleanup_error = exc
                if cleanup_error is not None:
                    raise cleanup_error
                raise
            info = runtime_private_directory(
                component,
                target,
                component_label,
                repairable=False,
            )
        else:
            require_current_owner(info, component_label)
            if stat.S_ISLNK(info.st_mode):
                runtime_fail(
                    f"{component_label} must not be a symlink",
                    code=f"{label_slug(component_label)}_symlink",
                    repairable=False,
                )
            if not stat.S_ISDIR(info.st_mode):
                runtime_fail(
                    f"{component_label} must be a directory",
                    code=f"{label_slug(component_label)}_type",
                    repairable=False,
                )
            if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                runtime_fail(
                    f"{component_label} must be private",
                    code=f"{label_slug(component_label)}_mode",
                    repairable=False,
                )
        refreshed_parent = runtime_private_directory(
            current,
            target,
            f"{component_label} parent directory",
            repairable=False,
        )
        if identity_of(refreshed_parent) != identity_of(parent_info):
            fail_concurrent(f"{component_label} parent changed while preparing runtime")
        refreshed = runtime_private_directory(
            component,
            target,
            component_label,
            repairable=False,
        )
        if identity_of(refreshed) != identity_of(info):
            fail_concurrent(f"{component_label} changed while preparing runtime")
        try:
            resolved = component.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            fail(f"{component_label} could not be resolved safely: {exc}")
        if resolved != target_resolved and not path_is_relative_to(resolved, target_resolved):
            runtime_fail(
                f"{component_label} escaped managed target",
                code=f"{label_slug(component_label)}_escaped_target",
                repairable=False,
            )
        current = component
    final_target = runtime_private_directory(target, target, "target", repairable=False)
    if identity_of(final_target) != identity_of(target_info):
        fail_concurrent("target changed while preparing runtime")
    return current


def runtime_regular_file(
    path: Path, target: Path, label: str, *, repairable: bool
) -> os.stat_result:
    info = runtime_lstat(path, target, label, repairable=repairable)
    if stat.S_ISLNK(info.st_mode):
        runtime_fail(
            f"{label} must not be a symlink", code=f"{label_slug(label)}_symlink", repairable=False
        )
    if not stat.S_ISREG(info.st_mode):
        runtime_fail(
            f"{label} must be a regular file", code=f"{label_slug(label)}_type", repairable=False
        )
    if info.st_nlink != 1:
        runtime_fail(
            f"{label} must not have hard-link aliases",
            code=f"{label_slug(label)}_hardlink",
            repairable=False,
        )
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
        runtime_fail(
            f"{label} could not be opened safely: {exc}",
            code=f"{label_slug(label)}_open",
            repairable=False,
        )
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(info):
            fail_concurrent(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            runtime_fail(
                f"{label} changed to an unsafe file",
                code=f"{label_slug(label)}_type",
                repairable=False,
            )
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
                runtime_fail(
                    f"{label} exceeds the {max_bytes}-byte size limit",
                    code=f"{label_slug(label)}_size",
                    repairable=False,
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = runtime_regular_file(path, target, label, repairable=False)
    if identity_of(after) != identity_of(info) or identity_of(final) != identity_of(info):
        fail_concurrent(f"{label} changed while it was being read")
    return digest.hexdigest()


def protect_directory_read_execute(path: Path, target: Path, label: str) -> ProtectedDirectory:
    if target not in path.parents and path != target:
        fail(f"{label} escaped target")
    snapshot = capture_directory_snapshot(path, label)
    info = require_owner_directory_mode(
        path,
        label,
        {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE},
    )
    original_mode = stat.S_IMODE(info.st_mode)
    if original_mode != LOCK_HELD_DIRECTORY_MODE:
        path.chmod(LOCK_HELD_DIRECTORY_MODE)
    protected = require_owner_directory_mode(path, label, {LOCK_HELD_DIRECTORY_MODE})
    if identity_of(protected) != identity_of(info):
        fail_concurrent(f"{label} changed while it was being protected")
    return ProtectedDirectory(path=path, snapshot=snapshot)


def restore_protected_directories(protected: list[ProtectedDirectory]) -> None:
    for item in reversed(protected):
        info = require_owner_directory_mode(
            item.path,
            f"protected directory {item.path}",
            {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE},
        )
        if item.snapshot.device is not None and info.st_dev != item.snapshot.device:
            fail_concurrent(f"protected directory changed before restore: {item.path}")
        if item.snapshot.inode is not None and info.st_ino != item.snapshot.inode:
            fail_concurrent(f"protected directory changed before restore: {item.path}")
        restore_directory_snapshot(
            item.path,
            item.snapshot,
            f"protected directory {item.path}",
        )


def protect_launch_handoff_paths(target: Path) -> list[ProtectedDirectory]:
    handoff_paths = [
        copilot_executable(target).parent,
        software_manifest_path(target).parent,
    ]
    expected_paths = {target / relative for relative in IMMUTABLE_LAUNCH_DIRECTORIES}
    for path in handoff_paths:
        if path not in expected_paths:
            fail("launch handoff protection is limited to dedicated immutable artifact directories")
    return [
        protect_directory_read_execute(handoff_paths[0], target, "Copilot CLI executable parent"),
        protect_directory_read_execute(handoff_paths[1], target, "software receipt parent"),
    ]


def current_software_metadata(target: Path) -> dict[str, Any]:
    runtime_private_directory(target, target, "target", repairable=False)
    executable = copilot_executable(target)
    manifest_path = software_manifest_path(target)
    binary_info = runtime_regular_file(
        executable, target, "Copilot CLI executable", repairable=True
    )
    if stat.S_IMODE(binary_info.st_mode) != OWNER_DIRECTORY_MODE or not os.access(
        executable, os.X_OK
    ):
        runtime_fail(
            "Copilot CLI executable mode is unsafe",
            code="copilot_executable_mode",
            repairable=False,
        )
    receipt_info = runtime_regular_file(manifest_path, target, "software receipt", repairable=True)
    if not is_owner_only_file(receipt_info):
        runtime_fail(
            "software receipt mode is unsafe", code="software_receipt_mode", repairable=False
        )
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
            runtime_fail(
                f"software receipt {key} does not match the baseline",
                code=f"software_receipt_{key}",
                repairable=True,
            )
    artifact = receipt.get("artifact")
    asset_name, asset = detect_platform_asset()
    expected_artifact = {
        "name": asset_name,
        "url": asset["browser_download_url"],
        "sha256": asset["sha256"],
        "size": asset["size"],
    }
    if artifact != expected_artifact:
        runtime_fail(
            "software receipt artifact does not match the baseline",
            code="software_receipt_artifact",
            repairable=True,
        )
    binary_sha = sha256_runtime_regular_file(
        executable,
        target,
        "Copilot CLI executable",
        binary_info,
        max_bytes=SOFTWARE_FILE_MAX_BYTES,
    )
    if receipt.get("binary_sha256") != binary_sha:
        runtime_fail(
            "software receipt binary SHA256 does not match target executable",
            code="software_receipt_binary_sha256",
            repairable=True,
        )
    if receipt.get("binary_size") != binary_info.st_size:
        runtime_fail(
            "software receipt binary size does not match target executable",
            code="software_receipt_binary_size",
            repairable=True,
        )
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
            "verification": "O_NOFOLLOW-fd-sha256",
        },
        "receipt_sha256": sha256_file_bounded(
            manifest_path, max_bytes=METADATA_MAX_BYTES, label="software receipt"
        ),
    }


def require_launch_executable_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before.get("binary") != after.get("binary"):
        fail_concurrent("Copilot CLI executable changed before launch")


def _software_status_locked(canonical_target: Path) -> dict[str, Any]:
    if not lstat_exists(canonical_target):
        return {
            "ok": True,
            "state": "absent",
            "installed": False,
            "current": False,
            "target": str(canonical_target),
            "version": None,
            "executable": str(copilot_executable(canonical_target)),
        }
    runtime_private_directory(canonical_target, canonical_target, "target", repairable=False)
    if not lstat_exists(copilot_executable(canonical_target)) and not lstat_exists(
        software_manifest_path(canonical_target)
    ):
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


def software_status(target: Path) -> dict[str, Any]:
    detect_supported_host(load_baseline())

    def read_status(canonical_target: Path) -> dict[str, Any]:
        result = _software_status_locked(canonical_target)
        result.update(cleanup_pending_status(canonical_target))
        return result

    return coordinated_target_read(target, read_status)


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
    durable_replace_file(
        installer,
        data,
        0o700,
        stage,
        "stage installer",
        marker=".install.tmp.",
    )
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


def install_software_to_stage(
    stage: Path,
    baseline: dict[str, Any],
    platform_preflight: dict[str, Any],
) -> dict[str, Any]:
    asset_name = str(platform_preflight["asset_name"])
    asset = platform_preflight["asset"]
    installer_url, expected_installer_sha, expected_installer_size = installer_source(baseline)
    installer_bytes = read_url_bounded(
        installer_url, max_bytes=INSTALLER_MAX_BYTES, label="Copilot CLI installer"
    )
    if len(installer_bytes) != expected_installer_size:
        fail("Copilot CLI installer size does not match the pinned baseline")
    if sha256_bytes(installer_bytes) != expected_installer_sha:
        fail("Copilot CLI installer SHA256 does not match the pinned baseline")
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
        "binary_sha256": sha256_file_bounded(
            staged_binary, max_bytes=SOFTWARE_FILE_MAX_BYTES, label="staged Copilot CLI executable"
        ),
        "binary_size": binary_info.st_size,
        "installer": {
            "url": baseline["installer"]["url"],
            "sha256": expected_installer_sha,
            "size": expected_installer_size,
        },
        "release": baseline["release"],
        "checksums": release_metadata["checksums"],
        "artifact": release_metadata["asset"],
        "artifact_verification": release_metadata["artifact_verification"],
        "installer_output_sha256": sha256_bytes(output.encode("utf-8")),
    }


def capture_file_snapshot(
    path: Path,
    label: str,
    *,
    allowed_modes: set[int] | None = None,
) -> FileSnapshot:
    if not lstat_exists(path):
        return FileSnapshot(exists=False)
    data, info = read_regular_file(path, label, owner_only=False, max_bytes=SOFTWARE_FILE_MAX_BYTES)
    if allowed_modes is not None and stat.S_IMODE(info.st_mode) not in allowed_modes:
        fail(f"{label} mode is not an allowed rollback snapshot mode")
    return FileSnapshot(
        exists=True,
        data=data,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
    )


def capture_directory_snapshot(path: Path, label: str) -> DirectorySnapshot:
    info = stat_existing(path, label)
    if info is None:
        return DirectorySnapshot(exists=False)
    require_current_owner(info, label)
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return DirectorySnapshot(
        exists=True,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        size=info.st_size,
    )


def restore_directory_snapshot(
    path: Path,
    snapshot: DirectorySnapshot,
    label: str,
    *,
    verify_size: bool = True,
) -> None:
    if not snapshot.exists:
        if lstat_exists(path):
            fail(f"{label} rollback expected absent directory")
        return
    if snapshot.mode is None or snapshot.mtime_ns is None:
        fail(f"{label} rollback directory snapshot is invalid")
    info = require_directory(path, label)
    if snapshot.device is not None and info.st_dev != snapshot.device:
        fail(f"{label} rollback directory device mismatch")
    if snapshot.inode is not None and info.st_ino != snapshot.inode:
        fail(f"{label} rollback directory inode mismatch")
    if stat.S_IMODE(info.st_mode) != snapshot.mode:
        path.chmod(snapshot.mode)
        info = require_directory(path, label)
        if snapshot.device is not None and info.st_dev != snapshot.device:
            fail(f"{label} rollback directory device mismatch")
        if snapshot.inode is not None and info.st_ino != snapshot.inode:
            fail(f"{label} rollback directory inode mismatch")
    os.utime(path, ns=(info.st_atime_ns, snapshot.mtime_ns))
    final = require_directory(path, label)
    if snapshot.device is not None and final.st_dev != snapshot.device:
        fail(f"{label} rollback directory device mismatch")
    if snapshot.inode is not None and final.st_ino != snapshot.inode:
        fail(f"{label} rollback directory inode mismatch")
    if stat.S_IMODE(final.st_mode) != snapshot.mode:
        fail(f"{label} rollback directory mode mismatch")
    if final.st_mtime_ns != snapshot.mtime_ns:
        fail(f"{label} rollback directory mtime mismatch")
    if verify_size and snapshot.size is not None and final.st_size != snapshot.size:
        fail(f"{label} rollback directory size mismatch")


def restore_absolute_directory_snapshots(
    snapshots: dict[Path, DirectorySnapshot],
    label: str,
) -> None:
    for path, snapshot in sorted(
        snapshots.items(),
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        restore_directory_snapshot(path, snapshot, f"{label} directory {path}")


def assert_file_snapshot_postcondition(path: Path, snapshot: FileSnapshot, label: str) -> None:
    if not snapshot.exists:
        if lstat_exists(path):
            fail(f"{label} rollback expected absent path")
        return
    if snapshot.data is None or snapshot.mode is None:
        fail(f"{label} rollback snapshot is invalid")
    data, info = read_regular_file(path, label, owner_only=False, max_bytes=SOFTWARE_FILE_MAX_BYTES)
    if data != snapshot.data:
        fail(f"{label} rollback content mismatch")
    if stat.S_IMODE(info.st_mode) != snapshot.mode:
        fail(f"{label} rollback mode mismatch")
    if snapshot.device is not None and info.st_dev != snapshot.device:
        fail(f"{label} rollback device mismatch")
    if snapshot.inode is not None and info.st_ino != snapshot.inode:
        fail(f"{label} rollback inode mismatch")
    if snapshot.mtime_ns is not None and info.st_mtime_ns != snapshot.mtime_ns:
        fail(f"{label} rollback mtime mismatch")


def directory_paths_for_files(relatives: tuple[Path, ...]) -> tuple[Path, ...]:
    directories: set[Path] = {Path(".")}
    for relative in relatives:
        parent = relative.parent
        while parent != Path("."):
            directories.add(parent)
            parent = parent.parent
        directories.add(relative.parent)
    return tuple(sorted(directories, key=lambda item: len(item.parts)))


def begin_file_set_transaction(
    root: Path,
    relatives: tuple[Path, ...],
    label: str,
    *,
    allowed_modes: dict[Path, set[int]],
) -> FileSetTransaction:
    unique_relatives = tuple(dict.fromkeys(relatives))
    parent_directories: dict[Path, DirectorySnapshot] = {}
    stash_root = transaction_stash_root(root, label, parent_directories)
    directories = {
        relative: capture_directory_snapshot(root / relative, f"{label} directory {relative}")
        for relative in directory_paths_for_files(unique_relatives)
    }
    snapshots: dict[Path, FileSnapshot] = {}
    transaction = FileSetTransaction(
        root=root,
        stash_root=stash_root,
        files=snapshots,
        directories=directories,
        parent_directories=parent_directories,
    )
    try:
        for relative in unique_relatives:
            if relative.is_absolute() or ".." in relative.parts:
                fail(f"unsafe {label} path: {relative}")
            path = root / relative
            snapshot = capture_file_snapshot(
                path,
                f"{label} file {relative}",
                allowed_modes=allowed_modes.get(relative),
            )
            snapshots[relative] = snapshot
            if not snapshot.exists:
                continue
            stash_path = stash_root / relative
            stash_path.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
            stash_path.parent.chmod(OWNER_DIRECTORY_MODE)
            os.replace(path, stash_path)
            fsync_directory(path.parent, f"{label} preserve source parent {relative}")
            fsync_directory(stash_path.parent, f"{label} preserve stash parent {relative}")
        return transaction
    except BaseException:
        rollback_file_set_transaction(transaction)
        raise


def restore_directory_metadata(transaction: FileSetTransaction, label: str) -> None:
    for relative, snapshot in sorted(
        transaction.directories.items(),
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        directory = transaction.root / relative
        if not snapshot.exists:
            if relative != Path(".") and lstat_exists(directory):
                directory.rmdir()
                fsync_directory(directory.parent, f"{label} directory remove parent {relative}")
            restore_directory_snapshot(directory, snapshot, f"{label} directory {relative}")
            continue
        restore_directory_snapshot(directory, snapshot, f"{label} directory {relative}")


def rollback_file_set_transaction(transaction: FileSetTransaction) -> None:
    rollback_error: BaseException | None = None
    for relative, snapshot in transaction.files.items():
        path = transaction.root / relative
        stash_path = transaction.stash_root / relative
        try:
            if snapshot.exists:
                restored = False
                if lstat_exists(path):
                    try:
                        assert_file_snapshot_postcondition(
                            path,
                            snapshot,
                            f"rollback original file {relative}",
                        )
                        restored = True
                    except BaseException:
                        require_regular_file(path, f"rollback current file {relative}")
                        retrying_unlink(path, f"rollback current file {relative}")
                if not restored:
                    if not lstat_exists(stash_path):
                        fail(f"rollback original file {relative} sidecar is missing")
                    ensure_real_parent(path, transaction.root)
                    retrying_replace(stash_path, path, f"rollback original file {relative}")
                    fsync_directory(path.parent, f"rollback original file {relative} parent")
                    assert_file_snapshot_postcondition(
                        path,
                        snapshot,
                        f"rollback original file {relative}",
                    )
            elif lstat_exists(path):
                require_regular_file(path, f"rollback created file {relative}")
                retrying_unlink(path, f"rollback created file {relative}")
        except BaseException as exc:
            if rollback_error is None:
                rollback_error = exc
    try:
        restore_directory_metadata(transaction, "rollback")
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    try:
        remove_private_tree_verified(transaction.stash_root, "rollback stash")
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    try:
        restore_absolute_directory_snapshots(transaction.parent_directories, "rollback parent")
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    if rollback_error is not None:
        raise rollback_error


def commit_file_set_transaction(transaction: FileSetTransaction) -> None:
    commit_transaction_stash(transaction.stash_root, "transaction stash")


def prune_empty_software_dirs(target: Path) -> None:
    snapshots: dict[Path, DirectorySnapshot] = {}
    for directory in (target / "software", target / "bin"):
        try:
            snapshots.setdefault(
                target,
                capture_directory_snapshot(target, "target before empty software dir prune"),
            )
            directory.rmdir()
            fsync_directory(target, f"empty software directory prune parent {directory.name}")
        except FileNotFoundError:
            continue
        except OSError:
            continue
    restore_absolute_directory_snapshots(snapshots, "empty software directory prune")


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


def software_allowed_modes(target: Path) -> dict[Path, set[int]]:
    return {
        relative: {expected_mode}
        for relative, _path, _label, expected_mode in software_remove_paths(target)
    }


def publish_stage_software(target: Path, install_result: dict[str, Any]) -> None:
    executable = copilot_executable(target)
    receipt_path = software_manifest_path(target)
    ensure_real_parent(executable, target)
    ensure_real_parent(receipt_path, target)
    staged = Path(install_result["staged_binary"])
    content, _ = read_regular_file(
        staged,
        "staged Copilot CLI executable",
        max_bytes=SOFTWARE_FILE_MAX_BYTES,
    )
    durable_replace_file(
        executable,
        content,
        0o700,
        target,
        "Copilot CLI executable",
        marker=".install.tmp.",
    )
    receipt = write_software_receipt(target, install_result)
    durable_replace_file(
        receipt_path,
        canonical_json(receipt),
        OWNER_FILE_MODE,
        target,
        "software receipt",
        marker=".install.tmp.",
    )


def persist_stage_software(target: Path, install_result: dict[str, Any]) -> None:
    transaction = begin_file_set_transaction(
        target,
        tuple(relative for relative, _path, _label, _mode in software_remove_paths(target)),
        "software",
        allowed_modes=software_allowed_modes(target),
    )
    try:
        publish_stage_software(target, install_result)
        current_software_metadata(target)
        commit_file_set_transaction(transaction)
        assert_no_transaction_residue(target.parent, "software parent")
    except BaseException:
        rollback_file_set_transaction(transaction)
        raise


def software_plan(target: Path) -> dict[str, Any]:
    detect_supported_host(load_baseline())

    def read_plan(canonical_target: Path) -> dict[str, Any]:
        cleanup = cleanup_pending_status(canonical_target)
        status = _software_status_locked(canonical_target)
        action = "none"
        if status["state"] == "absent":
            action = "install"
        elif status["state"] == "partial":
            action = "repair" if status.get("repairable") else "blocked"
        result = {
            "ok": True,
            "target": str(canonical_target),
            "mutates": False,
            "action": action,
            "software": status,
        }
        result.update(cleanup)
        return result

    return coordinated_target_read(target, read_plan)


def software_remove_paths(target: Path) -> tuple[tuple[Path, Path, str, int], ...]:
    return (
        (Path("bin") / COMMAND_NAME, copilot_executable(target), "Copilot CLI executable", 0o700),
        (
            Path("software") / "copilot-cli.json",
            software_manifest_path(target),
            "software receipt",
            OWNER_FILE_MODE,
        ),
    )


def software_remove_changed_paths(target: Path) -> list[str]:
    return [
        str(relative)
        for relative, path, _label, _mode in software_remove_paths(target)
        if lstat_exists(path)
    ]


def assert_software_removed_postconditions(target: Path, changed: list[str]) -> None:
    for relative, path, _label, _mode in software_remove_paths(target):
        if str(relative) in changed and lstat_exists(path):
            fail(f"software remove postcondition expected absent path: {relative}")


def unlink_software_file(path: Path, label: str, expected_mode: int) -> None:
    info = require_regular_file(path, label, owner_only=False, max_bytes=SOFTWARE_FILE_MAX_BYTES)
    if stat.S_IMODE(info.st_mode) != expected_mode:
        fail(f"{label} mode is not manager-owned")
    path.unlink()
    fsync_directory(path.parent, f"{label} remove parent")


def remove_software(target: Path) -> dict[str, Any]:
    detect_supported_host(load_baseline())
    with target_coordination(target) as canonical_target:
        drain_cleanup_before_mutation(canonical_target)
        status = _software_status_locked(canonical_target)
        if status["state"] == "absent":
            return {
                "ok": True,
                "operation": "software-remove",
                "changed": [],
                "target": str(canonical_target),
                "software": status,
                "cleanup_pending": False,
            }
        with target_file_lock(canonical_target, create_target=False):
            drain_cleanup_before_mutation(canonical_target)
            status = _software_status_locked(canonical_target)
            if status["state"] == "absent":
                return {
                    "ok": True,
                    "operation": "software-remove",
                    "changed": [],
                    "target": str(canonical_target),
                    "software": status,
                    "cleanup_pending": False,
                }
            if status["state"] == "partial" and not status.get("repairable"):
                fail(status.get("error", "Copilot CLI software is unsafe"))
            changed = software_remove_changed_paths(canonical_target)
            transaction: FileSetTransaction | None = begin_file_set_transaction(
                canonical_target,
                tuple(
                    relative
                    for relative, _path, _label, _expected_mode in software_remove_paths(
                        canonical_target
                    )
                ),
                "software-remove",
                allowed_modes=software_allowed_modes(canonical_target),
            )
            cleanup_pending = False
            try:
                for _relative, path, label, expected_mode in software_remove_paths(
                    canonical_target
                ):
                    if lstat_exists(path):
                        unlink_software_file(path, label, expected_mode)
                assert_software_removed_postconditions(canonical_target, changed)
                new_status = _software_status_locked(canonical_target)
                assert_no_transaction_residue(
                    canonical_target.parent,
                    "software remove parent",
                    allowed_roots=(transaction.stash_root,),
                )
                cleanup_pending = commit_lifecycle_transactions(canonical_target, transaction, None)
                transaction = None
            except BaseException:
                if transaction is not None:
                    rollback_file_set_transaction(transaction)
                raise
    return {
        "ok": True,
        "operation": "software-remove",
        "changed": changed,
        "target": str(canonical_target),
        "software": new_status,
        "cleanup_pending": cleanup_pending,
    }


def current_software_noop_result(target: Path, operation: str) -> dict[str, Any] | None:
    if operation not in {"software-install", "software-update"}:
        return None

    def read_current(canonical_target: Path) -> dict[str, Any] | None:
        cleanup = cleanup_pending_status_for_mutation(canonical_target)
        if cleanup["cleanup_pending"]:
            return None
        status = _software_status_locked(canonical_target)
        if status["state"] != "installed":
            return None
        return {
            "ok": True,
            "operation": operation,
            "changed": False,
            "target": str(canonical_target),
            "software": status,
            "cleanup_pending": False,
        }

    with target_coordination(target) as canonical_target:
        return read_current(canonical_target)


def install_or_update_cli(target: Path, *, operation: str) -> dict[str, Any]:
    baseline = load_baseline()
    platform_preflight = detect_supported_host(baseline)
    noop = current_software_noop_result(target, operation)
    if noop is not None:
        return noop
    create_parent = operation == "software-install"
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=create_parent) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        status = _software_status_locked(canonical_target)
        if operation == "software-install":
            if status["state"] == "installed":
                return {
                    "ok": True,
                    "operation": operation,
                    "changed": False,
                    "target": str(canonical_target),
                    "software": status,
                    "cleanup_pending": False,
                }
            if status["state"] == "partial":
                fail("Copilot CLI software is partial; run software-update to repair it")
        else:
            if status["state"] == "installed":
                return {
                    "ok": True,
                    "operation": operation,
                    "changed": False,
                    "target": str(canonical_target),
                    "software": status,
                    "cleanup_pending": False,
                }
            if status["state"] == "absent":
                fail("Copilot CLI software is not installed; run software-install")
            if status["state"] == "partial" and not status.get("repairable"):
                fail(status.get("error", "Copilot CLI software is unsafe"))
        locked.transaction.remember_directory(canonical_target.parent, "software lifecycle parent")
        transaction = begin_file_set_transaction(
            canonical_target,
            tuple(
                relative
                for relative, _path, _label, _expected_mode in software_remove_paths(
                    canonical_target
                )
            ),
            "software",
            allowed_modes=software_allowed_modes(canonical_target),
        )
        stage: Path | None = None
        cleanup_pending = False
        try:
            locked.transaction.remember_directory(
                canonical_target.parent, "software install stage parent"
            )
            stage = Path(
                tempfile.mkdtemp(
                    dir=canonical_target.parent,
                    prefix=f".{canonical_target.name}.nddev-copilot-cli-stage.",
                )
            )
            stage.chmod(OWNER_DIRECTORY_MODE)
            install_result = install_software_to_stage(stage, baseline, platform_preflight)
            publish_stage_software(canonical_target, install_result)
            remove_private_tree_verified(stage, "software install stage")
            stage = None
            current_software_metadata(canonical_target)
            cleanup_pending = commit_lifecycle_transactions(canonical_target, transaction, None)
            transaction = None
            if not cleanup_pending:
                assert_no_transaction_residue(canonical_target.parent, "software install parent")
        except BaseException:
            rollback_error: BaseException | None = None
            if stage is not None:
                try:
                    remove_private_tree_verified(stage, "software install stage")
                except BaseException as exc:
                    if rollback_error is None:
                        rollback_error = exc
            if transaction is not None:
                try:
                    rollback_file_set_transaction(transaction)
                except BaseException as exc:
                    if rollback_error is None:
                        rollback_error = exc
            if rollback_error is not None:
                raise rollback_error
            raise
        new_status = _software_status_locked(canonical_target)
    return {
        "ok": True,
        "operation": operation,
        "changed": True,
        "target": str(canonical_target),
        "software": new_status,
        "cleanup_pending": cleanup_pending,
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
    actual_skills = sorted(path.name for path in skill_root.iterdir() if path.is_dir())
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


def _builder_status_locked(
    canonical_target: Path,
    source_files: dict[Path, bytes] | None = None,
) -> dict[str, Any]:
    if source_files is None:
        source_files = validate_builder_toolkit_source()
    if not lstat_exists(canonical_target):
        return {
            "ok": True,
            "target": str(canonical_target),
            "installed": False,
            "current": False,
            "state": "absent",
            "plugin": BUILDER_PLUGIN_SPEC,
        }
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
        str(path) for path, content in source_files.items() if installed_files.get(path) != content
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


def builder_status(target: Path) -> dict[str, Any]:
    supported_host_preflight()

    def read_status(canonical_target: Path) -> dict[str, Any]:
        cleanup = cleanup_pending_status(canonical_target)
        source_files = validate_builder_toolkit_source()
        result = _builder_status_locked(canonical_target, source_files)
        result.update(cleanup)
        return result

    return coordinated_target_read(target, read_status)


def write_gh_blocker(target: Path, relative_directory: Path) -> Path:
    directory = create_or_require_private_runtime_directory(
        target,
        relative_directory,
        "gh fallback blocker directory",
    )
    blocker = directory / "gh"
    script = b"#!/bin/sh\nexit 127\n"
    if lstat_exists(blocker):
        content, info = read_regular_file(blocker, "gh fallback blocker")
        if content != script:
            fail("gh fallback blocker path is not owned by this manager")
        if stat.S_IMODE(info.st_mode) != 0o700:
            fail("gh fallback blocker must be owned by this manager with mode 0700")
        return directory
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= require_no_follow_flag("gh fallback blocker")
    fd: int | None = None
    created = False
    try:
        fd = os.open(blocker, flags, 0o700)
        created = True
        os.fchmod(fd, 0o700)
        remaining = script
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                fail("gh fallback blocker could not be written")
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        content, info = read_regular_file(blocker, "gh fallback blocker")
        if content != script:
            fail("gh fallback blocker changed while it was being created")
        if stat.S_IMODE(info.st_mode) != 0o700:
            fail("gh fallback blocker must be owned by this manager with mode 0700")
        fsync_directory(directory, "gh fallback blocker parent")
    except BaseException:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if created and lstat_exists(blocker):
            with contextlib.suppress(BaseException):
                retrying_unlink(blocker, "gh fallback blocker")
        raise
    return directory


def native_builder_environment(target: Path) -> dict[str, str]:
    env = isolated_child_environment(target)
    runtime = target / "runtime"
    gh_config = create_or_require_private_runtime_directory(
        target,
        Path("runtime") / "gh-config",
        "native builder GitHub config directory",
    )
    no_ambient_bin = write_gh_blocker(target, Path("runtime") / "no-ambient-bin")
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


def builder_install_rollback_paths() -> tuple[Path, ...]:
    return (
        Path("installed-plugins") / BUILDER_MARKETPLACE_NAME,
        Path("plugin-data") / BUILDER_MARKETPLACE_NAME,
    )


def builder_rollback_path_pairs(target: Path) -> tuple[tuple[Path, Path], ...]:
    return tuple((relative, target / relative) for relative in builder_install_rollback_paths())


def remember_builder_parent_snapshots(
    transaction: BuilderInstallPathTransaction,
    path: Path,
) -> None:
    current = path.parent
    while True:
        transaction.parent_directories.setdefault(
            current,
            capture_directory_snapshot(current, f"builder rollback parent {current}"),
        )
        if current == transaction.target:
            return
        current = current.parent


def prepare_builder_stash_parent(stash_root: Path, relative: Path) -> Path:
    destination = stash_root / relative
    destination.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    current = destination.parent
    while current != stash_root:
        current.chmod(OWNER_DIRECTORY_MODE)
        current = current.parent
    return destination


def require_builder_rollback_directory(path: Path, target: Path, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    require_current_owner(info, label)
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    try:
        resolved = path.resolve(strict=True)
        target_resolved = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        fail(f"{label} could not be resolved safely: {exc}")
    if resolved != target_resolved and not path_is_relative_to(resolved, target_resolved):
        fail(f"{label} escaped managed target")
    return info


def remove_builder_transaction_created_tree(path: Path, target: Path, label: str) -> None:
    if not lstat_exists(path):
        return
    require_builder_rollback_directory(path, target, label)
    shutil.rmtree(path)
    fsync_directory(path.parent, f"{label} parent")


def begin_builder_install_path_transaction(target: Path) -> BuilderInstallPathTransaction:
    parent_directories: dict[Path, DirectorySnapshot] = {}
    stash_root = transaction_stash_root(target, "builder-install", parent_directories)
    transaction = BuilderInstallPathTransaction(
        target=target,
        stash_root=stash_root,
        stashed_paths={},
        absent_paths=set(),
        parent_directories=parent_directories,
    )
    try:
        for relative, path in builder_rollback_path_pairs(target):
            remember_builder_parent_snapshots(transaction, path)
            info = stat_existing(path, f"builder install rollback path {relative}")
            if info is None:
                transaction.absent_paths.add(relative)
                continue
            require_builder_rollback_directory(
                path,
                target,
                f"builder install rollback path {relative}",
            )
            destination = prepare_builder_stash_parent(stash_root, relative)
            retrying_replace(path, destination, f"builder install preserve path {relative}")
            fsync_directory(path.parent, f"builder install preserve source parent {relative}")
            fsync_directory(destination.parent, f"builder install preserve stash parent {relative}")
            transaction.stashed_paths[relative] = destination
        return transaction
    except BaseException:
        rollback_builder_install_path_transaction(transaction)
        raise


def restore_builder_absent_parent_snapshots(transaction: BuilderInstallPathTransaction) -> None:
    for path, snapshot in sorted(
        transaction.parent_directories.items(),
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        if snapshot.exists or not lstat_exists(path):
            continue
        info = require_directory(path, f"builder rollback absent parent {path}")
        if stat.S_ISDIR(info.st_mode):
            path.rmdir()
            fsync_directory(path.parent, f"builder rollback absent parent {path}")


def rollback_builder_install_path_transaction(
    transaction: BuilderInstallPathTransaction,
) -> None:
    rollback_error: BaseException | None = None
    for relative, path in reversed(builder_rollback_path_pairs(transaction.target)):
        stash = transaction.stashed_paths.get(relative)
        try:
            if stash is not None:
                if not lstat_exists(stash):
                    continue
                if lstat_exists(path):
                    remove_builder_transaction_created_tree(
                        path,
                        transaction.target,
                        f"builder rollback created path {relative}",
                    )
                retrying_replace(stash, path, f"builder rollback original path {relative}")
                fsync_directory(path.parent, f"builder rollback original parent {relative}")
            elif lstat_exists(path):
                remove_builder_transaction_created_tree(
                    path,
                    transaction.target,
                    f"builder rollback created path {relative}",
                )
        except BaseException as exc:
            if rollback_error is None:
                rollback_error = exc
    try:
        remove_private_tree_verified(transaction.stash_root, "builder install rollback stash")
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    try:
        restore_builder_absent_parent_snapshots(transaction)
        restore_absolute_directory_snapshots(
            transaction.parent_directories,
            "builder install rollback parent",
        )
    except BaseException as exc:
        if rollback_error is None:
            rollback_error = exc
    if rollback_error is not None:
        raise rollback_error


def commit_builder_install_path_transaction(
    transaction: BuilderInstallPathTransaction,
) -> None:
    commit_error: BaseException | None = None
    for relative, path in reversed(builder_rollback_path_pairs(transaction.target)):
        stash = transaction.stashed_paths.get(relative)
        if stash is None:
            continue
        try:
            if lstat_exists(path):
                remove_builder_transaction_created_tree(
                    path,
                    transaction.target,
                    f"builder install created path {relative}",
                )
            if lstat_exists(stash):
                retrying_replace(stash, path, f"builder install restore path {relative}")
                fsync_directory(path.parent, f"builder install restore parent {relative}")
        except BaseException as exc:
            if commit_error is None:
                commit_error = exc
    try:
        remove_private_tree_verified(transaction.stash_root, "builder install transaction stash")
    except BaseException as exc:
        if commit_error is None:
            commit_error = exc
    if commit_error is not None:
        raise commit_error


def install_builder(target: Path) -> dict[str, Any]:
    supported_host_preflight()

    def read_current(canonical_target: Path) -> dict[str, Any] | None:
        cleanup = cleanup_pending_status_for_mutation(canonical_target)
        if cleanup["cleanup_pending"]:
            return None
        state = inspect_target(canonical_target)
        if state["state"] != "managed":
            return None
        status = _software_status_locked(canonical_target)
        if not status["installed"] or not status["current"]:
            return None
        current = _builder_status_locked(canonical_target)
        if not current["current"]:
            return None
        return {
            "ok": True,
            "operation": "install-builder",
            "changed": False,
            "target": str(canonical_target),
            "builder": current,
            "cleanup_pending": False,
        }

    with target_coordination(target) as canonical_target:
        noop = read_current(canonical_target)
    if noop is not None:
        return noop
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=False) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        state = inspect_target(canonical_target)
        if state["state"] == "legacy-managed":
            fail("target is legacy-managed; run migrate before installing builder")
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        status = _software_status_locked(canonical_target)
        if not status["installed"] or not status["current"]:
            fail("Copilot CLI is not installed at the tested version in this target")
        current = _builder_status_locked(canonical_target)
        if current["current"]:
            return {
                "ok": True,
                "operation": "install-builder",
                "changed": False,
                "target": str(canonical_target),
                "builder": current,
                "cleanup_pending": False,
            }
        if current["state"] not in {"missing", "absent"}:
            fail("builder plugin cache is not current; remove it before reinstalling")
        managed_snapshot = current_managed_snapshot(canonical_target, MANAGED_PATHS)
        builder_path_transaction: BuilderInstallPathTransaction | None = (
            begin_builder_install_path_transaction(canonical_target)
        )
        try:
            run_native_builder_command(
                canonical_target,
                ["plugin", "marketplace", "add", str(MARKETPLACE_ROOT)],
            )
            run_native_builder_command(
                canonical_target,
                ["plugin", "install", BUILDER_PLUGIN_SPEC],
            )
            restore_snapshot_if_drifted(canonical_target, managed_snapshot)
            installed = _builder_status_locked(canonical_target)
            if not installed["current"]:
                fail("native builder plugin install did not produce the expected toolkit")
            commit_builder_install_path_transaction(builder_path_transaction)
            builder_path_transaction = None
        except BaseException:
            rollback_error: BaseException | None = None
            try:
                restore_snapshot_if_drifted(canonical_target, managed_snapshot)
            except BaseException as exc:
                rollback_error = exc
            if builder_path_transaction is not None:
                try:
                    rollback_builder_install_path_transaction(builder_path_transaction)
                except BaseException as exc:
                    if rollback_error is None:
                        rollback_error = exc
            if rollback_error is not None:
                raise rollback_error
            raise
    return {
        "ok": True,
        "operation": "install-builder",
        "changed": True,
        "target": str(canonical_target),
        "builder": installed,
        "cleanup_pending": False,
    }


def isolated_child_environment(target: Path) -> dict[str, str]:
    home = create_or_require_private_runtime_directory(target, Path("home"), "child HOME")
    cache = create_or_require_private_runtime_directory(target, Path("cache"), "child cache")
    runtime = create_or_require_private_runtime_directory(target, Path("runtime"), "child runtime")
    tmp = create_or_require_private_runtime_directory(
        target,
        Path("runtime") / "tmp",
        "child temporary directory",
    )
    xdg_config = create_or_require_private_runtime_directory(
        target,
        Path("runtime") / "xdg-config",
        "child XDG config directory",
    )
    xdg_state = create_or_require_private_runtime_directory(
        target,
        Path("runtime") / "xdg-state",
        "child XDG state directory",
    )
    xdg_cache = create_or_require_private_runtime_directory(
        target,
        Path("cache") / "xdg-cache",
        "child XDG cache directory",
    )
    gh_config = create_or_require_private_runtime_directory(
        target,
        Path("runtime") / "gh-config",
        "child GitHub config directory",
    )
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
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_STATE_HOME": str(xdg_state),
            "GH_CONFIG_DIR": str(gh_config),
            "GITHUB_CONFIG_DIR": str(gh_config),
            "PATH": DETERMINISTIC_PATH,
        }
    )
    del runtime
    no_ambient_bin = write_gh_blocker(target, Path("runtime") / "no-ambient-bin")
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
    detect_supported_host(load_baseline())
    override = child_args_use_target_scope_overrides(args)
    if override is not None:
        fail(f"{override} is managed by the target launch environment")
    drain_cleanup_before_internal_target_lock(target)
    with target_lock(target, create_parent=False) as locked:
        canonical_target = locked.target
        drain_cleanup_before_mutation(canonical_target)
        state = inspect_target(canonical_target)
        if state["state"] == "legacy-managed":
            fail("target is legacy-managed; run migrate before launch")
        if state["state"] != "managed":
            fail("target is not managed by nddev-github-copilot-cli-app")
        status = _software_status_locked(canonical_target)
        if not status["installed"] or not status["current"]:
            fail("Copilot CLI is not installed at the tested version in this target")
        software_before = current_software_metadata(canonical_target)
        builder = _builder_status_locked(canonical_target)
        if not builder["current"]:
            fail("nddev-builder native plugin is not installed; run install-builder")
        executable = copilot_executable(canonical_target)
        child_args = list(state["launch_args"]) + args
        child_env = isolated_child_environment(canonical_target)
        protected = protect_launch_handoff_paths(canonical_target)
        try:
            software_after = current_software_metadata(canonical_target)
            require_launch_executable_unchanged(software_before, software_after)
            process = subprocess.Popen(
                [str(executable), *child_args],
                cwd=canonical_target,
                env=child_env,
            )
            return int(process.wait())
        finally:
            restore_protected_directories(protected)


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
    raw_argv = sys.argv[1:] if argv is None else argv
    json_errors = "--json" in raw_argv
    parser = JsonArgumentParser(description=__doc__, json_errors=json_errors)

    def subparser_factory(*args: Any, **kwargs: Any) -> JsonArgumentParser:
        return JsonArgumentParser(*args, json_errors=json_errors, **kwargs)

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=subparser_factory,
    )

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

    update_parser = subparsers.add_parser("update", help="update the current setup")
    add_target_argument(update_parser)
    add_json_argument(update_parser)

    restore_parser = subparsers.add_parser("restore", help="restore a target-bound backup")
    restore_parser.add_argument("--backup", type=int, required=True, help="backup slot 0..9")
    add_target_argument(restore_parser)
    add_json_argument(restore_parser)

    remove_parser = subparsers.add_parser("remove", help="remove nddev-managed setup files")
    add_target_argument(remove_parser)
    add_json_argument(remove_parser)

    for name in ("software-install", "software-update", "software-remove"):
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


HOST_PREFLIGHT_COMMANDS = {
    "status",
    "plan",
    "install",
    "update",
    "switch",
    "migrate",
    "restore",
    "remove",
    "builder-status",
    "install-builder",
    "software-plan",
    "software-status",
    "software-install",
    "software-update",
    "software-remove",
    "launch",
}


def supported_host_preflight() -> dict[str, Any]:
    return detect_supported_host(load_baseline())


def run(args: argparse.Namespace) -> int:
    if args.command == "list":
        print_payload(
            {"ok": True, "setups": list_setups(), "profiles": list_profiles()},
            json_output=args.json,
        )
        return 0
    if args.command in HOST_PREFLIGHT_COMMANDS:
        supported_host_preflight()
    if args.command == "status":
        target = require_explicit_absolute_target(args.target)

        def read_status(canonical_target: Path) -> dict[str, Any]:
            result = {"ok": True, **inspect_target(canonical_target)}
            result.update(cleanup_pending_status(canonical_target))
            return result

        print_payload(
            coordinated_target_read(
                target,
                read_status,
            ),
            json_output=args.json,
        )
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
    if args.command == "update":
        target = require_explicit_absolute_target(args.target)
        print_payload(
            mutate_setup(target, DEFAULT_SETUP_ID, DEFAULT_PROFILE_ID, "update"),
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
        print_payload(
            install_or_update_cli(target, operation="software-install"), json_output=args.json
        )
        return 0
    if args.command == "software-update":
        target = require_explicit_absolute_target(args.target)
        print_payload(
            install_or_update_cli(target, operation="software-update"), json_output=args.json
        )
        return 0
    if args.command == "software-remove":
        target = require_explicit_absolute_target(args.target)
        print_payload(remove_software(target), json_output=args.json)
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
    except JsonCliArgumentError as exc:
        return error_result(str(exc), json_output=True)
    except CopilotCliSetupError as exc:
        json_output = "--json" in (argv if argv is not None else sys.argv[1:])
        return error_result(str(exc), json_output=json_output)


if __name__ == "__main__":
    raise SystemExit(main())
