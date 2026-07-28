--!strict
--[[
	Verde Studio Plugin

	Live Sync (default): scripts only — Source (+ Name/meta on push).
	Experimental: property / attribute listeners (off by default).

	Also: search / set / tags / script dump-restore.
]]

local ChangeHistoryService = game:GetService("ChangeHistoryService")
local Selection = game:GetService("Selection")
local ServerStorage = game:GetService("ServerStorage")
local RunService = game:GetService("RunService")
local HttpService = game:GetService("HttpService")

local Verde: any
do
	local candidates = {
		script:FindFirstChild("Verde"),
		script.Parent and script.Parent:FindFirstChild("Verde"),
		ServerStorage:FindFirstChild("Verde"),
	}
	local found = false
	for _, c in candidates do
		if c and c:IsA("ModuleScript") then
			local ok, mod = pcall(require, c)
			if ok and type(mod) == "table" and type(mod.search) == "function" then
				Verde = mod
				found = true
				break
			end
		end
	end
	if not found then
		error("[Verde Plugin] Could not find the Verde ModuleScript. Place Verde.luau next to this plugin script or in ServerStorage.")
	end
end

local function makeTextBox(parent: Instance, placeholder: string, size: UDim2, position: UDim2): TextBox
	local box = Instance.new("TextBox")
	box.Size = size
	box.Position = position
	box.PlaceholderText = placeholder
	box.Text = ""
	box.ClearTextOnFocus = false
	box.BackgroundColor3 = Color3.fromRGB(40, 40, 40)
	box.TextColor3 = Color3.fromRGB(230, 230, 230)
	box.PlaceholderColor3 = Color3.fromRGB(140, 140, 140)
	box.Font = Enum.Font.SourceSans
	box.TextSize = 14
	box.BorderSizePixel = 0
	box.Parent = parent
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 4)
	corner.Parent = box
	return box
end

local function makeButton(parent: Instance, text: string, size: UDim2, position: UDim2): TextButton
	local btn = Instance.new("TextButton")
	btn.Size = size
	btn.Position = position
	btn.Text = text
	btn.BackgroundColor3 = Color3.fromRGB(0, 120, 80)
	btn.TextColor3 = Color3.fromRGB(255, 255, 255)
	btn.Font = Enum.Font.SourceSansBold
	btn.TextSize = 14
	btn.BorderSizePixel = 0
	btn.Parent = parent
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 4)
	corner.Parent = btn
	return btn
end

local function makeLabel(parent: Instance, text: string, size: UDim2, position: UDim2): TextLabel
	local lbl = Instance.new("TextLabel")
	lbl.Size = size
	lbl.Position = position
	lbl.Text = text
	lbl.BackgroundTransparency = 1
	lbl.TextColor3 = Color3.fromRGB(200, 200, 200)
	lbl.Font = Enum.Font.SourceSans
	lbl.TextSize = 13
	lbl.TextXAlignment = Enum.TextXAlignment.Left
	lbl.TextYAlignment = Enum.TextYAlignment.Top
	lbl.TextWrapped = true
	lbl.Parent = parent
	return lbl
end

local toolbar = plugin:CreateToolbar("Verde")
local toggleBtn = toolbar:CreateButton("Verde", "Open Verde panel", "")

local widgetInfo = DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Right, false, false, 380, 820, 320, 420)
local dock = plugin:CreateDockWidgetPluginGui("VerdeDock", widgetInfo)
dock.Title = "Verde"

local rootFrame = Instance.new("Frame")
rootFrame.Size = UDim2.fromScale(1, 1)
rootFrame.BackgroundColor3 = Color3.fromRGB(30, 30, 30)
rootFrame.BorderSizePixel = 0
rootFrame.Parent = dock

local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.new(1, -12, 1, -12)
scroll.Position = UDim2.fromOffset(6, 6)
scroll.BackgroundTransparency = 1
scroll.BorderSizePixel = 0
scroll.ScrollBarThickness = 6
scroll.CanvasSize = UDim2.fromOffset(0, 1320)
scroll.Parent = rootFrame

local content = Instance.new("Frame")
content.Size = UDim2.new(1, -8, 0, 1320)
content.BackgroundTransparency = 1
content.Parent = scroll

makeLabel(content, "LIVE SYNC  (scripts)", UDim2.new(1, 0, 0, 18), UDim2.fromOffset(0, 0))

