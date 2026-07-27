#!/usr/bin/env python3
"""
verde features.set_replace — set or replace any property across an extracted place tree.

Final replace checks remain exact-case (intentional). When --from yields multiple
original-cased values that collide under case-folding, --interactive surfaces the
list so the user can pick which exact value(s) to rewrite.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from .meta import matches, set_prop_value, walk_metas, save_meta, get_prop_value, prompt_choices


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Set or replace property values (by tag, ClassName, or current value). "
            "Replace uses exact string equality; --interactive resolves case ambiguity."
        )
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
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Treat --from as a case-insensitive discovery key (still exact final write)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="When multiple case variants of --from exist, prompt which to rewrite",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only show what would change")
    args = parser.parse_args()

    root = Path(args.extracted_dir)
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    # First pass: collect matching metas and (when --from) group by exact current value
    matched: list[tuple[Path, dict]] = []
    value_groups: dict[str, list[tuple[Path, dict]]] = defaultdict(list)

    for meta_path, meta in walk_metas(root):
        if not matches(
            meta,
            class_filter=args.class_name,
            name_filter=args.name,
            name_contains=args.name_contains,
            tag_filter=args.tag,
        ):
            continue
        matched.append((meta_path, meta))
        if args.old is not None:
            cur = get_prop_value(meta, args.prop)
            if cur is None:
                continue
            cur_s = str(cur)
            if args.ignore_case:
                if cur_s.lower() == args.old.lower():
                    value_groups[cur_s].append((meta_path, meta))
            else:
                if cur_s == args.old:
                    value_groups[cur_s].append((meta_path, meta))

    if args.old is None:
        # Unconditional set — no ambiguity path
        changed = 0
        for meta_path, meta in matched:
            if set_prop_value(meta, args.prop, args.new, only_if_old=None):
                loc = meta_path.relative_to(root)
                print(f"{'[dry-run] ' if args.dry_run else ''}{loc}: {args.prop} = {args.new!r}")
                if not args.dry_run:
                    save_meta(meta_path, meta)
                changed += 1
        action = "Would change" if args.dry_run else "Changed"
        print(f"\n{action} {changed} occurrence(s).")
        return

    # Conditional replace
    if not value_groups:
        print(f"No instances with {args.prop} matching {args.old!r} found.")
        return

    variants = sorted(
        ((val, len(locs)) for val, locs in value_groups.items()),
        key=lambda x: (-x[1], x[0]),
    )

    to_replace: list[str]
    if len(variants) == 1:
        to_replace = [variants[0][0]]
    elif args.interactive or (sys.stdin.isatty() and args.ignore_case):
        to_replace = prompt_choices(variants, f"values of {args.prop}")
        if not to_replace:
            print("Cancelled.")
            return
    else:
        print(
            f"Ambiguous case variants for {args.prop}={args.old!r} "
            f"(use --interactive or supply an exact --from):",
            file=sys.stderr,
        )
        for val, count in variants:
            print(f"  {val!r}  ({count} instance(s))", file=sys.stderr)
        sys.exit(2)

    changed = 0
    for exact_old in to_replace:
        for meta_path, meta in value_groups[exact_old]:
            if set_prop_value(meta, args.prop, args.new, only_if_old=exact_old):
                loc = meta_path.relative_to(root)
                print(
                    f"{'[dry-run] ' if args.dry_run else ''}{loc}: "
                    f"{args.prop} {exact_old!r} → {args.new!r}"
                )
                if not args.dry_run:
                    save_meta(meta_path, meta)
                changed += 1

    action = "Would change" if args.dry_run else "Changed"
    print(f"\n{action} {changed} occurrence(s).")


if __name__ == "__main__":
    main()
