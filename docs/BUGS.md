# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES), not silent case-folding of the final value.

---

## Open issues

### 1. Silent `bridgePost` failures in the plugin (Live Sync Studio→folder)

`pushInstanceToBridge` calls `Verde.bridgePost("/push", …)` and ignores the success/error return value. When the bridge is down, the HTTP request fails, or the payload is rejected, the plugin continues without updating the status line. Studio→folder Source/meta edits are therefore lost until the next poll cycle (or forever if the user never notices).

**Impact**  
Silent data loss for Live Sync in the Studio→folder direction.

### 2. Orphaned uniquified paths left on disk after re-export

When two siblings share a Name (or case-fold on Darwin/Windows), extract writes `Name` + `Name_2`. On a later re-export, if the colliding sibling is gone, path-reuse writes the survivor back to the bare `Name` path. The old `Name_2` directory/file is never removed because empty-dir prune only deletes empty directories. Over time the extracted tree accumulates stale uniquified leftovers.

**Impact**  
Disk clutter; potential confusion for users and for tools that walk the tree; residual files can be picked up by later imports if paths are ambiguous.

### 3. Luau dump/restore name sanitisation vs `OriginalFullName` mismatch on fallback paths

`dumpScripts` builds the archive hierarchy with a limited sanitiser (`[/\\%z]` → `_`). The preferred restore path uses the original `OriginalFullName` attribute. When that attribute is missing or empty, restore falls back to a relative path derived from the sanitised archive names. Names containing the sanitised characters therefore restore to the wrong hierarchy location.

**Impact**  
Incorrect restore location (or skipped restore) for scripts whose Names contain `/`, `\\`, or null.

### 4. Plugin: no user feedback when `ChangeHistoryService:TryBeginRecording` returns nil

Several plugin actions (Set/Replace, Rename tag, Restore scripts, Live Sync apply) call `TryBeginRecording`. When it returns `nil` (playtest mode, concurrent recording, etc.) the action still proceeds but no undo waypoint is created and the user receives no status-line indication.

**Impact**  
Silent loss of undo history; user may believe a change is undoable when it is not.

### 5. Tags stored as SharedString are not decoded on extract

`extract.py` only decodes the Tags property when its type is BinaryString, string, or ProtectedString. When Tags appears as a SharedString (rare but legal in some place formats), the value stays in the full Properties map and `meta["Tags"]` remains empty. Rebuild therefore does not re-emit a proper Tags BinaryString.

**Impact**  
Tags are lost on a round-trip for places that use the SharedString form.

### 6. Fragile `interesting.py` property-name extraction

The interesting-properties list is extracted from the Luau source with a simple regex that matches double-quoted strings. Any future double-quoted string that is not a property name (comments, string literals inside the module, etc.) will pollute the list, and legitimate property names written with single quotes or concatenation will be missed.

**Impact**  
Incorrect or incomplete “interesting” flatten set; search/set surface becomes unreliable if the Luau source changes style.

### 7. Child order not preserved on Python import

`build.py` / import walks the filesystem with `iterdir()`, whose order is not guaranteed and is typically sorted. Roblox instance child order is therefore not restored. Usually harmless for scripts, but prevents byte-identical round-trips and can affect order-sensitive behaviour (UI lists, some collection patterns).

**Impact**  
Non-identical rebuilds; rare behavioural differences for order-dependent instances.

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

- **Attributes search/filter and Luau wrappers** remain open (see TODO_FEATURES); not defects in the existing binary round-trip.
- Live Sync “N file(s) had no matching script” noise after renames is expected until Referent healing (TODO_FEATURES I1) lands; not treated as a correctness bug today.
- Selective-extract foundation is shipped; import-side grafting of a partial tree is still residual feature work, not a defect.

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
