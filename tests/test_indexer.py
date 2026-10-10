"""Hermetic tests: no Paradox source or assets are redistributed."""
import json
import tempfile
import unittest
from pathlib import Path

from ck3lib.indexer import scan, transitive_dependencies, main


class IndexerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.vanilla = self.root / "game"
        self.vanilla.mkdir()

    def write(self, rel, data):
        file = self.vanilla / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data, encoding="utf-8-sig")
        return file

    def fixture(self):
        self.write("common/governments/00_gov.txt", '''
clan_government = {
    house_unity = clan_house_unity
    tax_slot_type = clan_tax_slot
    flags = { government_is_clan government_has_tax_slot }
}
''')
        self.write("common/house_unities/00_house.txt", 'clan_house_unity = { default_value = 60 }')
        self.write("common/tax_slots/types/00_tax.txt", 'clan_tax_slot = { tax_slot_vassal_limit = { value = 12 } }')
        self.write("common/activities/activity_types/party.txt", '''
# trigger_event = bad.1
activity_camp_party = {
    is_shown = { has_government = clan_government }
    can_start = { government_has_flag = government_has_tax_slot }
    phases = { intro = { on_phase_active = {
        trigger_event = { id = demo.001 days = 1 }
        trigger_event = demo.002
        trigger_event = { id = demo.999 } # missing on purpose
        trigger_event = { id = "gfx/interface/ignored.dds" }
        trigger_event = { id = demo.001 }
        test_scripted_effect = yes
    } } }
    illustration = "gfx/interface/party.dds"
    tooltip = party_tooltip
}
''')
        self.write("events/test_events.txt", '''
namespace = demo
character_event = { id = demo.001 desc = party_tooltip }
character_event = { id = demo.002 }
''')
        self.write("common/scripted_effects/test.txt", 'test_scripted_effect = { add_gold = 5 }')
        self.write("localization/english/party_l_english.yml", 'l_english:\n party_tooltip:0 "Text"\n')
        self.write("gui/party.gui", 'windowType = { name = "party_window" iconType = { name = "party_icon" sprite = "GFX_party" } }')
        self.write("gfx/interface/party.gfx", 'spriteTypes = { spriteType = { name = "GFX_party" texturefile = "gfx/interface/party.dds" } }')
        gfx = self.vanilla / "gfx/interface/party.dds"
        gfx.write_bytes(b"FAKE_TEST_ONLY")

    def test_government_declares_and_references(self):
        self.fixture()
        graph = scan(self.vanilla, version="synthetic")
        pairs = {(e['source'], e['target'], e['relation']) for e in graph['edges']}
        self.assertIn(('government:clan_government', 'house_unity:clan_house_unity', 'references'), pairs)
        self.assertIn(('government:clan_government', 'tax_slot:clan_tax_slot', 'references'), pairs)
        self.assertIn(('government:clan_government', 'government_flag:government_has_tax_slot', 'declares_flag'), pairs)
        self.assertEqual(graph['status'], 'STATIC_PARTIAL_NOT_GAME_VALIDATED')

    def test_events_scripts_gui_gfx_localization(self):
        self.fixture()
        graph = scan(self.vanilla)
        pairs = {(e['source'], e['target'], e['relation']) for e in graph['edges']}
        src = 'activity:activity_camp_party'
        for target in ('event:demo.001', 'event:demo.002', 'government:clan_government', 'government_flag:government_has_tax_slot'):
            self.assertIn((src, target, 'references'), pairs)
        self.assertIn((src, 'scripted_effect:test_scripted_effect', 'calls_script'), pairs)
        self.assertIn((src, 'localization:party_tooltip', 'localizes'), pairs)
        self.assertIn((src, 'file:gfx/interface/party.dds', 'uses_asset'), pairs)
        ids = {n['id'] for n in graph['nodes']}
        self.assertIn('gui:party_window', ids)
        self.assertIn('gui:party_icon', ids)
        self.assertIn('sprite:GFX_party', ids)
        self.assertIn(('gui:party_icon', 'sprite:GFX_party', 'references'), pairs)
        missing = {(e['target_kind'], e['identifier']) for e in graph['unresolved']}
        self.assertIn(('event', 'demo.999'), missing)
        self.assertNotIn(('event', 'bad.1'), missing)
        self.assertNotIn(('event', 'gfx/interface/ignored.dds'), missing)

    def test_provenance_and_reverse_impact(self):
        self.fixture()
        graph = scan(self.vanilla)
        deps = transitive_dependencies(graph, 'activity:activity_camp_party')
        self.assertIn('tax_slot:clan_tax_slot', [r['node'] for r in deps['reachable']])
        self.assertIn('government:clan_government', [r['node'] for r in deps['reachable']])
        impacted = transitive_dependencies(graph, 'tax_slot:clan_tax_slot', reverse=True)
        self.assertIn('activity:activity_camp_party', [r['node'] for r in impacted['reachable']])
        direct = transitive_dependencies(graph, 'activity:activity_camp_party', max_depth=1)
        self.assertNotIn('tax_slot:clan_tax_slot', [r['node'] for r in direct['reachable']])
        edge = next(e for e in graph['edges'] if e['source'] == 'government:clan_government' and e['target'] == 'tax_slot:clan_tax_slot')
        self.assertTrue(edge['evidence']['path'].endswith('00_gov.txt'))
        self.assertGreater(edge['evidence']['line'], 0)

    def test_duplicate_identifier_warning(self):
        self.write('common/holdings/00_a.txt', 'castle_holding = { }')
        self.write('common/holdings/01_b.txt', 'castle_holding = { }')
        graph = scan(self.vanilla)
        self.assertEqual(1, len([x for x in graph['warnings'] if x['reason'] == 'duplicate_identifier']))
        node = next(n for n in graph['nodes'] if n['id'] == 'holding:castle_holding')
        self.assertEqual(2, len(node['definitions']))

    def test_braces_comments_strings_and_unsupported_syntax(self):
        self.write('common/activities/activity_types/example.txt', '''
activity_example = {
    tooltip = "not a = { real } # reference"
    block = { value >= 2 other ?= yes }
    # hidden = { strange = yes }
}
''')
        graph = scan(self.vanilla)
        self.assertIn('activity:activity_example', {n['id'] for n in graph['nodes']})
        self.assertNotIn('parse_failure', [w['reason'] for w in graph['warnings']])

    def test_malformed_file_uses_warning_without_stopping(self):
        self.write('common/governments/broken.txt', 'bad_government = {')
        self.write('common/holdings/valid.txt', 'castle_holding = { }')
        graph = scan(self.vanilla)
        self.assertIn('holding:castle_holding', {n['id'] for n in graph['nodes']})
        self.assertTrue(any(x['reason'] == 'parse_failure' for x in graph['warnings']))

    def test_wrong_encoding_skipped(self):
        p = self.vanilla / 'common/governments/binary.txt'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'\xff\xfe\x00')
        graph = scan(self.vanilla)
        self.assertEqual(graph['warnings'][0]['reason'], 'not_utf8')

    def test_graph_output_has_no_proprietary_bodies(self):
        self.fixture()
        graph = scan(self.vanilla)
        text = json.dumps(graph)
        self.assertNotIn('FAKE_TEST_ONLY', text)
        self.assertNotIn('Text"', text)
        self.assertIn('sha256', text)

    def test_output_protection_and_existing_file(self):
        self.fixture()
        within = self.vanilla / 'graphs/out.json'
        with self.assertRaises(SystemExit):
            main(['--vanilla-root', str(self.vanilla), '--output', str(within)])
        self.assertFalse(within.exists())
        outside = self.root / 'out.json'
        main(['--vanilla-root', str(self.vanilla), '--output', str(outside), '--version', 'fixture', '--query', 'activity:activity_camp_party'])
        self.assertTrue(outside.is_file())
        report = json.loads(outside.read_text())
        self.assertIn('query', report)
        with self.assertRaises(SystemExit):
            main(['--vanilla-root', str(self.vanilla), '--output', str(outside)])
        with self.assertRaises(SystemExit):
            main(['--vanilla-root', str(self.vanilla), '--output', str(self.root / 'second.json'), '--depth', '-1'])

    def test_unavailable_symbol(self):
        with self.assertRaisesRegex(ValueError, 'not indexed'):
            transitive_dependencies({'nodes': [], 'edges': []}, 'government:unknown')

    def test_symlink_source_is_skipped(self):
        external = self.root / 'external.txt'
        external.write_text('evil = {}')
        target = self.vanilla / 'common/holdings/link.txt'
        target.parent.mkdir(parents=True)
        try:
            target.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink unsupported on this host')
        graph = scan(self.vanilla)
        self.assertNotIn('holding:evil', {n['id'] for n in graph['nodes']})

    def test_large_synthetic_file_completes(self):
        content = "\n".join(f"test_activity_{i} = {{ max_province_icons = {i % 5} }}" for i in range(2000))
        self.write('common/activities/activity_types/many.txt', content)
        graph = scan(self.vanilla)
        self.assertEqual(2000, len([x for x in graph['nodes'] if x['kind'] == 'activity']))

    def test_size_guard(self):
        self.write('common/governments/huge.txt', 'government_test = {}')
        graph = scan(self.vanilla, max_file_bytes=3)
        self.assertIn('exceeds_size_limit', [w['reason'] for w in graph['warnings']])


if __name__ == '__main__':
    unittest.main()
