# TODO_REFACTORING.md — Verde

High-quality, high-impact simplifications that reduce codebase size, improve readability (especially by extracting common functions or modules), and are performance-neutral or better.  
Purely stylistic or low-impact changes do not belong here. Defects stay in BUGS.md; features in TODO_FEATURES.md / FEATURES.md.

---

## Recommended

*(none currently — residual scan 2026-07-30 after the July 28–30 fix wave (SharedString Tags, import graft/create/prune, interesting extractor, Live Sync metaRelPath, Attributes encode fidelity, etc.) found no additional candidates that clear the high-impact + size-reduction + performance-neutral bar. Prior completed extractions (xml_props helpers, claim_unique_name, prompt_choices) remain complete and fully wired. Luau sanitiser is language-isolated by design.)*

---

## Completed

### 1. Shared XML property parsing + name helpers (extract.py / build.py) — DONE

**What changed**  
Extracted the identical `parse_children`, `parse_property_element`, and near-identical `sanitize_name` into a new `python/xml_props.py` module. Updated extract.py and build.py to import the shared pure helpers and removed the local private copies. Also provided a shared `decode_tags_from_prop` for the repeated Tags BinaryString/string decoding, used by both extract_properties / _item_has_tag and build's _get_tags.

**Performance**  
Neutral (same algorithms, pure functions, single source of truth). Enables future optimisations of the structured property parser in one place. Removes ~80-100 lines of duplication and improves maintainability of the critical round-trip path.

### 2. Extract shared `prompt_choices` helper from tags.py / set_replace.py — DONE

**What changed**  
Moved the identical interactive case-disambiguation prompt (numbered list of (value, count) variants, support for a/all/n, multi-select) into `features/meta.py` as `prompt_choices`. Updated both call sites to import and use the shared function; deleted the two private local copies.

**Performance outcome**  
Neutral (CLI interactive path only). Removes ~35 lines of duplication and keeps prompt behaviour consistent between the two feature CLIs.

### 3. Shared unique-name claim helper + FS case constant (extract.py / build.py) — DONE

**What changed**  
`claim_unique_name` + `FS_CASE_INSENSITIVE` were added to `xml_props.py` and wired into extract in PR #29. This change completes the extraction: `build.py` `_build_instance_maps` now imports and uses the same pure helper; the local `_FS_CASE_INSENSITIVE` and while-loop were deleted. Export path-reuse and import path maps are now guaranteed identical.

**Performance**  
Neutral (identical algorithm, pure function). Future uniqueness policy changes need only touch one place.
