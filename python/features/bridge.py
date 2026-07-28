#!/usr/bin/env python3
"""
verde-sync — live bi-directional sync between an extracted Verde folder
and an open Roblox Studio place.

Designed for simplicity:

  1. Run once in a terminal:
         verde-sync path/to/extracted

  2. In Studio open the Verde panel and turn on the single "Live Sync" toggle.

No ports, no HTTP knowledge, and no extra configuration are required from the
user. The plugin auto-connects to the fixed local port used by this server.

When the plugin turns Live Sync on it requests a full scan-and-sync.
Afterwards both sides react to changes (file mtime/hash on the folder side,
Source on the Studio side by default).

For offline folder ↔ .rbxlx agreement (without Studio open), use verde-merge.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from features.meta import load_meta_merged, save_local_meta, split_local_keys
from features.sync import (
    content_hash,
    dirty_paths,
    load_manifest,
    write_manifest,
)

DEFAULT_PORT = 3847
POLL_INTERVAL = 0.8


class BridgeState:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.Lock()
        self.manifest = load_manifest(self.root) or {}
        self.known: dict[str, dict[str, Any]] = dict(self.manifest.get("files") or {})
        self.pending_to_studio: set[str] = set()
        self.last_event_id = 0
        self.events: list[dict[str, Any]] = []
        self.running = True

    def refresh_dirty(self) -> set[str]:
        dirty = dirty_paths(self.root, self.manifest)
        with self.lock:
            newly = dirty - self.pending_to_studio
            if newly:
                self.pending_to_studio |= newly
                self.last_event_id += 1
                self.events.append(
                    {
                        "id": self.last_event_id,
                        "type": "dirty",
                        "paths": sorted(newly),
                        "ts": time.time(),
                    }
                )
                if len(self.events) > 50:
                    self.events = self.events[-50:]
            return dirty

    def mark_applied(self, paths: list[str]) -> None:
        with self.lock:
            for p in paths:
                self.pending_to_studio.discard(p)
            for rel in paths:
                path = self.root / rel
                if path.is_file():
                    try:
                        raw = path.read_bytes()
                        st = path.stat()
                        self.known[rel] = {"h": content_hash(raw), "m": st.st_mtime}
                    except OSError:
                        pass
            try:
                write_manifest(self.root, extra={"live_sync": True})
                self.manifest = load_manifest(self.root) or self.manifest
            except Exception:
                pass

    def write_file(self, rel: str, content: str | bytes, is_binary: bool = False) -> bool:
        path = self.root / rel
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # When Studio pushes a .robloxmeta.json that still carries Referent,
            # move that key into the machine-local sibling so the shared file
            # stays VCS-clean.
            text: str | None = None
            if (
                not is_binary
                and rel.endswith(".robloxmeta.json")
                and not rel.endswith(".robloxmeta.local.json")
            ):
                try:
                    raw_text = content if isinstance(content, str) else content.decode("utf-8")
                    data = json.loads(raw_text)
                    if isinstance(data, dict) and "Referent" in data:
                        shared, local = split_local_keys(data)
                        text = json.dumps(shared, indent=2)
                        save_local_meta(path, local)
                except Exception:
                    text = None

            if text is not None:
                path.write_text(text, encoding="utf-8")
            elif is_binary:
                path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            else:
                path.write_text(
                    content if isinstance(content, str) else content.decode("utf-8"),
                    encoding="utf-8",
                )
            raw = path.read_bytes()
            st = path.stat()
            with self.lock:
                self.known[rel] = {"h": content_hash(raw), "m": st.st_mtime}
                self.pending_to_studio.discard(rel)
                try:
                    write_manifest(self.root, extra={"live_sync": True})
                    self.manifest = load_manifest(self.root) or self.manifest
                except Exception:
                    pass
            return True
        except Exception as e:
            print(f"  ! failed to write {rel}: {e}")
            return False


def make_handler(state: BridgeState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            if "GET /status" not in str(args):
                print(f"  · {args[0]}")

        def _json(self, code: int, obj: Any) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _text(self, code: int, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/status":
                with state.lock:
                    pending = len(state.pending_to_studio)
                self._json(
                    200,
                    {
                        "ok": True,
                        "root": str(state.root),
                        "pending": pending,
                        "port": DEFAULT_PORT,
                    },
                )
                return

            if path == "/dirty":
                dirty = state.refresh_dirty()
                self._json(200, {"paths": sorted(dirty)})
                return

            if path == "/events":
                since = int(qs.get("since", ["0"])[0] or 0)
                with state.lock:
                    newer = [e for e in state.events if e["id"] > since]
                    last_id = state.last_event_id
                self._json(200, {"events": newer, "last_id": last_id})
                return

            if path == "/file":
                rel = (qs.get("path") or [""])[0]
                if not rel or ".." in rel:
                    self._json(400, {"error": "bad path"})
                    return
                fpath = state.root / rel
                if not fpath.is_file():
                    self._json(404, {"error": "not found"})
                    return
                try:
                    text = fpath.read_text(encoding="utf-8")
                    self._text(200, text)
                except Exception as e:
                    self._json(500, {"error": str(e)})
                return

            if path == "/meta":
                rel = (qs.get("path") or [""])[0]
                if not rel:
                    self._json(400, {"error": "path required"})
                    return
                candidates = []
                p = Path(rel)
                if p.suffix == ".lua" or rel.endswith((".local.lua", ".module.lua")):
                    base = p.name
                    for suf in (".lua", ".local.lua", ".module.lua"):
                        if base.endswith(suf):
                            base = base[: -len(suf)]
                            break
                    candidates.append(p.parent / f"{base}.robloxmeta.json")
                candidates.append(p.parent / ".robloxmeta.json")
                for c in candidates:
                    full = state.root / c
                    if full.is_file():
                        # Return shared + machine-local overlay so matching still
                        # sees Referent when the .local.json is present.
                        data = load_meta_merged(full)
                        if data is not None:
                            self._json(200, data)
                            return
                self._json(404, {"error": "no meta"})
                return

            self._json(404, {"error": "unknown endpoint"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}

            if path == "/applied":
                paths = body.get("paths") or []
                state.mark_applied(paths)
                self._json(200, {"ok": True})
                return

            if path == "/push":
                files = body.get("files") or []
                written = []
                for entry in files:
                    rel = entry.get("path")
                    content = entry.get("content")
                    if not rel or content is None or ".." in rel:
                        continue
                    if state.write_file(rel, content):
                        written.append(rel)
                if written:
                    print(f"  ← Studio pushed {len(written)} file(s)")
                self._json(200, {"ok": True, "written": written})
                return

            if path == "/full-sync":
                dirty = state.refresh_dirty()
                self._json(
                    200,
                    {
                        "ok": True,
                        "dirty": sorted(dirty),
                        "root": str(state.root),
                    },
                )
                return

            self._json(404, {"error": "unknown endpoint"})

    return Handler


def watcher_loop(state: BridgeState) -> None:
    print("  Watching for file changes…")
    while state.running:
        try:
            state.refresh_dirty()
        except Exception as e:
            print(f"  ! watcher error: {e}")
        time.sleep(POLL_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Start Verde live sync with an open Studio place. "
            "Run this once, then turn on ‘Live Sync’ in the Studio plugin."
        )
    )
    parser.add_argument(
        "extracted_dir",
        help="Path to the extracted Verde folder (same folder as verde-export)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    if not root.is_dir():
        print(f"Error: folder not found → {root}")
        print("Example:  verde-sync ./myplace")
        return

    if load_manifest(root) is None:
        print("No .verde/manifest.json yet — creating one…")
        write_manifest(root)

    state = BridgeState(root)
    handler = make_handler(state)
    server = HTTPServer(("127.0.0.1", args.port), handler)

    t = threading.Thread(target=watcher_loop, args=(state,), daemon=True)
    t.start()

    print()
    print("══════════════════════════════════════════════════")
    print("  Verde Live Sync is running")
    print("══════════════════════════════════════════════════")
    print(f"  Folder : {root.resolve()}")
    print()
    print("  Next step:")
    print("    1. Open your place in Roblox Studio")
    print("    2. Open the Verde panel")
    print("    3. Turn ON the ‘Live Sync’ toggle")
    print()
    print("  File saves and Studio script edits stay in sync.")
    print("  Press Ctrl+C to stop.")
    print("══════════════════════════════════════════════════")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLive Sync stopped.")
        state.running = False
        server.shutdown()


if __name__ == "__main__":
    main()
