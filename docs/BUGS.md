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

### 1. Child order not preserved on Python full rebuild / import

`build.py` `process_directory` walks the filesystem with `sorted(iterdir())`. Roblox instance child order is therefore not restored on full rebuild. Differential import also leaves existing place children in their original order and does not re-order them to match the folder. Usually harmless for scripts, but prevents byte-identical round-trips and can affect order-sensitive behaviour (UI lists, some collection patterns).

**Impact**  
Non-identical rebuilds; rare behavioural differences for order-dependent instances.

### 2. Attributes decode stops at first unknown type_id

`attributes.decode_attributes` aborts the remaining attribute list as soon as it encounters an unrecognised type ID (it cannot safely skip a variable-length value). Later attributes in the same `AttributesSerialize` payload are therefore lost on extract. Encode also skips any `__type` that begins with `Unknown_`.

**Impact**  
Partial Attributes loss on places that use newer or rare attribute types; round-trip fidelity degrades for those instances.

### 3. Root-level non-Item elements dropped on full rebuild

Full extract + build (and differential create paths) do not preserve top-level children of the `<roblox>` root other than `Item`s (`SharedStrings` table, `Meta`, `External*`, etc.). Tags that were SharedString references are re-emitted as BinaryString (so the common Tags case survives), but any other property that remains a SharedString md5 key, or any place that relies on the root SharedStrings table / Meta / External references, will lose those elements after a rebuild.

**Impact**  
Data loss / dangling references for places that use SharedString for non-Tags properties or that depend on root Meta/External. Full preservation is also tracked as APPROVED work in TODO_FEATURES; the current behaviour is still a correctness gap for those places.

### 4. Live Sync “no matching script” noise after renames / stale Referent

When a script is renamed in Studio or the on-disk meta still carries a stale Referent/UniqueId, the bridge path-matching falls back to name/path and reports “N file(s) had no matching script”. The count is surfaced (not silent), but large places accumulate noise and require a re-export or manual healing. Full Referent/UniqueId healing is tracked as I1 in TODO_FEATURES; until then this remains a residual robustness gap in the live path.

**Impact**  
Operational friction / status noise on Live Sync after renames; no automatic data loss, but users can miss real mismatches among the noise.

### 5. `import_rbxlx` still swallows `write_manifest` failures

At the end of a successful differential import, `build.import_rbxlx` refreshes `.verde/manifest.json` inside a bare `except Exception: pass`. Unlike the Live Sync bridge path (Previously corrected #21), a permission / disk / concurrent-access failure leaves the on-disk manifest stale with no diagnostic. Subsequent imports then re-treat clean files as dirty (or worse, re-skip creates incorrectly until `--force`).

**Where**  
`python/build.py` end of `import_rbxlx`.

**Impact**  
Silent robustness gap; dirty-tracking drift after import when the manifest write fails.

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

- **Live Sync non-goals**  
  No auto-create/delete of instances from disk while Studio is open; scripts-only default watch; no user-facing port configuration.

---

## Remaining minor / edge-case notes

- Full-rebuild child order (Open #1) is the only remaining order-related item; differential import intentionally does not reorder existing place children.
- Bridge manifest write failures are now surfaced (Previously corrected #21); **import** still silent (Open #5).
- Shared uniqueness helper is now fully wired in both extract and build (Previously corrected #22).
- Attributes unknown-type early-stop (Open #2) remains the main residual Attributes edge case; encode now filters unknown structured types cleanly and accepts Luau CFrame/EnumItem shapes (Previously corrected #27).
- Interesting-properties extractor is now line-oriented inside the return table (Previously corrected #25).
- Selective `--tag` keep-map: after SharedString decode work, `_item_has_tag` / extract correctly populate `meta["Tags"]` for all currently supported forms. No additional Tags wire forms are known; keep the shared decoder as the single source of truth if Studio ever adds one.
- Differential import `_get_tags` does not pass a SharedStrings table. Places that still store Tags as SharedString hashes will look “dirty” once and be rewritten as BinaryString (self-healing; not data loss after the first write).
- Live Sync metaRelPath now uses the correct type stem for ModuleScript / LocalScript (Previously corrected #26).

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
21. Bridge `write_manifest` / `mark_applied` no longer swallow exceptions silently. Both paths now print a short diagnostic (same style as other bridge `!` lines) when the on-disk manifest write fails, while still continuing so the live path stays robust. (PR #32)
22. `build.py` `_build_instance_maps` now uses the shared `claim_unique_name` helper from `xml_props.py` (and no longer carries a private `_FS_CASE_INSENSITIVE` + while-loop). Completes the shared-helper extraction begun in PR #29; export and import path uniqueness are now a single source of truth. (this PR)
23. SharedString Tags resolution now looks up the real payload from the root `<SharedStrings>` table (md5 → base64 BinaryString content). Previously the hash itself was treated as BinaryString data, producing garbage tags such as `['iA@NMuvp']` instead of the real list; `verde-test-roundtrip` reported widespread Tags mismatches. Fixed in `xml_props.parse_shared_strings` + decode helpers; extract and the roundtrip test both pass the map. Full root-level SharedStrings preservation remains TODO_FEATURES #2.
24. Differential import now always attempts create for a disk entry that is absent from the place (clean/manifest skip only applies when the place still has the matching Item). Missing intermediate parents are recursively grafted as Folders. This removes the need for `--force` when adding new/AI-generated scripts (including bare `.module.lua` with no companion `.robloxmeta.json`) and closes the residual “parent path missing; cannot auto-create” path. (PR pending)
25. Fragile `interesting.py` property-name extraction. The interesting-properties list is now extracted with a line-oriented scan of the `return { ... }` table (comments stripped; only standalone double-quoted table rows collected). Falls back to the previous whole-file regex only if the structured pass yields nothing. Stops incidental double-quoted strings from polluting the set. (this PR)
26. Live Sync Studio→folder meta path for ModuleScript / LocalScript. `Verde.metaRelPath` previously always appended bare `.robloxmeta.json` for any LuaSourceContainer, creating a second meta file at the wrong path while export writes `Name.module.robloxmeta.json` / `Name.local.robloxmeta.json`. Fixed so metaRelPath mirrors scriptRelPath type stems. (this PR)
27. Attributes encode no longer produces a count/body desync on unknown structured `__type` values (those entries are filtered before the leading u32 count is written). Encode also accepts Live Sync Luau shapes for CFrame (`components` list → RotationId=0 + matrix) and EnumItem (`Name` present; `Value` defaults to 0). (this PR)

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES.*
