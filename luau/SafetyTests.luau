--!strict
-- Run from Studio's Command Bar or a local plugin, outside Play mode:
-- require(path.to.SafetyTests)(require(path.to.Verde))
-- All instances created by this suite are removed, including after a failure.
return function(Verde: any)
	assert(not game:GetService("RunService"):IsRunning(), "Run outside Play mode")
	local storage = game:GetService("ServerStorage")
	local collection = game:GetService("CollectionService")
	local root = Instance.new("Folder")
	root.Name = "VerdeSafetyTests_" .. game:GetService("HttpService"):GenerateGUID(false)
	root.Parent = storage
	local prefix = "ServerStorage/" .. root.Name .. "/"
	local checks = 0
	local function check(condition: boolean, message: string)
		assert(condition, message)
		checks += 1
	end
	local ok, err = xpcall(function()
		local first = Instance.new("ModuleScript")
		first.Name = "Duplicate"
		first.Source = "return 'first'"
		first.Parent = root
		local second = Instance.new("ModuleScript")
		second.Name = "Duplicate"
		second.Source = "return 'second'"
		second.Parent = root
		check(Verde.resolveByRelPath(prefix .. "Duplicate.module.lua") == nil, "Ambiguous names must be refused")
		check(Verde.resolveByRelPath(prefix .. "Duplicate_2.module.lua") == nil, "Suffix must not select another instance")
		local module = Instance.new("ModuleScript")
		module.Name = "Exact"
		module.Parent = root
		check(Verde.resolveByRelPath(prefix .. "Exact.module.robloxmeta.json") == module, "Module meta path")
		local localScript = Instance.new("LocalScript")
		localScript.Name = "Local"
		localScript.Parent = root
		check(Verde.resolveByRelPath(prefix .. "Local.local.robloxmeta.json") == localScript, "Local meta path")
		local meta = Verde.serializeMeta(module)
		check(typeof(meta.Tags) == "table" and #meta.Tags == 0, "Empty tags must be explicit")
		check(typeof(meta.Attributes) == "table" and next(meta.Attributes) == nil, "Empty attributes must be explicit")
		collection:AddTag(module, "RemoveMe")
		module:SetAttribute("RemoveMe", true)
		Verde.applyMeta(module, { Tags = {}, Attributes = {} })
		check(#collection:GetTags(module) == 0 and module:GetAttribute("RemoveMe") == nil, "Clear tags and attributes")
		local part = Instance.new("Part")
		part.Parent = root
		Verde.applyMeta(part, { Properties = {
			Anchored = { type = "bool", value = "true" },
			Transparency = { type = "float", value = "0.5" },
		} })
		check(part.Anchored and part.Transparency == 0.5, "Offline scalar types must decode")
		local dotted = Instance.new("Folder")
		dotted.Name = "Name.With.Dots"
		dotted.Parent = root
		local scriptInstance = Instance.new("Script")
		scriptInstance.Name = "Code"
		scriptInstance.Source = "print('original')"
		scriptInstance.RunContext = Enum.RunContext.Server
		scriptInstance.Parent = dotted
		local dump, count = Verde.dumpScripts({ roots = { root }, parentFolder = root })
		check(count == 5, "Dump only the five test scripts")
		first.Source = "changed"
		second.Source = "changed"
		scriptInstance.Source = "changed"
		scriptInstance.RunContext = Enum.RunContext.Legacy
		local restored, created, skipped = Verde.restoreScripts({ dumpFolder = dump })
		check(restored == 5 and created == 0 and skipped == 0, "Restore exact original instances")
		check(first.Source == "return 'first'" and second.Source == "return 'second'", "Duplicate archives must not overwrite each other")
		check(scriptInstance.RunContext == Enum.RunContext.Server, "RunContext restoration")
		scriptInstance:Destroy()
		local _, recreated = Verde.restoreScripts({ dumpFolder = dump })
		local replacement = dotted:FindFirstChild("Code")
		check(recreated == 1 and replacement ~= nil and (replacement :: any).Source == "print('original')", "Dotted path recreation")
	end, debug.traceback)
	root:Destroy()
	assert(ok, tostring(err))
	print(string.format("[Verde] %d Studio safety checks passed", checks))
	return checks
end
