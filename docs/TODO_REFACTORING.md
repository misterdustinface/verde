# TODO_REFACTORING.md — Verde

High-quality, high-impact simplifications that reduce codebase size, improve readability (especially extracting common functions or modules), and are performance-neutral or better.  
Purely stylistic or low-impact changes do not belong here. Defects stay in BUGS.md; features in TODO_FEATURES.md / FEATURES.md.

---

## Recommended

### 1. Shared unique-name claim helper + FS case constant (extract.py / build.py)

**Why / Impact**  
The sibling-name uniqueness loop (base → base_2 → … with casefold on Darwin/Windows) and the `_FS_CASE_INSENSITIVE` platform check are duplicated between `extract.py` (used_names / written_names) and `build.py` (`_build_instance_maps` taken set). Past correctness bugs (case-only collisions producing unmatchable path_map keys) show that drift between the two sides is costly. A single pure helper eliminates the duplication, guarantees identical uniqueness rules for export path reuse and import path maps, and shrinks both files.

**Scope / Approach**  
- Add to `python/xml_props.py` (already owns `sanitize_name`):
  - `FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")`
  - `def claim_unique_name(base: str, claimed: set[str]) -> str` that returns the uniquified name and mutates the claimed set (casefold key when needed).
- Update the two call sites in extract.py and the walk in build.py to import and use it; delete the local `_FS_CASE_INSENSITIVE` and while-loops.
- Optionally also use it in extract’s `_cleanup_orphaned_uniquified` casefold checks for consistency.

**Performance notes**  
Neutral (identical algorithm, pure function, no extra allocations on the hot path). Future changes to uniqueness policy need only touch one place.

### 2. Residual Tags decoding consolidation (extract.py)

**Why / Impact**  
Completed item 1 introduced `decode_tags_from_prop` and claimed it was used by extract_properties / _item_has_tag, but the current extract.py still re-implements BinaryString (base64 + null-split) and string/ProtectedString decoding both in `extract_properties` and in `_item_has_tag`. This residual duplication is the incomplete half of the earlier extraction; cleaning it finishes the single-source goal for Tags and removes ~25–30 lines of near-identical logic.

**Scope / Approach**  
- Extend `xml_props.py` with a small `decode_tags_from_structured(structured: dict) -> list[str]` (or make the existing decoder accept either Element or structured dict).
- Rewrite the two Tags blocks in `extract_properties` and the body of `_item_has_tag` to call the shared helper.
- Keep the existing Element-based path used by build.py’s `_get_tags`.

**Performance notes**  
Neutral (same decode paths). Slightly fewer allocations if the structured path can avoid re-parsing text when already structured.

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
