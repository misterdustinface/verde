--!strict
--[[
	Canonical list of "interesting" properties.
	This is the single source of truth (optimized for Luau).

	- Verde.luau requires this ModuleScript (as a child or sibling).
	- Python loads it via interesting.py (simple string extraction).

	Keep this list in sync; expand freely for search/set convenience.
]]

return {
	-- Core identity / content
	"Source",
	"Name",
	"Value",
	"Text",
	"PlaceholderText",

	-- Asset / content IDs (most common migration targets)
	"SoundId",
	"Texture",
	"TextureId",
	"MeshId",
	"AnimationId",
	"Image",
	"ImageContent",
	"ContentId",
	"LinkedSource",
	"ScriptGuid",
	"MeshContent",
	"TextureContent",
	"PackageId",
	"Video",
	"CursorIcon",
	"IconImageId",

	-- UI image variants
	"HoverImage",
	"PressedImage",
	"SelectedImage",
	"ImageRectOffset",
	"ImageRectSize",

	-- Sky / lighting
	"SkyboxBk",
	"SkyboxDn",
	"SkyboxFt",
	"SkyboxLf",
	"SkyboxRt",
	"SkyboxUp",

	-- Appearance / physics
	"Material",
	"MaterialVariant",
	"Color",
	"BrickColor",
	"Transparency",
	"Reflectance",
	"Size",
	"Position",
	"Orientation",
	"CFrame",
	"VertexColor",
	"RenderFidelity",
	"CollisionFidelity",
	"DoubleSided",
	"CollisionGroup",
	"CastShadow",

	-- Anchoring / collision
	"Anchored",
	"CanCollide",
	"CanTouch",
	"CanQuery",
	"Massless",
	"Locked",
	"Archivable",

	-- Script / UI state
	"Disabled",
	"Enabled",
	"Active",
	"Visible",
	"ZIndex",
	"LayoutOrder",
	"BackgroundTransparency",
	"BorderSizePixel",
	"ClipsDescendants",
	"AutomaticSize",
	"SizeConstraint",

	-- Typography
	"Font",
	"FontFace",
	"TextSize",
	"TextColor3",
	"TextStrokeTransparency",
	"TextXAlignment",
	"TextYAlignment",
	"TextWrapped",
	"TextScaled",
	"RichText",
	"MaxVisibleGraphemes",
	"ClearTextOnFocus",
	"MultiLine",
	"PlaceholderColor3",
	"CursorPosition",
	"SelectionStart",
	"ShowNativeInput",
	"TextEditable",

	-- Sound
	"SoundGroup",
	"RollOffMode",
	"PlaybackSpeed",
	"Volume",
	"Looped",
	"Playing",
	"TimePosition",

	-- Misc references
	"PrimaryPart",
	"CameraSubject",
	"RootPriority",
	"AssemblyLinearVelocity",
	"AssemblyAngularVelocity",
}
