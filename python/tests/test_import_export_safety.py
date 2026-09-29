"""Regression coverage for destructive import/export decisions."""
import base64
import json
import struct
import xml.etree.ElementTree as ET

import pytest
import build
import extract


def place(tmp_path, items):
    p = tmp_path / 'place.rbxlx'
    p.write_text('<roblox version="4">' + items + '</roblox>', encoding='utf-8')
    return p


def item(name, cls='Folder', source=''):
    return f'<Item class="{cls}" referent="{name}"><Properties><string name="Name">{name}</string><ProtectedString name="Source">{source}</ProtectedString></Properties></Item>'


def test_scripts_only_never_deletes_non_scripts(tmp_path):
    p = place(tmp_path, item('Workspace', source='')[:-7] + item('KeepMe', 'Part') + item('Code', 'Script', 'old') + '</Item>')
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder))
    (folder / 'Workspace' / 'Code.lua').write_text('new', encoding='utf-8')
    build.import_rbxlx(str(folder), str(p), force=True)
    root = ET.parse(p)
    assert root.find('.//Item[@referent="KeepMe"]') is not None
    assert root.find('.//Item[@referent="Code"]/Properties/ProtectedString').text == 'new'


def test_export_retains_unvisited_numeric_siblings(tmp_path):
    p = place(tmp_path, item('Code', 'Script', 'new'))
    folder = tmp_path / 'code'
    folder.mkdir()
    extra = folder / 'Code_2.lua'
    extra.write_text('local edits', encoding='utf-8')
    extract.extract(str(p), str(folder))
    assert extra.read_text() == 'local edits'


def test_import_keeps_bare_numeric_siblings(tmp_path):
    p = place(tmp_path, '')
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Code.lua').write_text('one')
    (folder / 'Code_2.lua').write_text('two')
    build.import_rbxlx(str(folder), str(p), force=True, no_delete=True, no_rename=True)
    assert {x.text for x in ET.parse(p).findall('.//ProtectedString')} == {'one', 'two'}


def test_unreadable_source_aborts_before_place_write(tmp_path):
    p = place(tmp_path, item('Code', 'Script', 'keep'))
    original = p.read_bytes()
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Code.lua').write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError):
        build.import_rbxlx(str(folder), str(p), force=True)
    assert p.read_bytes() == original


def test_rebuild_preserves_document_tables(tmp_path):
    p = place(tmp_path, '<Meta name="ExplicitAutoJoints">true</Meta><SharedStrings><SharedString md5="abc">eA==</SharedString></SharedStrings>' + item('Code', 'Script', 'x'))
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder), scripts_only=False)
    out = tmp_path / 'rebuilt.rbxlx'
    build.build_rbxlx(str(folder), str(out))
    assert ET.parse(out).find('./SharedStrings/SharedString').text == 'eA=='
    assert ET.parse(out).find('./Meta').text == 'true'


def test_unknown_attributes_survive_export_rebuild(tmp_path):
    raw = struct.pack('<II', 2, 1) + b'a\xffunrecognized-data'
    encoded = base64.b64encode(raw).decode()
    p = place(tmp_path, '<Item class="Part"><Properties><string name="Name">Part</string><BinaryString name="AttributesSerialize">' + encoded + '</BinaryString></Properties></Item>')
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder), scripts_only=False)
    out = tmp_path / 'rebuilt.rbxlx'
    build.build_rbxlx(str(folder), str(out))
    assert ET.parse(out).find('.//BinaryString[@name="AttributesSerialize"]').text == encoded


def test_empty_tags_override_old_serialized_tags():
    root = ET.Element('Item')
    build.add_properties(root, {'Tags': [], 'Properties': {'Tags': {'type': 'BinaryString', 'value': 'b2xk'}}})
    assert root.find('.//*[@name="Tags"]') is None


def test_name_edit_overrides_structured_old_name():
    root = ET.Element('Item')
    build.add_properties(root, {'Name': 'New', 'Properties': {'Name': {'type': 'string', 'value': 'Old'}}})
    assert root.find('.//*[@name="Name"]').text == 'New'


def test_full_export_clears_previous_scope(tmp_path):
    p = place(tmp_path, item('Code', 'Script', 'x'))
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder))
    assert json.loads((folder / '.verde/partial.json').read_text())['scripts_only']
    extract.extract(str(p), str(folder), scripts_only=False)
    assert not (folder / '.verde/partial.json').exists()


def test_partial_meta_update_preserves_existing_source():
    root = ET.fromstring(item('Code', 'Script', 'keep'))
    build._apply_meta_to_item(root, {'Name': 'Renamed'})
    assert root.find('.//*[@name="Source"]').text == 'keep'


