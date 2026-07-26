# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES), not silent case-folding of the final value.

---

## Open issues

Prioritized by impact (data loss / silent failure / Live Sync reliability first).

### 1. Silent `bridgePost` failures in the plugin (Live Sync Studio→folder)

`pushInstanceToBridge` calls `Verde.bridgePost("/push", …)` and ignores the success/error return value. When the bridge is down, HttpService is disabled, or the POST fails for any other reason, Studio→folder edits are dropped with no status-line feedback. The user only discovers the problem on the next successful poll or full-scan.

**Impact**  
Silent data loss for Live Sync writes originating in Studio.

### 2. Orphaned uniquified paths left on disk after re-export

Path-reuse correctly writes to a clean `Name` when a previous sibling collision no longer exists, but the old `Name_2` (or higher) directory/file is never removed. Empty-dir prune only deletes empty folders; non-empty leftovers accumulate across repeated exports.

**Impact**  
Stale files and folders accumulate in the extracted tree; later imports or Live Sync can see phantom paths.

### 3. Name sanitisation vs `OriginalFullName` / `GetFullName` mismatch (Luau dump/restore)

`dumpScripts` builds the archive hierarchy with a limited sanitiser (`[/\\%z]` → `_`). The preferred restore path uses the original `OriginalFullName` attribute. When that attribute is missing or the fallback relative-path logic is used, the sanitised form can fail to locate the target instance for names that contained the replaced characters.

**Impact**  
Restore can skip or mis-place scripts whose names contain `/`, `\\`, or nulls when falling back from `OriginalFullName`.

### 4. Plugin: no feedback when `ChangeHistoryService:TryBeginRecording` returns nil

Several plugin actions (set/replace, tag rename, restore, Live Sync apply) call `TryBeginRecording` and only call `FinishRecording` when a recording handle is returned. When the call returns `nil` (playtest, concurrent recording, etc.) the mutation still proceeds but the user receives no warning that the change will not be undoable via Studio’s history.

**Impact**  
Silent loss of undo history for the affected operation.

### 5. Tags stored as SharedString are not decoded on extract

`extract_properties` only promotes Tags into `meta["Tags"]` when the property type is `BinaryString`, `string`, or `ProtectedString`. A `SharedString` Tags value remains inside the full Properties map; `meta["Tags"]` stays empty and the offline tag tools see no tags for that instance (pass-through on rebuild only).

**Impact**  
Tag search/replace and Live Sync meta lose tags for the uncommon SharedString encoding.

### 6. Fragile interesting-properties extraction

`python/interesting.py` extracts property names with a simple `re.findall(r'"([^"]+)"', text)` over the Luau source. Any future double-quoted string that is not a property name (comment, error message, etc.) will pollute the interesting set.

**Impact**  
Incorrect or incomplete “interesting” surface for search/set until the Luau file is cleaned or the parser is hardened.

### 7. Child order not preserved on Python import

`build` / import walks the filesystem with `iterdir()` (effectively sorted by name on most platforms). Original sibling order from the `.rbxlx` is not recorded or restored. Usually harmless for behaviour, but prevents byte-identical round-trips and can affect systems that rely on child order.

**Impact**  
Non-identical rebuilds; potential ordering surprises for order-sensitive instances.

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

## Remaining lower-severity notes

- **Attributes search/filter and Luau wrappers** remain open (see TODO_FEATURES); not defects in the existing binary round-trip.
- Live Sync “N file(s) had no matching script” noise after renames / missing Referents is tracked as a future healing feature (TODO I1), not a pure defect in the current path-matching fallback.

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
12. `Verde.dumpScripts` / `restoreScripts` no longer corrupt tags that contain commas. Tags are now stored as a JSON array via `HttpService:JSONEncode`; restore prefers JSONDecode and falls back to the legacy comma-split for older ScriptDump_* archives. Offline Python path was already safe (null-byte BinaryString).

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES.*
