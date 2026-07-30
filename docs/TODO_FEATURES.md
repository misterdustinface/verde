# TODO_FEATURES.md — Verde

Future features and intentional enhancements.  
Pure defects remain in `BUGS.md`.

---

## APPROVED

Ordered per operator preference. (Item 1 residual shipped; remaining renumbered.)

### 1. Preserve root-level Meta / External / SharedStrings

**Description**  
Some `.rbxlx` files contain top-level elements outside the main `Item` tree (`Meta`, `External`, `ExternalAssets`, `SharedStrings`, etc.). These are currently dropped on extract/build.

**Recommendations & options**
- On extract, write a special top-level file (e.g. `.robloxroot.json` or `meta/root.xml` fragments) that stores any non-`Item` children of the `<roblox>` root.
- On build, re-insert those fragments in the original order before or after the instance tree.
- Minimal viable approach: capture the raw XML snippets of unknown root children and round-trip them verbatim.
- Document that places using SharedString tables or external asset references will now survive a round-trip.

---

### 2. Richer property round-tripping for complex / rare types

**Description**  
Improve fidelity for property types that currently lose information or are only partially reconstructed (NumberSequence / ColorSequence keypoints, PhysicalProperties, FontFace, Content, SharedString references, Attributes, etc.).

**Recommendations & options**
- Extend `_parse_property_element` / `_emit_property` to treat repeated child tags as ordered lists (list-of-dicts) instead of a single dict entry.
- Add explicit handlers for well-known complex types (NumberSequence, ColorSequence, NumberRange, Rect, UDim2, Font, PhysicalProperties, …).
- Optionally capture Attributes (currently under a different XML structure in newer places) as a first-class map in `.robloxmeta.json`.
- Keep the “interesting properties” surface limited to scalars for search/set; complex types stay in the structured `Properties` map only.
- Add focused unit tests that assert full keypoint / sequence round-trips.

---

### 3. Plugin: persist last search filters

**Description**  
Remember the most recent ClassName / Name / Tag / Property filters in the Studio plugin so users do not have to re-type them every session.

**Recommendations & options**
- Store the last values in `plugin:SetSetting` / `plugin:GetSetting` (Studio’s built-in plugin settings API).
- On panel open, pre-fill the TextBoxes from the saved settings.
- Add a small “Clear filters” button that also clears the persisted values.
- Optionally persist the last dump/restore options (dry-run, recreate-missing, etc.) the same way.

---

### 4. Streaming search / replace on live `.rbxlx`

**Description**  
Operate on a `.rbxlx` file in place (or via a temporary copy) without a full extract → edit → rebuild cycle. Useful for large places where disk I/O and intermediate folder trees are expensive.

**Recommendations & options**
- **SAX / iterative parser** (preferred for memory): walk the XML with `xml.etree.ElementTree.iterparse` (or `lxml` if added as an optional dependency). Match `Item` elements on the fly, apply set/replace, and write a new file.
- **In-memory DOM with selective rewrite**: parse once, mutate matching nodes, then serialise. Simpler but higher peak memory.
- CLI shape: `verde-search --rbxlx Place.rbxlx …` and `verde-set --rbxlx Place.rbxlx …` that accept the same filters as the folder-based commands.
- Keep the existing folder-based tools as the default; make streaming an explicit flag or sub-command so behaviour stays predictable.

---

### 5. Live Sync with open Studio (CLI: `verde-sync`)

**Description**  
Bi-directional event-driven sync between an extracted folder and an **open** Studio place (scripts-first).

**Shipped on `feature/live-bridge` (v1.0.0):**
- `python/features/bridge.py` → **`verde-sync`** (fixed localhost port 3847, not user-facing)
- Plugin **Live Sync** toggle + full scan-and-sync on enable
- Scripts-only default watch; experimental property sync **off** by default
- Referent / UniqueId–first matching; **scripts-only UniqueId map** on connect (full map only if a future all-instance mode is enabled)
- Actionable setup errors; artist-oriented README

**Still open before treating Live Sync as fully artist-ready:**
- [ ] Large-place hitch test (default mode)
- [ ] Manual Referent / path edge cases (renames, `Name_2` collisions, missing Referent)
- [ ] Plugin install path for non-coders (beyond paste ModuleScript)
- [ ] Manual matrix + optional HTTP smoke tests
- [ ] `verde-merge` design note / implementation for git-merge-style conflicts (see remaining merge work under PENDING)

**Explicit non-goals (for now):**
- Watching every Part / full DataModel property fan-out
- Auto-creating or deleting instances from disk
- User-configurable ports in the UI

---

### 6. Plugin hierarchy navigator + recent-sync timeline