def test_default_import_preserves_original_pruning_behavior(tmp_path):
    p = place(tmp_path, item('Workspace')[:-7] + item('KeepMe', 'Part') + item('Code', 'Script', 'x') + '</Item>')
    folder = tmp_path / 'code'
    (folder / 'Workspace').mkdir(parents=True)
    (folder / 'Workspace/.robloxmeta.json').write_text(json.dumps({'ClassName': 'Folder', 'Name': 'Workspace'}))
    (folder / 'Workspace/Code.lua').write_text('x')
    build.import_rbxlx(str(folder), str(p), force=True)
    assert ET.parse(p).find('.//Item[@referent="KeepMe"]') is None


@pytest.mark.parametrize('no_rename,no_delete,old_survives', [(True, False, True), (False, True, False)])
def test_rename_and_delete_flags_keep_original_independent_controls(tmp_path, no_rename, no_delete, old_survives):
    p = place(tmp_path, item('Old', 'Script', 'same'))
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'New.lua').write_text('same')
    build.import_rbxlx(str(folder), str(p), force=True, no_delete=no_delete, no_rename=no_rename)
    assert (ET.parse(p).find('.//Item[@referent="Old"]') is not None) == old_survives


def test_explicit_delete_still_prunes_scripts_not_parts(tmp_path):
    p = place(tmp_path, item('Workspace')[:-7] + item('KeepMe', 'Part') + item('Old', 'Script', 'old') + item('Code', 'Script', 'x') + '</Item>')
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder))
    for f in (folder / 'Workspace').glob('Old*'):
        f.unlink()
    build.import_rbxlx(str(folder), str(p), force=True, no_delete=False)
    assert ET.parse(p).find('.//Item[@referent="Old"]') is None
    assert ET.parse(p).find('.//Item[@referent="KeepMe"]') is not None


def test_corrupt_scope_aborts_without_writing(tmp_path):
    p = place(tmp_path, item('Code', 'Script', 'keep'))
    before = p.read_bytes()
    folder = tmp_path / 'code'
    (folder / '.verde').mkdir(parents=True)
    (folder / '.verde/partial.json').write_text('bad json')
    (folder / 'Code.lua').write_text('new')
    with pytest.raises(ValueError, match='Cannot safely read import scope'):
        build.import_rbxlx(str(folder), str(p), force=True)
    assert p.read_bytes() == before


def test_failed_xml_write_keeps_original_place(tmp_path, monkeypatch):
    p = place(tmp_path, item('Code', 'Script', 'keep'))
    before = p.read_bytes()
    tree = ET.parse(p)
    def fail(stream, **kwargs):
        stream.write(b'partial')
        raise OSError('disk write failed')
    monkeypatch.setattr(tree, 'write', fail)
    with pytest.raises(OSError):
        build._write_place(tree, p)
    assert p.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))


def test_corrupt_meta_aborts_import(tmp_path):
    p = place(tmp_path, item('Code', 'Script', 'keep'))
    before = p.read_bytes()
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Code.robloxmeta.json').write_text('invalid')
    (folder / 'Code.lua').write_text('new')
    with pytest.raises(ValueError, match='Cannot read metadata'):
        build.import_rbxlx(str(folder), str(p), force=True)
    assert p.read_bytes() == before


def test_bridge_acknowledgement_does_not_clean_other_files(tmp_path):
    from features.bridge import BridgeState
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Good.lua').write_text('one')
    (folder / 'Failed.lua').write_text('two')
    state = BridgeState(folder)
    assert state.refresh_dirty() == {'Good.lua', 'Failed.lua'}
    state.mark_applied(['Good.lua'])
    assert state.refresh_dirty() == {'Failed.lua'}
    assert state.pending_to_studio == {'Failed.lua'}
    restarted = BridgeState(folder)
    assert restarted.refresh_dirty() == {'Failed.lua'}


def test_studio_push_does_not_clean_unapplied_disk_changes(tmp_path):
    from features.bridge import BridgeState
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Pending.lua').write_text('disk edit')
    state = BridgeState(folder)
    assert state.write_file('Other.lua', 'Studio edit')
    assert state.refresh_dirty() == {'Pending.lua'}


def test_stable_unique_id_wins_over_reused_referent(tmp_path):
    p = place(tmp_path, '<Item class="Script" referent="REUSED"><Properties><string name="Name">Wrong</string><UniqueId name="UniqueId">other</UniqueId><ProtectedString name="Source">keep</ProtectedString></Properties></Item><Item class="Script" referent="CURRENT"><Properties><string name="Name">Right</string><UniqueId name="UniqueId">stable</UniqueId><ProtectedString name="Source">old</ProtectedString></Properties></Item>')
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'Right.lua').write_text('new')
    (folder / 'Right.robloxmeta.json').write_text(json.dumps({'ClassName': 'Script', 'Name': 'Right', 'Referent': 'REUSED', 'Properties': {'UniqueId': {'type': 'UniqueId', 'value': 'stable'}}}))
    build.import_rbxlx(str(folder), str(p), force=True, no_delete=True)
    root = ET.parse(p)
    assert root.find('.//Item[@referent="REUSED"]/Properties/ProtectedString').text == 'keep'
    assert root.find('.//Item[@referent="CURRENT"]/Properties/ProtectedString').text == 'new'


