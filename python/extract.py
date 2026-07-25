#!/usr/bin/env python3
"""
verde extract.py — primary feature (CLI: verde-export / verde-extract)

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
- After a successful export a .verde/manifest.json is written so later sync/import
  can skip unchanged files (simple adler32 hash + mtime).
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes
from interesting import load_interesting_props


SCRIPT_EXTS = (".lua", ".local.lua", ".module.lua")

# macOS and Windows ship case-insensitive (or case-preserving) filesystems by
# default. Treating the uniqueness set as case-sensitive on those platforms
# lets a second sibling that differs only by case overwrite the first on disk.
_FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")


def sanitize_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, "_")
    name = name.strip()
    return name or "Unnamed"


def get_script_extension(class_name: str) -> str:
    if class_name == "LocalScript":
        return ".local.lua"
    if class_name == "ModuleScript":
        return ".module.lua"
    return ".lua"


def _parse_children(elem: ET.Element) -> dict[str, Any]:
    """Parse child elements, preserving order and multiples of the same tag as lists."""
    children: dict[str, Any] = {}
    for child in elem:
        if len(child) == 0 and not child.attrib:
            val: Any = child.text if child.text is not None else ""
        else:
            sub = _parse_children(child)
            if child.attrib:
                if not isinstance(sub, dict):
                    sub = {"_value": sub} if sub else {}
                sub = dict(sub)
                sub["_attrs"] = dict(child.attrib)
            val = sub if sub else (child.text if child.text is not None else "")

        if child.tag in children:
            existing = children[child.tag]
            if not isinstance(existing, list):
                children[child.tag] = [existing]
            children[child.tag].append(val)
        else:
            children[child.tag] = val
    return children


def _parse_property_element(prop: ET.Element) -> dict[str, Any]:
    """Convert a single <Type name=\"...\">...</Type> element into a structured dict."""
    tag = prop.tag
    result: dict[str, Any] = {"type": tag}

    if tag in (
        "string",
        "ProtectedString",
        "bool",
        "int",
        "int64",
        "float",
        "double",
        "token",
        "BinaryString",
        "Content",
        "SharedString",
        "Ref",
        "UniqueId",
        "BrickColor",
    ):
        result["value"] = prop.text if prop.text is not None else ""
        return result

    children = _parse_children(prop)
    if children:
        result["children"] = children
    else:
        result["value"] = prop.text if prop.text is not None else ""

    return result


def extract_properties(
    item: ET.Element, interesting: set[str]
) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    """Parse all Properties of an Item.

    Returns:
      flat: interesting string-like values for search/replace convenience
      tags: decoded CollectionService tags (list)
      full: complete structured property map for lossless rebuild
      attributes: decoded Instance Attributes map
    """
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

        structured = _parse_property_element(prop)
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
            if decoded:  # only promote when we actually got attributes
                attributes = decoded
                full.pop("AttributesSerialize", None)
            # else: leave the raw BinaryString in full so a rebuild re-emits it
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
    """Resolve the Instance Name for filesystem paths and meta.

    Real Roblox Studio .rbxlx files encode Name only as a property
    (<string name=\"Name\">...</string>). The Item@name attribute is absent.
    Some tools (including Verde build) also emit Item@name; prefer the
    property when present, then the attribute, then \"Unnamed\".
    """
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


def _compute_keep_map(items: list[ET.Element]) -> dict[int, bool]:
    """Bottom-up: mark every Item that is a script or has a script descendant.

    Used by the default (scripts-only) path so we never mkdir a directory that
    would later be empty. id(item) is stable for the lifetime of the ElementTree.

    Iterative post-order walk (explicit stack) so deep places cannot hit the
    Python recursion limit.
    """
    keep: dict[int, bool] = {}
    # (item, children_done)
    stack: list[tuple[ET.Element, bool]] = []
    for it in items:
        stack.append((it, False))

    while stack:
        item, children_done = stack.pop()
        if item.tag != "Item":
            continue

        if not children_done:
            # Re-push as "children done", then push children so they run first.
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
        keep[id(item)] = is_script or has_kept_child

    return keep


