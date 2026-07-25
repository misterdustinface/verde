--!strict
--[[
	Verde RestoreScripts — thin Command-Bar / temporary-Script wrapper.

	Requires the full Verde ModuleScript (single source of truth).

	Setup:
	  1. Place luau/Verde.luau as a ModuleScript named "Verde"
	     (e.g. under ServerStorage, or as a child of this script).
	  2. Insert a previously saved ScriptDump_*.rbxm into the place.
	  3. Paste this file into the Command Bar or a temporary Script and run.

	All logic lives in Verde.restoreScripts. Edit the CONFIG table below or
	call Verde.restoreScripts directly from your own code.
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
			if ok and type(mod) == "table" and type(mod.restoreScripts) == "function" then
				return mod
			end
		end
	end
	error("[Verde RestoreScripts] Could not require Verde ModuleScript.\n"
		.. "Place luau/Verde.luau as a ModuleScript named \"Verde\" (recommended location: ServerStorage).")
end

local Verde = findVerde()

-- ── CONFIG (edit freely) ────────────────────────────────────────────────────
local CONFIG = {
	dumpFolder = nil :: Folder?, -- nil = auto-find newest ScriptDump_*
	dryRun = false,
	recreateMissing = true,
	archivePrefix = "ScriptDump_",
}

-- ── Run ─────────────────────────────────────────────────────────────────────
local restored, created, skipped = Verde.restoreScripts({
	dumpFolder = CONFIG.dumpFolder,
	dryRun = CONFIG.dryRun,
	recreateMissing = CONFIG.recreateMissing,
	archivePrefix = CONFIG.archivePrefix,
})

print(`[Verde RestoreScripts] Restored {restored} scripts ({created} created, {skipped} skipped)`)
if not CONFIG.dryRun then
	print("You can delete the ScriptDump folder when finished.")
end