**Description**  
Artists and designers currently context-switch between the extracted folder on disk and the Studio DataModel. A lightweight, scripts-first hierarchy view inside the existing Verde plugin panel, plus a short list of the most recent bridge events, would make Live Sync feel trustworthy and reduce the need to leave Studio to confirm what just happened.

**Scope / Rough idea**  
- On Live Sync connect the bridge already builds a UniqueId/Referent map for the watch scope; expose a compact hierarchy summary (or let the plugin walk the map).
- Render a collapsible or filterable list/tree of scripts (and optionally tagged containers) inside the dockable panel.
- Clicking an entry selects the instance in Studio and shows last-sync direction / status.
- Below the tree, keep a rolling “Recent changes” list (path, Studio→disk or disk→Studio, timestamp) fed by the same bridge events that already drive Source updates.
- Stay strictly within existing non-goals: no full DataModel mirror, no auto-create/delete, scripts-first by default. Re-use or lightly extend the existing HTTP endpoints; avoid new long-lived state on the Python side.

---

## PENDING APPROVAL

### IMAGINEERED

### I1. Referent / UniqueId healing and rename reconciliation for Live Sync

**Why**  
Live Sync and offline merge already prefer Referent/UniqueId, but renames, `Name_2` collisions, deleted-then-recreated scripts, or meta that lags Studio can leave the UniqueId map and `.robloxmeta.json` files drifting. Large places then accumulate “N file(s) had no matching script” noise and silent path fallbacks. Healing would make the system self-repairing across sessions without requiring a full re-export.

**Rough idea**  
On Live Sync connect (and optionally on a lightweight periodic or on-demand “Heal” action in the plugin):
- Build the current Studio UniqueId/Referent map for the watch scope (scripts-only by default).
- Walk the extracted tree’s `.robloxmeta.json` files and match by path → Referent → fuzzy Name+ClassName.
- For high-confidence mismatches, rewrite the meta file’s Referent/UniqueId (and optionally the on-disk path if a clean rename is detected) so future syncs stay Referent-first.
- Surface a short human summary (“healed 7, ambiguous 2, left alone 3”) and never auto-delete or invent instances.
- Keep the existing non-goals (no create/delete from disk) intact; this is only map + meta repair.

### I2. Conflict markers (git-style) for offline merge when both sides dirty

**Why**  
Today’s mtime-win silently prefers one side when both the folder and the `.rbxlx` have changed the same logical content. Version-control users need an explicit conflict signal so they can choose which version to keep (or merge by hand) instead of losing the other edit.

**Rough idea**  
When `verde-merge` (or a forced import) detects that a tracked file is dirty on both sides relative to the last manifest, write a sibling `*.conflict` (or annotate the Source / meta with classic <<<< / ==== / >>>> markers) and exit non-zero. Add optional `--prefer-folder` / `--prefer-place` to auto-resolve in one direction. Keep the current pure mtime-win behaviour as the default for non-interactive scripts.

### I3. Plugin-side Source diff preview before applying Live Sync changes

**Why**  
When Studio→folder or folder→Studio would overwrite a script Source that the other side also modified, artists currently get no visual cue of the delta. A lightweight inline diff in the plugin panel would let them accept, reject, or open the full editor before the write lands, reducing accidental overwrites during concurrent editing.

**Rough idea**  
- On detecting a content mismatch during Live Sync apply (already computed for dirty checks), send a short unified-diff or side-by-side snippet over the existing HTTP endpoints.
- Plugin renders a scrollable “Pending change” card with Accept / Discard / Open in Script Editor buttons.
- Keep scope scripts-only; no full DataModel property diffs. Re-use ChangeHistoryService for the Studio side.
- Optional config: “auto-accept when only whitespace” or “always prompt”.

### I4. Automatic UniqueId / Referent backfill for AI-generated or newly created scripts on import

**Why**  
AI agents and manual “new script” folders often produce bare `.lua` files without companion meta or UniqueId. Differential import currently creates them as Folders/Instances but the resulting UniqueIds are Studio-generated and not written back to disk, so subsequent Live Sync or re-exports start with noisy “no matching” reports until a full re-export. Backfill would close the loop for agentic workflows.

**Rough idea**  
- After a successful create-graft in import (or on Live Sync first connect for unmatched new scripts), ask Studio (via bridge or post-import) for the new UniqueId and write it into the on-disk `.robloxmeta.json` (or local sibling).
- Optional `--assign-ids` flag on `verde-import`.
- Never overwrite an existing UniqueId; only fill missing ones.
- Aligns with the healing idea in I1 but focused on the create path.

### I5. Scoped Live Sync (tag or path-limited watch)

**Why**  
Full scripts-only Live Sync on a large place still walks and maps every script. Artists iterating on a single system (a UI pack, a combat module, a tagged “FeatureX”) want the bridge and watcher focused so rename noise and scan time stay proportional to the work in progress.

