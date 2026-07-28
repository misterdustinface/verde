# Verde — System Overview

**Minimal Roblox place export / edit / import toolkit** — offline `.rbxlx` tools plus a matching Luau module and Studio plugin for live DataModel operations.

**Version 1.0.0** · [Unlicense](../LICENSE) (public domain)

You can use **either** the Python CLI **or** the Luau module / Studio plugin (or both). Python is **not required** for in-Studio search / set / tags.

> Non-programmers: start with the [main README](../README.md) — especially **Live Sync** (`verde-sync`).

---

## Why Verde?

Verde focuses on:

- One-shot export of an existing place into a searchable, editable folder tree
- Bulk search / set / replace of properties and CollectionService tags
- Near-lossless round-trips (`export` → edit → `import`)
- **Live Sync** so an **open** Studio place stays in sync with script files on disk (no close/reopen)
- A **single shared Luau module** used by the plugin
- Iterative version-control friendly import that patches an existing `.rbxlx` instead of always rebuilding from scratch
- Touched-file tracking (`.verde/manifest.json`) so repeated import/merge can skip unchanged work

Scripts become real `.lua` / `.local.lua` / `.module.lua` files. Everything else becomes a folder + `.robloxmeta.json`.

### Critical: open place vs on-disk `.rbxlx`

| Tool | Updates `.rbxlx` on disk | Updates **open** Studio place |
|------|--------------------------|-------------------------------|
| `verde-import` / `verde-merge` | Yes | **No** |
| **`verde-sync` + plugin Live Sync** | Writes script/meta files | **Yes** |

Always run **`verde-sync`** when artists/designers need live updates in Studio.

---

## CLI commands (no aliases)

| Command | Module | Purpose |
|---------|--------|---------|
| `verde-export` | `export:main` | `.rbxlx` → folder tree |
| `verde-import` | `build:main` | folder → existing or new `.rbxlx` |
| `verde-merge` | `features.sync:main` | Offline folder ↔ `.rbxlx` (mtime-win today; **future: git-merge-style conflicts**) |
| `verde-sync` | `features.bridge:main` | Live folder ↔ **open** Studio |
| `verde-search` | `features.search:main` | Find instances in the folder tree |
| `verde-set` / `verde-replace` | `features.set_replace:main` | Set or conditionally replace properties |
| `verde-tags` | `features.tags:main` | List or rename tags |
| `verde-test-roundtrip` | `test_roundtrip:main` | Smoke test |

Use only the names above. There are no alternate command aliases.

### Luau (single source of truth)

`Verde.luau` provides `search` / `setProp` / `replaceProp` / `listTags` / `replaceTag` and Live Sync helpers (path/Referent resolve, serialize/apply, scoped UniqueId map, HTTP client).

## Install

### Studio plugin

See **[plugin/README.md](../plugin/README.md)**.

### Python CLI

Requires **Python ≥ 3.9.6**.

```bash
git clone https://github.com/misterdustinface/verde.git
cd verde
pip install -e ".[dev]"
```

## Live Sync (open Studio)

```bash
verde-export MyPlace.rbxlx code/
verde-sync code/          # leave running

# Studio: Allow HTTP Requests ON → Verde panel → Live Sync ON
```

Architecture (port is fixed and not shown in the UI):

```
extracted/  ←→  verde-sync (Python, localhost :3847)
                      ↕
               Verde Studio plugin  →  live DataModel (scripts)
```

| Mode | Watched | UniqueId map on connect |
|------|---------|-------------------------|
| **Default** | Script `Source` only | **Scripts only** (script-bearing services) |
| **Experimental: property sync** | Scripts + Name / LIVE_PROPS / Attributes | Still **scripts only** (same watch set) |
| Future all-instance mode | (not shipped) | `refreshUniqueIdMap(false)` → full DataModel |

Matching order: **Referent / UniqueId** from `.robloxmeta.json`, then hierarchy path. Map is rebuilt once on connect for the active scope, then maintained incrementally (add/destroy). Dirty applies never rebuild the map.

Safe defaults: never auto-creates or deletes instances from disk.

Artist-facing steps: [main README](../README.md). Open follow-ups: [TODO_FEATURES.md](TODO_FEATURES.md) §10.

## Quick start (Python CLI)

```bash
verde-export MyPlace.rbxlx code/
verde-export MyPlace.rbxlx extracted/ --all

verde-sync code/                    # live with Studio

verde-search extracted/ --class Sound --prop SoundId --contains 123456789
verde-set extracted/ --prop CastShadow --to false --tag NoShadow
verde-tags extracted/ --list

verde-import code/ MyPlace.rbxlx    # on-disk only; does not refresh open Studio
verde-import code/ MyPlace.rbxlx --force   # ignore mtime-win / clean skips
verde-merge code/ MyPlace.rbxlx     # offline dirty push/pull via manifest + mtime-win
verde-merge code/ MyPlace.rbxlx --dry-run
```

### Flags (summary)

**`verde-export`:** `--all`, `--interesting`, `--interactive`  
**`verde-import`:** target path; creates file if missing; `--force` (bypass mtime-win / clean-manifest skips)  
**`verde-merge`:** `--dry-run`  
**`verde-sync`:** extracted folder path only (port hidden)  
**`verde-search` / `verde-set` / `verde-tags`:** see `--help`

## Exported layout

```
extracted/
├── .verde/manifest.json
├── ServerScriptService/
│   ├── Main.lua
│   └── Main.robloxmeta.json
└── ...
```

| ClassName     | Extension        |
|---------------|------------------|
| Script        | `.lua`           |
| LocalScript   | `.local.lua`     |
| ModuleScript  | `.module.lua`    |

## Project layout

```
verde/
├── docs/
│   ├── SYSTEM_OVERVIEW.md
│   ├── BUGS.md
│   └── TODO_FEATURES.md
├── luau/
│   ├── Verde.luau
│   └── interesting_properties.luau
├── plugin/
│   ├── VerdePlugin.server.luau
│   └── README.md
├── python/
│   ├── export.py               # verde-export
│   ├── build.py                # verde-import
│   ├── features/
│   │   ├── sync.py             # verde-merge (manifest + mtime-win)
│   │   ├── bridge.py           # verde-sync (live Studio)
│   │   ├── search.py / set_replace.py / tags.py / meta.py
│   └── tests/
└── pyproject.toml
```

## Development

```bash
pip install -e ".[dev]"
pytest
verde-test-roundtrip
```

## License

Unlicense — see [LICENSE](../LICENSE).
