--!strict
--[[
	Verde Luau module — the single source of truth for all live DataModel operations.

	Provides:
	  • search / setProp / replaceProp
	  • listTags / replaceTag
	  • dumpScripts / restoreScripts
	  • DEFAULT_INTERESTING_PROPS (from sibling/child interesting_properties.luau)

	Designed to be required by the Studio plugin, Command-Bar wrappers, or any other Luau code.

	Installation note:
	  Place this as a ModuleScript named "Verde".
	  Place interesting_properties.luau as a child ModuleScript of Verde (recommended)
	  or as a sibling ModuleScript named "interesting_properties".
]]

local CollectionService = game:GetService("CollectionService")
local ServerStorage = game:GetService("ServerStorage")

local Verde = {}

-- ── Interesting properties (single source: interesting_properties.luau) ─────

local function loadInteresting(): { string }
	local candidates = {
		script:FindFirstChild("interesting_properties"),
		script.Parent and script.Parent:FindFirstChild("interesting_properties"),
	}
	for _, child in candidates do
		if child and child:IsA("ModuleScript") then
			local ok, result = pcall(require, child)
			if ok and type(result) == "table" then
				return result :: { string }
			end
		end
	end
	-- Minimal fallback if the companion file is missing (should not happen in normal install)
	warn("[Verde] interesting_properties.luau not found as child/sibling; using minimal fallback list")
	return {
		"Source", "Name", "SoundId", "Texture", "MeshId", "Image",
		"Anchored", "CanCollide", "CastShadow", "Transparency", "Enabled", "Disabled",
	}
end

Verde.DEFAULT_INTERESTING_PROPS = loadInteresting()

export type SearchOptions = {
	className: string?,
	name: string?,
	nameContains: string?,
	tag: string?,
	prop: string?,
	propContains: string?,
	root: Instance?,
}

export type DumpOptions = {
	roots: { Instance }?,
	excludeNamePrefixes: { string }?,
	parentFolder: Instance?,
	archivePrefix: string?,
}

export type RestoreOptions = {
	dumpFolder: Folder?,
	dryRun: boolean?,
	recreateMissing: boolean?,
	archivePrefix: string?,
}

local function lower(s: string): string
	return string.lower(s)
end

local function coerce(value: any): any
	if typeof(value) ~= "string" then
		return value
	end
	local s = value :: string
	if s == "true" then return true end
	if s == "false" then return false end
	local n = tonumber(s)
	if n ~= nil then return n end
	return s
end

-- ── Search / set / replace / tags ───────────────────────────────────────────

function Verde.search(options: SearchOptions): { Instance }
	local results: { Instance } = {}
	local root = options.root or game

	local function matches(inst: Instance): boolean
		if options.className and lower(inst.ClassName) ~= lower(options.className) then return false end
		if options.name and lower(inst.Name) ~= lower(options.name) then return false end
		if options.nameContains and not string.find(lower(inst.Name), lower(options.nameContains), 1, true) then return false end
		if options.tag then
			local has = false
			for _, t in CollectionService:GetTags(inst) do
				if lower(t) == lower(options.tag :: string) then has = true break end
			end
			if not has then return false end
		end
		if options.prop then
			local ok, val = pcall(function() return (inst :: any)[options.prop :: string] end)
			if not ok or val == nil then return false end
			if options.propContains then
				if not string.find(lower(tostring(val)), lower(options.propContains :: string), 1, true) then
					return false
				end
			end
		end
		return true
	end

	if matches(root) then table.insert(results, root) end
	for _, inst in root:GetDescendants() do
		if matches(inst) then table.insert(results, inst) end
	end
	return results
end

function Verde.setProp(propName: string, value: any, options: SearchOptions?): number
	local candidates = Verde.search(options or {})
	local coerced = coerce(value)
	local changed = 0
	for _, inst in candidates do
		if pcall(function() (inst :: any)[propName] = coerced end) then
			changed += 1
		end
	end
	return changed
end

function Verde.replaceProp(propName: string, oldValue: string, newValue: any, options: SearchOptions?): number
	local opts = table.clone(options or {})
	opts.prop = propName
	opts.propContains = oldValue
	local candidates = Verde.search(opts)
	local coercedNew = coerce(newValue)
	local changed = 0
	for _, inst in candidates do
		local ok, current = pcall(function() return (inst :: any)[propName] end)
		if ok and current ~= nil and tostring(current) == oldValue then
			if pcall(function() (inst :: any)[propName] = coercedNew end) then
				changed += 1
			end
		end
	end
	return changed
end