local howTo = makeLabel(
	content,
	"1. In a terminal run:  verde-sync path/to/extracted\n"
		.. "2. Click Live Sync below.\n"
		.. "Default: only script Source stays in sync (safe for large places).",
	UDim2.new(1, 0, 0, 52),
	UDim2.fromOffset(0, 20)
)
howTo.TextColor3 = Color3.fromRGB(160, 160, 160)
howTo.TextSize = 12

local liveToggle = makeButton(content, "Live Sync: OFF", UDim2.new(1, 0, 0, 34), UDim2.fromOffset(0, 76))
liveToggle.BackgroundColor3 = Color3.fromRGB(80, 80, 80)

local liveStatus = makeLabel(content, "Waiting…", UDim2.new(1, 0, 0, 90), UDim2.fromOffset(0, 116))
liveStatus.TextColor3 = Color3.fromRGB(180, 180, 180)

local expToggle = makeButton(
	content,
	"Experimental: property sync OFF",
	UDim2.new(1, 0, 0, 28),
	UDim2.fromOffset(0, 212)
)
expToggle.BackgroundColor3 = Color3.fromRGB(60, 60, 70)
expToggle.TextSize = 12

local expHint = makeLabel(
	content,
	"Experimental watches Name, Tags, Attributes, and other properties on scripts.\n"
		.. "Can be slower on large places. Leave OFF unless you need it.",
	UDim2.new(1, 0, 0, 36),
	UDim2.fromOffset(0, 244)
)
expHint.TextColor3 = Color3.fromRGB(140, 140, 150)
expHint.TextSize = 11

local liveOn = false
local experimentalProps = false
local lastEventId = 0
local pollConnection: RBXScriptConnection? = nil
local changeConnections: { RBXScriptConnection } = {}
local mapConnections: { RBXScriptConnection } = {}
local applyingFromBridge = false
local pushDebounce: { [Instance]: boolean } = {}

-- Live Sync is scripts-scoped today. Pass false to refreshUniqueIdMap only if
-- a future mode watches non-script instances.
local MAP_SCRIPTS_ONLY = true

local SCRIPT_SERVICES = {
	"Workspace",
	"ServerScriptService",
	"ServerStorage",
	"ReplicatedStorage",
	"ReplicatedFirst",
	"StarterGui",
	"StarterPack",
	"StarterPlayer",
}

local function setLiveStatus(text: string, isError: boolean?)
	liveStatus.Text = text
	liveStatus.TextColor3 = if isError then Color3.fromRGB(230, 130, 130) else Color3.fromRGB(180, 180, 180)
end

local function diagnoseBridgeFailure(rawError: any): string
	local err = string.lower(tostring(rawError or ""))
	if string.find(err, "http requests are not enabled", 1, true)
		or string.find(err, "httpenabled", 1, true)
		or string.find(err, "not enabled", 1, true)
	then
		return table.concat({
			"Studio is blocking the connection (HttpService).",
			"",
			"How to fix:",
			"1. In Studio: Home → Game Settings → Security",
			"2. Turn ON  ‘Allow HTTP Requests’",
			"3. Click Save, then try Live Sync again",
		}, "\n")
	end
	if string.find(err, "connect", 1, true)
		or string.find(err, "refused", 1, true)
		or string.find(err, "timed out", 1, true)
		or string.find(err, "connection", 1, true)
		or err == ""
	then
		return table.concat({
			"Cannot reach Live Sync (verde-sync is not running).",
			"",
			"How to fix:",
			"1. Open a terminal (PowerShell / Terminal / cmd)",
			"2. Run:  verde-sync path/to/your/extracted",
			"   (use the same folder you exported with verde-export)",
			"3. Leave that window open",
			"4. Click Live Sync again",
			"",
			"Still stuck? Confirm HttpService is allowed:",
			"Game Settings → Security → Allow HTTP Requests = ON",
		}, "\n")
	end
	return table.concat({
		"Live Sync could not connect.",
		"",
		"Details: " .. tostring(rawError),
		"",
		"Checklist:",
		"• Terminal: verde-sync is running on your export folder",
		"• Studio: Game Settings → Security → Allow HTTP Requests = ON",
		"• Plugin: this place has the latest Verde ModuleScript",
	}, "\n")
end

local function stopLive()
	liveOn = false
	liveToggle.Text = "Live Sync: OFF"
	liveToggle.BackgroundColor3 = Color3.fromRGB(80, 80, 80)
	if pollConnection then
		pollConnection:Disconnect()
		pollConnection = nil
	end
	for _, c in changeConnections do
		c:Disconnect()
	end
	for _, c in mapConnections do
		c:Disconnect()
	end
	table.clear(changeConnections)
	table.clear(mapConnections)
	table.clear(pushDebounce)