**Rough idea**  
- Plugin panel gains an optional Scope text field (accepts a dot-path or a tag name, same semantics as `verde-export --root` / `--tag`).
- On Live Sync enable, the UniqueId/Referent map and disk watcher are limited to the scoped subtree (or tagged instances + ancestors).
- Empty scope = current full scripts-only behaviour.
- Re-use the existing keep-map / partial.json helpers and the bridge’s current map-building path; no new long-lived state.
- Stay inside non-goals (no auto-create/delete, scripts-first).

### I6. Session-scoped Live Sync ignore list (temporary exclusions)

**Why**  
Artists often keep Live Sync on while heavily editing one or two scripts. Intermediate saves can bounce back and forth or be overwritten by a concurrent disk change. A temporary, session-only ignore list lets them protect those scripts without disabling Live Sync for the rest of the place or changing permanent scope.

**Rough idea**  
- Plugin panel gains a small “Ignore for this session” multi-line or tag-like list (accepts paths or UniqueIds already present in the map).  
- On Live Sync enable the ignore set is sent to the bridge; push/pull skips those entries for the lifetime of the connection.  
- List is cleared automatically on disconnect or toggle OFF; never written to disk, meta, or settings.  
- Stays strictly inside existing non-goals (no permanent config, no auto-create/delete). Re-uses the current UniqueId map and HTTP surface with one optional additional field.

### SIMPLISTIC

### S1. Machine-readable `--json` output for `verde-search`, `verde-tags`, and `verde-set`/`verde-replace`

**Why**  
The current human-oriented text output is fine for interactive use but awkward for CI, external scripts, or editor integrations. A stable JSON shape lets other tools consume matches without fragile parsing.

**Scope**  
- Add an optional `--json` flag to the three CLI entry points.
- When set, emit a single JSON array (or object) of results instead of pretty-printed lines: path, ClassName, Name, Referent, matched property/tag, and relevant values.
- Keep the default human output unchanged.
- Minimal surface: only the print/format paths in `features/search.py`, `features/tags.py`, and `features/set_replace.py`; no new dependencies.
- Document the schema briefly in `--help` and SYSTEM_OVERVIEW.

### S2. `--dry-run` for `verde-import`

**Why**  
Symmetric with the existing `--dry-run` on `verde-merge`. Lets a user (or CI) preview exactly which instances would be updated without touching the target `.rbxlx` or the manifest.

**Scope**  
- Add `--dry-run` to `build.main` / `import_rbxlx`.
- When set, perform matching + `_needs_update` checks and print the list of paths that would be applied, then exit without writing the place file or refreshing the manifest.
- Zero behavioural change when the flag is absent.

### S3. `--verbose` / `--quiet` for import and merge

**Why**  
Default summary lines are good for interactive use; scripts and large places benefit from either more detail (every applied path) or silence.

**Scope**  
- Add mutually exclusive `--verbose` / `--quiet` (or a single `-v`/`-q`) to `verde-import` and `verde-merge`.
- Verbose: list every path that was (or would be) applied.
- Quiet: suppress the “Applied N …” / “Nothing to merge” banners; still emit real errors on stderr.
- Minimal changes to the existing print sites in `build.py` and `features/sync.py`.

### S4. `verde-export --dry-run` that reports what would be written / overwritten / pruned

**Why**  
Symmetric with import/merge dry-run. Large places benefit from previewing the keep-map, selective filters, and which existing files would be touched before any disk writes.

**Scope**  
- Add `--dry-run` to `extract.main`.
- Walk the hierarchy (or selective), print the planned filesystem paths + action (create / overwrite / skip-identical / prune), then exit without writing.
- Minimal change to the existing progress / path-reuse logic; re-uses the same keep-map and uniqueness helpers.

### S5. Plugin status-line “last bridge event” timestamp + one-click “Force full resync”

**Why**  
Artists currently have only the Live Sync toggle; when the bridge briefly disconnects or a rename leaves residual noise, there is no obvious recovery button short of toggling off/on. A small status affordance makes the system feel more reliable.

**Scope**  
- Extend the existing plugin status line with the timestamp of the last successful /push or /pull.
- Add a “Resync now” button that triggers the same full scan-and-sync already performed on toggle ON.
- Pure UI + existing bridge endpoints; no new Python surface.

### S6. `verde-search --limit N` and matching plugin result cap

**Why**  
Huge places can produce thousands of matches; the current unbounded list is hard to scan and can freeze the plugin output. A soft limit keeps interactive use snappy.

**Scope**  
- CLI: `--limit` (default unlimited or a high soft default such as 500) truncates the printed list with a “… and N more” note.
- Plugin: same cap on the status / results area, with a “Show all” affordance that re-runs unbounded.
- Trivial change to the print / list loops in `features/search.py` and the plugin result renderer.

