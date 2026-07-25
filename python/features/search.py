#!/usr/bin/env python3
"""
verde features.search — search an extracted place tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .meta import get_prop_value, matches, walk_metas


def main() -> None:
    parser = argparse.ArgumentParser(description="Search extracted Roblox place for instances")
    parser.add_argument("extracted_dir", help="Path to extracted folder")
    parser.add_argument("--class", dest="class_name", help="Filter by ClassName")
    parser.add_argument("--name", help="Exact Name match")
    parser.add_argument("--name-contains", help="Name contains substring")
    parser.add_argument("--tag", help="Has CollectionService tag")
    parser.add_argument("--prop", help="Property name to inspect")
    parser.add_argument("--contains", dest="prop_contains", help="Property value contains substring")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    results = []
    for meta_path, meta in walk_metas(root):
        if matches(
            meta,
            class_filter=args.class_name,
            name_filter=args.name,
            name_contains=args.name_contains,
            tag_filter=args.tag,
            prop_name=args.prop,
            prop_contains=args.prop_contains,
        ):
            if meta_path.name == ".robloxmeta.json":
                location = meta_path.parent
            else:
                location = meta_path.with_suffix("")
            results.append({"path": str(location.relative_to(root)), "meta": meta})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Found {len(results)} matching instance(s):\n")
        for r in results:
            m = r["meta"]
            tags = m.get("Tags") or []
            tag_str = f"  tags={tags}" if tags else ""
            extra = ""
            if args.prop:
                val = get_prop_value(m, args.prop)
                if val is not None:
                    extra = f"  {args.prop}={val!r}"
            print(f"• {r['path']}")
            print(f"    {m.get('ClassName')}  Name={m.get('Name')!r}{tag_str}{extra}")


if __name__ == "__main__":
    main()