function Verde.listTags(root: Instance?): { [string]: { Instance } }
	local map: { [string]: { Instance } } = {}
	local r = root or game
	local function consider(inst: Instance)
		for _, tag in CollectionService:GetTags(inst) do
			if not map[tag] then map[tag] = {} end
			table.insert(map[tag], inst)
		end
	end
	consider(r)
	for _, inst in r:GetDescendants() do consider(inst) end
	return map
end

function Verde.replaceTag(oldTag: string, newTag: string, root: Instance?): number
	local r = root or game
	local changed = 0
	local function consider(inst: Instance)
		if CollectionService:HasTag(inst, oldTag) then
			CollectionService:RemoveTag(inst, oldTag)
			CollectionService:AddTag(inst, newTag)
			changed += 1
		end
	end
	consider(r)
	for _, inst in r:GetDescendants() do consider(inst) end
	return changed
end

-- ── Script dump / restore ───────────────────────────────────────────────────

local DEFAULT_DUMP_ROOTS = {
	"Workspace", "ServerScriptService", "ServerStorage", "ReplicatedStorage",
	"ReplicatedFirst", "StarterGui", "StarterPack", "StarterPlayer",
	"Lighting", "MaterialService", "SoundService", "Chat", "Teams",
}

local SERVICE_NAMES: { [string]: boolean } = {
	Workspace = true, ServerScriptService = true, ServerStorage = true,
	ReplicatedStorage = true, ReplicatedFirst = true, StarterGui = true,
	StarterPack = true, StarterPlayer = true, Lighting = true,
	MaterialService = true, SoundService = true, Chat = true, Teams = true,
	Players = true, HttpService = true,
}