end

local function pushInstanceToBridge(inst: Instance)
	if applyingFromBridge or not liveOn then
		return
	end
	if not inst:IsA("LuaSourceContainer") then
		return
	end
	if pushDebounce[inst] then
		return
	end
	pushDebounce[inst] = true
	task.delay(0.15, function()
		pushDebounce[inst] = nil
	end)

	local files = {}
	local meta = Verde.serializeMeta(inst)
	table.insert(files, {
		path = Verde.metaRelPath(inst),
		content = HttpService:JSONEncode(meta),
	})
	table.insert(files, {
		path = Verde.scriptRelPath(inst),
		content = (inst :: LuaSourceContainer).Source,
	})
	local okPush, errPush = Verde.bridgePost("/push", { files = files })
	if not okPush then
		setLiveStatus(
			diagnoseBridgeFailure(errPush)
				.. "\n\nStudio→folder push failed. Your last Source/meta edit may not have reached disk until the bridge is healthy again.",
			true
		)
		-- leave liveOn running so the 1s poll can recover when the bridge returns
	end
end

local function applyDirtyPaths(paths: { string })
	if #paths == 0 then
		return
	end

	local recording = ChangeHistoryService:TryBeginRecording("Verde Live Sync")
	local recordingOk = recording ~= nil
	local applied, noMatch = 0, 0

	applyingFromBridge = true
	for _, rel in paths do
		local isScript = string.match(rel, "%.lua$") ~= nil
		local isMeta = string.match(rel, "%.robloxmeta%.json$") ~= nil
		if not isScript and not isMeta then
			continue
		end

		local source: string? = nil
		local meta: any = nil

		if isScript then
			local okFile, body = Verde.bridgeGet("/file?path=" .. HttpService:UrlEncode(rel))
			if okFile and typeof(body) == "string" then
				source = body
			end
			local okMeta, m = Verde.bridgeGet("/meta?path=" .. HttpService:UrlEncode(rel))
			if okMeta and typeof(m) == "table" then
				meta = m
			end
		elseif isMeta then
			local okMeta, m = Verde.bridgeGet("/file?path=" .. HttpService:UrlEncode(rel))
			if okMeta and typeof(m) == "string" then
				local decodeOk, decoded = pcall(function()
					return HttpService:JSONDecode(m)
				end)
				if decodeOk and typeof(decoded) == "table" then
					meta = decoded
				end
			end
		end

		local changed, err = Verde.applyFromBridge(rel, source, meta)
		if err == "no match" then
			noMatch += 1
		elseif changed then
			applied += 1
		end
	end
	applyingFromBridge = false

	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	end
	Verde.bridgePost("/applied", { paths = paths })

	local undoNote = if not recordingOk then "\n(No undo waypoint: playtest or concurrent recording.)" else ""
	if noMatch > 0 then
		setLiveStatus(
			string.format(
				"Synced %d script change(s).\n%d file(s) had no matching script in Studio.\n"
					.. "Tip: names/paths must match the export, or re-export after renames.",
				applied,
				noMatch
			) .. undoNote,
			noMatch > applied
		)
	else
		setLiveStatus(string.format("Synced %d script change(s). Watching…", applied) .. undoNote)
	end
end

local function wireMapListeners()
	for _, c in mapConnections do
		c:Disconnect()
	end
	table.clear(mapConnections)

	local function trackForMap(inst: Instance)
		if MAP_SCRIPTS_ONLY and not inst:IsA("LuaSourceContainer") then
			return
		end
		Verde.indexInstance(inst)
		table.insert(
			mapConnections,
			inst.Destroying:Connect(function()
				Verde.unindexInstance(inst)
			end)
		)
	end

	for _, svcName in SCRIPT_SERVICES do
		local ok, svc = pcall(function()
			return game:GetService(svcName)
		end)
		if ok and svc then
			table.insert(
				mapConnections,
				svc.DescendantAdded:Connect(function(d)
					if liveOn then
						trackForMap(d)
					end
				end)
			)
		end
	end
end

