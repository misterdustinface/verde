--!strict
--[[
	Verde Luau module — the single source of truth for all live DataModel operations.

	Provides:
	  • search / setProp / replaceProp
	  • listTags / replaceTag
	  • dumpScripts / restoreScripts
	  • Live-sync helpers (scoped UniqueId map, complex property serialize/apply, HTTP)
	  • DEFAULT_INTERESTING_PROPS
]]

local CollectionService = game:GetService("CollectionService")
local ServerStorage = game:GetService("ServerStorage")
local HttpService = game:GetService("HttpService")

local Verde = {}

-- ── Interesting properties ──────────────────────────────────────────────────

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
	warn("[Verde] interesting_properties.luau not found; using minimal fallback")
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
	if typeof(value) ~= "string" then return value end
	local s = value :: string
	if s == "true" then return true end
	if s == "false" then return false end
	local n = tonumber(s)
	if n ~= nil then return n end
	return s
end

-- Shared name sanitiser used by dumpScripts (archive hierarchy) and
-- instanceToRelPath / scriptRelPath / metaRelPath (Live Sync + export paths).
-- Matches the Python xml_props.sanitize_name set of invalid filesystem chars
-- plus null and whitespace normalisation so fallback restore paths stay
-- consistent when OriginalFullName is absent.
local function sanitizeName(name: string): string
	local s = name:gsub('[<>:"/\\|?*\0]', "_")
	s = s:gsub("%s+", " ")
	s = s:match("^%s*(.-)%s*$") or s
	return if s == "" then "Unnamed" else s
end

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
			table.insert(pathParts, 1, sanitizeName(current.Name))
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
			-- JSON array so tags containing commas (or other special chars) round-trip cleanly.
			archive:SetAttribute("Tags", HttpService:JSONEncode(tags))
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
					if ok and svc then nextInst = svc else return current end
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
			if not ok or not inst or not inst:IsA("LuaSourceContainer") then skipped += 1 return end
			target = inst
			target.Name = leafName
			if not dryRun then target.Parent = parent end
			created += 1
		else
			skipped += 1
			return
		end
		if dryRun then restored += 1 return end
		target.Source = archive.Source
		if target:IsA("BaseScript") and enabled ~= nil then
			(target :: BaseScript).Enabled = enabled :: boolean
		end
		if runContext ~= nil then
			pcall(function() (target :: any).RunContext = Enum.RunContext[runContext :: string] end)
		end
		-- Always replace the tag set so restore matches the archived state
		-- (including the case where dump omitted the Tags attribute because
		-- the original script had zero tags). Matches applyMeta / Python.
		-- Tags are stored as a JSON array (post-fix) so commas and other
		-- special characters inside tag names are preserved. Legacy comma-
		-- joined dumps are still accepted for backward compatibility.
		for _, existing in CollectionService:GetTags(target) do
			CollectionService:RemoveTag(target, existing)
		end
		if typeof(tagsAttr) == "string" and (tagsAttr :: string) ~= "" then
			local tagsList: {string} = {}
			local decodeOk, decoded = pcall(function()
				return HttpService:JSONDecode(tagsAttr :: string)
			end)
			if decodeOk and typeof(decoded) == "table" then
				for _, t in decoded :: {any} do
					if typeof(t) == "string" and t ~= "" then
						table.insert(tagsList, t)
					end
				end
			else
				-- Legacy comma-joined format (pre-JSON encoding)
				for _, tag in string.split(tagsAttr :: string, ",") do
					tag = (tag:match("^%s*(.-)%s*$") or tag)
					if tag ~= "" then
						table.insert(tagsList, tag)
					end
				end
			end
			for _, tag in tagsList do
				CollectionService:AddTag(target, tag)
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

function Verde.instanceToRelPath(inst: Instance): string
	local parts: { string } = {}
	local cur: Instance? = inst
	while cur and cur ~= game do
		table.insert(parts, 1, sanitizeName(cur.Name))
		cur = cur.Parent
	end
	return table.concat(parts, "/")
end

function Verde.scriptRelPath(inst: LuaSourceContainer): string
	local base = Verde.instanceToRelPath(inst)
	if inst:IsA("LocalScript") then return base .. ".local.lua" end
	if inst:IsA("ModuleScript") then return base .. ".module.lua" end
	return base .. ".lua"
