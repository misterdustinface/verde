#!/usr/bin/env python3
"""
verde features.tags — list or replace CollectionService tags across an extracted place tree.

Final tag mutations are exact-case by design (Roblox is case-sensitive).
Case-insensitive matching is available only as a discovery aid; when several
original-cased values fold to the same key, interactive mode surfaces the
ambiguity so the user can pick.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from .meta import save_meta, walk_metas


def _prompt_choices(variants: list[tuple[str, int]], label: str) -> list[str]:
    """Present numbered list of (value, count) and return the chosen exact values."""
    print(f"\nAmbiguous {label} (differ only by case):")
    for i, (val, count) in enumerate(variants, 1):
        print(f"  {i}. {val!r}  ({count} instance(s))")
    print("  a. all of the above")
    print("  n. none / cancel")
    while True:
        try:
            raw = input("Choose number(s), 'a', or 'n' [n]: ").strip().lower() or "n"
        except EOFError:
            return []
        if raw in ("n", "none", "cancel", ""):
            return []
        if raw in ("a", "all"):
            return [v for v, _ in variants]
        chosen: list[str] = []
        ok = True
        for part in raw.replace(",", " ").split():
            if not part.isdigit():
                ok = False
                break
            idx = int(part)
            if not (1 <= idx <= len(variants)):
                ok = False
                break
            chosen.append(variants[idx - 1][0])
        if ok and chosen:
            # preserve order, unique
            seen: set[str] = set()
            ordered: list[str] = []
            for c in chosen:
                if c not in seen:
                    seen.add(c)
                    ordered.append(c)
            return ordered
        print("  Invalid choice; try again.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Manage CollectionService tags in extracted tree. "
            "Final replacements are exact-case; use --interactive when "
            "case-insensitive discovery finds multiple variants."
        )
    )
    parser.add_argument("extracted_dir")
    parser.add_argument("--list", action="store_true", help="List all tags and where they appear")
    parser.add_argument(
        "--replace",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Replace tag OLD with NEW (exact match by default)",
    )
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="Treat OLD as a case-insensitive key for discovery (still writes exact NEW)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="When multiple case variants of OLD exist, prompt which to rewrite",
    )
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
                tag_map[str(t)].append(str(meta_path.relative_to(root)))

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
        # Collect exact tags that would be candidates
        # Under exact mode: only the precise string
        # Under --ignore-case: any tag whose lower() matches
        candidates: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
        for meta_path, meta in walk_metas(root):
            tags = meta.get("Tags") or []
            for t in tags:
                t_str = str(t)
                if args.ignore_case:
                    if t_str.lower() == old.lower():
                        candidates[t_str].append((meta_path, meta))
                else:
                    if t_str == old:
                        candidates[t_str].append((meta_path, meta))

        if not candidates:
            print(f"No instances with tag {old!r} found.")
            return

        variants = sorted(
            ((val, len(locs)) for val, locs in candidates.items()),
            key=lambda x: (-x[1], x[0]),
        )

        to_replace: list[str]
        if len(variants) == 1:
            to_replace = [variants[0][0]]
        elif args.interactive or (sys.stdin.isatty() and args.ignore_case):
            # Interactive path when ambiguity + (explicit flag or TTY + ignore-case)
            to_replace = _prompt_choices(variants, "tags")
            if not to_replace:
                print("Cancelled.")
                return
        else:
            # Non-interactive multi-variant: refuse so scripts stay safe
            print(
                f"Ambiguous case variants for {old!r} (use --interactive or supply an exact OLD):",
                file=sys.stderr,
            )
            for val, count in variants:
                print(f"  {val!r}  ({count} instance(s))", file=sys.stderr)
            sys.exit(2)

        changed = 0
        for exact_old in to_replace:
            for meta_path, meta in candidates[exact_old]:
                tags = list(meta.get("Tags") or [])
                new_tags = [new if str(t) == exact_old else t for t in tags]
                if new_tags != tags:
                    print(
                        f"{'[dry-run] ' if args.dry_run else ''}{meta_path.relative_to(root)}: "
                        f"tag {exact_old!r} → {new!r}"
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