def test_selective_root_keeps_ancestry_for_import(tmp_path):
    p = place(tmp_path, item('Workspace')[:-7] + item('Model')[:-7] + item('Code', 'Script', 'old') + '</Item></Item>')
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder), root_filter='Workspace.Model')
    script = folder / 'Workspace/Model/Code.lua'
    assert script.is_file()
    script.write_text('new')
    build.import_rbxlx(str(folder), str(p), force=True)
    assert ET.parse(p).find('.//Item[@referent="Code"]/Properties/ProtectedString').text == 'new'


def test_bridge_never_uses_parent_meta_for_bare_script(tmp_path):
    from features.bridge import BridgeState, make_handler
    (tmp_path / '.robloxmeta.json').write_text(json.dumps({'ClassName': 'Folder', 'Name': 'Parent', 'Referent': 'parent-id'}))
    cls = make_handler(BridgeState(tmp_path))
    handler = cls.__new__(cls)
    handler.path = '/meta?path=Code.lua'
    replies = []
    handler._json = lambda code, data: replies.append((code, data))
    handler.do_GET()
    assert replies[0][0] == 404


def test_bridge_meta_prefers_script_companion_with_local_identity(tmp_path):
    from features.bridge import BridgeState, make_handler
    (tmp_path / 'Code.module.robloxmeta.json').write_text(json.dumps({'ClassName': 'ModuleScript', 'Name': 'Code'}))
    (tmp_path / 'Code.module.robloxmeta.local.json').write_text(json.dumps({'Referent': 'script-id'}))
    cls = make_handler(BridgeState(tmp_path))
    handler = cls.__new__(cls)
    handler.path = '/meta?path=Code.module.lua'
    replies = []
    handler._json = lambda code, data: replies.append((code, data))
    handler.do_GET()
    assert replies[0] == (200, {'ClassName': 'ModuleScript', 'Name': 'Code', 'Referent': 'script-id'})


def test_bridge_events_include_pending_after_cursor_advances(tmp_path):
    from features.bridge import BridgeState, make_handler
    (tmp_path / 'Code.lua').write_text('pending')
    state = BridgeState(tmp_path)
    state.refresh_dirty()
    cls = make_handler(state)
    handler = cls.__new__(cls)
    handler.path = f'/events?since={state.last_event_id}'
    replies = []
    handler._json = lambda code, data: replies.append((code, data))
    handler.do_GET()
    assert replies[0][1]['events'] == []
    assert replies[0][1]['pending'] == ['Code.lua']


def test_import_detects_ai_edit_with_preserved_old_timestamp(tmp_path):
    import os
    p = place(tmp_path, item('Code', 'Script', 'old'))
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder))
    script = folder / 'Code.lua'
    old_time = script.stat().st_mtime
    script.write_text('AI edited source')
    os.utime(script, (old_time, old_time))
    os.utime(p, (old_time + 100, old_time + 100))
    build.import_rbxlx(str(folder), str(p))
    assert ET.parse(p).find('.//ProtectedString[@name="Source"]').text == 'AI edited source'


def test_live_bridge_detects_hash_change_older_than_place(tmp_path):
    import os
    from features.bridge import BridgeState
    from features.sync import write_manifest
    p = place(tmp_path, '')
    folder = tmp_path / 'code'
    folder.mkdir()
    script = folder / 'Code.lua'
    script.write_text('old')
    os.utime(script, (1, 1))
    write_manifest(folder, rbxlx_path=p)
    state = BridgeState(folder)
    script.write_text('AI edit')
    os.utime(script, (1, 1))
    assert state.refresh_dirty() == {'Code.lua'}


def test_merge_timestamp_policy_remains_explicit(tmp_path):
    import os
    from features.sync import is_file_dirty, load_manifest, write_manifest
    p = place(tmp_path, '')
    script = tmp_path / 'Code.lua'
    script.write_text('old')
    os.utime(script, (1, 1))
    write_manifest(tmp_path, rbxlx_path=p)
    manifest = load_manifest(tmp_path)
    script.write_text('new')
    os.utime(script, (1, 1))
    assert not is_file_dirty(tmp_path, 'Code.lua', manifest)
    assert is_file_dirty(tmp_path, 'Code.lua', manifest, mtime_win=False)


