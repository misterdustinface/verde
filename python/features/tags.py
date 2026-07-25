#!/usr/bin/env python3
"""
verde features.tags — list or replace CollectionService tags across an extracted place tree.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from .meta import save_meta, walk_metas


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage CollectionService tags in extracted tree")
    parser.add_argument("extracted_dir")
    parser.add_argument("--list", action="store_true", help="List all tags and where they appear")
    parser.add_argument("--replace", nargs=2, metavar=("OLD", "NEW"), help="Replace tag OLD with NEW (case-insensitive match)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    if args.list:
        tag_map: dict[str, list[str]] = defaultdict(list)
        for meta_path, meta in walk_metas(root):
            for t in meta.get("Tags") or []:
                tag_map[t].append(str(meta_path.relative_to(root)))

        print(f"Found {len(tag_map)} unique tag(s):\n")
        for tag, locs in sorted(tag_map.items()):
            print(f"• {tag}  ({len(locs)} instance(s))")
            for loc in locs[:5]:
                print(f"    {loc}")
            if len(locs) > 5:
                print(f"    ... and {len(locs)-5} more")
        return

    if args.replace:
        old, new = args.replace
        old_lower = old.lower()
        changed = 0
        for meta_path, meta in walk_metas(root):
            tags = meta.get("Tags") or []
            matched = False
            new_tags = []
            for t in tags:
                if str(t).lower() == old_lower:
                    new_tags.append(new)
                    matched = True
                else:
                    new_tags.append(t)
            if matched:
                print(
                    f"{'[dry-run] ' if args.dry_run else ''}{meta_path.relative_to(root)}: "
                    f"tag {old!r} → {new!r}"
                )
                if not args.dry_run:
                    meta["Tags"] = new_tags
                    save_meta(meta_path, meta)
                changed += 1
        print(f"\n{'Would change' if args.dry_run else 'Changed'} {changed} instance(s).")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