local function wireChangeListeners()
	for _, c in changeConnections do
		c:Disconnect()
	end
	table.clear(changeConnections)

	local liveProps: { string } = Verde.LIVE_PROPS or { "Name", "Enabled" }

	local function considerScript(inst: Instance)
		if not inst:IsA("LuaSourceContainer") then
			return
		end

		table.insert(
			changeConnections,
			inst:GetPropertyChangedSignal("Source"):Connect(function()
				if liveOn then
					pushInstanceToBridge(inst)
				end
			end)
		)

		if not experimentalProps then
			return
		end

		for _, prop in liveProps do
			pcall(function()
				table.insert(
					changeConnections,
					inst:GetPropertyChangedSignal(prop):Connect(function()
						if liveOn then
							pushInstanceToBridge(inst)
						end
					end)
				)
			end)
		end
		table.insert(
			changeConnections,
			inst.AttributeChanged:Connect(function()
				if liveOn then
					pushInstanceToBridge(inst)
				end
			end)
		)
	end

	for _, svcName in SCRIPT_SERVICES do
		local ok, svc = pcall(function()
			return game:GetService(svcName)
		end)
		if ok and svc then
			if svc:IsA("LuaSourceContainer") then
				considerScript(svc)
			end
			for _, d in svc:GetDescendants() do
				considerScript(d)
			end
			table.insert(
				changeConnections,
				svc.DescendantAdded:Connect(function(d)
					if liveOn then
						considerScript(d)
					end
				end)
			)
		end
	end
end

local function startLive()
	local ok, statusOrErr = Verde.bridgeGet("/status")
	if not ok then
		setLiveStatus(diagnoseBridgeFailure(statusOrErr), true)
		return
	end
	if typeof(statusOrErr) ~= "table" or not statusOrErr.ok then
		setLiveStatus(diagnoseBridgeFailure(statusOrErr), true)
		return
	end

	liveOn = true
	liveToggle.Text = "Live Sync: ON"
	liveToggle.BackgroundColor3 = Color3.fromRGB(0, 140, 90)
	setLiveStatus(
		"Connected to:\n"
			.. tostring(statusOrErr.root or "(folder)")
			.. "\n\nRunning first full scan (scripts)…"
	)

	-- Map scope matches watch mode (scripts-only today).
	Verde.refreshUniqueIdMap(MAP_SCRIPTS_ONLY)
	wireMapListeners()

	local okFull, full = Verde.bridgePost("/full-sync", {})
	if okFull and typeof(full) == "table" and full.dirty then
		applyDirtyPaths(full.dirty)
	else
		setLiveStatus(
			"Connected. Watching script files…\n"
				.. "Edit a .lua file or a script Source — both sides stay in sync."
		)
	end

	wireChangeListeners()

	local accum = 0
	pollConnection = RunService.Heartbeat:Connect(function(dt)
		if not liveOn then
			return
		end
		accum += dt
		if accum < 1.0 then
			return
		end
		accum = 0

		local okEv, data = Verde.bridgeGet("/events?since=" .. tostring(lastEventId))
		if not okEv or typeof(data) ~= "table" then
			setLiveStatus(
				diagnoseBridgeFailure(data)
					.. "\n\nLive Sync was turned off. Fix the issue, then turn it on again.",
				true
			)
			stopLive()
			return
		end
		if data.last_id then
			lastEventId = data.last_id
		end
		for _, ev in (data.events or {}) do
			if ev.type == "dirty" and ev.paths then
				applyDirtyPaths(ev.paths)
			end
		end
	end)
end

liveToggle.MouseButton1Click:Connect(function()
	if liveOn then
		stopLive()
		setLiveStatus("Live Sync is off. Script files are no longer watched.")
	else
		startLive()
	end
end)

expToggle.MouseButton1Click:Connect(function()
	experimentalProps = not experimentalProps
	if experimentalProps then
		expToggle.Text = "Experimental: property sync ON"
		expToggle.BackgroundColor3 = Color3.fromRGB(120, 90, 40)
	else
		expToggle.Text = "Experimental: property sync OFF"
		expToggle.BackgroundColor3 = Color3.fromRGB(60, 60, 70)
	end
	if liveOn then
		wireChangeListeners()
		setLiveStatus(
			if experimentalProps
				then "Experimental property sync enabled (scripts only)."
				else "Back to default: Source only."
		)
	end
end)

makeLabel(content, "SEARCH", UDim2.new(1, 0, 0, 18), UDim2.fromOffset(0, 290))

local classBox = makeTextBox(content, "ClassName (e.g. Sound)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 312))
local nameBox = makeTextBox(content, "Exact Name", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 346))
local nameContainsBox = makeTextBox(content, "Name contains", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 380))
local tagBox = makeTextBox(content, "Tag", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 414))
local propBox = makeTextBox(content, "Property name (e.g. SoundId)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 448))
local propContainsBox = makeTextBox(content, "Property value contains", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 482))