def test_full_rebuild_preserves_mixed_child_order(tmp_path):
    p = place(tmp_path, item('ZFolder')[:-7] + item('ZCode', 'ModuleScript', 'z') + item('APart', 'Part') + item('ACode', 'Script', 'a') + '</Item>' + item('ARoot', 'Part'))
    folder = tmp_path / 'code'
    extract.extract(str(p), str(folder), scripts_only=False)
    out = tmp_path / 'rebuilt.rbxlx'
    build.build_rbxlx(str(folder), str(out))
    root = ET.parse(out).getroot()
    assert [build.resolve_item_name(c) for c in root if c.tag == 'Item'] == ['ZFolder', 'ARoot']
    zfolder = root.find('./Item')
    assert [build.resolve_item_name(c) for c in zfolder if c.tag == 'Item'] == ['ZCode', 'APart', 'ACode']
    assert root.find('.//*[@name="_VerdeOrder"]') is None


def test_versioned_acknowledgement_rejects_edit_after_read(tmp_path):
    import hashlib
    from features.bridge import BridgeState
    p = tmp_path / 'Code.lua'
    p.write_text('read by Studio')
    state = BridgeState(tmp_path)
    revision = hashlib.sha256(p.read_bytes()).hexdigest()
    p.write_text('newer disk edit')
    state.mark_applied(['Code.lua'], versions={'Code.lua': revision})
    assert state.refresh_dirty() == {'Code.lua'}
    assert 'Code.lua' in state.pending_to_studio
    revision = hashlib.sha256(p.read_bytes()).hexdigest()
    state.mark_applied(['Code.lua'], versions={'Code.lua': revision})
    assert state.refresh_dirty() == set()


def test_file_envelope_preserves_json_shaped_source_and_revision(tmp_path):
    import hashlib
    from features.bridge import BridgeState, make_handler
    raw = b'"a Lua string"'
    (tmp_path / 'Code.lua').write_bytes(raw)
    cls = make_handler(BridgeState(tmp_path))
    handler = cls.__new__(cls)
    handler.path = '/file?envelope=1&path=Code.lua'
    replies = []
    handler._json = lambda code, data: replies.append((code, data))
    handler.do_GET()
    assert replies[0] == (200, {'content': raw.decode(), 'revision': hashlib.sha256(raw).hexdigest()})


@pytest.mark.parametrize('identity', ['Referent', 'UniqueId'])
def test_duplicate_disk_identity_aborts_instead_of_ignoring_files(tmp_path, identity):
    p = place(tmp_path, item('Original', 'Script', 'keep'))
    before = p.read_bytes()
    folder = tmp_path / 'code'
    folder.mkdir()
    for name in ['First', 'Second']:
        meta = {'ClassName': 'Script', 'Name': name}
        if identity == 'Referent':
            meta['Referent'] = 'same'
        else:
            meta['Properties'] = {'UniqueId': {'type': 'UniqueId', 'value': 'same'}}
        (folder / f'{name}.robloxmeta.json').write_text(json.dumps(meta))
        (folder / f'{name}.lua').write_text(name)
    with pytest.raises(ValueError, match=f'Duplicate {identity}'):
        build.import_rbxlx(str(folder), str(p), force=True)
    assert p.read_bytes() == before


def test_empty_source_is_not_a_rename_match_for_nonempty_source(tmp_path):
    p = place(tmp_path, item('Old', 'Script', ''))
    folder = tmp_path / 'code'
    folder.mkdir()
    (folder / 'New.lua').write_text('new content')
    build.import_rbxlx(str(folder), str(p), force=True, no_delete=True)
    assert ET.parse(p).find('.//Item[@referent="Old"]') is not None


def test_studio_meta_push_retains_offline_properties_and_order(tmp_path):
    from features.bridge import BridgeState
    path = tmp_path / 'Code.robloxmeta.json'
    path.write_text(json.dumps({'ClassName': 'Script', '_VerdeOrder': 4, 'Properties': {'UniqueId': {'type': 'UniqueId', 'value': 'stable'}, 'Enabled': {'type': 'bool', 'value': 'false'}}}))
    state = BridgeState(tmp_path)
    assert state.write_file(path.name, json.dumps({'ClassName': 'Script', 'Referent': 'live-id', 'Tags': [], 'Attributes': {}, 'Properties': {'Enabled': {'type': 'bool', 'value': True}}}))
    meta = json.loads(path.read_text())
    assert meta['_VerdeOrder'] == 4
    assert meta['Properties']['UniqueId']['value'] == 'stable'
    assert meta['Properties']['Enabled']['value'] is True
    assert 'Referent' not in meta


def test_invalid_studio_meta_push_does_not_overwrite_existing_meta(tmp_path):
    from features.bridge import BridgeState
    path = tmp_path / 'Code.robloxmeta.json'
    path.write_text('{"ClassName": "Script"}')
    original = path.read_bytes()
    state = BridgeState(tmp_path)
    assert not state.write_file(path.name, 'bad JSON')
    assert path.read_bytes() == original
