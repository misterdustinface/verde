# Bugs

Known correctness and data-loss issues in verde (**v1.0.0**).
Focus is on extract/import round-trips, Luau live operations, and shared helpers.

---

## Open issues

### 1. Restore does not clear existing tags

`Verde.restoreScripts` currently *adds* the archived tags (from the `Tags` attribute) without first removing any tags already present on the target. Restore therefore merges rather than replaces the tag set. Clearing via `CollectionService:GetTags` + `RemoveTag` before adding the archived set would make restore replace, matching the documented intent and the Python-side tag handling philosophy.

### 2. Tag matching is case-inconsistent (Python vs Luau)

- **Python** `verde-tags --replace` and search filters perform case-insensitive matching (consistent with the rest of the CLI). The original-cased tag is removed and the new tag is added.
- **Luau** `Verde.replaceTag` still uses `CollectionService:HasTag` / `RemoveTag` / `AddTag` with exact (case-sensitive) match. Roblox tags are case-sensitive, so this is intentional for live DataModel fidelity, but it diverges from the Python CLI’s case-insensitive behaviour.

---

## Remaining minor / edge-case notes

- **Name sanitisation vs `GetFullName`** (Luau dump/restore): archive hierarchy uses a limited sanitiser; the preferred restore path uses the original `OriginalFullName`. Fallback relative paths use the sanitised form and can mismatch when names contain the sanitised characters.
- **Tags containing commas** (Luau dump): tags are joined with `","` and later split; a tag that itself contains a comma is corrupted.
- **Child order** is not preserved (Python import sorts `iterdir()`). Usually harmless but prevents byte-identical round-trips.
- **Fragile interesting-props extraction** (`interesting.py`): a simple regex works today but will be polluted by any future double-quoted string in the Luau file.
- **Plugin recording**: no user feedback when `ChangeHistoryService:TryBeginRecording` returns `nil` (playtest, concurrent recording, etc.).
- **Scripts-only default** (export): only directories that lead to scripts are written; empty directories are always pruned (both modes). Use `--all` for the full hierarchy. This is intentional and documented in the README / extract docstring.
- **Attributes**: full binary round-trip for AttributesSerialize is supported; search/filter by attribute and Luau wrappers remain open (see TODO #8).
- **Orphaned uniquified paths**: if a previous export created `Name_2` because of a sibling collision that no longer exists, a later re-export will write to `Name` and leave the old `Name_2` on disk. Empty-dir prune does not remove non-empty leftovers.

---

## Previously corrected issues (for reference)

These correctness problems were fixed during development and are no longer present:

1. Children of scripts are now extracted (companion directory under the script).
2. Duplicate Names under the same parent are uniquified on disk; existing paths are reused on re-export.
3. Complex properties with repeated child tags (NumberSequence, ColorSequence, etc.) round-trip completely.
4. Duplicate `<Tags>` elements no longer appear on rebuild.
5. `set_prop_value` refuses non-scalar properties that contain a `"children"` dict.
6. Extract prefers the `Name` property over a missing `Item@name` attribute (real Studio .rbxlx format).
7. `replaceProp` candidate selection vs final check mismatch (Luau) — FIXED
   The final equality check in `Verde.replaceProp` is now case-insensitive (`lower(tostring(current)) == lower(oldValue)`), consistent with `Verde.search` and the Python CLI.

---

*Open items are the restore tag replacement behaviour, and the intentional Python/Luau tag case divergence. Everything else listed above is resolved in the current tree.*
