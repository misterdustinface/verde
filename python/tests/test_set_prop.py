"""Tests for unconditional set-by-tag / set-by-class and conditional replace."""

from __future__ import annotations

import json
from pathlib import Path

import export
from features.meta import get_prop_value, set_prop_value, matches, walk_metas


def _write_tree(tmp_path: Path) -> Path:
    """Build a small extracted tree with two Parts (one tagged) and a MeshPart."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Part" name="TaggedPart">
    <Properties>
      <bool name="CastShadow">true</bool>
      <bool name="Anchored">false</bool>
      <BinaryString name="Tags">Tm9TaGFkb3cA</BinaryString>
    </Properties>
  </Item>
  <Item class="Part" name="PlainPart">
    <Properties>
      <bool name="CastShadow">true</bool>
      <bool name="Anchored">false</bool>
    </Properties>
  </Item>
  <Item class="MeshPart" name="AMesh">
    <Properties>
      <bool name="CastShadow">true</bool>
      <float name="Transparency">0</float>
    </Properties>
  </Item>
</roblox>
"""
    import base64
    raw = b"NoShadow\0"
    b64 = base64.b64encode(raw).decode("ascii")
    xml = xml.replace("Tm9TaGFkb3cA", b64)

    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))
    return out


def test_set_by_tag(tmp_path: Path):
    root = _write_tree(tmp_path)
    changed = 0
    for meta_path, meta in walk_metas(root):
        if not matches(meta, tag_filter="NoShadow"):
            continue
        if set_prop_value(meta, "CastShadow", "false"):
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            changed += 1

    assert changed == 1
    tagged = json.loads((root / "TaggedPart" / ".robloxmeta.json").read_text())
    plain = json.loads((root / "PlainPart" / ".robloxmeta.json").read_text())
    assert get_prop_value(tagged, "CastShadow") == "false"
    assert get_prop_value(plain, "CastShadow") == "true"


def test_set_by_class(tmp_path: Path):
    root = _write_tree(tmp_path)
    changed = 0
    for meta_path, meta in walk_metas(root):
        if not matches(meta, class_filter="MeshPart"):
            continue
        if set_prop_value(meta, "Transparency", "1"):
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            changed += 1

    assert changed == 1
    mesh = json.loads((root / "AMesh" / ".robloxmeta.json").read_text())
    assert get_prop_value(mesh, "Transparency") == "1"
    part = json.loads((root / "PlainPart" / ".robloxmeta.json").read_text())
    assert get_prop_value(part, "CastShadow") == "true"


def test_set_all_parts_anchored(tmp_path: Path):
    root = _write_tree(tmp_path)
    changed = 0
    for meta_path, meta in walk_metas(root):
        if not matches(meta, class_filter="Part"):
            continue
        if set_prop_value(meta, "Anchored", "true"):
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            changed += 1

    assert changed == 2
    for name in ("TaggedPart", "PlainPart"):
        m = json.loads((root / name / ".robloxmeta.json").read_text())
        assert get_prop_value(m, "Anchored") == "true"


def test_conditional_replace_still_works(tmp_path: Path):
    root = _write_tree(tmp_path)
    changed = 0
    for meta_path, meta in walk_metas(root):
        if set_prop_value(meta, "CastShadow", "false", only_if_old="true"):
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            changed += 1

    assert changed == 3