end

function Verde.metaRelPath(inst: Instance): string
	-- Must match the on-disk companion layout produced by export:
	--   ModuleScript → Name.module.robloxmeta.json (next to Name.module.lua)
	--   LocalScript  → Name.local.robloxmeta.json
	--   Script       → Name.robloxmeta.json
	--   non-scripts  → Name/.robloxmeta.json
	-- Previously always appended bare ".robloxmeta.json" for any LuaSourceContainer,
	-- which created a second meta file and left Live Sync meta edits on the wrong path.
	if inst:IsA("LocalScript") then
		return Verde.instanceToRelPath(inst) .. ".local.robloxmeta.json"
	end
	if inst:IsA("ModuleScript") then
		return Verde.instanceToRelPath(inst) .. ".module.robloxmeta.json"
	end
	if inst:IsA("LuaSourceContainer") then
		return Verde.instanceToRelPath(inst) .. ".robloxmeta.json"
	end
	return Verde.instanceToRelPath(inst) .. "/.robloxmeta.json"
end

function Verde.resolveByRelPath(rel: string): Instance?
	local parts = string.split(rel, "/")
	if #parts == 0 then return nil end
	local last = parts[#parts]
	last = last:gsub("%.robloxmeta%.json$", "")
	last = last:gsub("%.module%.lua$", ""):gsub("%.local%.lua$", ""):gsub("%.lua$", "")
	parts[#parts] = last

	local current: Instance? = game
	for _, name in parts do
		if not current then return nil end
		local child = current:FindFirstChild(name)
		if not child and current == game then
			local ok, svc = pcall(function() return game:GetService(name) end)
			if ok then child = svc end
		end
		if not child then
			local base = name:match("^(.-)_%d+$") or name
			child = current:FindFirstChild(base)
		end
		current = child
	end
	return current
end

-- ── UniqueId map — scope matches Live Sync mode ─────────────────────────────
--
-- scriptsOnly = true  (default / current Live Sync): only LuaSourceContainers
--                 under the usual script-bearing services. Cheap on large places.
-- scriptsOnly = false: every Instance under game (for a future all-instance mode).
--
-- Lifecycle:
--   1. Verde.refreshUniqueIdMap(scriptsOnly)  once when Live Sync turns on
--   2. Verde.indexInstance / unindexInstance    O(1) on add/destroy
--   3. Dirty applies never rebuild the map.

local SCRIPT_MAP_SERVICES = {
	"Workspace",
	"ServerScriptService",
	"ServerStorage",
	"ReplicatedStorage",
	"ReplicatedFirst",
	"StarterGui",
	"StarterPack",
	"StarterPlayer",
}

Verde._uidMap = {} :: { [string]: Instance }
Verde._uidMapScriptsOnly = true

local function readUniqueId(inst: Instance): string?
	local ok, uid = pcall(function() return (inst :: any).UniqueId end)
	if ok and typeof(uid) == "string" and uid ~= "" then
		return uid
	end
	return nil
end

-- Build a map. Default scriptsOnly=true.
function Verde.buildUniqueIdMap(scriptsOnly: boolean?): { [string]: Instance }
	local onlyScripts = if scriptsOnly == false then false else true
	local map: { [string]: Instance } = {}

	local function consider(inst: Instance)
		if onlyScripts and not inst:IsA("LuaSourceContainer") then
			return
		end
		local uid = readUniqueId(inst)
		if uid then
			map[uid] = inst
		end
	end

	if onlyScripts then
		for _, name in SCRIPT_MAP_SERVICES do
			local ok, svc = pcall(function()
				return game:GetService(name)
			end)
			if ok and svc then
				consider(svc)
				for _, d in svc:GetDescendants() do
					consider(d)
				end
			end
		end
	else
		consider(game)
		for _, d in game:GetDescendants() do
			consider(d)
		end
	end

	return map
end

function Verde.refreshUniqueIdMap(scriptsOnly: boolean?)
	local onlyScripts = if scriptsOnly == false then false else true
	Verde._uidMapScriptsOnly = onlyScripts
	Verde._uidMap = Verde.buildUniqueIdMap(onlyScripts)
end

function Verde.indexInstance(inst: Instance)
	if Verde._uidMapScriptsOnly and not inst:IsA("LuaSourceContainer") then
		return
	end
	local uid = readUniqueId(inst)
	if uid then
		Verde._uidMap[uid] = inst
	end
end

function Verde.unindexInstance(inst: Instance)
	local uid = readUniqueId(inst)
	if uid then
		if Verde._uidMap[uid] == inst then
			Verde._uidMap[uid] = nil
		end
	end
end

function Verde.resolveTarget(rel: string, meta: { [string]: any }?): Instance?
	if meta then
		local ref = meta.Referent or meta.UniqueId
		if typeof(ref) == "string" and ref ~= "" then
			local hit = Verde._uidMap[ref]
			if hit and hit.Parent then
				return hit
			end
		end
	end
	return Verde.resolveByRelPath(rel)
end

local function encodeValue(val: any): any
	local t = typeof(val)
	if t == "string" or t == "number" or t == "boolean" or t == "nil" then
		return val
	elseif t == "Color3" then
		local c = val :: Color3
		return { __type = "Color3", R = c.R, G = c.G, B = c.B }
	elseif t == "Vector3" then
		local v = val :: Vector3
		return { __type = "Vector3", X = v.X, Y = v.Y, Z = v.Z }
	elseif t == "Vector2" then
		local v = val :: Vector2
		return { __type = "Vector2", X = v.X, Y = v.Y }
	elseif t == "UDim" then
		local u = val :: UDim
		return { __type = "UDim", Scale = u.Scale, Offset = u.Offset }
	elseif t == "UDim2" then
		local u = val :: UDim2
		return {
			__type = "UDim2",
			X = { Scale = u.X.Scale, Offset = u.X.Offset },
			Y = { Scale = u.Y.Scale, Offset = u.Y.Offset },
		}
	elseif t == "CFrame" then
		local cf = val :: CFrame
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = cf:GetComponents()
		return {
			__type = "CFrame",
			components = { x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 },
		}
	elseif t == "NumberRange" then
		local n = val :: NumberRange
		return { __type = "NumberRange", Min = n.Min, Max = n.Max }
	elseif t == "Rect" then
		local r = val :: Rect
		return { __type = "Rect", Min = { X = r.Min.X, Y = r.Min.Y }, Max = { X = r.Max.X, Y = r.Max.Y } }
	elseif t == "BrickColor" then
		return { __type = "BrickColor", Number = (val :: BrickColor).Number }
	elseif t == "EnumItem" then
		local e = val :: EnumItem
		return { __type = "EnumItem", EnumType = tostring(e.EnumType), Name = e.Name }
	elseif t == "ColorSequence" or t == "NumberSequence" then
		local ok, keypoints = pcall(function() return (val :: any).Keypoints end)
		if ok and typeof(keypoints) == "table" then
			local list = {}
			for _, kp in keypoints do
				local entry: { [string]: any } = { Time = kp.Time }
				if typeof(kp.Value) == "Color3" then
					entry.Value = { R = kp.Value.R, G = kp.Value.G, B = kp.Value.B }
				else
					entry.Value = kp.Value
				end
				if kp.Envelope ~= nil then entry.Envelope = kp.Envelope end
				table.insert(list, entry)
			end
			return { __type = t, Keypoints = list }
		end
	end
	return nil
end

-- Hardened decode: accepts both Live Sync (__type + components/R/G/B) and
-- offline Python structured form (type + children). Incomplete / singular
-- CFrame matrices fall back to identity rotation at the given (or origin)
-- position so the engine never invents the far-Y sentinel.
local function decodeValue(encoded: any): any
	if typeof(encoded) ~= "table" then
		return encoded
	end

	local ty = encoded.__type or encoded.type
	if ty == nil then
		return encoded
	end

	-- Prefer children when present (offline export form)
	local children = encoded.children
	local src: any = if typeof(children) == "table" then children else encoded

	if ty == "Color3" or ty == "Color3uint8" then
		local r = tonumber(src.R or src.r) or 0
		local g = tonumber(src.G or src.g) or 0
		local b = tonumber(src.B or src.b) or 0
		return Color3.new(r, g, b)
	elseif ty == "Vector3" then
		return Vector3.new(tonumber(src.X) or 0, tonumber(src.Y) or 0, tonumber(src.Z) or 0)
	elseif ty == "Vector2" then
		return Vector2.new(tonumber(src.X) or 0, tonumber(src.Y) or 0)
	elseif ty == "UDim" then
		return UDim.new(tonumber(src.Scale) or 0, tonumber(src.Offset) or 0)
	elseif ty == "UDim2" then
		local x = src.X or {}
		local y = src.Y or {}
		return UDim2.new(tonumber(x.Scale) or 0, tonumber(x.Offset) or 0, tonumber(y.Scale) or 0, tonumber(y.Offset) or 0)
	elseif ty == "CFrame" or ty == "CoordinateFrame" then
		local c = encoded.components or src.components
		if typeof(c) == "table" and #c >= 12 then
			local matrixOk = false
			for i = 4, 12 do
				if math.abs(tonumber(c[i]) or 0) > 1e-12 then
					matrixOk = true
					break
				end
			end
			if matrixOk then
				return CFrame.new(
					tonumber(c[1]) or 0, tonumber(c[2]) or 0, tonumber(c[3]) or 0,
					tonumber(c[4]) or 1, tonumber(c[5]) or 0, tonumber(c[6]) or 0,
					tonumber(c[7]) or 0, tonumber(c[8]) or 1, tonumber(c[9]) or 0,
					tonumber(c[10]) or 0, tonumber(c[11]) or 0, tonumber(c[12]) or 1
				)
			end
			-- singular / all-zero rotation → identity at position
			return CFrame.new(tonumber(c[1]) or 0, tonumber(c[2]) or 0, tonumber(c[3]) or 0)
		end
		-- children form: X Y Z R00..R22 (missing rotation components → identity)
		local x = tonumber(src.X) or 0
		local y = tonumber(src.Y) or 0
		local z = tonumber(src.Z) or 0
		local r00 = tonumber(src.R00)
		local r01 = tonumber(src.R01)
		local r02 = tonumber(src.R02)
		local r10 = tonumber(src.R10)
		local r11 = tonumber(src.R11)
		local r12 = tonumber(src.R12)
		local r20 = tonumber(src.R20)
		local r21 = tonumber(src.R21)
		local r22 = tonumber(src.R22)
		local hasAnyRot = r00 ~= nil or r01 ~= nil or r02 ~= nil or r10 ~= nil or r11 ~= nil or r12 ~= nil or r20 ~= nil or r21 ~= nil or r22 ~= nil
		if not hasAnyRot then
			return CFrame.new(x, y, z)
		end
		-- fill missing with identity; detect all-zero
		r00 = r00 or 1
		r01 = r01 or 0
		r02 = r02 or 0
		r10 = r10 or 0
		r11 = r11 or 1
		r12 = r12 or 0
		r20 = r20 or 0
		r21 = r21 or 0
		r22 = r22 or 1
		if math.abs(r00) < 1e-12 and math.abs(r01) < 1e-12 and math.abs(r02) < 1e-12
			and math.abs(r10) < 1e-12 and math.abs(r11) < 1e-12 and math.abs(r12) < 1e-12
			and math.abs(r20) < 1e-12 and math.abs(r21) < 1e-12 and math.abs(r22) < 1e-12
		then
			return CFrame.new(x, y, z)
		end
		return CFrame.new(x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22)
	elseif ty == "NumberRange" then
		return NumberRange.new(tonumber(src.Min) or 0, tonumber(src.Max) or 0)
	elseif ty == "Rect" then
		local mn = src.Min or {}
		local mx = src.Max or {}
		return Rect.new(tonumber(mn.X) or 0, tonumber(mn.Y) or 0, tonumber(mx.X) or 0, tonumber(mx.Y) or 0)
	elseif ty == "BrickColor" then
		return BrickColor.new(tonumber(src.Number) or 1)
	elseif ty == "EnumItem" then
		local enumType = (Enum :: any)[encoded.EnumType or src.EnumType]
		if enumType then
			return enumType[encoded.Name or src.Name]
		end
	elseif ty == "ColorSequence" then
		local kps = {}
		for _, kp in (encoded.Keypoints or src.Keypoints or {}) do
			local v = kp.Value or {}
			table.insert(kps, ColorSequenceKeypoint.new(tonumber(kp.Time) or 0, Color3.new(tonumber(v.R) or 0, tonumber(v.G) or 0, tonumber(v.B) or 0)))
		end
		if #kps >= 2 then return ColorSequence.new(kps) end
	elseif ty == "NumberSequence" then
		local kps = {}
		for _, kp in (encoded.Keypoints or src.Keypoints or {}) do
			table.insert(kps, NumberSequenceKeypoint.new(tonumber(kp.Time) or 0, tonumber(kp.Value) or 0, tonumber(kp.Envelope) or 0))
		end
		if #kps >= 2 then return NumberSequence.new(kps) end
	end
	return nil
end

local LIVE_PROPS = {
	"Name", "Enabled", "Anchored", "CanCollide", "CastShadow", "Transparency",
	"SoundId", "Texture", "MeshId", "Image", "Disabled",
	"Color", "Color3", "Size", "Position", "Orientation", "CFrame",
	"BrickColor", "Material", "Shape", "Reflectance", "BackgroundColor3",
	"BorderColor3", "TextColor3", "PlaceholderColor3", "ImageColor3",
	"BackgroundTransparency", "TextTransparency", "ImageTransparency",
	"AnchorPoint", "SizeConstraint", "AutomaticSize",
	"Text", "PlaceholderText", "Font", "TextSize", "TextScaled",
	"Volume", "PlaybackSpeed", "RollOffMode", "MaxDistance", "EmitterSize",
	"Brightness", "Range", "Shadows", "Face",
}

Verde.LIVE_PROPS = LIVE_PROPS

function Verde.serializeMeta(inst: Instance): { [string]: any }
	local meta: { [string]: any } = {
		ClassName = inst.ClassName,
		Name = inst.Name,
	}

	local uid = readUniqueId(inst)
	if uid then meta.Referent = uid end

	local tags = CollectionService:GetTags(inst)
	if #tags > 0 then meta.Tags = tags end

	local attrs: { [string]: any } = {}
	for name, value in inst:GetAttributes() do
		local encoded = encodeValue(value)
		if encoded ~= nil then attrs[name] = encoded end
	end
	if next(attrs) then meta.Attributes = attrs end

	local props: { [string]: any } = {}
	for _, prop in LIVE_PROPS do
		if prop == "Name" then continue end
		local ok, val = pcall(function() return (inst :: any)[prop] end)
		if not ok or val == nil then continue end
		local encoded = encodeValue(val)
		if encoded == nil then continue end
		if typeof(encoded) == "table" and encoded.__type then
			props[prop] = { type = encoded.__type, value = encoded }
			meta[prop] = encoded
		else
			local t = typeof(val)
			props[prop] = {
				type = if t == "boolean" then "bool" elseif t == "number" then "float" else "string",
				value = encoded,
			}
			meta[prop] = encoded
		end
	end
	if next(props) then meta.Properties = props end

	return meta
end

local function valuesEqual(a: any, b: any): boolean
	if a == b then return true end
	local ta, tb = typeof(a), typeof(b)
	if ta ~= tb then return false end
	if ta == "Color3" then
		return math.abs(a.R - b.R) < 1e-5 and math.abs(a.G - b.G) < 1e-5 and math.abs(a.B - b.B) < 1e-5
	elseif ta == "Vector3" or ta == "Vector2" then
		return a:FuzzyEq(b, 1e-5)
	elseif ta == "CFrame" then
		return a:FuzzyEq(b, 1e-5)
	elseif ta == "UDim" then
		return a.Scale == b.Scale and a.Offset == b.Offset
	elseif ta == "UDim2" then
		return a.X.Scale == b.X.Scale and a.X.Offset == b.X.Offset
			and a.Y.Scale == b.Y.Scale and a.Y.Offset == b.Y.Offset
	end
	return false
end

function Verde.applyMeta(target: Instance, meta: { [string]: any }): boolean
	local changed = false

	if typeof(meta.Name) == "string" and meta.Name ~= "" and target.Name ~= meta.Name then
		target.Name = meta.Name
		changed = true
	end

	if typeof(meta.Tags) == "table" then
		local want: { [string]: boolean } = {}
		for _, t in meta.Tags :: { any } do
			if typeof(t) == "string" then want[t] = true end
		end
		for _, t in CollectionService:GetTags(target) do
			if not want[t] then
				CollectionService:RemoveTag(target, t)
				changed = true
			end
		end
		for t in want do
			if not CollectionService:HasTag(target, t) then
				CollectionService:AddTag(target, t)
				changed = true
			end
		end
	end

	if typeof(meta.Attributes) == "table" then
		local want: { [string]: any } = {}
		for name, value in meta.Attributes :: { [string]: any } do
			want[name] = decodeValue(value)
		end
		for name, _ in target:GetAttributes() do
			if want[name] == nil then
				pcall(function() target:SetAttribute(name, nil) end)
				changed = true
			end
		end
		for name, decoded in want do
			local ok, cur = pcall(function() return target:GetAttribute(name) end)
			if ok and not valuesEqual(cur, decoded) then
				pcall(function() target:SetAttribute(name, decoded) end)
				changed = true
			end
		end
	end

	local function applyOne(prop: string, raw: any)
		if raw == nil or prop == "Name" or prop == "Source" or prop == "Tags" or prop == "AttributesSerialize" then
			return
		end
		local value = raw
		if typeof(raw) == "table" then
			if raw.value ~= nil then
				value = decodeValue(raw.value)
			else
				value = decodeValue(raw)
			end
		end
		if value == nil then return end
		local ok, cur = pcall(function() return (target :: any)[prop] end)
		if ok and not valuesEqual(cur, value) then
			pcall(function() (target :: any)[prop] = value end)
			changed = true
		end
	end

	for _, prop in LIVE_PROPS do
		if meta[prop] ~= nil then applyOne(prop, meta[prop]) end
	end
	if typeof(meta.Properties) == "table" then
		for prop, structured in meta.Properties :: { [string]: any } do
			applyOne(prop, structured)
		end
	end

	return changed
end

function Verde.applyScript(target: LuaSourceContainer, source: string, meta: { [string]: any }?): boolean
	local changed = false
	if target.Source ~= source then
		target.Source = source
		changed = true
	end
	if meta then
		if Verde.applyMeta(target, meta) then changed = true end
		if meta.RunContext ~= nil then
			pcall(function()
				local rc = Enum.RunContext[tostring(meta.RunContext)]
				if rc and (target :: any).RunContext ~= rc then
					(target :: any).RunContext = rc
					changed = true
				end
			end)
		end
	end
	return changed
end

function Verde.applyFromBridge(rel: string, sourceOrNil: string?, meta: { [string]: any }?): (boolean, string?)
	local target = Verde.resolveTarget(rel, meta)
	if not target then
		return false, "no match"
	end
	local changed = false
	if target:IsA("LuaSourceContainer") and typeof(sourceOrNil) == "string" then
		changed = Verde.applyScript(target, sourceOrNil, meta)
	elseif meta then
		changed = Verde.applyMeta(target, meta)
	end
	return changed, nil
end

Verde.BRIDGE_PORT = 3847
Verde.BRIDGE_BASE = "http://127.0.0.1:3847"

function Verde.bridgeGet(path: string): (boolean, any)
	local url = Verde.BRIDGE_BASE .. path
	local ok, result = pcall(function()
		return HttpService:GetAsync(url, true)
	end)
	if not ok then return false, tostring(result) end
	local decodeOk, data = pcall(function() return HttpService:JSONDecode(result) end)
	if decodeOk then return true, data end
	return true, result
end

function Verde.bridgePost(path: string, body: any): (boolean, any)
	local url = Verde.BRIDGE_BASE .. path
	local payload = HttpService:JSONEncode(body)
	local ok, result = pcall(function()
		return HttpService:PostAsync(url, payload, Enum.HttpContentType.ApplicationJson, true)
	end)
	if not ok then return false, tostring(result) end
	local decodeOk, data = pcall(function() return HttpService:JSONDecode(result) end)
	if decodeOk then return true, data end
	return true, result
end

return Verde
