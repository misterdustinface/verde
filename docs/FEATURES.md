# FEATURES.md — Verde

Single source of truth documenting the features that are currently implemented and working in the project.  
Planned work lives in `TODO_FEATURES.md`. Defects live in `BUGS.md`.

**Version 1.0.0**

---

## Implemented

### 1. Export `.rbxlx` → editable folder tree (`verde-export`)

**Description**  
Parses a Roblox place file into a hierarchy of folders + `.robloxmeta.json` (and script source files). Default is scripts-only (only paths leading to Script/LocalScript/ModuleScript); `--all` exports the full instance tree. Empty directories are pruned. Existing on-disk paths are reused on re-export; content is compared so identical files are left untouched (overwrite on diff, or `--interactive` prompt). Sibling Name collisions are uniquified within a run; case-insensitive uniqueness is enforced on Darwin/Windows to prevent silent overwrites. Name is taken from the Name property (preferred) or Item@name attribute. After export a `.verde/manifest.json` (adler32 + mtime) is written for later merge/import skipping.

**Machine-local metadata (local-only keys)**  
Top-level keys that are local to one machine / one Studio session and must not be version-controlled are written only to a sibling `*.robloxmeta.local.json` (gitignored). The shared `.robloxmeta.json` never contains them.

Current local-only keys (`LOCAL_META_KEYS` in `python/features/meta.py`):

- `Referent`

Rationale for `Referent`:  
The XML `referent` attribute is a serialization-time ID local to one `.rbxlx` / Studio session. It is useful for matching and exact Ref re-emission on the same machine, but it churns across saves. Import, Live Sync, and search load the merged view (shared + local) so matching continues to work on the producing machine. Old shared files that still contain `"Referent"` remain readable for backward compatibility; the next export moves the key into the local sibling.

Candidates for future expansion (not yet enforced as local-only):

- Raw referent strings that appear as values of `Ref`-typed Properties (e.g. PrimaryPart, object references). These are the same class of session-local ID and currently remain in shared `Properties`.
- Absolute / machine-specific paths if ever stored on a meta dict.
- Any other pure session-only or bridge-state fields.

Stable identifiers that are real Instance properties (the `UniqueId` property) stay in shared metadata. Studio Live Sync already maps `UniqueId` into the `Referent` key so matching uses the local sibling.

On every successful export, Verde also ensures a top-level `.gitignore` in the extracted folder ignores `*.robloxmeta.local.json`:
- missing file → creates a short Verde block;
- existing file missing the pattern → appends it;
- already present → left unchanged.

**Selective export**  
`--root PATH` (dot-separated Names, e.g. `ServerScriptService` or `Workspace.MyModel`) starts the export from that instance as the top of the output tree. `--tag TAG` keeps only instances that carry the tag (or ancestors of tagged instances) so hierarchy is preserved. Both combine with the scripts-only keep map. A `.verde/partial.json` records the filter for future import grafting.

**AI agent notes directory**  
Every successful export ensures a top-level `.ai/` directory exists (with a short README if newly created). This directory is reserved for notes written by AI agents. Export never prunes, cleans, or overwrites anything under `.ai/`. Import / merge never treat paths under `.ai/` as Roblox instances (see feature 15).

**Key components**  
- `python/extract.py` (iterative stack walk + progress, keep-map, prune, selective root/tag, local-meta split, `.gitignore` ensure, `.ai` ensure)
- `python/features/meta.py` (`load_meta_merged`, `save_local_meta`, `split_local_keys`, `AI_NOTES_DIRNAME`, `is_under_ai_notes`)
- `python/attributes.py` (AttributesSerialize decode)
- `python/interesting.py` + `luau/interesting_properties.luau`

### 2. Import / rebuild folder → `.rbxlx` (`verde-import`)

**Description**  
Applies an extracted folder tree back into an existing `.rbxlx` (or creates a new one). Matching prefers Referent / UniqueId from meta (Referent comes from the machine-local sibling when present), then hierarchy path. Re-emits Source, Properties, Tags, and Attributes. Unmatched place instances are left untouched. Falls back to full rebuild when the target file is missing. `verde-merge` is the same entry point with manifest-aware dirty set + mtime-win conflict rule.

