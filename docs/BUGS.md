# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES), not silent case-folding of the final value.

### Agent / skill maintenance rule (github-pickaxe, github-inspect, github-inspire, github-iterate, and related)

The Open issues list must stay usefully populated for as long as residual true defects exist in the system. “None currently.” is not a terminal state while residual notes, known edge cases, or silent-failure paths remain.

When Open issues is empty, contains only “None currently.”, or is sparse (roughly fewer than 5–7 prioritized items) while residual defects are still present:

1. Scan the residual notes in this file, recent code (extract / build / Luau / plugin / bridge), tests, and previously-corrected items for remaining true defects.
2. Prioritize by impact: silent failure, data loss, and Live Sync reliability first.
3. Rewrite the Open issues section as a numbered prioritized list with short impact statements.
4. Keep pure missing features in `TODO_FEATURES.md` and intentional design choices in the Intentional design section.

`github-inspect` is the primary skill for this scan-and-populate step. `github-pickaxe` and `github-iterate` must invoke or re-run the scan when the list is sparse before treating the bug list as clean. `github-inspire` should note or recommend the same when it reads a sparse list.

---

## Open issues

### 1. Fragile `interesting.py` property-name extraction

The interesting-properties list is extracted from the Luau source with a simple regex that matches double-quoted strings. Any future double-quoted string that is not a property name (comments, string literals inside the module, etc.) will pollute the list, and legitimate property names written with single quotes or concatenation will be missed. The current `luau/interesting_properties.luau` is a clean flat table, so behaviour is correct today, but the extractor remains brittle.

**Impact**  
Incorrect or incomplete “interesting” flatten set if the Luau source changes style; search/set surface becomes unreliable.

### 2. Child order not preserved on Python full rebuild / import

`build.py` `process_directory` walks the filesystem with `sorted(iterdir())`. Roblox instance child order is therefore not restored on full rebuild. Differential import also leaves existing place children in their original order and does not re-order them to match the folder. Usually harmless for scripts, but prevents byte-identical round-trips and can affect order-sensitive behaviour (UI lists, some collection patterns).

**Impact**  
Non-identical rebuilds; rare behavioural differences for order-dependent instances.

### 3. Bridge `write_manifest` / `mark_applied` swallow exceptions

In `features/bridge.py`, both `mark_applied` and `write_file` catch broad `Exception` around the `write_manifest` call and continue. Under rare permission, disk-full, or concurrent-access conditions the on-disk `.verde/manifest.json` can lag the in-memory `known` map. The primary file write already records known, so practical impact is low while the folder remains writable, but the silent path can produce transient “dirty again” flicker after a successful Studio→folder push.

**Impact**  
Silent lag of the on-disk manifest; low practical impact, but a real silent-failure path.

### 4. `build.py` still re-implements sibling name uniqueness (residual of shared helper)

`claim_unique_name` + `FS_CASE_INSENSITIVE` live in `xml_props.py` and are used by extract. `build.py` `_build_instance_maps` still contains its own identical while-loop + local `_FS_CASE_INSENSITIVE`. The algorithms match today (so no path-map mismatch), but the duplication is the incomplete half of the shared-helper extraction and is the same class of residual that previously allowed case-path drift.

**Impact**  
Maintainability risk; future uniqueness policy changes must be applied in two places or the case-path-map class of bugs can reappear.

### 5. Selective `--tag` / keep-map still only surface first-class Tags (post-SharedString fix residual)

After the SharedString decode work, `_item_has_tag` and extract correctly populate `meta["Tags"]` for all supported forms. Selective export itself is correct. Residual observation: if a place ever stores Tags exclusively in a form the shared decoder does not yet recognise, the keep-map would still treat the instance as untagged. No additional forms are known today; this item exists so the decoder remains the single source of truth for any future Tags variants.

**Impact**  
Future-proofing note only; no current incorrect behaviour.

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
- Full-rebuild child order (Open #2) is the only remaining order-related item; differential import intentionally does not reorder existing place children.

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
13. Silent `bridgePost` failures in the plugin (Live Sync Studio→folder). `pushInstanceToBridge` previously ignored the success/error return of `Verde.bridgePost("/push", …)`. Failures are now surfaced via `setLiveStatus` + `diagnoseBridgeFailure` with an explicit note that the last Source/meta edit may not have reached disk; `liveOn` remains true so the poll loop can recover.
14. Orphaned uniquified paths left on disk after re-export. When a prior export produced `Name` + `Name_2` for colliding siblings and a later export has only the survivor, path-reuse writes to the bare `Name` but left the stale `Name_2` (and associated .lua / .robloxmeta.json / child directory). Empty-dir prune only removed empty directories. `_cleanup_orphaned_uniquified` now removes such leftovers when the bare base was claimed this run and the `_N` stem was not.
15. Luau dump/restore name sanitisation vs `OriginalFullName` mismatch on fallback paths. `dumpScripts` previously used a limited sanitiser (`[/\\%z]` → `_`). The preferred restore path uses the original `OriginalFullName` attribute. When that attribute is missing or empty, restore fell back to a relative path derived from the sanitised archive names, which could place scripts with names containing `/`, `\\`, null, or other invalid filesystem characters in the wrong hierarchy location. Fixed by unifying on the fuller `sanitizeName` (same set as Python + path helpers) so archive hierarchy names stay consistent with Live Sync / export path conventions.
16. Differential import (including `--force`) no longer imports redundant on-disk entries that caused Studio “DM contains duplicate Unique ids”. Candidates that share a Referent, share a UniqueId in meta, or look like Name_N leftovers of a bare Name sibling (with no distinct Referent) are skipped before any place Item is updated. Each place Item is applied at most once per run. The place Item’s existing UniqueId is still preserved as a safety net. We do not invent or regenerate UniqueIds for disk duplicates — the redundant files simply are not imported.
17. MeshPart MeshId / TextureID (and similar Content properties) that use a child `<url>` element are no longer dropped on extract/import. `parse_property_element` previously treated Content as pure text and discarded children, so MeshId became empty on re-emit and MeshParts failed to load in Studio. Content / SharedString / Ref now keep the children structure when present.
18. Differential import path_key for ModuleScript / LocalScript companion metas (`Name.module.robloxmeta.json` / `Name.local.robloxmeta.json`) no longer includes the type suffix. Previously path_key ended in `…/Name.module` while the place path_map used the instance Name (`…/Name`), so the path fallback never matched and Sources were skipped whenever Referent was missing or stale. Fixed by stripping a trailing `.module` / `.local` when building the hierarchy key (PR #24).
19. Plugin actions (Set/Replace, Rename tag, Restore scripts, Live Sync apply) now surface a status note when `ChangeHistoryService:TryBeginRecording` returns nil (playtest mode, concurrent recording, etc.). The change still applies; the user is informed that no undo waypoint was created.
20. Tags stored as SharedString are now decoded on extract (and visible to selective `--tag`). `decode_tags_from_prop` / `decode_tags_from_structured` handle BinaryString, string/ProtectedString, and SharedString forms; extract_properties and `_item_has_tag` both use the shared helpers. Residual Tags-decoding duplication inside extract was removed. (PR #29)

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES.*
