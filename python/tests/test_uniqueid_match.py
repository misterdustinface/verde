"""UniqueId is preferred over path when Referent is absent.

Prevents same-Name siblings from cross-applying Color/CFrame on differential
import when machine-local *.robloxmeta.local.json (Referent) is missing.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import build


def test_uniqueid_match_prevents_same_name_color_swap(tmp_path: Path):
    """Two Parts named Seat with distinct UniqueIds and Colors.

    Folder layout uses path Seat / Seat_2. Place XML has the opposite child
    order so path-only matching would cross them. UniqueId must win.
    """
    # Place: first child is blue Seat (uid-B), second is red Seat (uid-R)
    place_xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<roblox version=\"4\">
  <Item class=\"Model\" name=\"Chair\">
    <Properties>
      <string name=\"Name\">Chair</string>
    </Properties>
    <Item class=\"Part\" name=\"Seat\" referent=\"RBX_BLUE\">
      <Properties>
        <string name=\"Name\">Seat</string>
        <UniqueId name=\"UniqueId\">uid-blue</UniqueId>
        <Color3 name=\"Color\">
          <R>0</R><G>0</G><B>1</B>
        </Color3>
      </Properties>
    </Item>
    <Item class=\"Part\" name=\"Seat\" referent=\"RBX_RED\">
      <Properties>
        <string name=\"Name\">Seat</string>
        <UniqueId name=\"UniqueId\">uid-red</UniqueId>
        <Color3 name=\"Color\">
          <R>1</R><G>0</G><B>0</B>
        </Color3>
      </Properties>
    </Item>
  </Item>
</roblox>
"""
    place = tmp_path / "place.rbxlx"
    place.write_text(place_xml, encoding="utf-8")

    # Extracted folder: path Seat = red (uid-red), Seat_2 = blue (uid-blue)
    # Opposite of place child order → path-only match would swap colors.
    extracted = tmp_path / "extracted"
    chair = extracted / "Chair"
    seat = chair / "Seat"
    seat2 = chair / "Seat_2"
    for d in (chair, seat, seat2):
        d.mkdir(parents=True)

    (chair / ".robloxmeta.json").write_text(
        json.dumps({"ClassName": "Model", "Name": "Chair", "Tags": [], "Properties": {}}),
        encoding="utf-8",
    )
    (seat / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Part",
                "Name": "Seat",
                "Tags": [],
                "Properties": {
                    "UniqueId": {"type": "UniqueId", "value": "uid-red"},
                    "Color": {
                        "type": "Color3",
                        "children": {"R": "1", "G": "0", "B": "0"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (seat2 / ".robloxmeta.json").write_text(
        json.dumps(
            {
                "ClassName": "Part",
                "Name": "Seat",
                "Tags": [],
                "Properties": {
                    "UniqueId": {"type": "UniqueId", "value": "uid-blue"},
                    "Color": {
                        "type": "Color3",
                        "children": {"R": "0", "G": "0", "B": "1"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    build.import_rbxlx(str(extracted), str(place), force=True)

    tree = ET.parse(place)
    parts = [el for el in tree.findall(".//Item") if el.get("class") == "Part"]
    assert len(parts) == 2

    by_uid = {}
    for p in parts:
        props = p.find("Properties")
        uid = None
        color = None
        for prop in props:
            if prop.get("name") == "UniqueId":
                uid = (prop.text or "").strip()
            if prop.get("name") == "Color" and prop.tag == "Color3":
                color = {c.tag: (c.text or "") for c in prop}
        by_uid[uid] = color

    # Colors must stay with their UniqueId, not follow inverted path order
    assert by_uid["uid-red"] == {"R": "1", "G": "0", "B": "0"}
    assert by_uid["uid-blue"] == {"R": "0", "G": "0", "B": "1"}
