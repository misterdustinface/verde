"""--all / --delete / --rename must not wipe real *_N assets.

Referent lives in gitignored local.json, so identity has to work from
shared UniqueId and from meta Name == path stem.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import build
import extract


def _write_place(tmp_path: Path) -> Path:
    place_xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<roblox version=\"4\">
  <Item class=\"Workspace\" name=\"Workspace\" referent=\"RBX1\">
    <Properties>
      <string name=\"Name\">Workspace</string>
    </Properties>
    <Item class=\"Part\" name=\"Part\" referent=\"RBX2\">
      <Properties>
        <string name=\"Name\">Part</string>
        <string name=\"UniqueId\">uid-part</string>
      </Properties>
    </Item>
    <Item class=\"Part\" name=\"Part_2\" referent=\"RBX3\">
      <Properties>
        <string name=\"Name\">Part_2</string>
        <string name=\"UniqueId\">uid-part-2</string>
      </Properties>
    </Item>
    <Item class=\"Folder\" name=\"Utility\" referent=\"RBX4\">
      <Properties>
        <string name=\"Name\">Utility</string>
        <string name=\"UniqueId\">uid-util</string>
      </Properties>
    </Item>
  </Item>
</roblox>
"""
    place = tmp_path / "TheGame.rbxlx"
    place.write_text(place_xml, encoding="utf-8")
    return place


def _names(place: Path) -> set[str]:
    tree = ET.parse(place)
    return {item.get("name") or "" for item in tree.iter("Item")}


def test_all_delete_keeps_real_part_2_without_referent(tmp_path: Path):
    """--all tree + --delete must not drop a real Part_2 when Referent is absent."""
    place = _write_place(tmp_path)
    folder = tmp_path / "hubbub"
    ws = folder / "Workspace"
    part = ws / "Part"
    part2 = ws / "Part_2"
    part.mkdir(parents=True)
    part2.mkdir(parents=True)
    (ws / ".robloxmeta.json").write_text(
        json.dumps({"ClassName": "Workspace", "Name": "Workspace"}),
        encoding="utf-8",
    )
    (part / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Part",
                "Name": "Part",
                "Properties": {"UniqueId": {"type": "UniqueId", "value": "uid-part"}},
            }
        ),
        encoding="utf-8",
    )
    (part2 / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Part",
                "Name": "Part_2",
                "Properties": {"UniqueId": {"type": "UniqueId", "value": "uid-part-2"}},
            }
        ),
        encoding="utf-8",
    )
    util = ws / "Utility"
    util.mkdir()
    (util / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Folder",
                "Name": "Utility",
                "Properties": {"UniqueId": {"type": "UniqueId", "value": "uid-util"}},
            }
        ),
        encoding="utf-8",
    )

    build.import_rbxlx(
        str(folder),
        str(place),
        force=True,
        scripts_only=False,
        no_delete=False,
        no_rename=False,
    )

    names = _names(place)
    assert "Part" in names
    assert "Part_2" in names
    assert "Utility" in names


def test_uid_matches_when_path_was_remapped(tmp_path: Path):
    """UniqueId match still updates the right instance if the folder was renamed."""
    place = _write_place(tmp_path)
    folder = tmp_path / "hubbub"
    dest = folder / "Workspace" / "MovedPart"
    dest.mkdir(parents=True)
    (dest / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Part",
                "Name": "MovedPart",
                "Properties": {
                    "UniqueId": {"type": "UniqueId", "value": "uid-part-2"},
                    "Name": {"type": "string", "value": "MovedPart"},
                },
            }
        ),
        encoding="utf-8",
    )

    build.import_rbxlx(
        str(folder),
        str(place),
        force=True,
        scripts_only=False,
        no_delete=True,
        no_rename=True,
    )

    tree = ET.parse(place)
    matched = None
    for item in tree.iter("Item"):
        props = item.find("Properties")
        if props is None:
            continue
        for p in props:
            if p.get("name") == "UniqueId" and (p.text or "") == "uid-part-2":
                matched = item
                break
    assert matched is not None
    assert matched.get("name") == "MovedPart"


def test_rename_does_not_delete_folder_on_1to1_class(tmp_path: Path):
    """--rename must not treat one new Folder as a rename of an unmatched Folder."""
    place = _write_place(tmp_path)
    folder = tmp_path / "hubbub"
    arcade = folder / "Workspace" / "Arcade"
    arcade.mkdir(parents=True)
    (arcade / ".robloxmeta.json").write_text(
        json.dumps({"ClassName": "Folder", "Name": "Arcade"}),
        encoding="utf-8",
    )

    build.import_rbxlx(
        str(folder),
        str(place),
        force=True,
        scripts_only=False,
        no_delete=True,
        no_rename=False,
    )

    names = _names(place)
    assert "Utility" in names
    assert "Arcade" in names


def test_all_export_keeps_real_named_n_sibling(tmp_path: Path):
    place = _write_place(tmp_path)
    out = tmp_path / "extracted"
    extract.extract(str(place), str(out), scripts_only=False)
    assert (out / "Workspace" / "Part_2" / ".robloxmeta.json").is_file()

    extract.extract(str(place), str(out), scripts_only=False)
    assert (out / "Workspace" / "Part_2" / ".robloxmeta.json").is_file()
