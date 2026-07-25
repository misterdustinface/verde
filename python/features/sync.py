#!/usr/bin/env python3
"""
Touched-file tracking and verde-sync helpers.

Manifest lives at <extracted>/.verde/manifest.json and records a simple numeric
content hash (zlib.adler32) + mtime for every .lua / .robloxmeta.json so that
import can skip unchanged files and conflicts can be resolved by "most recently
modified wins".
"""

from __future__ import annotations

import argparse
import json
import time
import zlib
from pathlib import Path
from typing import Any


MANIFEST_DIR = ".verde"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1

# File suffixes we track for change detection
TRACKED_SUFFIXES = (
    ".lua",
    ".local.lua",
    ".module.lua",
    ".robloxmeta.json",
)


def content_hash(data: str | bytes) -> int:
    """Simple, fast numeric hash of file content (stdlib zlib.adler32).

    Only needs to turn a string/bytes into a stable integer for change detection.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return zlib.adler32(data) & 0xFFFFFFFF


def _file_entry(path: Path) -> dict[str, Any] | None:
    """Return {h, m} for a tracked file, or None if unreadable."""
    try:
        raw = path.read_bytes()
        st = path.stat()
        return {"h": content_hash(raw), "m": st.st_mtime}
    except OSError:
        return None


def _is_tracked(path: Path) -> bool:
    name = path.name
    if name == ".robloxmeta.json":
        return True
    for suf in TRACKED_SUFFIXES:
        if name.endswith(suf):
            return True
    return False


def collect_file_entries(root: Path) -> dict[str, dict[str, Any]]:
    """Walk root and build relpath → {h, m} for every tracked file."""
    files: dict[str, dict[str, Any]] = {}
    for p in root.rglob("*"):
        if not p.is_file() or not _is_tracked(p):
            continue
        # Skip anything under .verde itself
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == MANIFEST_DIR:
            continue
        entry = _file_entry(p)
        if entry is not None:
            files[str(rel).replace("\\", "/")] = entry
    return files


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_DIR / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
            return None
        return data
    except Exception:
        return None


def write_manifest(
    root: Path,
    *,
    rbxlx_path: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write / overwrite the manifest after a successful extract or sync.

    Records current hashes + mtimes of all tracked files under root, plus
    optional rbxlx path/mtime and last_sync timestamp.
    """
    root = Path(root)
    manifest_dir = root / MANIFEST_DIR
    manifest_dir.mkdir(parents=True, exist_ok=True)

    files = collect_file_entries(root)

    rbxlx_mtime = None
    rbxlx_str = None
    if rbxlx_path is not None:
        rp = Path(rbxlx_path)
        rbxlx_str = str(rp)
        try:
            rbxlx_mtime = rp.stat().st_mtime
        except OSError:
            pass

    data: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "rbxlx": rbxlx_str,
        "rbxlx_mtime": rbxlx_mtime,
        "last_sync": time.time(),
        "files": files,
    }
    if extra:
        data.update(extra)

    out = manifest_dir / MANIFEST_NAME
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out


def is_file_dirty(
    root: Path,
    rel: str,
    manifest: dict[str, Any] | None,
    *,
    rbxlx_mtime: float | None = None,
) -> bool:
    """Return True if the file at root/rel should be considered changed.

    Rules:
    - No manifest → always dirty (safe full path).
    - Missing from manifest → dirty.
    - Current hash or mtime differs from recorded → dirty.
    - Conflict / mtime-win: if the Verde file’s mtime is older than the
      recorded rbxlx_mtime (Roblox side is newer), treat as *not* dirty for
      a push, so the more recent Roblox side wins.
    """
    path = root / rel
    if not path.is_file():
        return False

    if manifest is None:
        return True

    recorded = (manifest.get("files") or {}).get(rel)
    if not recorded:
        return True

    entry = _file_entry(path)
    if entry is None:
        return False

    hash_differs = entry["h"] != recorded.get("h")
    mtime_differs = abs(entry["m"] - float(recorded.get("m") or 0)) > 1e-6

    if not hash_differs and not mtime_differs:
        return False

    # Content changed. Apply mtime-wins against the Roblox side.
    recorded_rbxlx_m = manifest.get("rbxlx_mtime")
    if recorded_rbxlx_m is not None:
        # If the .rbxlx itself is newer than this Verde file, Roblox wins → not dirty for push.
        if entry["m"] < float(recorded_rbxlx_m):
            return False
    if rbxlx_mtime is not None and entry["m"] < rbxlx_mtime:
        return False

    return True


def dirty_paths(
    root: Path,
    manifest: dict[str, Any] | None = None,
    *,
    rbxlx_mtime: float | None = None,
) -> set[str]:
    """Return the set of relative paths that are dirty under the mtime-win rule."""
    if manifest is None:
        manifest = load_manifest(root)
    dirty: set[str] = set()
    for p in root.rglob("*"):
        if not p.is_file() or not _is_tracked(p):
            continue
        try:
            rel = str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if rel.split("/")[0] == MANIFEST_DIR:
            continue
        if is_file_dirty(root, rel, manifest, rbxlx_mtime=rbxlx_mtime):
            dirty.add(rel)
    return dirty


def main() -> None:
    """verde-sync: push dirty Verde files → .rbxlx (mtime-win), or pull if .rbxlx is newer."""
    parser = argparse.ArgumentParser(
        description=(
            "Sync an extracted Verde folder with a .rbxlx. "
            "Most-recently-modified side wins. Uses a simple numeric content hash "
            "(adler32) + mtime tracking in .verde/manifest.json."
        )
    )
    parser.add_argument("extracted_dir", help="Path to extracted Verde folder")
    parser.add_argument(
        "rbxlx",
        help="Path to the .rbxlx place file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing",
    )
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    rbxlx = Path(args.rbxlx)

    if not root.is_dir():
        print(f"Error: extracted dir not found: {root}")
        return

    manifest = load_manifest(root)
    rbxlx_mtime = None
    try:
        if rbxlx.is_file():
            rbxlx_mtime = rbxlx.stat().st_mtime
    except OSError:
        pass

    dirty = dirty_paths(root, manifest, rbxlx_mtime=rbxlx_mtime)

    last_sync = (manifest or {}).get("last_sync") or 0
    rbxlx_is_newer = (
        rbxlx_mtime is not None
        and rbxlx_mtime > float(last_sync)
        and not dirty
    )

    if dirty:
        print(f"Pushing {len(dirty)} dirty file(s) from {root} → {rbxlx}")
        if args.dry_run:
            for rel in sorted(dirty):
                print(f"  · {rel}")
            return
        # Re-use the differential import; it already skips content-identical
        # instances. The dirty set just tells us work is needed.
        from build import import_rbxlx

        import_rbxlx(str(root), str(rbxlx))
        write_manifest(root, rbxlx_path=rbxlx)
        print("Manifest updated.")
        return

    if rbxlx_is_newer:
        print(f".rbxlx is newer than last sync → pulling (full export)")
        if args.dry_run:
            print("  (would run verde-export)")
            return
        from extract import extract

        # Full export for now; selective pull can arrive with TODO #7.
        extract(str(rbxlx), str(root), scripts_only=True)
        write_manifest(root, rbxlx_path=rbxlx)
        print("Manifest updated after pull.")
        return

    print("Nothing to sync — folder and .rbxlx are in agreement.")


if __name__ == "__main__":
    main()