**`--force`**  
Bypasses the clean-manifest / mtime-win skip logic. Every matching folder entry is considered for application even when the on-disk file is older than the target `.rbxlx` or matches the recorded hash+mtime. Content is still only written when `_needs_update` detects a real difference. Manifest is refreshed after a successful run.

**Key components**  
- `python/build.py`
- `python/features/sync.py` (manifest helpers, mtime-win)

### 3. Offline touched-file tracking + mtime-win merge (`verde-merge`)

**Description**  
Uses `.verde/manifest.json` (zlib.adler32 numeric hash + mtime) written by export. Import/merge can skip clean files. When both sides changed the same logical content, the most-recently-modified side wins. Dry-run supported. Foundation for a future git-merge-style conflict path. Machine-local `*.robloxmeta.local.json` files are never tracked in the manifest. The top-level `.ai/` AI agent notes directory is never tracked either.

**Key components**  
- `python/features/sync.py`

### 4. Live Sync between extracted folder and open Studio (`verde-sync` + plugin)

**Description**  
Bi-directional event-driven sync of script Source (default) while a place remains open in Studio. Python side runs a fixed-port (3847) HTTP bridge + file watcher; the Studio plugin exposes a single Live Sync toggle. On toggle ON a full scan-and-sync occurs. Matching prefers Referent/UniqueId then path; UniqueId map is scripts-only by default. Experimental property sync (Name / selected props / Attributes on scripts) is off by default. Never auto-creates or deletes instances from disk. Actionable connection-error messages for artists. The `/meta` endpoint returns the merged (shared + local) view; Studio-pushed meta that still contains `Referent` has the key moved into the local sibling.

**Key components**  
- `python/features/bridge.py` (`verde-sync`)
- `luau/Verde.luau` (HTTP client, serialize/apply, UniqueId map)
- `plugin/VerdePlugin.server.luau` (UI toggle + panel)

### 5. Search (CLI + Studio)

**Description**  
Find instances by ClassName, Name (contains), tag, or property value/contains. Python operates on the folder tree; Luau/plugin operates on the live DataModel. Discovery filters are case-insensitive; final mutation paths remain exact-case (intentional).

**Key components**  
- `python/features/search.py` (`verde-search`)
- `luau/Verde.luau` (`Verde.search`)

### 6. Bulk property set / replace (CLI + Studio)

**Description**  
Set a property to a value, or replace only when the current value matches an old value (`only_if`). Filters by class/tag/etc. Studio path uses ChangeHistoryService for undo. Complex / non-scalar properties are refused by the set path. Exact string equality for the final replace check (case-sensitive by design). When `--from` (or the plugin “Only if…” field) would match multiple distinct values that differ only by case, the CLI (`--interactive` / TTY) prompts for which exact value(s) to rewrite; the plugin lists the variants in the status line so the user can re-type an exact match.

**Key components**  
- `python/features/set_replace.py` (`verde-set` / `verde-replace`)
- `luau/Verde.luau` (`setProp` / `replaceProp`)
- `plugin/VerdePlugin.server.luau` (status-line variant listing)

### 7. Tag list / rename (CLI + Studio)

**Description**  
List all CollectionService tags in the place or folder tree; rename a tag across matching instances. Final mutations are exact-case on both paths. CLI `--replace` is exact by default; `--ignore-case` enables discovery of case-folded matches and `--interactive` (or a TTY) lets the user choose which exact original-cased tag(s) to rewrite. The plugin surfaces the same ambiguity in the status line when zero exact matches exist but case variants do.

**Key components**  
- `python/features/tags.py` (`verde-tags`)
- `luau/Verde.luau` (`listTags` / `replaceTag`)
- `plugin/VerdePlugin.server.luau` (status-line variant listing)

### 8. Attributes as first-class extract/build citizens

**Description**  
Full binary codec for the AttributesSerialize format. On extract, Attributes appear as a top-level map in `.robloxmeta.json`. On build they are re-emitted as a correct BinaryString. Search/filter by attribute and Luau GetAttribute/SetAttribute wrappers remain open (see TODO).

