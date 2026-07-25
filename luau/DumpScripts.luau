--!strict
--[[
	Verde DumpScripts — thin Command-Bar / temporary-Script wrapper.

	Requires the full Verde ModuleScript (single source of truth).

	Setup:
	  1. Place luau/Verde.luau as a ModuleScript named "Verde"
	     (e.g. under ServerStorage, or as a child of this script).
	  2. Optionally place interesting_properties.luau as a child of Verde.
	  3. Paste this file into the Command Bar or a temporary Script and run.

	All logic lives in Verde.dumpScripts. Edit the CONFIG table below or
	call Verde.dumpScripts directly from your own code.
]]

local ServerStorage = game:GetService("ServerStorage")

-- ── Locate Verde ModuleScript ───────────────────────────────────────────────
local function findVerde(): any
	local candidates = {
		script:FindFirstChild("Verde"),
		script.Parent and script.Parent:FindFirstChild("Verde"),
		ServerStorage:FindFirstChild("Verde"),
		game:FindFirstChild("Verde"),
	}
	for _, c in candidates do
		if c and c:IsA("ModuleScript") then
			local ok, mod = pcall(require, c)
			if ok and type(mod) == "table" and type(mod.dumpScripts) == "function" then
				return mod
			end
		end
	end
	error("[Verde DumpScripts] Could not require Verde ModuleScript.\n"
		.. "Place luau/Verde.luau as a ModuleScript named \"Verde\" (recommended location: ServerStorage).")
end

local Verde = findVerde()

-- ── CONFIG (edit freely) ────────────────────────────────────────────────────
local CONFIG = {
	roots = nil :: { Instance }?, -- nil = use Verde defaults (common services)
	excludeNamePrefixes = { "ScriptDump_" },
	parentFolder = ServerStorage,
	archivePrefix = "ScriptDump_",
}

-- ── Run ─────────────────────────────────────────────────────────────────────
local archive, count = Verde.dumpScripts({
	roots = CONFIG.roots,
	excludeNamePrefixes = CONFIG.excludeNamePrefixes,
	parentFolder = CONFIG.parentFolder,
	archivePrefix = CONFIG.archivePrefix,
})

print(`[Verde DumpScripts] Archived {count} scripts into {archive:GetFullName()}`)
print("→ Select the folder in Explorer → right-click → Save to File… → .rbxm / .rbxmx")
print("→ For git-friendly offline trees use the Python extract tools")
