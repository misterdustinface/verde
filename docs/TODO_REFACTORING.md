# TODO_REFACTORING.md — Verde

High-quality, high-impact simplifications that reduce codebase size, improve readability (especially extracting common functions or modules), and are performance-neutral or better.  
Purely stylistic or low-impact changes do not belong here. Defects stay in BUGS.md; features in TODO_FEATURES.md / FEATURES.md.

---

## Recommended

### 1. Extract shared `_prompt_choices` helper from tags.py / set_replace.py

**Why / Impact**  
Near-identical interactive prompt helpers are duplicated in two feature modules. Extracting to a small common util reduces ~30-40 lines and keeps prompt behaviour consistent.

**Scope / Approach**  
- Move the common prompt logic into a shared helper (e.g. under features/ or a new util).
- Update call sites in tags.py and set_replace.py.

**Performance notes**  
Neutral (CLI interactive path only; no hot-path impact).

---

## Completed

### 1. Shared XML property parsing + name helpers (extract.py / build.py) — DONE

**What changed**  
Extracted the identical `parse_children`, `parse_property_element`, and near-identical `sanitize_name` into a new `python/xml_props.py` module. Updated extract.py and build.py to import the shared pure helpers and removed the local private copies. Also provided a shared `decode_tags_from_prop` for the repeated Tags BinaryString/string decoding, used by both extract_properties / _item_has_tag and build's _get_tags.

**Performance**  
Neutral (same algorithms, pure functions, single source of truth). Enables future optimisations of the structured property parser in one place. Removes ~80-100 lines of duplication and improves maintainability of the critical round-trip path.
