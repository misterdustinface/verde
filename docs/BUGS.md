# Bugs

True defects in current behaviour of verde (**v1.0.0**).
Missing features and intentional design choices live in `TODO_FEATURES.md`.

**Important design principle:** Case sensitivity of properties and tags is intentional and valuable. Roblox itself treats tags and many property string values as case-sensitive. Verde’s live Luau path therefore preserves exact case for final set/replace operations. Case-insensitive filters exist only as a discovery aid; when they produce ambiguous matches that differ only by case, the preferred future behaviour is interactive prompting (see TODO_FEATURES), not silent case-folding of the final value.

---

## Open issues

### 1. Restore does not clear existing tags

`Verde.restoreScripts` currently *adds* the archived tags (from the `Tags` attribute) without first removing any tags already present on the target. Restore therefore merges rather than replaces the tag set.

PR #6 (`fix/restore-clear-tags`) implements the clear-before-add when a `Tags` attribute is present. Residual even after that lands: the Luau dump path only sets the `Tags` attribute when `#tags > 0`. When the original script had zero tags the attribute is absent, so restore still never clears. Full fidelity for “no tags” requires either always emitting `Tags=""` on dump or clearing when the attribute is absent.

**Impact**  
Correctness / data fidelity on restore.

### 2. Live Sync bridge: Studio→folder push leaves files dirty vs on-disk manifest

In `features/bridge.py`, `write_file` (Studio push) updates only the in-memory `self.known` map and discards from `pending_to_studio`. It does **not** update `self.manifest` or call `write_manifest`. The watcher and `/dirty` / `/full-sync` paths call `refresh_dirty` → `dirty_paths(self.root, self.manifest)`, which still compares against the stale on-disk manifest.

Consequence: a just-pushed file can immediately look dirty again, re-enter `pending_to_studio`, emit a dirty event, and cause Studio to re-apply its own change (usually a no-op via `valuesEqual`, but produces event noise, status flicker, and a race window if the user also edits the same file on disk).

`mark_applied` (folder→Studio) does refresh the manifest; the Studio→folder direction does not.

**Impact**  
Robustness / correctness of Live Sync; wasted work and possible brief echo loops.

### 3. `applyMeta` leaves stale Attributes

`Verde.applyMeta` correctly replaces the tag set (remove extras + add missing). For Attributes it only *sets* keys present in `meta.Attributes`; it never removes attributes that exist on the target Instance but are absent from the meta table. Live Sync experimental property path and any full meta apply therefore leave stale attributes behind.

Inconsistent with the Tags handling in the same function and with the offline Python import path (which clears and re-emits Properties/Attributes).

**Impact**  
Data fidelity on Live Sync (experimental) and any `applyMeta` / `applyFromBridge` callers.

### 4. Case-insensitive extract uniqueness vs case-sensitive import path maps

On Darwin/Windows, `extract.py` uniquifies sibling Names with `name.casefold()` so `Foo` / `foo` become `Foo` + `foo_2` on disk. `build.py` `_build_instance_maps` builds the path map with a case-sensitive `used` set. Differential import therefore cannot match the on-disk `foo_2` path for the original case-sibling and silently skips the update.

Rare (requires two siblings that differ only by case under the same parent) but real data-fidelity loss on case-insensitive filesystems.

**Impact**  
Correctness / silent data skip on import (Darwin/Windows).

### 5. Luau dump/restore corrupts tags that contain commas

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
- **Fragile interesting-props extraction** (`interesting.py`): a simple regex works today but will be polluted by any future double-quoted string in the Luau file.
- **Plugin recording**: no user feedback when `ChangeHistoryService:TryBeginRecording` returns `nil` (playtest, concurrent recording, etc.).
- **Orphaned uniquified paths**: if a previous export created `Name_2` because of a sibling collision that no longer exists, a later re-export will write to `Name` and leave the old `Name_2` on disk. Empty-dir prune does not remove non-empty leftovers.
- **Tags as SharedString on extract**: extract only decodes Tags when the property type is BinaryString / string / ProtectedString. A SharedString Tags value stays in the full Properties map and `meta["Tags"]` remains empty (pass-through on rebuild). Edge format; not observed as common.
- **Silent bridgePost errors in plugin**: `pushInstanceToBridge` does not surface `bridgePost` failures to the status line; a dead bridge loses Studio→folder edits until the next poll error. Lower priority than the dirty/echo issue above.
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
7. `build.add_properties` only suppresses Tags from the full Properties map when `meta["Tags"]` is non-empty (previously any leftover SharedString hash was dropped).

---

*Only true defects belong here. Case sensitivity of properties and tags is an important intentional feature; interactive handling of ambiguous case-insensitive search results is tracked in TODO_FEATURES.*
