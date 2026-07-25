# Future Features

Planned and aspirational features for verde.  
Each entry includes a short description plus concrete implementation options.

---

## 1. Streaming search / replace on live `.rbxlx`

**Description**  
Operate on a `.rbxlx` file in place (or via a temporary copy) without a full extract → edit → rebuild cycle. Useful for large places where disk I/O and intermediate folder trees are expensive.

**Recommendations & options**
- **SAX / iterative parser** (preferred for memory): walk the XML with `xml.etree.ElementTree.iterparse` (or `lxml` if added as an optional dependency). Match `Item` elements on the fly, apply set/replace, and write a new file.
- **In-memory DOM with selective rewrite**: parse once, mutate matching nodes, then serialise. Simpler but higher peak memory.
- CLI shape: `verde-search --rbxlx Place.rbxlx …` and `verde-set --rbxlx Place.rbxlx …` that accept the same filters as the folder-based commands.
- Keep the existing folder-based tools as the default; make streaming an explicit flag or sub-command so behaviour stays predictable.

---

## 2. Richer property round-tripping for complex / rare types

**Description**  
Improve fidelity for property types that currently lose information or are only partially reconstructed (NumberSequence / ColorSequence keypoints, PhysicalProperties, FontFace, Content, SharedString references, Attributes, etc.).

**Recommendations & options**
- Extend `_parse_property_element` / `_emit_property` to treat repeated child tags as ordered lists (list-of-dicts) instead of a single dict entry.
- Add explicit handlers for well-known complex types (NumberSequence, ColorSequence, NumberRange, Rect, UDim2, Font, PhysicalProperties, …).
- Optionally capture Attributes (currently under a different XML structure in newer places) as a first-class map in `.robloxmeta.json`.
- Keep the “interesting properties” surface limited to scalars for search/set; complex types stay in the structured `Properties` map only.
- Add focused unit tests that assert full keypoint / sequence round-trips.

---

## 3. Preserve root-level Meta / External / SharedStrings

**Description**  
Some `.rbxlx` files contain top-level elements outside the main `Item` tree (`Meta`, `External`, `ExternalAssets`, `SharedStrings`, etc.). These are currently dropped on extract/build.

**Recommendations & options**
- On extract, write a special top-level file (e.g. `.robloxroot.json` or `meta/root.xml` fragments) that stores any non-`Item` children of the `<roblox>` root.
- On build, re-insert those fragments in the original order before or after the instance tree.
- Minimal viable approach: capture the raw XML snippets of unknown root children and round-trip them verbatim.
- Document that places using SharedString tables or external asset references will now survive a round-trip.

---

## 4. Optional Rojo-compatible project layout export

**Description**  
Emit a folder structure and `default.project.json` that Rojo (or Argon / similar) can consume directly, so teams can move between verde’s lightweight workflow and a full Rojo pipeline.

**Recommendations & options**
- New command: `verde-export-rojo extracted/ --out rojo-project/`.
- Map scripts to the conventional `.server.lua` / `.client.lua` / `.lua` extensions Rojo expects (or keep verde’s `.lua` / `.local.lua` / `.module.lua` and document the mapping).
- Generate a basic `default.project.json` that mirrors the extracted hierarchy under `Workspace`, `ServerScriptService`, etc.
- Optional flag to also emit a `.gitignore` and a minimal README.
- Keep this as an *export* only; do not change the primary extract/build format.

---

## 5. Plugin: persist last search filters

**Description**  
Remember the most recent ClassName / Name / Tag / Property filters in the Studio plugin so users do not have to re-type them every session.

**Recommendations & options**
- Store the last values in `plugin:SetSetting` / `plugin:GetSetting` (Studio’s built-in plugin settings API).
- On panel open, pre-fill the TextBoxes from the saved settings.
- Add a small “Clear filters” button that also clears the persisted values.
- Optionally persist the last dump/restore options (dry-run, recreate-missing, etc.) the same way.

---

## 6. Live `.rbxlx` diff / patch

**Description**  
Produce a human-readable or machine-readable diff between two `.rbxlx` files (or an extracted tree and a `.rbxlx`) focusing on instance hierarchy, script sources, tags, and interesting properties.

**Recommendations & options**
- Build on the existing structural comparison already present in `test_roundtrip.py`.
- CLI: `verde-diff a.rbxlx b.rbxlx` or `verde-diff extracted/ place.rbxlx`.
- Output formats: plain text summary, unified-diff style for script sources, optional JSON for tooling.
- Useful both for debugging round-trips and for reviewing changes before a rebuild.

---

## 7. Selective extract / partial rebuild