function Verde.dumpScripts(options: DumpOptions?): (Folder, number)
	local opts = options or {}
	local prefix = opts.archivePrefix or "ScriptDump_"
	local parentFolder = opts.parentFolder or ServerStorage
	local excludePrefixes = opts.excludeNamePrefixes or { "ScriptDump_" }

	local roots: { Instance } = opts.roots or {}
	if #roots == 0 then
		for _, name in DEFAULT_DUMP_ROOTS do
			local ok, svc = pcall(function() return game:GetService(name) end)
			if ok and svc then table.insert(roots, svc) end
		end
	end

	local function excluded(inst: Instance): boolean
		for _, pfx in excludePrefixes do
			if string.sub(inst.Name, 1, #pfx) == pfx then return true end
		end
		local p: Instance? = inst
		while p do
			for _, pfx in excludePrefixes do
				if string.sub(p.Name, 1, #pfx) == pfx then return true end
			end
			p = p.Parent
		end
		return false
	end

	local function ensureFolder(parent: Instance, name: string): Instance
		local f = parent:FindFirstChild(name)
		if not f then
			f = Instance.new("Folder")
			f.Name = name
			f.Parent = parent
		end
		return f
	end

	local function sanitize(name: string): string
		local s = name:gsub("[/\\%z]", "_")
		return if s == "" then "Unnamed" else s
	end

	local archiveRoot = Instance.new("Folder")
	archiveRoot.Name = prefix .. os.date("%Y%m%d_%H%M%S")
	archiveRoot.Parent = parentFolder

	local count = 0
	local nameCounters: { [string]: number } = {}

	local function archiveOne(scriptInstance: LuaSourceContainer)
		if excluded(scriptInstance) then return end

		local pathParts: { string } = {}
		local current: Instance? = scriptInstance
		while current and current ~= game do
			table.insert(pathParts, 1, sanitize(current.Name))
			current = current.Parent
		end

		local parent: Instance = archiveRoot
		for i = 1, #pathParts - 1 do
			parent = ensureFolder(parent, pathParts[i])
		end

		local baseName = pathParts[#pathParts] or "Unnamed"
		local fullKey = table.concat(pathParts, "/")
		nameCounters[fullKey] = (nameCounters[fullKey] or 0) + 1
		local idx = nameCounters[fullKey]
		local archiveName = if idx > 1 then `{baseName}_{idx}` else baseName

		local archive = Instance.new("ModuleScript")
		archive.Name = archiveName
		archive.Source = scriptInstance.Source
		archive:SetAttribute("OriginalClass", scriptInstance.ClassName)
		archive:SetAttribute("OriginalName", scriptInstance.Name)
		archive:SetAttribute("OriginalFullName", scriptInstance:GetFullName())

		if scriptInstance:IsA("BaseScript") then
			archive:SetAttribute("Enabled", (scriptInstance :: BaseScript).Enabled)
		end

		local okRC, runContext = pcall(function() return (scriptInstance :: any).RunContext end)
		if okRC and runContext ~= nil then
			archive:SetAttribute("RunContext", tostring(runContext))
		end

		local tags = CollectionService:GetTags(scriptInstance)
		if #tags > 0 then
			archive:SetAttribute("Tags", table.concat(tags, ","))
		end

		archive.Parent = parent
		count += 1
	end

	for _, service in roots do
		if excluded(service) then continue end
		if service:IsA("LuaSourceContainer") then archiveOne(service) end
		for _, desc in service:GetDescendants() do
			if desc:IsA("LuaSourceContainer") then archiveOne(desc) end
		end
	end

	return archiveRoot, count
end

function Verde.restoreScripts(options: RestoreOptions?): (number, number, number)
	local opts = options or {}
	local prefix = opts.archivePrefix or "ScriptDump_"
	local dryRun = opts.dryRun == true
	local recreateMissing = if opts.recreateMissing == nil then true else opts.recreateMissing

	local function findDump(): Folder?
		if opts.dumpFolder and opts.dumpFolder.Parent then return opts.dumpFolder end
		local candidates: { Folder } = {}
		for _, child in ServerStorage:GetChildren() do
			if child:IsA("Folder") and string.sub(child.Name, 1, #prefix) == prefix then
				table.insert(candidates, child)
			end
		end
		table.sort(candidates, function(a, b) return a.Name > b.Name end)
		if #candidates > 0 then return candidates[1] end
		for _, desc in game:GetDescendants() do
			if desc:IsA("Folder") and string.sub(desc.Name, 1, #prefix) == prefix then
				return desc
			end
		end
		return nil
	end

	local dumpRoot = findDump()
	if not dumpRoot then
		warn("[Verde] No ScriptDump_* folder found")
		return 0, 0, 0
	end

	local function getOrCreatePath(fullPath: string): Instance
		local parts = string.split(fullPath, ".")
		local current: Instance = game
		for _, name in parts do
			if name == "" or name == "game" then continue end
			local nextInst = current:FindFirstChild(name)
			if not nextInst then
				if SERVICE_NAMES[name] and current == game then
					local ok, svc = pcall(function() return game:GetService(name) end)
					if ok and svc then
						nextInst = svc
					else
						return current
					end
				else
					nextInst = Instance.new("Folder")
					nextInst.Name = name
					if not dryRun then nextInst.Parent = current end
				end
			end
			current = nextInst
		end
		return current
	end

	local restored, created, skipped = 0, 0, 0

	local function restoreOne(archive: ModuleScript)
		local originalClass = (archive:GetAttribute("OriginalClass") or "ModuleScript") :: string
		local enabled = archive:GetAttribute("Enabled")
		local originalFullName = archive:GetAttribute("OriginalFullName") :: string?
		local originalName = (archive:GetAttribute("OriginalName") or archive.Name) :: string
		local runContext = archive:GetAttribute("RunContext")
		local tagsAttr = archive:GetAttribute("Tags")

		if not originalFullName or originalFullName == "" then
			local dumpFull = dumpRoot:GetFullName()
			local archFull = archive:GetFullName()
			local relative = archFull
			if string.sub(archFull, 1, #dumpFull) == dumpFull then
				relative = string.sub(archFull, #dumpFull + 2)
			end
			originalFullName = relative:gsub("/", ".")
		end

		local parentPath = string.match(originalFullName, "^(.+)%..+$") or ""
		local leafName = originalName

		local parent = if parentPath ~= "" then getOrCreatePath(parentPath) else game
		local existing = parent:FindFirstChild(leafName)
		local target: LuaSourceContainer?

		if existing and existing:IsA("LuaSourceContainer") then
			target = existing
		elseif recreateMissing then
			local ok, inst = pcall(function() return Instance.new(originalClass) end)
			if not ok or not inst or not inst:IsA("LuaSourceContainer") then
				skipped += 1
				return
			end
			target = inst
			target.Name = leafName
			if not dryRun then target.Parent = parent end
			created += 1
		else
			skipped += 1
			return
		end

		if dryRun then
			restored += 1
			return
		end

		target.Source = archive.Source
		if target:IsA("BaseScript") and enabled ~= nil then
			(target :: BaseScript).Enabled = enabled :: boolean
		end
		if runContext ~= nil then
			pcall(function()
				(target :: any).RunContext = Enum.RunContext[runContext :: string]
			end)
		end
		if typeof(tagsAttr) == "string" and (tagsAttr :: string) ~= "" then
			for _, tag in string.split(tagsAttr :: string, ",") do
				tag = (tag:match("^%s*(.-)%s*$") or tag)
				if tag ~= "" then CollectionService:AddTag(target, tag) end
			end
		end
		restored += 1
	end

	for _, desc in dumpRoot:GetDescendants() do
		if desc:IsA("ModuleScript") and desc:GetAttribute("OriginalClass") then
			restoreOne(desc)
		end
	end

	return restored, created, skipped
end

return Verde
