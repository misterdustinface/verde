# Verde — System Overview

**Minimal Roblox place export / edit / import toolkit** — offline `.rbxlx` tools plus a matching Luau module and Studio plugin for live DataModel operations.

**Version 0.0.0** · [Unlicense](../LICENSE) (public domain)

You can use **either** the Python CLI **or** the Luau module / Studio plugin (or both). Python is **not required**.

> Looking for a simple getting-started guide? See the [main README](../README.md).

---

## Why Verde?

Verde focuses on:

- One-shot export of an existing place into a searchable, editable folder tree
- Bulk search / set / replace of properties and CollectionService tags
- Near-lossless round-trips (`export` → edit → `import`)
- Script dump & restore inside Studio without leaving the DataModel
- A **single shared Luau module** used by both the plugin and Command-Bar scripts
- Iterative version-control friendly import that patches an existing `.rbxlx` instead of always rebuilding from scratch
- Touched-file tracking (`.verde/manifest.json`) so repeated import/sync can skip unchanged work

Scripts become real `.lua` / `.local.lua` / `.module.lua` files. Everything else becomes a folder + `.robloxmeta.json` that captures **all** properties (not just a curated subset) so rebuilds stay faithful. Attributes are also first-class (decoded/encoded via `AttributesSerialize`).

## Features

### Python CLI (optional)

| Command | Purpose |
|---------|---------|
| `verde-export` | `.rbxlx` → folder tree (alias: `verde-extract`) |
| `verde-import` | folder tree → apply changes into an existing `.rbxlx` (or create it if missing) (alias: `verde-merge`) |
| `verde-sync` | Push dirty extracted files → `.rbxlx` (or pull when the place is newer); uses manifest + mtime-win |
| `verde-search` | Find instances by ClassName, Name, tag, or property value |
| `verde-set` / `verde-replace` | Set or conditionally replace any property |
| `verde-tags` | List or rename CollectionService tags |

### Luau (single source of truth)

`Verde.luau` provides:

- `search` / `setProp` / `replaceProp`
- `listTags` / `replaceTag`
- `dumpScripts` / `restoreScripts`

The Studio plugin and the thin `DumpScripts` / `RestoreScripts` Command-Bar wrappers all `require` this module — no duplicated logic. These work entirely inside Roblox Studio; no Python needed.

### Shared design principles

- **Interesting properties** live in one place: `luau/interesting_properties.luau` (Luau-first; the optional Python tools parse the same file)
- **Tags** are first-class (BinaryString ↔ list) in both export/import and live operations
- **Attributes** are first-class (AttributesSerialize binary ↔ map in `.robloxmeta.json`)
- Full structured property map is preserved for successful round-trips
- Shared helpers (`features/meta.py` on the Python side; search reused inside Luau set/replace)
- Manifest-driven dirty tracking for efficient iterative workflows (`features/sync.py`)

## Install

### Luau / Studio plugin only (no Python required)

Copy the ModuleScript(s) into a local plugin as described in **[plugin/README.md](../plugin/README.md)**.

### Python CLI (optional)

Requires **Python ≥ 3.9.6** if you want the offline export / import / search tools.

```bash
git clone https://github.com/misterdustinface/verde.git
cd verde
pip install -e ".[dev]"
```

This installs the console scripts:

`verde-export` · `verde-extract` (alias) · `verde-import` · `verde-merge` (alias) · `verde-sync` · `verde-search` · `verde-set` · `verde-replace` · `verde-tags` · `verde-test-roundtrip`

## Quick start (Python CLI)