**Description**  
Extract or rebuild only a subtree (e.g. everything under `ServerScriptService` or a single tagged model) instead of the whole place.

**Recommendations & options**
- Add `--root ClassName.Name` or `--tag SomeTag` filters to `verde-export` and `verde-import`.
- On export, emit a smaller folder tree plus a manifest that records the original attachment point.
- On import, allow grafting the partial tree back into an existing `.rbxlx` (or into a previously extracted full tree).
- Reduces turnaround time for large places when only a few systems are being edited.

---

## 8. Attributes as first-class citizens

**Description**  
Treat Instance Attributes the same way Tags are treated today: extract them into `.robloxmeta.json`, support search/filter by attribute name/value, and round-trip them losslessly.

**Status**  
Foundation complete:
- `python/attributes.py` — full decode/encode for the AttributesSerialize binary format (string, bool, int32, float32/64, UDim, UDim2, BrickColor, Color3, Vector2/3, CFrame, EnumItem, NumberSequence, ColorSequence, NumberRange, Rect, Font).
- `extract.py` parses `AttributesSerialize` into top-level `meta["Attributes"]` and removes the opaque BinaryString from `Properties`.
- `build.py` re-emits a correct `AttributesSerialize` BinaryString when `meta["Attributes"]` is present.
- Unit tests in `python/tests/test_attributes.py`.

Still open:
- Extend `matches` / search CLI with `--attr Name` and `--attr-value …`.
- In the Luau module, add thin wrappers around `GetAttribute` / `SetAttribute` that mirror the existing tag helpers.
- Keep Attributes out of the “interesting properties” list unless explicitly requested; they are orthogonal to the classic property system.

---

## 9. Touched-file tracking + verde-sync

**Description**  
Track which files in an extracted Verde tree have changed (simple numeric content hash + mtime) so that export/import can skip unchanged work and so a `verde-sync` command can keep the folder and a `.rbxlx` (or later a live Studio DataModel) in agreement.

**Conflict rule**  
When the same instance has been modified on both sides, the **most recently modified** side wins and is replicated to the other. File mtime is the authority for the Verde side; the `.rbxlx` file mtime is the authority for the Roblox side when a per-instance timestamp is unavailable.

**Hash**  
Use a simple, efficient non-cryptographic numeric hash of the file content (stdlib `zlib.adler32`). Only needs to turn a string/bytes into a stable integer for change detection; collisions are acceptable for this use-case.

**Recommendations & options**
- Manifest stored at `<extracted>/.verde/manifest.json`:
  ```json
  {
    "version": 1,
    "rbxlx": "/absolute/or/relative/path/to/Place.rbxlx",
    "rbxlx_mtime": 1721…,
    "last_sync": 1721…,
    "files": {
      "Workspace/Main.lua": {"h": 1234567890, "m": 1721…},
      "Workspace/Main.robloxmeta.json": {"h": …, "m": …}
    }
  }
  ```
- On every successful `verde-export` / extract, rewrite the manifest with current hashes + mtimes of every `.lua` / `.local.lua` / `.module.lua` and every `.robloxmeta.json`.
- On `verde-import`, if a manifest is present:
  - Skip any file whose current `(hash, mtime)` matches the recorded entry (fast path — no XML apply).
  - When a file’s content has changed, apply the existing differential import only if the Verde file’s mtime is ≥ the recorded / `.rbxlx` mtime (mtime-wins rule).
- `verde-sync extracted/ Place.rbxlx`:
  - Push dirty Verde → `.rbxlx` using the rules above.
  - If the `.rbxlx` is newer than `last_sync` and no Verde files are dirty, optionally pull (full or selective re-extract). Full re-extract is the safe first implementation; selective pull can come later with #7.
- Keep the current full-walk behaviour as the fallback when no manifest exists.
- Future: live Studio bridge that uses the same dirty-set + Referent matching already present in the Luau module.

**Status**  
Foundation complete:
- `python/features/sync.py` — `content_hash` (zlib.adler32), load/write manifest, `is_file_dirty` / `dirty_paths` with mtime-win, `verde-sync` CLI.
- `extract.py` writes `.verde/manifest.json` after every successful export.
- `build.py` / `verde-import` skips clean files via the manifest and refreshes the manifest after a successful import.
- Entry point: `verde-sync`.

Still open:
- Selective pull (instead of full re-export when `.rbxlx` is newer) once #7 lands.
- Live Studio DataModel bridge.

---

*Prioritise items 1–3 for correctness and large-place usability. Items 4–5 improve workflow integration. Items 6–9 are natural extensions once the core round-trip is solid.*
