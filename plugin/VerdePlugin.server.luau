--!strict
--[[
	Verde Studio Plugin

	Integrates the Luau Verde module (single source of truth):
	  • Search / set / replace properties (by tag or ClassName)
	  • CollectionService tag list / rename
	  • Script dump → ServerStorage archive / restore from archive

	Installation (required):
	  1. Create a local plugin folder.
	  2. Add a ModuleScript named "Verde" and paste luau/Verde.luau.
	  3. (Recommended) Add interesting_properties.luau as a child of that ModuleScript.
	  4. Add a Script, paste this file, save as local plugin.
]]

local ChangeHistoryService = game:GetService("ChangeHistoryService")
local Selection = game:GetService("Selection")
local ServerStorage = game:GetService("ServerStorage")

-- ── Require Verde (must be present) ─────────────────────────────────────────
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
		error("[Verde Plugin] Could not require Verde ModuleScript.\n"
			.. "Place luau/Verde.luau as a ModuleScript named \"Verde\" next to this plugin script (or under ServerStorage).")
	end
end

-- ── UI helpers ──────────────────────────────────────────────────────────────

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
	lbl.Parent = parent
	return lbl
end

-- ── Plugin chrome ───────────────────────────────────────────────────────────

local toolbar = plugin:CreateToolbar("Verde")
local toggleBtn = toolbar:CreateButton(
	"Verde",
	"Open Verde panel (search / set / tags / script dump)",
	""
)

local widgetInfo = DockWidgetPluginGuiInfo.new(
	Enum.InitialDockState.Right,
	false,
	false,
	360,
	720,
	300,
	400
)
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
scroll.CanvasSize = UDim2.fromOffset(0, 1040)
scroll.Parent = rootFrame

local content = Instance.new("Frame")
content.Size = UDim2.new(1, -8, 0, 1040)
content.BackgroundTransparency = 1
content.Parent = scroll

-- ── Search ──────────────────────────────────────────────────────────────────

makeLabel(content, "SEARCH", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 0))

local classBox = makeTextBox(content, "ClassName (e.g. Sound)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 24))
local nameBox = makeTextBox(content, "Exact Name", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 58))
local nameContainsBox = makeTextBox(content, "Name contains", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 92))
local tagBox = makeTextBox(content, "Tag", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 126))
local propBox = makeTextBox(content, "Property name (e.g. SoundId)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 160))
local propContainsBox = makeTextBox(content, "Property value contains", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 194))

local searchBtn = makeButton(content, "Search", UDim2.new(0.48, 0, 0, 30), UDim2.fromOffset(0, 232))
local selectBtn = makeButton(content, "Select results", UDim2.new(0.48, 0, 0, 30), UDim2.new(0.52, 0, 0, 232))
selectBtn.BackgroundColor3 = Color3.fromRGB(60, 90, 140)

local resultLabel = makeLabel(content, "Results: —", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 268))
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
	if #lastResults > 0 then Selection:Set(lastResults) end
end)

-- ── Set / Replace ───────────────────────────────────────────────────────────

makeLabel(content, "SET / REPLACE PROPERTY", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 300))

local setPropBox = makeTextBox(content, "Property (CastShadow, Anchored, SoundId, …)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 324))
local setValueBox = makeTextBox(content, "New value (true / false / number / string)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 358))
local setClassBox = makeTextBox(content, "Only ClassName (optional, e.g. Part)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 392))
local setTagBox = makeTextBox(content, "Only tag (optional, e.g. NoShadow)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 426))
local setFromBox = makeTextBox(content, "Only if current value equals (optional)", UDim2.new(1, 0, 0, 28), UDim2.fromOffset(0, 460))

local setBtn = makeButton(content, "Set / Replace", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 498))
local setStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 534))

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
	else
		n = Verde.setProp(prop, newV, opts)
	end
	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	end
	setStatus.Text = string.format("Updated %d instance(s).", n)
end)

-- ── Tags ────────────────────────────────────────────────────────────────────

makeLabel(content, "TAGS", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 570))

local listTagsBtn = makeButton(content, "List all tags", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 594))
listTagsBtn.BackgroundColor3 = Color3.fromRGB(90, 70, 140)

local tagListLabel = makeLabel(content, "", UDim2.new(1, 0, 0, 50), UDim2.fromOffset(0, 630))
tagListLabel.TextWrapped = true
tagListLabel.TextYAlignment = Enum.TextYAlignment.Top

listTagsBtn.MouseButton1Click:Connect(function()
	local map = Verde.listTags()
	local lines = {}
	local keys = {}
	for tag in pairs(map) do table.insert(keys, tag) end
	table.sort(keys)
	for _, tag in keys do
		table.insert(lines, string.format("%s (%d)", tag, #map[tag]))
	end
	tagListLabel.Text = if #lines > 0 then table.concat(lines, ", ") else "(no tags found)"
end)

local oldTagBox = makeTextBox(content, "Old tag", UDim2.new(0.48, 0, 0, 28), UDim2.fromOffset(0, 686))
local newTagBox = makeTextBox(content, "New tag", UDim2.new(0.48, 0, 0, 28), UDim2.new(0.52, 0, 0, 686))

local renameTagBtn = makeButton(content, "Rename tag", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 722))
local tagStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 758))

renameTagBtn.MouseButton1Click:Connect(function()
	local oldT, newT = oldTagBox.Text, newTagBox.Text
	if oldT == "" or newT == "" then
		tagStatus.Text = "Both old and new tag names required."
		return
	end
	local recording = ChangeHistoryService:TryBeginRecording("Verde Rename Tag")
	local n = Verde.replaceTag(oldT, newT)
	if recording then
		ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
	end
	tagStatus.Text = string.format("Updated %d instance(s).", n)
end)

-- ── Scripts dump / restore ──────────────────────────────────────────────────

makeLabel(content, "SCRIPTS (DUMP / RESTORE)", UDim2.new(1, 0, 0, 20), UDim2.fromOffset(0, 790))

local dumpBtn = makeButton(content, "Dump scripts → ServerStorage", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 814))
dumpBtn.BackgroundColor3 = Color3.fromRGB(40, 100, 140)

local restoreBtn = makeButton(content, "Restore from ScriptDump_*", UDim2.new(1, 0, 0, 30), UDim2.fromOffset(0, 852))
restoreBtn.BackgroundColor3 = Color3.fromRGB(100, 70, 40)

local scriptStatus = makeLabel(content, "", UDim2.new(1, 0, 0, 40), UDim2.fromOffset(0, 890))
scriptStatus.TextWrapped = true
scriptStatus.TextYAlignment = Enum.TextYAlignment.Top

dumpBtn.MouseButton1Click:Connect(function()
	local archive, count = Verde.dumpScripts()
	if archive then
		scriptStatus.Text = string.format("Archived %d scripts → %s\nSelect folder → Save to File (.rbxm)", count, archive:GetFullName())
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
end)

-- Toggle
toggleBtn.Click:Connect(function()
	dock.Enabled = not dock.Enabled
end)

print("[Verde] Plugin loaded. Click the Verde toolbar button to open the panel.")
