# Verde

**Get your Roblox place organized, searchable, and editable — without writing code.**

Verde is a small toolkit that works right inside Roblox Studio.  
It lets artists, designers, and builders quickly find objects, change properties in bulk, manage tags, and back up scripts.

**Version 0.0.0** · Free & open source ([Unlicense](LICENSE))

---

## What can I do with Verde?

Once the plugin is installed you can:

- **Search** your whole place for Parts, Sounds, Models, or anything else by name, class, or tag
- **Change properties in bulk** — e.g. turn off CastShadow on every Part, or set Anchored on everything tagged FROZEN
- **Rename or list tags** across the entire place
- **Dump & restore scripts** — make a quick backup of all scripts, then put them back later

Everything happens live in Studio. No external tools required for everyday use.

---

## Install the Studio plugin (5 minutes)

You only need to do this once.

1. Download or clone this repository so you have the files on your computer.
2. In Roblox Studio go to the **Plugins** tab → **Plugins Folder** (or create a new local plugin).
3. Create a **ModuleScript** and name it exactly `Verde`.
4. Open [`luau/Verde.luau`](luau/Verde.luau), copy **all** of its contents, and paste them into the ModuleScript.
5. (Recommended) Right-click the `Verde` ModuleScript → Insert Object → **ModuleScript**, name it `interesting_properties`, then paste the contents of [`luau/interesting_properties.luau`](luau/interesting_properties.luau) into it.
6. Create a **Script** (not a LocalScript) next to the Verde ModuleScript and paste the contents of [`plugin/VerdePlugin.server.luau`](plugin/VerdePlugin.server.luau) into it.
7. Save the plugin and restart Studio (or reload plugins).

You should now see the **Verde** panels in the Studio UI (Search, Set, Tags, Dump/Restore).

> Full install notes and screenshots live in [plugin/README.md](plugin/README.md).

---

## Everyday workflow

1. Open your place in Studio.
2. Use the **Search** panel to find what you need (by name, class, tag, or property value).
3. Use the **Set** panel to change properties on the results (you can limit the change to a tag or class, and you can undo).
4. Use the **Tags** panel to list every tag or rename one everywhere it appears.
5. Use **Dump Scripts** when you want a backup of all script sources (they appear under ServerStorage). Use **Restore** later if needed.

That’s it — you can stay inside Studio the whole time.

---

## Optional: work with place files on disk

If you (or a programmer on your team) want to export a place into folders so you can edit scripts in a normal text editor or put the project under version control, Verde also has offline tools. Those are documented in the technical overview:

→ **[System Overview](docs/SYSTEM_OVERVIEW.md)** (for developers)

You do **not** need those tools for the Studio plugin to work.

---

## Need help?

- Plugin install & features → [plugin/README.md](plugin/README.md)
- Full technical details, CLI commands, and project layout → [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)
- Known issues → [docs/BUGS.md](docs/BUGS.md)

Verde is intentionally small and focused. If something is confusing, open an issue on the repository — we want it to be easy for non-programmers too.