### S7. `verde-status --root` / `--tag` for partial dirty reports

**Why**  
When a selective extract is active (`.verde/partial.json` present), a full status list still reports every tracked file. Restricting the dirty/clean report to the same root or tag keeps status output useful for the current work focus and matches the selective export surface.

**Scope**  
- Accept the same `--root` / `--tag` flags already used by export.
- Filter the manifest walk (and any bridge probe) to the corresponding paths.
- Zero change when flags are absent. Minimal addition to `features/status.py` and the shared keep-map helpers.

### S8. `verde-export --quiet` / `--verbose`

**Why**  
Large places already emit progress every 100 instances. Interactive users and CI scripts often want complete silence or, conversely, a full per-path list of create / reuse / overwrite / prune actions. Symmetric with the quiet/verbose flags already pending for import and merge.

**Scope**  
- Add mutually exclusive `--quiet` / `--verbose` (or `-q` / `-v`) to `extract.main`.  
- Quiet: suppress the every-100 progress lines and the final “Exported N …” summary; still emit real errors on stderr.  
- Verbose: after the walk, list every filesystem action taken (or that would be taken under `--dry-run`).  
- Default behaviour unchanged. Minimal print-site edits in `extract.py`; re-uses existing keep-map, path-reuse, and progress helpers.

---

### Other (demoted from prior APPROVED)

#### Optional Rojo-compatible project layout export

**Description**  
Emit a folder structure and `default.project.json` that Rojo (or Argon / similar) can consume directly, so teams can move between verde’s lightweight workflow and a full Rojo pipeline.

**Recommendations & options**
- New command: `verde-export-rojo extracted/ --out rojo-project/`.
- Map scripts to the conventional `.server.lua` / `.client.lua` / `.lua` extensions Rojo expects (or keep verde’s `.lua` / `.local.lua` / `.module.lua` and document the mapping).
- Generate a basic `default.project.json` that mirrors the extracted hierarchy under `Workspace`, `ServerScriptService`, etc.
- Optional flag to also emit a `.gitignore` and a minimal README.
- Keep this as an *export* only; do not change the primary extract/build format.

#### Live `.rbxlx` diff / patch

**Description**  
Produce a human-readable or machine-readable diff between two `.rbxlx` files (or an extracted tree and a `.rbxlx`) focusing on instance hierarchy, script sources, tags, and interesting properties.

**Recommendations & options**
- Build on the existing structural comparison already present in `test_roundtrip.py`.
- CLI: `verde-diff a.rbxlx b.rbxlx` or `verde-diff extracted/ place.rbxlx`.
- Output formats: plain text summary, unified-diff style for script sources, optional JSON for tooling.
- Useful both for debugging round-trips and for reviewing changes before a rebuild.

#### Attributes as first-class citizens (remaining work)

**Description**  
Treat Instance Attributes the same way Tags are treated today: extract them into `.robloxmeta.json`, support search/filter by attribute name/value, and round-trip them losslessly.

**Status**  
Foundation complete:
- `python/attributes.py` — full decode/encode for the AttributesSerialize binary format.
- `extract.py` parses `AttributesSerialize` into top-level `meta["Attributes"]`.
- `build.py` re-emits a correct `AttributesSerialize` BinaryString when `meta["Attributes"]` is present.
- Unit tests in `python/tests/test_attributes.py`.

Still open:
- Extend `matches` / search CLI with `--attr Name` and `--attr-value …`.
- In the Luau module, add thin wrappers around `GetAttribute` / `SetAttribute` that mirror the existing tag helpers.
- Keep Attributes out of the “interesting properties” list unless explicitly requested.

#### Touched-file tracking + offline merge (CLI: `verde-merge`) — remaining work

**Description**  
Track which files in an extracted Verde tree have changed (simple numeric content hash + mtime) so that export/import can skip unchanged work and so **`verde-merge`** can keep the folder and a `.rbxlx` in agreement offline.

**Conflict rule (today)**  
Most recently modified side wins (mtime-win).

**Future improvement**  
Replace pure mtime-win with **git-merge-style conflict resolution** when both sides changed the same logical content (manual or 3-way merge), instead of silently picking one mtime.

**Hash**  
`zlib.adler32` — stable integer for change detection.

**Status**  
Foundation complete:
- `python/features/sync.py` — manifest helpers + **`verde-merge`** CLI.
- `extract.py` writes `.verde/manifest.json` after export.
- `build.py` / `verde-import` skips clean files via the manifest.

Still open:
- Selective pull once selective extract lands.
- Git-merge-style conflicts for `verde-merge`.

---

*APPROVED items are eligible for the Build skill. PENDING items (including demoted work) await further approval. Order of APPROVED items follows operator preference.*