def _prune_empty_dirs(root: Path) -> int:
    """Remove directories that contain nothing (no files, no subdirs).

    Post-order iterative walk. The root itself is never removed.
    Returns number of dirs removed. Guarantees the invariant "only maintain a
    folder if it has children" in every mode.
    """
    removed = 0
    # (path, children_visited)
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
            # After children have been processed (and possibly removed), check emptiness.
            if not any(dir_path.iterdir()):
                dir_path.rmdir()
                removed += 1
        except OSError:
            pass

    return removed


def _confirm_overwrite(path: Path) -> bool:
    """Prompt the user whether to overwrite a differing file. Default is yes."""
    while True:
        try:
            ans = input(f"  Diff at {path} — overwrite? [Y/n] ").strip().lower()
        except EOFError:
            # Non-interactive stdin (piped / CI): fall back to overwrite.
            return True
        if ans in ("", "y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer Y or n")


def _maybe_write(path: Path, content: str, interactive: bool) -> str:
    """Write *content* to *path* only when needed.

    Returns one of:
      "written"   — file was created or content changed and was written
      "unchanged" — existing file already had identical content
      "skipped"   — interactive mode and user declined overwrite
    """
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


def extract(
    rbxlx_path: str,
    output_dir: str = "extracted",
    interesting: set[str] | None = None,
    scripts_only: bool = True,
    interactive: bool = False,
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

    keep_map: dict[int, bool] | None = None
    if scripts_only:
        top_items = [c for c in root if c.tag == "Item"]
        keep_map = _compute_keep_map(top_items)

    # Per-parent set of base names *assigned during this export run*.
    # Pre-existing paths on disk are intentionally *not* seeded here so a
    # re-export reuses the same path instead of inventing Name_2 / Name_3.
    # True sibling collisions within the place (two instances, same Name)
    # still uniquify so both can be represented on disk.
    # On case-insensitive filesystems the keys are casefolded so "Foo"/"foo"
    # cannot silently overwrite each other.
    used_names: dict[Path, set[str]] = {}

    # Iterative DFS (explicit stack) so deep place hierarchies cannot hit the
    # default Python recursion limit, and so we can emit progress while walking
    # large Workspace subtrees under --all.
    # Seed with top-level Items in reverse so LIFO yields document order.
    stack: list[tuple[ET.Element, Path]] = []
    for top in reversed(list(root.findall("Item"))):
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
            _record(_maybe_write(meta_path, json.dumps(meta, indent=2), interactive))
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
                # push reversed so children are processed in document order
                for child in reversed(child_items):
                    stack.append((child, full_path))
            continue

        # Non-script
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

        _record(
            _maybe_write(
                full_path / ".robloxmeta.json",
                json.dumps(meta, indent=2),
                interactive,
            )
        )

        # push reversed so children are processed in document order
        for child in reversed(list(item)):
            stack.append((child, full_path))

    # Final safety net for both modes: never leave empty directories
    pruned = _prune_empty_dirs(out)

    if scripts_only:
        print(f"Export complete → {out}/  (scripts-only)")
    else:
        print(f"Export complete → {out}/  (--all)")
    print(f"  Instances : {instance_count}")
    print(f"  Scripts   : {script_count}")
    print(f"  Wrote     : {written_count}")
    if unchanged_count:
        print(f"  Unchanged : {unchanged_count}")
    if skipped_count:
        print(f"  Skipped   : {skipped_count} (interactive)")
    if pruned:
        print(f"  Empty dirs removed: {pruned}")

    # Touched-file tracking: record simple numeric hashes + mtimes so later
    # import / verde-sync can skip unchanged work and apply mtime-wins.
    try:
        from features.sync import write_manifest

        write_manifest(out, rbxlx_path=rbxlx_path)
        print(f"  Manifest  : {out / '.verde' / 'manifest.json'}")
    except Exception as exc:
        print(f"  (manifest not written: {exc})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export a Roblox .rbxlx into a searchable/editable folder tree "
            "(alias: verde-extract). Existing paths are reused; files are "
            "overwritten only when content differs."
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
    )


if __name__ == "__main__":
    main()