```bash
# Export code-only tree (default): only directories that lead to scripts
verde-export MyPlace.rbxlx code/

# Export full hierarchy (every instance) for lossless round-trips
verde-export MyPlace.rbxlx extracted/ --all

# Re-export into an existing tree: reuses paths, overwrites only on content diff
verde-export MyPlace.rbxlx code/

# Same, but prompt Y/n before overwriting differing files
verde-export MyPlace.rbxlx code/ --interactive

# Search
verde-search extracted/ --class Sound --prop SoundId --contains 123456789
verde-search extracted/ --tag NoShadow --json

# Set / replace (unconditional or conditional)
verde-set extracted/ --prop CastShadow --to false --tag NoShadow
verde-set extracted/ --prop Anchored --to true --class Part
verde-replace extracted/ --prop SoundId --from 123456789 --to 987654321
verde-set extracted/ --prop Transparency --to 0.5 --name-contains Window --dry-run

# Tags
verde-tags extracted/ --list
verde-tags extracted/ --replace OldTag NewTag

# Import / merge changes back into the original place (preserves everything not present in the folder)
verde-import code/ MyPlace.rbxlx
# (or the alias)
verde-merge code/ MyPlace.rbxlx

# Or create a brand-new .rbxlx from the folder (previous "build" behaviour)
verde-import extracted/ NewPlace.rbxlx

# Sync: push dirty files (mtime-win) or pull when the .rbxlx is newer
verde-sync code/ MyPlace.rbxlx
verde-sync code/ MyPlace.rbxlx --dry-run
```

### CLI flags at a glance

**`verde-export`** (alias: `verde-extract`)

```
--all                        # full hierarchy (default is scripts-only)
--interesting PROP1,PROP2    # override flattened property list
--interactive                # prompt Y/n before overwriting a file that differs
                             # (default: overwrite on diff, skip when identical;
                             #  existing paths are always reused — no Name_2 inventing)
```

**`verde-import`** (alias: `verde-merge`)

```
# No extra flags required.
# - If the target .rbxlx exists → differential import (match by Referent, then path;
#   apply Source + Properties + Tags + Attributes; leave unmatched instances alone;
#   skips files that match the .verde/manifest dirty check)
# - If the target .rbxlx does not exist → full rebuild from the folder
```

**`verde-sync`**

```
# Uses .verde/manifest.json (written by export / refreshed by import & sync)
# - Dirty Verde files (content hash or mtime) are pushed via import when Verde is newer
# - If the .rbxlx is newer than last_sync and no Verde files are dirty → full re-export (pull)
# --dry-run   show what would be done
```

**`verde-search`**

```
--class CLASSNAME
--name NAME                  # exact
--name-contains SUBSTR
--tag TAG
--prop PROP --contains SUBSTR
--json
```

**`verde-set` / `verde-replace`**

```
--prop PROP                  # required
--to VALUE                   # required
--from OLD                   # optional; only change when current value matches
--tag TAG
--class CLASSNAME
--name / --name-contains
--dry-run
```

**`verde-tags`**

```
--list
--replace OLD NEW
--dry-run
```

## Exported layout

```
extracted/
├── .verde/
│   └── manifest.json                 # content hashes + mtimes for dirty tracking
├── Workspace/
│   ├── Baseplate/
│   │   └── .robloxmeta.json          # ClassName, Name, Tags, Attributes, full Properties
│   └── ...
├── ServerScriptService/
│   ├── Main.lua                      # real Source content
│   └── Main.robloxmeta.json
└── ...
```

Script file naming:

| ClassName     | File extension   |
|---------------|------------------|
| Script        | `.lua`           |
| LocalScript   | `.local.lua`     |
| ModuleScript  | `.module.lua`    |

## Luau module & Studio plugin

**`Verde.luau` is the single source of truth.** All live DataModel operations go through it.

```luau
local Verde = require(path.to.Verde)

-- Search
local sounds = Verde.search({
	className = "Sound",
	prop = "SoundId",
	propContains = "123",
})

-- Set / replace
Verde.setProp("CastShadow", false, { tag = "NoShadow" })
Verde.setProp("Anchored", true, { className = "Part" })
Verde.replaceProp("SoundId", "123456789", "987654321")

-- Tags
local tagMap = Verde.listTags()
Verde.replaceTag("OldTag", "NewTag")

-- Script archive (under ServerStorage by default)
local archive, count = Verde.dumpScripts()
local restored, created, skipped = Verde.restoreScripts()
```

