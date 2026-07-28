#!/usr/bin/env python3
"""
verde test_roundtrip.py

Tests export + build round-trip for .rbxlx files.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def run_extract(input_rbxlx: str, output_dir: str) -> None:
    print(f"[1/4] Exporting {input_rbxlx} ...")
    # --all is required for a complete round-trip (default is now scripts-only)
    try:
        from export import export

        export(input_rbxlx, output_dir, scripts_only=False)
        return
    except ImportError:
        pass

    # Fallback when modules are not on sys.path (e.g. raw source checkout)
    cmd = [
        sys.executable,
        "-m",
        "export",
        input_rbxlx,
        output_dir,
        "--all",
    ]
    rc = subprocess.call(cmd)
    if rc != 0:
        # Last-ditch relative script path (repo root layout)
        script = Path(__file__).resolve().parent / "export.py"
        if script.is_file():
            rc = subprocess.call(
                [sys.executable, str(script), input_rbxlx, output_dir, "--all"]
            )
    if rc != 0:
        raise RuntimeError("export failed")


def run_build(input_dir: str, output_rbxlx: str) -> None:
    print(f"[2/4] Rebuilding into {output_rbxlx} ...")
    try:
        from build import build_rbxlx

        build_rbxlx(input_dir, output_rbxlx)
        return
    except ImportError:
        pass

    cmd = [sys.executable, "-m", "build", input_dir, output_rbxlx]
    rc = subprocess.call(cmd)
    if rc != 0:
        script = Path(__file__).resolve().parent / "build.py"
        if script.is_file():
            rc = subprocess.call([sys.executable, str(script), input_dir, output_rbxlx])
    if rc != 0:
        raise RuntimeError("build failed")


def _resolve_name(item: ET.Element) -> str:
    """Mirror export._resolve_name / build._resolve_item_name.

    Real Studio .rbxlx files put Name only as a property; the Item@name
    attribute is usually absent. Prefer the property, then the attribute,
    then "Unnamed".
    """
    props = item.find("Properties")
    if props is not None:
        for p in props:
            if p.get("name") == "Name" and p.text is not None and p.text != "":
                return p.text
    attr = item.get("name")
    if attr:
        return attr
    return "Unnamed"


def _decode_tags_prop(prop: ET.Element) -> list[str]:
    """Decode a Tags property the same way export does."""
    text = (prop.text or "").strip()
    if not text:
        return []
    if prop.tag == "BinaryString":
        raw = text.replace("\n", "").replace(" ", "")
        try:
            data = base64.b64decode(raw)
            return [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
        except Exception:
            pass
    # string / ProtectedString or decode fallback
    return [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]


def collect_structure(rbxlx_path: str) -> dict:
    tree = ET.parse(rbxlx_path)
    root = tree.getroot()

    instances: list[dict] = []
    scripts = 0

    def walk(item: ET.Element, path: str) -> None:
        nonlocal scripts
        if item.tag != "Item":
            return
        class_name = item.get("class", "?")
        name = _resolve_name(item)
        full = f"{path}/{name}" if path else name
        referent = item.get("referent")  # may be None

        props: dict[str, str] = {}
        tags: list[str] = []
        props_elem = item.find("Properties")
        if props_elem is not None:
            for prop in props_elem:
                pname = prop.get("name")
                if not pname:
                    continue
                if pname == "Tags":
                    tags = _decode_tags_prop(prop)
                elif prop.tag in ("string", "ProtectedString", "Content", "token", "BinaryString"):
                    # Skip AttributesSerialize — it is intentionally transformed
                    if pname != "AttributesSerialize":
                        props[pname] = (prop.text or "")[:200]
                elif prop.tag in ("bool", "int", "float", "double"):
                    props[pname] = prop.text or ""

        instances.append(
            {
                "path": full,
                "class": class_name,
                "name": name,
                "referent": referent,
                "tags": sorted(tags),
                "props": {k: props[k] for k in sorted(props) if k != "Source"},
            }
        )
        if class_name in ("Script", "LocalScript", "ModuleScript"):
            scripts += 1

        for child in item:
            walk(child, full)

    for top in root.findall("Item"):
        walk(top, "")

    return {
        "instance_count": len(instances),
        "script_count": scripts,
        "instances": instances,
    }


def compare_structures(orig: dict, rebuilt: dict) -> list[str]:
    diffs: list[str] = []
    if orig["instance_count"] != rebuilt["instance_count"]:
        diffs.append(
            f"Instance count: {orig['instance_count']} → {rebuilt['instance_count']}"
        )
    if orig["script_count"] != rebuilt["script_count"]:
        diffs.append(
            f"Script count: {orig['script_count']} → {rebuilt['script_count']}"
        )

    # Prefer Referent (stable unique ID emitted by Studio). Fall back to path
    # only for the minority of instances that lack a referent. This eliminates
    # false "Extra" / "Missing" caused by non-unique Name paths.
    orig_by_ref: dict[str, dict] = {}
    orig_by_path: dict[str, dict] = {}
    for i in orig["instances"]:
        if i["referent"]:
            orig_by_ref[i["referent"]] = i
        else:
            # last-wins for path collisions among no-ref instances
            orig_by_path[i["path"]] = i

    rebuilt_by_ref: dict[str, dict] = {}
    rebuilt_by_path: dict[str, dict] = {}
    for i in rebuilt["instances"]:
        if i["referent"]:
            rebuilt_by_ref[i["referent"]] = i
        else:
            rebuilt_by_path[i["path"]] = i

    missing_refs = set(orig_by_ref) - set(rebuilt_by_ref)
    extra_refs = set(rebuilt_by_ref) - set(orig_by_ref)
    missing_paths = set(orig_by_path) - set(rebuilt_by_path)
    extra_paths = set(rebuilt_by_path) - set(orig_by_path)

    if missing_refs or missing_paths:
        total = len(missing_refs) + len(missing_paths)
        samples: list[str] = []
        for ref in sorted(missing_refs)[:6]:
            inst = orig_by_ref[ref]
            samples.append(f"{inst['path']} ({inst['class']}, ref={ref[:12]}…)")
        for p in sorted(missing_paths)[: 6 - len(samples)]:
            inst = orig_by_path[p]
            samples.append(f"{p} ({inst['class']}, no-ref)")
        diffs.append(
            f"Missing after rebuild ({total}): {samples}"
            + (" ..." if total > len(samples) else "")
        )

    if extra_refs or extra_paths:
        total = len(extra_refs) + len(extra_paths)
        samples = []
        for ref in sorted(extra_refs)[:6]:
            inst = rebuilt_by_ref[ref]
            samples.append(f"{inst['path']} ({inst['class']}, ref={ref[:12]}…)")
        for p in sorted(extra_paths)[: 6 - len(samples)]:
            inst = rebuilt_by_path[p]
            samples.append(f"{p} ({inst['class']}, no-ref)")
        diffs.append(
            f"Extra after rebuild ({total}): {samples}"
            + (" ..." if total > len(samples) else "")
        )

    # Property / class / tag checks only on instances that matched by referent
    # (or by path for the no-ref remainder).
    matched: list[tuple[dict, dict]] = []
    for ref, o in orig_by_ref.items():
        if ref in rebuilt_by_ref:
            matched.append((o, rebuilt_by_ref[ref]))
    for path, o in orig_by_path.items():
        if path in rebuilt_by_path:
            matched.append((o, rebuilt_by_path[path]))

    for o, r in matched:
        label = o["path"]
        if o["class"] != r["class"]:
            diffs.append(f"{label}: ClassName {o['class']!r} → {r['class']!r}")
        if o["name"] != r["name"]:
            diffs.append(f"{label}: Name {o['name']!r} → {r['name']!r}")
        if o["tags"] != r["tags"]:
            diffs.append(f"{label}: Tags {o['tags']} → {r['tags']}")
        o_keys = set(o["props"])
        r_keys = set(r["props"])
        lost = sorted(o_keys - r_keys)
        # AttributesSerialize is intentionally transformed (or preserved as raw);
        # never report it as a loss.
        lost = [k for k in lost if k != "AttributesSerialize"]
        if lost:
            diffs.append(f"{label}: lost properties {lost}")

    return diffs


def test_roundtrip(original_rbxlx: str, keep: bool = False) -> bool:
    if not os.path.isfile(original_rbxlx):
        print(f"Error: File not found: {original_rbxlx}")
        return False

    print("=" * 60)
    print("ROBLOX .RBXLX ROUNDTRIP TEST")
    print("=" * 60)

    if keep:
        test_dir = Path("roundtrip_test")
        test_dir.mkdir(exist_ok=True)
    else:
        test_dir = Path(tempfile.mkdtemp(prefix="verde_roundtrip_"))

    copy_rbxlx = test_dir / "original_copy.rbxlx"
    extracted_dir = test_dir / "extracted"
    rebuilt_rbxlx = test_dir / "rebuilt.rbxlx"

    shutil.copy2(original_rbxlx, copy_rbxlx)

    try:
        run_extract(str(copy_rbxlx), str(extracted_dir))
        run_build(str(extracted_dir), str(rebuilt_rbxlx))

        print("\n[3/4] Structural comparison...")
        orig_struct = collect_structure(str(copy_rbxlx))
        rebuilt_struct = collect_structure(str(rebuilt_rbxlx))
        diffs = compare_structures(orig_struct, rebuilt_struct)

        print("\n[4/4] Byte comparison...")
        with open(copy_rbxlx, "rb") as f1, open(rebuilt_rbxlx, "rb") as f2:
            byte_match = f1.read() == f2.read()

        print()
        if not diffs and byte_match:
            print("✅ SUCCESS: Exact byte-identical round-trip!")
            ok = True
        elif not diffs:
            print("✅ SUCCESS: Structural round-trip matched (formatting differs).")
            print("   (This is expected and fine for Studio.)")
            ok = True
        else:
            print("⚠️  Structural differences detected:")
            for d in diffs[:20]:
                print(f"   • {d}")
            if len(diffs) > 20:
                print(f"   ... and {len(diffs) - 20} more")
            ok = False

        print(f"\nInstances: {orig_struct['instance_count']}  Scripts: {orig_struct['script_count']}")
        print(f"Test folder: {test_dir.resolve()}")
        if not keep:
            print("(temporary; will be cleaned on process exit if not --keep)")
        return ok
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Verde export/build round-trip")
    parser.add_argument("rbxlx", help="Path to a .rbxlx place file")
    parser.add_argument(
        "--keep", action="store_true", help="Keep the temporary test directory"
    )
    args = parser.parse_args()
    ok = test_roundtrip(args.rbxlx, keep=args.keep)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
