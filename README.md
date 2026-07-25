# Verde

**Edit Roblox scripts in a normal text editor — and see the changes in Studio without reopening the place.**

Verde also helps you search the place, change properties in bulk, and manage tags.  
**Version 1.0.0** · Free & open source ([Unlicense](LICENSE))

---

## The important part: Live Sync

If you edit scripts as files on disk (or someone on your team does), **Live Sync** is how Studio stays up to date **while the place stays open**.

Without it, changing files and running `verde-import` only updates the `.rbxlx` on disk — **Studio does not reload an open place**. You would have to close and reopen. Live Sync fixes that.

### What you need once

1. **Python tools installed** (a programmer on the team can do this once):
   ```bash
   git clone https://github.com/misterdustinface/verde.git
   cd verde
   pip install -e ".[dev]"
   ```
2. **Verde Studio plugin installed** — see [Install the Studio plugin](#install-the-studio-plugin-once) below.
3. **Allow HTTP in the place** (required for Live Sync):
   - In Studio: **Home → Game Settings → Security**
   - Turn **Allow HTTP Requests** **ON**
   - Save

### Everyday Live Sync (do this whenever you work)

**Terminal (leave this window open):**
```bash
# Folder from a previous export, e.g. code/
verde-sync code/
```

**Roblox Studio:**
1. Open your place
2. Open the **Verde** panel (toolbar button)
3. Click **Live Sync** so it shows **ON**

You should see a “Connected” message and the folder path.

| You do this… | What happens |
|--------------|--------------|
| Edit a script **in Studio** | The matching `.lua` file on disk updates |
| Edit a `.lua` file **in your editor** | Studio updates that script’s Source (no reopen) |

**Default:** only **script Source** is live-synced (safe on large places).  
**Experimental:** optional property sync on scripts — off by default in the panel.

Matching prefers **Referent / UniqueId** from `.robloxmeta.json`, then hierarchy path. The UniqueId map is **scripts-only** by default (same as the watch set).

### If Live Sync fails

| Message | Fix |
|---------|-----|
| Studio is blocking the connection (HttpService) | **Game Settings → Security → Allow HTTP Requests = ON** |
| Cannot reach Live Sync (`verde-sync` not running) | Run `verde-sync path/to/extracted` and **leave it running** |
| Lost connection | Restart `verde-sync`, turn Live Sync **ON** again |
| N file(s) had no matching script | Re-export after renames, or fix folder paths to match Studio |

More detail for programmers: [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) and [plugin/README.md](plugin/README.md).

---

## First-time export (usually done by a programmer once)

```bash
verde-export MyPlace.rbxlx code/
```

That creates a `code/` folder with script files you can edit. Point `verde-sync` at that same folder.

---

## Install the Studio plugin (once)

1. Have this repository on your computer.
2. In Roblox Studio: **Plugins** → open or create a **local plugin**.
3. Create a **ModuleScript** named exactly `Verde`.
4. Copy all of [`luau/Verde.luau`](luau/Verde.luau) into it.
5. (Recommended) Add a child **ModuleScript** named `interesting_properties` and paste [`luau/interesting_properties.luau`](luau/interesting_properties.luau).
6. Create a **Script** next to `Verde` and paste [`plugin/VerdePlugin.server.luau`](plugin/VerdePlugin.server.luau).
7. Save / reload plugins.

You should see the **Verde** toolbar button and panel (**Live Sync**, Search, Set, Tags).

Full notes: [plugin/README.md](plugin/README.md).

---

## Other things you can do in Studio (no Live Sync required)

These work with the plugin alone:

- **Search** the place by name, class, tag, or property
- **Set / replace properties** in bulk (with undo)
- **List or rename tags** across the place

You do **not** need `verde-sync` for search / set / tags.

---

## Optional offline tools (programmers)

→ **[System Overview](docs/SYSTEM_OVERVIEW.md)**

| Command | Purpose |
|---------|---------|
| `verde-export` | Place file → folder of scripts / meta |
| `verde-import` | Folder → update `.rbxlx` **on disk** |
| `verde-merge` | Offline folder ↔ `.rbxlx` using manifest + mtime-win (future: git-merge-style conflicts) |
| `verde-sync` | **Live** link folder ↔ **open** Studio |
| `verde-search` / `verde-set` / `verde-tags` | Offline helpers |

Remember: **`verde-import` / `verde-merge` alone do not refresh an already-open Studio place.** Use **`verde-sync`** + the plugin Live Sync toggle for that.

---

## Need help?

- Plugin install → [plugin/README.md](plugin/README.md)
- Full technical docs → [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)
- Planned work → [docs/TODO_FEATURES.md](docs/TODO_FEATURES.md)
- Known issues → [docs/BUGS.md](docs/BUGS.md)