See **[plugin/README.md](../plugin/README.md)** for:

- Exact install steps (ModuleScript named `Verde` + optional `interesting_properties` child)
- Plugin feature list (Search / Set / Tags / Dump-Restore panels)
- Mapping between Python CLI commands and Studio actions

Standalone Command-Bar scripts (`luau/DumpScripts.luau`, `luau/RestoreScripts.luau`) are thin wrappers that also require the same `Verde` ModuleScript.

## Interesting properties

The list of properties that are flattened for convenient search/set lives in a single canonical file:

```
luau/interesting_properties.luau
```

The optional Python tools load the same file (via `python/interesting.py`). You can override at runtime with:

1. Environment variable `VERDE_INTERESTING_PROPS=Prop1,Prop2,...`
2. A local `verde.interesting` file (one name per line or comma-separated)
3. `--interesting` flag on `verde-export`

## Project layout

```
verde/
├── docs/
│   ├── SYSTEM_OVERVIEW.md            # This file — full technical documentation
│   ├── BUGS.md                       # Known correctness / data-loss issues
│   └── TODO_FEATURES.md              # Planned features and implementation options
├── luau/
│   ├── Verde.luau                    # Single source of truth for all live DataModel ops
│   │                                 # (search, setProp, replaceProp, tags, dump/restore)
│   ├── interesting_properties.luau   # Canonical list of properties flattened for search/set
│   ├── DumpScripts.luau              # Command-Bar wrapper that calls Verde.dumpScripts
│   └── RestoreScripts.luau           # Command-Bar wrapper that calls Verde.restoreScripts
├── plugin/
│   ├── VerdePlugin.server.luau       # Studio plugin UI (Search / Set / Tags / Dump-Restore panels)
│   └── README.md                     # Plugin install instructions and feature mapping
├── python/                           # Optional offline CLI tools (not required for Luau/plugin)
│   ├── extract.py                    # Primary: parse .rbxlx → searchable/editable folder tree (CLI: verde-export)
│   ├── build.py                      # Primary: import / rebuild .rbxlx from an extracted folder tree (CLI: verde-import / verde-merge)
│   ├── interesting.py                # Loads the canonical interesting_properties.luau list
│   ├── attributes.py                 # Binary codec for AttributesSerialize
│   ├── test_roundtrip.py             # Round-trip smoke test (export → import → compare)
│   ├── features/
│   │   ├── meta.py                   # Shared helpers: walk metas, get/set props, match filters
│   │   ├── search.py                 # CLI: find instances by class / name / tag / property
│   │   ├── set_replace.py            # CLI: set or conditionally replace any property
│   │   ├── tags.py                   # CLI: list or rename CollectionService tags
│   │   └── sync.py                   # Touched-file tracking + verde-sync (adler32 + mtime-win)
│   └── tests/                        # Unit tests (property parsing, attributes, set_prop, etc.)
│       ├── test_attributes.py
│       ├── test_properties.py
│       └── test_set_prop.py
└── pyproject.toml                    # Packaging, entry points, and project metadata
```

## Development

```bash
pip install -e ".[dev]"
pytest
# or
verde-test-roundtrip
```

`pytest` discovers tests under `python/tests/` (configured in `pyproject.toml`). The `pythonpath = ["python"]` setting lets the tests import `extract`, `build`, `attributes`, and `features.*` directly.

See [`docs/BUGS.md`](BUGS.md) for known issues and [`docs/TODO_FEATURES.md`](TODO_FEATURES.md) for planned features (streaming edit of a live `.rbxlx`, richer complex property types, optional project-layout export, plugin filter persistence, selective extract, etc.). Foundations for Attributes (#8) and touched-file sync (#9) are already landed.

## License

Unlicense — released into the public domain. See [LICENSE](../LICENSE).