**Key components**  
- `python/attributes.py`
- extract/build integration + `python/tests/test_attributes.py`

### 9. Studio plugin UI

**Description**  
Toolbar button + dockable panel providing Live Sync toggle, Search, Set/Replace, and Tags surfaces. All DataModel logic lives in the shared `Verde` ModuleScript. Install is a one-time local-plugin paste of the Luau sources.

**Key components**  
- `plugin/VerdePlugin.server.luau`
- `luau/Verde.luau` + `interesting_properties.luau`

### 10. Round-trip testing harness

**Description**  
`verde-test-roundtrip` exercises export → import structural fidelity (Referent-keyed comparison, Tags BinaryString decode, AttributesSerialize handling, Name-from-property resolution). Expanded unit tests under `python/tests/` cover properties, attributes, and set_prop edge cases.

**Key components**  
- `python/test_roundtrip.py`
- `python/tests/`

### 11. Path reuse, collision handling, and platform-aware uniqueness

**Description**  
Re-exports reuse existing filesystem paths instead of inventing Name_2 suffixes. Content-hash comparison avoids unnecessary writes. Intra-run sibling collisions still receive numeric suffixes. On case-insensitive filesystems uniqueness is case-insensitive so "Foo" / "foo" cannot clobber each other.

### 12. Status report CLI (`verde-status`)

**Description**  
Read-only command that answers “which files are dirty?” and “is the Live Sync bridge reachable?”. Reports clean / dirty / missing tracked files from `.verde/manifest.json` (adler32 + mtime) and optionally probes the Live Sync bridge on localhost:3847 (GET /status). Human-readable by default; `--json` for tooling. Supports `-v` for recorded hash/mtime details. Zero side-effects; re-uses existing helpers from `features/sync.py`. No new dependencies.

**Key components**  
- `python/features/status.py` (`verde-status`)

### 13. Selective / partial extract (`--root` / `--tag`)

**Description**  
Foundation for partial place exports. `--root PATH` limits the export to a named subtree; `--tag TAG` keeps tagged instances and their ancestor chain. Writes `.verde/partial.json` so a future import can graft the partial tree back. Import-side grafting is still residual work (see TODO).

**Key components**  
- `python/extract.py`

### 14. Interactive case disambiguation for set/replace and tags

**Description**  
When a case-insensitive discovery filter yields multiple distinct original-cased values (properties or tags), the CLI presents a short numbered list (value + instance count) and, under `--interactive` or a TTY, lets the user pick which exact value(s) to act on. Non-interactive multi-variant runs exit non-zero with the list so scripts remain deterministic. The Studio plugin lists the same variants in the status line when a replace finds zero exact matches, so the user can copy an exact value back into the input field. Final mutation always uses exact case (Roblox semantics).

**Key components**  
- `python/features/set_replace.py`, `python/features/tags.py`
- `plugin/VerdePlugin.server.luau`

### 15. Top-level `.ai` AI agent notes directory

**Description**  
Defines a reserved top-level directory `.ai` for notes written by AI agents working on an extracted Verde tree. Behaviour:

- **Export (`verde-export`)**: ensures `.ai/` exists (creates it with a short README if missing). Never prunes empty dirs inside it, never runs orphan-uniquify cleanup on it, and never overwrites any of its contents.
- **Import (`verde-import` / full rebuild / differential)**: never walks `.ai/` for candidates. `walk_metas` and bare-script discovery both skip paths under `.ai/`. Full-rebuild `process_directory` also skips the directory name.
- **Manifest / merge**: files under `.ai/` are never recorded in `.verde/manifest.json` and never considered dirty.

This keeps agent scratchpads, plans, and observations out of Roblox Studio while preserving them across re-exports.

**Key components**  
- `python/features/meta.py` (`AI_NOTES_DIRNAME`, `is_under_ai_notes`)
- `python/extract.py` (`_ensure_ai_notes_dir`, protected prune/cleanup)
- `python/build.py` (explicit skips)
- `python/features/sync.py` (manifest exclusion)

---

*This list is the authoritative record of what exists today. When a feature lands via Build, update this file in the same change set.*
