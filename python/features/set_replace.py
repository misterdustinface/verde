#!/usr/bin/env python3
"""
verde features.set_replace — set or replace any property across an extracted place tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .meta import matches, set_prop_value, walk_metas, save_meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set or replace property values (by tag, ClassName, or current value)"
    )
    parser.add_argument("extracted_dir", help="Path to extracted folder")
    parser.add_argument("--prop", required=True, help="Property name (CastShadow, SoundId, Anchored, …)")
    parser.add_argument("--to", dest="new", required=True, help="New value to set")
    parser.add_argument(
        "--from",
        dest="old",
        default=None,
        help="Only change instances whose current value equals this (omit for unconditional set)",
    )
    parser.add_argument("--tag", help="Only instances with this CollectionService tag")
    parser.add_argument("--class", dest="class_name", help="Only instances of this ClassName (Part, MeshPart, …)")
    parser.add_argument("--name", help="Exact Name match")
    parser.add_argument("--name-contains", help="Name contains substring")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would change")
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    changed = 0
    for meta_path, meta in walk_metas(root):
        if not matches(
            meta,
            class_filter=args.class_name,
            name_filter=args.name,
            name_contains=args.name_contains,
            tag_filter=args.tag,
        ):
            continue

        if set_prop_value(meta, args.prop, args.new, only_if_old=args.old):
            loc = meta_path.relative_to(root)
            mode = f"{args.old!r} → {args.new!r}" if args.old is not None else f"= {args.new!r}"
            print(f"{'[dry-run] ' if args.dry_run else ''}{loc}: {args.prop} {mode}")
            if not args.dry_run:
                save_meta(meta_path, meta)
            changed += 1

    action = "Would change" if args.dry_run else "Changed"
    print(f"\n{action} {changed} occurrence(s).")


if __name__ == "__main__":
    main()
