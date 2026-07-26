#!/usr/bin/env python3
"""
verde-status — report dirty / missing files from .verde/manifest.json
and Live Sync bridge health (read-only).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sync import collect_file_entries, dirty_paths, load_manifest

DEFAULT_PORT = 3847


def probe_bridge(port: int = DEFAULT_PORT, timeout: float = 0.6) -> dict[str, Any] | None:
    url = f"http://127.0.0.1:{port}/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    return None


def find_missing(root: Path, manifest: dict[str, Any] | None) -> list[str]:
    if not manifest:
        return []
    missing = []
    for rel in (manifest.get("files") or {}):
        if not (root / rel).is_file():
            missing.append(rel)
    return sorted(missing)


def format_ts(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Report dirty / missing files from the Verde manifest and "
            "optionally check whether the Live Sync bridge is reachable. "
            "Purely read-only."
        )
    )
    parser.add_argument(
        "extracted_dir",
        nargs="?",
        default=".",
        help="Path to extracted Verde folder (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bridge port to probe (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="Skip the Live Sync bridge probe",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Include per-file hash/mtime details when available",
    )
    args = parser.parse_args()

    root = Path(args.extracted_dir).resolve()
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest(root)
    dirty = sorted(dirty_paths(root, manifest))
    missing = find_missing(root, manifest)
    on_disk = collect_file_entries(root)
    # dirty are a subset of on_disk; clean = tracked present and not dirty
    clean_count = max(0, len(on_disk) - len(dirty))

    bridge_info = None if args.no_bridge else probe_bridge(args.port)

    result: dict[str, Any] = {
        "root": str(root),
        "manifest_present": manifest is not None,
        "last_sync": (manifest or {}).get("last_sync"),
        "rbxlx": (manifest or {}).get("rbxlx"),
        "dirty": dirty,
        "missing": missing,
        "clean_count": clean_count,
        "tracked_on_disk": len(on_disk),
        "bridge": bridge_info,
        "bridge_reachable": bridge_info is not None and bridge_info.get("ok") is True,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    # Human-readable output
    print(f"Verde status for: {root}")
    if manifest is None:
        print("  Manifest: none (no .verde/manifest.json)")
        print("  Tip: run verde-export or verde-sync once to create it")
    else:
        print("  Manifest: present")
        print(f"  Last sync: {format_ts(manifest.get('last_sync'))}")
        if manifest.get("rbxlx"):
            print(f"  Associated .rbxlx: {manifest.get('rbxlx')}")

    print(f"  Tracked files on disk: {len(on_disk)}")
    print(f"  Clean: {clean_count}")
    print(f"  Dirty: {len(dirty)}")
    if dirty:
        for rel in dirty:
            print(f"    · {rel}")
            if args.verbose and manifest:
                rec = (manifest.get("files") or {}).get(rel)
                if rec:
                    print(f"        recorded h={rec.get('h')} m={rec.get('m')}")
    print(f"  Missing (in manifest, absent on disk): {len(missing)}")
    if missing:
        for rel in missing:
            print(f"    · {rel}")

    print()
    if args.no_bridge:
        print("  Bridge probe: skipped")
    elif bridge_info is None:
        print(f"  Live Sync bridge: not reachable on 127.0.0.1:{args.port}")
    else:
        print(f"  Live Sync bridge: UP on port {bridge_info.get('port', args.port)}")
        print(f"    root: {bridge_info.get('root')}")
        print(f"    pending → Studio: {bridge_info.get('pending', 0)}")


if __name__ == "__main__":
    main()