local searchBtn = makeButton(content, "Search", UDim2.new(0.48, 0, 0, 30), UDim2.fromOffset(0, 520))
local selectBtn = makeButton(content, "Select results", UDim2.new(0.48, 0, 0, 30), UDim2.new(0.52, 0, 0, 520))
selectBtn.BackgroundColor3 = Color3.fromRGB(60, 90, 140)

local resultLabel = makeLabel(content, "Results: —", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 556))
local lastResults: { Instance } = {}

searchBtn.MouseButton1Click:Connect(function()
	local opts = {
		className = classBox.Text ~= "" and classBox.Text or nil,
		name = nameBox.Text ~= "" and nameBox.Text or nil,
		nameContains = nameContainsBox.Text ~= "" and nameContainsBox.Text or nil,
		tag = tagBox.Text ~= "" and tagBox.Text or nil,
		prop = propBox.Text ~= "" and propBox.Text or nil,
		propContains = propContainsBox.Text ~= "" and propContainsBox.Text or nil,
	}
	lastResults = Verde.search(opts)
	resultLabel.Text = string.format("Results: %d instance(s)", #lastResults)
end)

selectBtn.MouseButton1Click:Connect(function()
	if #lastResults > 0 then
		Selection:Set(lastResults)
	end
end)

makeLabel(content, "SET / REPLACE PROPERTY", UDim2.new(1, 0, 0, 18), UDim2.fromOffset(0, 588))

local setPropBox = makeTextBox(content, "Property (CastShadow, Anchored, SoundId, …)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 610))
local setValueBox = makeTextBox(content, "New value (true / false / number / string)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 644))
local setClassBox = makeTextBox(content, "Only ClassName (optional)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 678))
local setTagBox = makeTextBox(content, "Only tag (optional)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 712))
local setFromBox = makeTextBox(content, "Only if current value equals (optional)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 746))

local setBtn = makeButton(content, "Set / Replace", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 784))
local setStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 40), UDim2.fromOffset(0, 820))

-- Helper: collect distinct current values that case-fold to the typed --from
local function collectCaseVariants(propName: string, typedOld: string, opts: any): { string }
	local fold = string.lower(typedOld)
	local seen: { [string]: boolean } = {}
	local list: { string } = {}
	local candidates = Verde.search({
		className = opts.className,
		tag = opts.tag,
		prop = propName,
		propContains = typedOld, -- case-insensitive discovery
	})
	for _, inst in candidates do
		local ok, cur = pcall(function() return (inst :: any)[propName] end)
		if ok and cur ~= nil then
			local s = tostring(cur)
			if string.lower(s) == fold and not seen[s] then
				seen[s] = true
				table.insert(list, s)
			end
		end
	end
	table.sort(list)
	return list
end

setBtn.MouseButton1Click:Connect(function()
	local prop = setPropBox.Text
	local newV = setValueBox.Text
	if prop == "" or newV == "" then
		setStatus.Text = "Property and New value are required."
		return
	end
	local opts = {
		className = setClassBox.Text ~= "" and setClassBox.Text or nil,
		tag = setTagBox.Text ~= "" and setTagBox.Text or nil,
	}
	local recording = ChangeHistoryService:TryBeginRecording("Verde Set " .. prop)
	local n: number
	if setFromBox.Text ~= "" then
		n = Verde.replaceProp(prop, setFromBox.Text, newV, opts)
		if n == 0 then
			local variants = collectCaseVariants(prop, setFromBox.Text, opts)
			if #variants > 1 then
				setStatus.Text = string.format(
					"0 exact matches. Case variants found: %s\nRe-type one exact value in ‘Only if…’ and try again.",
					table.concat(variants, ", ")
				)
			elseif #variants == 1 and variants[1] ~= setFromBox.Text then
				setStatus.Text = string.format(
					"0 exact matches. Closest case variant: %q\nCopy it into ‘Only if…’ to replace.",
					variants[1]
				)
			else
				setStatus.Text = "Updated 0 instance(s). (no matches)"
			end
		else
			setStatus.Text = string.format("Updated %d instance(s).", n)
		end
	else
		n = Verde.setProp(prop, newV, opts)
		setStatus.Text = string.format("Updated %d instance(s).", n)
	end
	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	else
		setStatus.Text = setStatus.Text .. "\n(No undo: playtest or concurrent recording active)"
	end
end)

makeLabel(content, "TAGS", UDim2.new(1, 0, 0, 18), UDim2.fromOffset(0, 852))

local listTagsBtn = makeButton(content, "List all tags", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 874))
listTagsBtn.BackgroundColor3 = Color3.fromRGB(90, 70, 140)

local tagListLabel = makeLabel(content, "", UDim2.new(1, 0, 0, 44), UDim2.fromOffset(0, 910))

listTagsBtn.MouseButton1Click:Connect(function()
	local map = Verde.listTags()
	local lines, keys = {}, {}
	for tag in pairs(map) do
		table.insert(keys, tag)
	end
	table.sort(keys)
	for _, tag in keys do
		table.insert(lines, string.format("%s (%d)", tag, #map[tag]))
	end
	tagListLabel.Text = if #lines > 0 then table.concat(lines, ", ") else "(no tags found)"
end)

local oldTagBox = makeTextBox(content, "Old tag", UDim2.new(0.48, 0, 0, 28), UDim2.fromOffset(0, 960))
local newTagBox = makeTextBox(content, "New tag", UDim2.new(0.48, 0, 0, 28), UDim2.new(0.52, 0, 0, 960))

local renameTagBtn = makeButton(content, "Rename tag", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 996))
local tagStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 40), UDim2.fromOffset(0, 1032))

renameTagBtn.MouseButton1Click:Connect(function()
	local oldT, newT = oldTagBox.Text, newTagBox.Text
	if oldT == "" or newT == "" then
		tagStatus.Text = "Both old and new tag names required."
		return
	end
	local recording = ChangeHistoryService:TryBeginRecording("Verde Rename Tag")
	local n = Verde.replaceTag(oldT, newT)
	if n == 0 then
		-- Surface case variants so the user can type the exact tag
		local map = Verde.listTags()
		local fold = string.lower(oldT)
		local variants = {}
		for tag in pairs(map) do
			if string.lower(tag) == fold then
				table.insert(variants, tag)
			end
		end
		table.sort(variants)
		if #variants > 1 then
			tagStatus.Text = string.format(
				"0 exact matches. Case variants: %s\nType one exact tag name and try again.",
				table.concat(variants, ", ")
			)
		elseif #variants == 1 and variants[1] ~= oldT then
			tagStatus.Text = string.format(
				"0 exact matches. Closest: %q\nCopy it into ‘Old tag’ to rename.",
				variants[1]
			)
		else
			tagStatus.Text = "Updated 0 instance(s). (no matches)"
		end
	else
		tagStatus.Text = string.format("Updated %d instance(s).", n)
	end
	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	else
		tagStatus.Text = tagStatus.Text .. "\n(No undo: playtest or concurrent recording active)"
	end
end)

makeLabel(content, "SCRIPTS (DUMP / RESTORE)", UDim2.new(1, 0, 0, 18), UDim2.fromOffset(0, 1064))

local dumpBtn = makeButton(content, "Dump scripts → ServerStorage", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 1086))
dumpBtn.BackgroundColor3 = Color3.fromRGB(40, 100, 140)

