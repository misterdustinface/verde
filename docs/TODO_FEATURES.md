# TODO_FEATURES.md — Verde

Future features and intentional enhancements.  
Pure defects remain in `BUGS.md`.

---

## APPROVED

Ordered per operator preference.

### 1. `verde-status` CLI for manifest dirtiness and bridge health

**Description**  
There is currently no single, zero-risk command that answers “which files are dirty?” or “is the Live Sync bridge reachable?”. Artists and power users both benefit from an instant, read-only status check.

**Scope**  
- New entry point `verde-status [extracted/]` (default: current directory or the path last used by sync).
- Report clean / dirty / missing files from `.verde/manifest.json` (optionally with hash and mtime).
- Optionally probe `localhost:3847` and report whether the bridge is up plus any last-activity hint the bridge already exposes.
- Purely read-only; re-uses helpers already present in `features/sync.py` and `features/bridge.py`.
- Human-readable default; honour a `--json` flag for machine consumption (aligns with pending JSON output work).
- Document in the main README and SYSTEM_OVERVIEW; no new dependencies or configuration surface.

---

### 2. Interactive disambiguation for case-insensitive search matches

**Description**  
When a case-insensitive search (e.g. `propContains` / nameContains / tag filters) yields multiple distinct values that differ only by case, prompt the user to choose which match(es) to act on instead of silently applying a case-insensitive equality or forcing one. Case sensitivity for properties and tags remains intentional and important.

**Why**  
Per HUMAN OPERATOR guidance: case matters for properties and tags. The previous approach of making `replaceProp` fully case-insensitive was rejected. Search can still be helpful case-insensitively for discovery, but the final selection / replace must respect exact case and offer explicit choice when ambiguity exists.

**Rough idea / Scope**
- In the Studio plugin UI and (optionally) CLI interactive mode, when the candidate set contains multiple values that collide under case-folding, present a short list (original-cased values + instance counts / paths) and let the user pick one or more before proceeding with set/replace.
- Keep non-interactive / scripted paths exact-case by default.
- Do not change the existing exact-match final check in `Verde.replaceProp` or Python `only_if_old`.
- Document the behaviour clearly so users understand that case-insensitive filters are for discovery only.

---

### 3. Selective extract / partial rebuild

**Description**  
Extract or rebuild only a subtree (e.g. everything under `ServerScriptService` or a single tagged model) instead of the whole place.

**Recommendations & options**
- Add `--root ClassName.Name` or `--tag SomeTag` filters to `verde-export` and `verde-import`.
- On export, emit a smaller folder tree plus a manifest that records the original attachment point.
- On import, allow grafting the partial tree back into an existing `.rbxlx` (or into a previously extracted full tree).
- Reduces turnaround time for large places when only a few systems are being edited.

---

### 4. Preserve root-level Meta / External / SharedStrings

**Description**  
Some `.rbxlx` files contain top-level elements outside the main `Item` tree (`Meta`, `External`, `ExternalAssets`, `SharedStrings`, etc.). These are currently dropped on extract/build.

**Recommendations & options**
- On extract, write a special top-level file (e.g. `.robloxroot.json` or `meta/root.xml` fragments) that stores any non-`Item` children of the `<roblox>` root.
- On build, re-insert those fragments in the original order before or after the instance tree.
- Minimal viable approach: capture the raw XML snippets of unknown root children and round-trip them verbatim.
- Document that places using SharedString tables or external asset references will now survive a round-trip.

---

### 5. Richer property round-tripping for complex / rare types

**Description**  
Improve fidelity for property types that currently lose information or are only partially reconstructed (NumberSequence / ColorSequence keypoints, PhysicalProperties, FontFace, Content, SharedString references, Attributes, etc.).

**Recommendations & options**
- Extend `_parse_property_element` / `_emit_property` to treat repeated child tags as ordered lists (list-of-dicts) instead of a single dict entry.
- Add explicit handlers for well-known complex types (NumberSequence, ColorSequence, NumberRange, Rect, UDim2, Font, PhysicalProperties, …).
- Optionally capture Attributes (currently under a different XML structure in newer places) as a first-class map in `.robloxmeta.json`.
- Keep the “interesting properties” surface limited to scalars for search/set; complex types stay in the structured `Properties` map only.
- Add focused unit tests that assert full keypoint / sequence round-trips.

---

### 6. Plugin: persist last search filters

**Description**  
Remember the most recent ClassName / Name / Tag / Property filters in the Studio plugin so users do not have to re-type them every session.

**Recommendations & options**
- Store the last values in `plugin:SetSetting` / `plugin:GetSetting` (Studio’s built-in plugin settings API).
- On panel open, pre-fill the TextBoxes from the saved settings.
- Add a small “Clear filters” button that also clears the persisted values.
- Optionally persist the last dump/restore options (dry-run, recreate-missing, etc.) the same way.

---

### 7. Streaming search / replace on live `.rbxlx`

**Description**  
Operate on a `.rbxlx` file in place (or via a temporary copy) without a full extract → edit → rebuild cycle. Useful for large places where disk I/O and intermediate folder trees are expensive.

**Recommendations & options**
- **SAX / iterative parser** (preferred for memory): walk the XML with `xml.etree.ElementTree.iterparse` (or `lxml` if added as an optional dependency). Match `Item` elements on the fly, apply set/replace, and write a new file.
- **In-memory DOM with selective rewrite**: parse once, mutate matching nodes, then serialise. Simpler but higher peak memory.
- CLI shape: `verde-search --rbxlx Place.rbxlx …` and `verde-set --rbxlx Place.rbxlx …` that accept the same filters as the folder-based commands.
- Keep the existing folder-based tools as the default; make streaming an explicit flag or sub-command so behaviour stays predictable.

---

### 8. Live Sync with open Studio (CLI: `verde-sync`)

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

### 9. Plugin hierarchy navigator + recent-sync timeline

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
