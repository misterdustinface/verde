# Verde Studio Plugin

In-Studio counterpart to the Python CLI tools. All DataModel logic lives in the **Verde ModuleScript** (single source of truth).

## Features

- **Search** – filter by ClassName, Name, tag, or property value.
- **Set / Replace property** – by ClassName, by tag, or only when current value matches (undo via ChangeHistoryService).
- **Tags** – list every CollectionService tag; rename a tag across the place.
- **Script dump / restore** – archive all scripts under ServerStorage as a `ScriptDump_*` folder (Save to File as `.rbxm`), then restore Source / Enabled / RunContext / tags back into the place.

## Install (required layout)

1. Create a local plugin folder.
2. Add a **ModuleScript** named `Verde` and paste the contents of [`luau/Verde.luau`](../luau/Verde.luau).
3. (Recommended) Add a child **ModuleScript** named `interesting_properties` and paste [`luau/interesting_properties.luau`](../luau/interesting_properties.luau).
4. Add a **Script** and paste [`VerdePlugin.server.luau`](VerdePlugin.server.luau).
5. Save / reload the plugin.

The plugin will error at load time if the Verde ModuleScript cannot be required.

## Standalone Command-Bar scripts

If you prefer not to use the plugin dock:

| Script | Purpose |
|--------|---------|
| [`luau/DumpScripts.luau`](../luau/DumpScripts.luau) | Thin wrapper → calls `Verde.dumpScripts` |
| [`luau/RestoreScripts.luau`](../luau/RestoreScripts.luau) | Thin wrapper → calls `Verde.restoreScripts` |

Both require the same `Verde` ModuleScript to be present (e.g. under ServerStorage).

## Relationship to Python tools

| Task                    | Python CLI                              | Studio                                      |
|-------------------------|-----------------------------------------|---------------------------------------------|
| Search                  | `verde-search`                          | Search panel / `Verde.search`               |
| Set by tag / class      | `verde-set --tag` / `--class`           | Set panel / `Verde.setProp`                 |
| Replace asset IDs       | `verde-replace --from … --to …`         | Set panel (optional “only if”)              |
| Tags                    | `verde-tags`                            | Tags panel                                  |
| Export place            | `verde-export` (alias `verde-extract`)  | (file-system)                               |
| Import / merge changes  | `verde-import` (alias `verde-merge`)    | (file-system)                               |
| Sync dirty files        | `verde-sync`                            | (file-system)                               |
| Script-only archive     | —                                       | Dump / Restore panel or standalone scripts  |
