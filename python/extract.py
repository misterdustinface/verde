#!/usr/bin/env python3
"""
verde extract.py — primary feature (CLI: verde-export)

Exports a Roblox .rbxlx place into a folder hierarchy that is easy to version-control,
search, and edit.

- Scripts → .lua / .local.lua / .module.lua (Source content)
- All other Instances → folder + .robloxmeta.json (ClassName, Name, Tags, Attributes, ALL properties)
- Hierarchy is preserved.
- Full property type support for successful round-trips.
- Default: only the cascading directories that lead to scripts (use --all for full hierarchy).
- Empty directories are never retained.
- Name collision handling:
  - Within a single export, sibling instances that share the same Name still get
    numeric suffixes (Name, Name_2, …) so both can live on disk.
  - On case-insensitive filesystems (macOS / Windows) uniqueness is also
    case-insensitive so a "Foo" / "foo" pair cannot overwrite each other.
  - Paths that already exist on disk from a previous export are *reused* (no new
    digit suffix). Content is compared: identical files are left untouched;
    differing files are overwritten by default, or prompted with --interactive.
  - After re-export, stale uniquified siblings (Name_N left when the collision
    disappeared) are removed so the tree does not accumulate orphans.
- After a successful export a .verde/manifest.json is written so later merge/import
  can skip unchanged files (simple adler32 hash + mtime).
- Selective: --root PATH and/or --tag TAG limit the exported tree.
- Machine-local Referent is written to *.robloxmeta.local.json (gitignored),
  never into the shared .robloxmeta.json that is checked into VCS.
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes
from features.meta import (
    LOCAL_META_KEYS,
    local_meta_path,
    save_local_meta,
    split_local_keys,
)
from interesting import load_interesting_props
from xml_props import sanitize_name, parse_children, parse_property_element, decode_tags_from_prop


SCRIPT_EXTS = (".lua", ".local.lua", ".module.lua")

_FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")


def get_script_extension(class_name: str) -> str:
    if class_name == "LocalScript":
        return ".local.lua"
    if class_name == "ModuleScript":
        return ".module.lua"
    return ".lua"


def extract_properties(
    item: ET.Element, interesting: set[str]
) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    flat: dict[str, Any] = {}
    tags: list[str] = []
    full: dict[str, Any] = {}
    attributes: dict[str, Any] = {}

    props_elem = item.find("Properties")
    if props_elem is None:
        return flat, tags, full, attributes

    for prop in list(props_elem):
        prop_name = prop.get("name")
        if not prop_name:
            continue

        structured = parse_property_element(prop)
        full[prop_name] = structured

        if prop_name == "Tags" and structured.get("type") == "BinaryString":
            raw = (structured.get("value") or "").replace("\n", "").replace(" ", "")
            try:
                data = base64.b64decode(raw)
                tags = [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
            except Exception:
                tags = [t.strip() for t in (structured.get("value") or "").replace("\0", ",").split(",") if t.strip()]
            full.pop("Tags", None)
            continue

        if prop_name == "Tags" and structured.get("type") in ("string", "ProtectedString"):
            text = structured.get("value") or ""
            tags = [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]
            full.pop("Tags", None)
            continue

        if prop_name == "AttributesSerialize" and structured.get("type") == "BinaryString":
            decoded = decode_attributes(structured.get("value") or "")
            if decoded:
                attributes = decoded
                full.pop("AttributesSerialize", None)
            continue

        if prop_name in interesting and structured.get("type") in (
            "string",
            "ProtectedString",
            "Content",
            "token",
            "BinaryString",
        ):
            flat[prop_name] = structured.get("value") or ""

        if prop_name in interesting and structured.get("type") in ("bool", "int", "float", "double", "token"):
            flat[prop_name] = structured.get("value")

    return flat, tags, full, attributes


def _resolve_name(
    item: ET.Element,
    flat: dict[str, Any],
    full_props: dict[str, Any],
) -> str:
    if "Name" in flat and isinstance(flat["Name"], str) and flat["Name"]:
        return flat["Name"]

    structured = full_props.get("Name")
    if isinstance(structured, dict):
        val = structured.get("value")
        if isinstance(val, str) and val:
            return val

    attr = item.get("name")
    if attr:
        return attr

    return "Unnamed"


def _item_has_tag(item: ET.Element, tag: str) -> bool:
    """Quick check without full property parse — Tags BinaryString or string."""
    props = item.find("Properties")
    if props is None:
        return False
    tag_lower = tag.lower()
    for prop in props:
        if prop.get("name") != "Tags":
            continue
        if prop.tag == "BinaryString":
            raw = (prop.text or "").replace("\n", "").replace(" ", "")
            try:
                data = base64.b64decode(raw)
                tags = [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
            except Exception:
                tags = []
            return any(t.lower() == tag_lower for t in tags)
        text = prop.text or ""
        tags = [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]
        return any(t.lower() == tag_lower for t in tags)
    return False


def _compute_keep_map(
    items: list[ET.Element],
    *,
    scripts_only: bool = True,
    tag_filter: str | None = None,
) -> dict[int, bool]:
    """Bottom-up keep: scripts and/or tagged instances, plus their ancestors."""
    keep: dict[int, bool] = {}
    stack: list[tuple[ET.Element, bool]] = []
    for it in items:
        stack.append((it, False))

    while stack:
        item, children_done = stack.pop()
        if item.tag != "Item":
            continue

        if not children_done:
            stack.append((item, True))
            for child in reversed(list(item)):
                if child.tag == "Item":
                    stack.append((child, False))
            continue

        class_name = item.get("class", "Folder")
        is_script = class_name in ("Script", "LocalScript", "ModuleScript")
        has_kept_child = any(
            keep.get(id(c), False) for c in item if c.tag == "Item"
        )
        has_tag = bool(tag_filter) and _item_has_tag(item, tag_filter)

        if scripts_only and tag_filter:
            keep[id(item)] = is_script or has_tag or has_kept_child
        elif tag_filter:
            keep[id(item)] = has_tag or has_kept_child
        else:
            keep[id(item)] = is_script or has_kept_child

    return keep


def _find_root_item(root: ET.Element, path: str) -> ET.Element | None:
    """Locate an Item by dot-separated Name path from top-level Items."""
    parts = [p for p in path.split(".") if p]
    if not parts:
        return None

    current_list = [c for c in root if c.tag == "Item"]
    target: ET.Element | None = None

    for i, part in enumerate(parts):
        found = None
        for it in current_list:
            flat, _, full, _ = extract_properties(it, set())
            name = _resolve_name(it, flat, full)
            if name == part or sanitize_name(name) == part:
                found = it
                break
        if found is None:
            return None
        target = found
        if i < len(parts) - 1:
            current_list = [c for c in found if c.tag == "Item"]

    return target


def _prune_empty_dirs(root: Path) -> int:
    removed = 0
    stack: list[tuple[Path, bool]] = [(root, False)]

    while stack:
        dir_path, children_visited = stack.pop()
        if not children_visited:
            stack.append((dir_path, True))
            try:
                for child in dir_path.iterdir():
                    if child.is_dir():
                        stack.append((child, False))
            except OSError:
                pass
            continue

        if dir_path == root:
            continue
        try:
            if not any(dir_path.iterdir()):
                dir_path.rmdir()
                removed += 1
        except OSError:
            pass

    return removed


def _cleanup_orphaned_uniquified(root: Path, written: dict[Path, set[str]]) -> int:
    """Remove stale Name_N siblings left from a prior collision that no longer exists.

    When path-reuse writes a survivor back to the bare Name, the old Name_2
    (file or dir) is otherwise left behind because empty-dir prune only deletes
    empty directories. Only remove entries whose stem matches the uniquify
    pattern and whose bare base was claimed this run.
    """
    removed = 0
    for parent, used in written.items():
        if not parent.is_dir():
            continue
        try:
            entries = list(parent.iterdir())
        except OSError:
            continue
        for entry in entries:
            stem = entry.name
            for ext in SCRIPT_EXTS + (".robloxmeta.json", ".robloxmeta.local.json"):
                if entry.name.endswith(ext):
                    stem = entry.name[: -len(ext)]
                    break
            # Already used this run → keep
            if _FS_CASE_INSENSITIVE:
                if any(stem.casefold() == u.casefold() for u in used):
                    continue
            else:
                if stem in used:
                    continue
            m = re.match(r"^(.+)_([0-9]+)$", stem)
            if not m:
                continue
            base = m.group(1)
            if _FS_CASE_INSENSITIVE:
                base_used = any(base.casefold() == u.casefold() for u in used)
            else:
                base_used = base in used
            if not base_used:
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _confirm_overwrite(path: Path) -> bool:
    while True:
        try:
            ans = input(f"  Diff at {path} — overwrite? [Y/n] ").strip().lower()
        except EOFError:
            return True
        if ans in ("", "y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer Y or n")


def _maybe_write(path: Path, content: str, interactive: bool) -> str:
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing is not None and existing == content:
            return "unchanged"
        if interactive and not _confirm_overwrite(path):
            return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def _write_meta_pair(
    meta_path: Path,
    meta: dict[str, Any],
    interactive: bool,
) -> str:
    """Write shared meta (no LOCAL keys) + optional machine-local sibling.

    Returns the status of the shared write ("written" / "unchanged" / "skipped").
    Local file is always written when a Referent (or other local key) is present;
    it is not subject to the interactive prompt because it is never checked in.
    """
    shared, local = split_local_keys(meta)
    status = _maybe_write(meta_path, json.dumps(shared, indent=2), interactive)
    save_local_meta(meta_path, local)
    return status


def extract(
    rbxlx_path: str,
    output_dir: str = "extracted",
    interesting: set[str] | None = None,
    scripts_only: bool = True,
    interactive: bool = False,
    root_filter: str | None = None,
    tag_filter: str | None = None,
) -> None:
    if interesting is None:
        interesting = load_interesting_props()

    print(f"Parsing {rbxlx_path} ...")
    tree = ET.parse(rbxlx_path)
    root = tree.getroot()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    script_count = 0
    instance_count = 0
    written_count = 0
    unchanged_count = 0
    skipped_count = 0
    PROGRESS_EVERY = 500

    start_items: list[ET.Element]
    if root_filter:
        found = _find_root_item(root, root_filter)
        if found is None:
            print(f"Error: --root {root_filter!r} not found in place", file=sys.stderr)
            sys.exit(1)
        start_items = [found]
        print(f"  Selective root: {root_filter}")
    else:
        start_items = [c for c in root if c.tag == "Item"]

    keep_map: dict[int, bool] | None = None
    if scripts_only or tag_filter:
        keep_map = _compute_keep_map(
            start_items if root_filter else [c for c in root if c.tag == "Item"],
            scripts_only=scripts_only,
            tag_filter=tag_filter,
        )
        if tag_filter:
            print(f"  Selective tag: {tag_filter}")

    used_names: dict[Path, set[str]] = {}  # keys for uniqueness (casefolded when needed)
    written_names: dict[Path, set[str]] = {}  # actual names assigned this run

    stack: list[tuple[ET.Element, Path]] = []
    for top in reversed(start_items):
        stack.append((top, out))

    while stack:
        item, current = stack.pop()
        if item.tag != "Item":
            continue

        if keep_map is not None and not keep_map.get(id(item), False):
            continue

        class_name = item.get("class", "Folder")
        referent = item.get("referent")

        flat, tags, full_props, attributes = extract_properties(item, interesting)
        raw_name = _resolve_name(item, flat, full_props)
        name = sanitize_name(raw_name)

        claimed = used_names.setdefault(current, set())

        base_name = name
        counter = 1
        key = name.casefold() if _FS_CASE_INSENSITIVE else name
        while key in claimed:
            counter += 1
            name = f"{base_name}_{counter}"
            key = name.casefold() if _FS_CASE_INSENSITIVE else name
        claimed.add(key)
        written_names.setdefault(current, set()).add(name)

        full_path = current / name
        instance_count += 1
        if instance_count % PROGRESS_EVERY == 0:
            print(f"  ... {instance_count} instances processed")

        def _record(status: str) -> None:
            nonlocal written_count, unchanged_count, skipped_count
            if status == "written":
                written_count += 1
            elif status == "unchanged":
                unchanged_count += 1
            elif status == "skipped":
                skipped_count += 1

        if class_name in ("Script", "LocalScript", "ModuleScript"):
            source = flat.pop("Source", None)
            if source is None and "Source" in full_props:
                source = full_props["Source"].get("value", "")
            source = source or ""

            full_props.pop("Source", None)

            ext = get_script_extension(class_name)
            script_file = full_path.with_name(full_path.name + ext)

            _record(_maybe_write(script_file, source, interactive))

            meta: dict[str, Any] = {
                "ClassName": class_name,
                "Name": raw_name,
                "Tags": tags,
                "Properties": full_props,
            }
            if attributes:
                meta["Attributes"] = attributes
            if referent:
                meta["Referent"] = referent
            for k, v in flat.items():
                if k != "Source":
                    meta[k] = v

            meta_path = script_file.parent / f"{script_file.stem}.robloxmeta.json"
            _record(_write_meta_pair(meta_path, meta, interactive))
            script_count += 1

            child_items = [c for c in item if c.tag == "Item"]
            will_write_children = False
            if child_items:
                if keep_map is None:
                    will_write_children = True
                else:
                    will_write_children = any(keep_map.get(id(c), False) for c in child_items)

            if will_write_children:
                full_path.mkdir(parents=True, exist_ok=True)
                for child in reversed(child_items):
                    stack.append((child, full_path))
            continue

        full_path.mkdir(parents=True, exist_ok=True)
        meta = {
            "ClassName": class_name,
            "Name": raw_name,
            "Tags": tags,
            "Properties": full_props,
            **flat,
        }
        if attributes:
            meta["Attributes"] = attributes
        if referent:
            meta["Referent"] = referent

        meta_path = full_path / ".robloxmeta.json"
        _record(_write_meta_pair(meta_path, meta, interactive))

        for child in reversed(list(item)):
            stack.append((child, full_path))

    pruned = _prune_empty_dirs(out)
    orphans = _cleanup_orphaned_uniquified(out, written_names)
    if orphans:
        # Removing non-empty orphans can leave newly-empty parents; prune again.
        pruned += _prune_empty_dirs(out)

    mode_bits = []
    if scripts_only:
        mode_bits.append("scripts-only")
    else:
        mode_bits.append("--all")
    if root_filter:
        mode_bits.append(f"root={root_filter}")
    if tag_filter:
        mode_bits.append(f"tag={tag_filter}")
    print(f"Export complete → {out}/  ({', '.join(mode_bits)})")
    print(f"  Instances : {instance_count}")
    print(f"  Scripts   : {script_count}")
    print(f"  Wrote     : {written_count}")
    if unchanged_count:
        print(f"  Unchanged : {unchanged_count}")
    if skipped_count:
        print(f"  Skipped   : {skipped_count} (interactive)")
    if pruned:
        print(f"  Empty dirs removed: {pruned}")
    if orphans:
        print(f"  Orphaned uniquified removed: {orphans}")

    if root_filter or tag_filter:
        partial = {
            "root": root_filter,
            "tag": tag_filter,
            "scripts_only": scripts_only,
            "source_rbxlx": str(Path(rbxlx_path).resolve()),
        }
        partial_dir = out / ".verde"
        partial_dir.mkdir(parents=True, exist_ok=True)
        (partial_dir / "partial.json").write_text(
            json.dumps(partial, indent=2), encoding="utf-8"
        )
        print(f"  Partial   : {partial_dir / 'partial.json'}")

    try:
        from features.sync import write_manifest

        write_manifest(out, rbxlx_path=rbxlx_path)
        print(f"  Manifest  : {out / '.verde' / 'manifest.json'}")
    except Exception as exc:
        print(f"  (manifest not written: {exc})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export a Roblox .rbxlx into a searchable/editable folder tree (CLI: verde-export). "
            "Existing paths are reused; files are overwritten only when content differs. "
            "Use --root / --tag for selective (partial) exports. "
            "Referent is written only to machine-local *.robloxmeta.local.json (gitignored)."
        )
    )
    parser.add_argument("rbxlx", help="Path to .rbxlx file")
    parser.add_argument(
        "output_dir", nargs="?", default="extracted", help="Output directory (default: extracted)"
    )
    parser.add_argument(
        "--interesting",
        help="Comma-separated list of property names to flatten (overrides env/file/default)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Export the full hierarchy (every instance → folder + meta). "
            "Default is scripts-only: only directories that lead to scripts are created."
        ),
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "When an existing file differs from the export, prompt Y/n before "
            "overwriting (default is to overwrite on diff, skip when identical)."
        ),
    )
    parser.add_argument(
        "--root",
        metavar="PATH",
        help=(
            "Selective: start export from this instance path (dot-separated Names, "
            "e.g. ServerScriptService or Workspace.MyModel). The subtree becomes "
            "the top of the output folder."
        ),
    )
    parser.add_argument(
        "--tag",
        metavar="TAG",
        help=(
            "Selective: keep only instances that have this CollectionService tag "
            "(or ancestors of tagged instances) so hierarchy is preserved."
        ),
    )
    args = parser.parse_args()

    interesting = None
    if args.interesting:
        interesting = {p.strip() for p in args.interesting.split(",") if p.strip()}

    extract(
        args.rbxlx,
        args.output_dir,
        interesting=interesting,
        scripts_only=not args.all,
        interactive=args.interactive,
        root_filter=args.root,
        tag_filter=args.tag,
    )


if __name__ == "__main__":
    main()
