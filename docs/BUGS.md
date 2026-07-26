# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES #11), not silent case-folding of the final value.

---

## Open issues

### 1. Restore does not clear existing tags

`Verde.restoreScripts` currently *adds* the archived tags (from the `Tags` attribute) without first removing any tags already present on the target. Restore therefore merges rather than replaces the tag set. Clearing via `CollectionService:GetTags` + `RemoveTag` before adding the archived set would make restore replace, matching the documented intent and the Python-side tag handling philosophy.

**Impact**  
Correctness / data fidelity on restore.

---

## Intentional design (not bugs)

These behaviours are deliberate and should not be “fixed” without an explicit product decision:

- **Case-sensitive final checks for properties and tags (Luau)**  
  `Verde.replaceProp` uses exact `tostring(current) == oldValue`. `Verde.replaceTag` uses exact `CollectionService:HasTag` / `RemoveTag` / `AddTag`. This matches Roblox’s own case-sensitive semantics and is considered an important feature.

- **Case-insensitive discovery filters**  
  `Verde.search` (and the Python CLI search/tag filters) treat nameContains / propContains / tag filters case-insensitively so users can locate instances more easily. This is discovery-only; final mutation remains exact-case.

- **Python CLI vs Luau divergence on tags**  
  The offline Python path (`verde-tags --replace`, search filters) currently performs case-insensitive matching for convenience. The live Luau path stays case-sensitive. This split is accepted; aligning Python toward exact-case (or adding an explicit `--ignore-case` flag) can be tracked as a future enhancement if desired, but is not treated as a defect.

- **Scripts-only default on export**  
  Only directories that lead to scripts are written; empty directories are pruned. Use `--all` for the full hierarchy. Documented and intentional.

---

## Remaining minor / edge-case notes

- **Name sanitisation vs `GetFullName`** (Luau dump/restore): archive hierarchy uses a limited sanitiser; the preferred restore path uses the original `OriginalFullName`. Fallback relative paths use the sanitised form and can mismatch when names contain the sanitised characters.
- **Tags containing commas** (Luau dump): tags are joined with `","` and later split; a tag that itself contains a comma is corrupted.
- **Child order** is not preserved (Python import sorts `iterdir()`). Usually harmless but prevents byte-identical round-trips.
- **Fragile interesting-props extraction** (`interesting.py`): a simple regex works today but will be polluted by any future double-quoted string in the Luau file.
- **Plugin recording**: no user feedback when `ChangeHistoryService:TryBeginRecording` returns `nil` (playtest, concurrent recording, etc.).
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

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES #11.*
