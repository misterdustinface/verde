# Import/export safety audit — 2026-09-29

This audit records import/export hardening and its verification limits.
It does not certify every possible Roblox place or property type.

## Python verification bar

`python3 -m pytest -q`: **65 passed**, including **35 new safety cases**
in `python/tests/test_import_export_safety.py`. The named Python regression bar
is **35/35 (100%)**. A wheel built with setuptools 84.0.0 imports successfully outside the checkout,
including the previously omitted `xml_props` module. Existing property tests
now explicitly request full exports;
the scripts-only default remains intact.

The new cases cover:

1. Scripts-only imports retain non-script content, including with explicit deletion.
2. Export retains unvisited numeric-suffix files; import includes legitimate numeric-suffix scripts.
3. Deletion/rename defaults and their independent CLI controls retain the original behavior.
4. Unreadable Source, corrupt metadata, and corrupt scope abort before modifying the place.
5. Incomplete XML writes leave the original place intact.
6. Full rebuild retains root tables, unknown attribute payloads, and mixed child order.
7. Explicit empty Tags clears old serialized tags; top-level Name edits override old structured Name.
8. Partial metadata does not erase Source; a full export clears stale selective scope.
9. Nested root exports retain ancestry and import their script edits successfully.
10. Stable UniqueId wins over reused Referent, and existing target Referents remain intact.
11. Bridge acknowledgements and Studio pushes do not mark unrelated disk changes clean.
12. Bridge script lookup never substitutes parent metadata, and script companion local identity is retained.
13. Pending bridge changes remain visible after the event cursor advances.
14. Import and Live Sync detect changed content despite preserved old timestamps and newer place timestamps.
15. The explicit offline merge command retains its documented timestamp policy.
16. File-read envelopes preserve JSON-shaped Source and supply its SHA-256 revision.
17. Acknowledging an old file revision does not mark a newer disk edit clean.
18. Duplicate Referent/UniqueId metadata aborts import rather than ignoring one file.
19. An empty old script Source does not match a nonempty new Source as a rename.
20. Studio metadata pushes retain offline-only properties and child order.
21. Invalid Studio metadata pushes do not overwrite existing metadata.

These categories summarize 35 parametrized test cases, rather than representing
35 claims about complete product readiness.

## Studio verification bar

Luau source was reviewed against the Python bridge path and Roblox's
[Instance documentation](https://create.roblox.com/docs/reference/engine/classes/Instance)
and [change history documentation](https://create.roblox.com/docs/reference/engine/classes/ChangeHistoryService).
Luau 0.740 successfully compiled `Verde.luau`, `VerdePlugin.server.luau`, and
`SafetyTests.luau`. Studio runtime behavior has not been verified.
The named Studio runtime bar is **0/12 (0%) verified**:

| Case awaiting runtime verification | Changed path |
| --- | --- |
| Ambiguous duplicate names and numeric-suffix guesses do not mutate a different instance | `resolveByRelPath` |
| ModuleScript/LocalScript metadata paths resolve correctly | `resolveByRelPath` |
| Failed HTTP reads remain pending | plugin `applyDirtyPaths` |
| Partial Studio pushes surface a failure instead of reporting success | plugin `pushInstanceToBridge` |
| Mutation exceptions are reported and remain pending | `applyMeta`, plugin `applyDirtyPaths` |
| Unmatched files retry after event cursor advances | bridge `/events`, plugin polling |
| Acknowledgement applies only to the file revision read by Studio | bridge `/file`, `/applied`, plugin `applyDirtyPaths` |
| Empty tags/attributes serialize explicitly and can clear the target | `serializeMeta`, `applyMeta` |
| Offline scalar bool/number/string/Content properties decode correctly | `decodeValue`, `applyMeta` |
| Duplicate script archives restore their original instance identities | `dumpScripts`, `restoreScripts` |
| New archives recreate paths containing dots without splitting those names | `dumpScripts`, `restoreScripts` |
| Script RunContext round-trips | `dumpScripts`, `restoreScripts` |

`luau/SafetyTests.luau` provides real Studio checks for resolver, scalar/meta,
and archive behavior. Install it as a ModuleScript alongside Verde and run
`require(path.to.SafetyTests)(require(path.to.Verde))` from the Command Bar or a
local plugin outside Play mode. It creates and removes its own test instances.
The suite has not been executed here. HTTP disconnect/retry cases additionally
need the plugin connected to `verde-sync`.

## Changed workflow

Ordinary `verde-import code/ MyPlace.rbxlx` retains the original deletion and
rename-removal defaults. `--no-delete --no-rename` requests report-only handling.
There are no new `--delete` or `--rename` CLI flags.

New default scripts-only exports record their scope so imports protect
non-script types. `--scripts-only` remains available for older exports and
script-only imports of a full hierarchy. Changed file content bypasses timestamp
suppression, so preserved timestamps alone no longer require `--force`.
Identity matches update existing instances and preserve their serialization IDs.

## Remaining limits

- Older exports that already dropped root tables, attributes, or ordering need
  a fresh export from the original place; these fixes cannot reconstruct lost data.
- Existing-place differential imports preserve existing child order. Full
  rebuilds from new exports restore exported sibling order.
- Unknown attribute types remain opaque raw blobs and cannot safely be edited
  through the decoded JSON attribute map.
- Legacy Studio archives without the new reference/path metadata cannot
  unambiguously represent names containing dots. New archives address this;
  duplicate legacy paths are refused.
- Live Sync still lacks a three-way conflict policy. Simultaneous Studio and
  disk edits can overwrite one side. New plugin acknowledgements carry SHA-256
  revisions; older plugins still use the legacy unversioned acknowledgement.
  Update the Python bridge and plugin together.
- Cross-place imports of Ref-valued properties need explicit reference remapping;
  preserving target Referents alone does not remap every old exported Ref.
- Duplicate disk identities now abort import. Copying an instance's meta
  without clearing Referent and UniqueId is not a safe clone operation.
