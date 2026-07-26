# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES), not silent case-folding of the final value.

---

## Open issues

### 1. Luau dump/restore corrupts tags that contain commas

`Verde.dumpScripts` stores tags via `table.concat(tags, ",")` into a string attribute. Restore splits on `","`. Any CollectionService tag that itself contains a comma is truncated or split into multiple tags.

Offline Python extract/build uses null-byte BinaryString encoding and is not affected. The Luau dump/restore path is lossy for this case.

**Impact**  
Data loss for tags containing `,` on the Studio dump/restore workflow.

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

- **mtime-win on import/merge**  
  Most-recent-wins is the documented offline conflict policy; not a defect.

---

## Remaining minor / edge-case notes

- **Name sanitisation vs `GetFullName`** (Luau dump/restore): archive hierarchy uses a limited sanitiser; the preferred restore path uses the original `OriginalFullName`. Fallback relative paths use the sanitised form and can mismatch when names contain the sanitised characters.
- **Child order** is not preserved (Python import sorts `iterdir()`). Usually harmless but prevents byte-identical round-trips.
- **Fragile interesting-props extraction** (`interesting.py): a simple regex works today but will be polluted by any future double-quoted string in the Luau file.
- **Plugin recording**: no user feedback when `ChangeHistoryService:TryBeginRecording` returns `nil` (playtest, concurrent recording, etc.).
- **Orphaned uniquified paths**: if a previous export created `Name_2` because of a sibling collision that no longer exists, a later re-export will write to `Name` and leave the old `Name_2` on disk. Empty-dir prune does not remove non-empty leftovers.
- **Tags as SharedString on extract**: extract only decodes Tags when the property type is BinaryString / string / ProtectedString. A SharedString Tags value stays in the full Properties map and `meta["Tags"]` remains empty (pass-through on rebuild). Edge format; not observed as common.
- **Silent bridgePost errors in plugin**: `pushInstanceToBridge` does not surface `bridgePost` failures to the status line; a dead bridge loses Studio→folder edits until the next poll error.
- **Attributes search/filter and Luau wrappers** remain open (see TODO_FEATURES); not defects in the existing binary round-trip.

---

## Previously corrected issues (for reference)

These correctness problems were fixed during development and are no longer present:

1. Children of scripts are now extracted (companion directory under the script).
2. Duplicate Names under the same parent are uniquified on disk; existing paths are reused on re-export.
3. Complex properties with repeated child tags (NumberSequence, ColorSequence, etc.) round-trip completely.
4. Duplicate `<Tags>` elements no longer appear on rebuild.
5. `set_prop_value` refuses non-scalar properties that contain a `"children"` dict.
6. Extract prefers the `Name` property over a missing `Item@name` attribute (real Studio .rbxlx format).
7. `Verde.restoreScripts` now always clears existing tags via `CollectionService:GetTags` + `RemoveTag` before applying the archived tag set (including when dump omitted the Tags attribute because the original had zero tags).
8. `build.add_properties` only suppresses Tags from the full Properties map when `meta["Tags"]` is non-empty (previously any leftover SharedString hash was dropped).
9. `Verde.applyMeta` now fully replaces the Attributes set (removes attributes present on the target but absent from `meta.Attributes`, then sets/updates the wanted ones) when the key is present as a table. Matches Tags handling in the same function and the offline Python path.
10. Live Sync `BridgeState.write_file` (Studio→folder) now calls `write_manifest` and reloads `self.manifest` after updating the in-memory known map (mirrors `mark_applied`). Previously the on-disk manifest stayed stale, so a just-pushed file immediately looked dirty again and could produce echo noise / status flicker. Fixed in PR #8; docs update completed here.
11. On Darwin/Windows, `_build_instance_maps` in `build.py` now applies the same casefold uniqueness as `extract.py` when constructing the hierarchy path map. Previously a case-only sibling collision (Foo / foo → Foo + foo_2 on disk) produced a path_map key that could not match the on-disk `foo_2`, causing silent skip of the update on differential import. Fixed here.

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES.*
