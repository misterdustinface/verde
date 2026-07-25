# Verde Studio Plugin

In-Studio UI for Verde. All DataModel logic lives in the **Verde ModuleScript** (single source of truth).

## Features

- **Live Sync** — bi-directional script Source sync with an extracted folder (requires `verde-sync` CLI; see below)
- **Search** — filter by ClassName, Name, tag, or property value
- **Set / Replace property** — by ClassName, by tag, or only when current value matches (undo via ChangeHistoryService)
- **Tags** — list every CollectionService tag; rename a tag across the place

## Live Sync — required for live file ↔ Studio updates

`verde-import` updates the `.rbxlx` **on disk**. It does **not** refresh an already-open place in Studio.

To keep Studio and your script files in sync **while the place is open**:

1. **Game Settings → Security → Allow HTTP Requests = ON** (once per place)
2. In a terminal (leave it open):
   ```bash
   verde-sync path/to/your/extracted
   ```
   Use the same folder you created with `verde-export`.
3. In Studio open the **Verde** panel → turn **Live Sync** **ON**

**Default:** only script **Source** is watched (safe for large places).  
**Experimental: property sync** is **OFF** by default (optional Name / attributes / extra props on scripts only).

**Matching:** Referent / UniqueId from meta first, then hierarchy path. On connect, the UniqueId map is built **scripts-only** (same scope as the watch set). Incremental add/remove thereafter.

If connection fails, the panel shows step-by-step fixes (HttpService vs `verde-sync` not running).

Artist-oriented steps: [main README](../README.md). Technical overview: [docs/SYSTEM_OVERVIEW.md](../docs/SYSTEM_OVERVIEW.md).

## Install (required layout)

1. Create a local plugin folder.
2. Add a **ModuleScript** named `Verde` and paste the contents of [`luau/Verde.luau`](../luau/Verde.luau).
3. (Recommended) Add a child **ModuleScript** named `interesting_properties` and paste [`luau/interesting_properties.luau`](../luau/interesting_properties.luau).
4. Add a **Script** and paste [`VerdePlugin.server.luau`](VerdePlugin.server.luau).
5. Save / reload the plugin.

The plugin will error at load time if the Verde ModuleScript cannot be required.

## Relationship to Python tools

| Task | Python CLI | Studio |
|------|------------|--------|
| **Live script sync** | **`verde-sync`** | **Live Sync toggle** |
| Search | `verde-search` | Search panel / `Verde.search` |
| Set by tag / class | `verde-set` | Set panel / `Verde.setProp` |
| Replace values | `verde-replace` | Set panel (optional “only if”) |
| Tags | `verde-tags` | Tags panel |
| Export place | `verde-export` | (file-system) |
| Import on disk | `verde-import` | does **not** refresh open Studio — use Live Sync |
| Offline folder ↔ place file | `verde-merge` | (file-system; mtime-win today) |