local restoreBtn = makeButton(content, "Restore from ScriptDump_*", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 1124))
restoreBtn.BackgroundColor3 = Color3.fromRGB(100, 70, 40)

local scriptStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 40), UDim2.fromOffset(0, 1160))

dumpBtn.MouseButton1Click:Connect(function()
	local archive, count = Verde.dumpScripts()
	if archive then
		scriptStatus.Text = string.format(
			"Archived %d scripts → %s\nSelect folder → Save to File (.rbxm)",
			count,
			archive:GetFullName()
		)
		Selection:Set({ archive })
	else
		scriptStatus.Text = "Dump failed."
	end
end)

restoreBtn.MouseButton1Click:Connect(function()
	local recording = ChangeHistoryService:TryBeginRecording("Verde Restore Scripts")
	local restored, created, skipped = Verde.restoreScripts()
	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	end
	scriptStatus.Text = string.format("Restored %d (created %d, skipped %d)", restored, created, skipped)
	if not recording then
		scriptStatus.Text = scriptStatus.Text .. "\n(No undo: playtest or concurrent recording active)"
	end
end)

toggleBtn.Click:Connect(function()
	dock.Enabled = not dock.Enabled
end)

print("[Verde] Plugin loaded. Open the Verde panel → Live Sync for script live-edit.")
