"""Adapter v0.4 tests: synthetic CK3 only, no proprietary material."""
import json
from pathlib import Path
import tempfile
import unittest

from ck3lib.indexer import scan
from ck3lib.adapters import _fingerprint, make_recipe, prepare, main


class AdapterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vanilla = self.root / 'game'
        self.vanilla.mkdir()

    def write(self, path, content):
        file = self.vanilla / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')
        return file

    def fixture(self):
        self.write('common/activities/activity_types/sample.txt',
                   'activity_x = { trigger_event = demo.1 illustration = "gfx/interface/example.dds" }')
        self.write('events/sample.txt', 'character_event = { id = demo.1 }')
        self.write('gfx/interface/example.dds', 'binary-fixture-not-real-gfx')
        graph = scan(self.vanilla, version='synthetic')
        recipe = {'version': 1, 'component': 'activity:activity_x', 'namespace': 'sample',
                  'graph_sha256': _fingerprint(graph), 'default_dependency_policy': 'reference',
                  'decisions': {}}
        return graph, recipe

    def test_dryrun_references_vanilla_and_clones_root(self):
        graph, recipe = self.fixture()
        plan = prepare(graph, recipe)
        names = {x['source']: x for x in plan['operations']}
        self.assertEqual(names['activity:activity_x']['proposed_identifier'], 'cklib_sample_activity_x')
        self.assertEqual(names['event:demo.1']['action'], 'reference')
        self.assertEqual(names['file:gfx/interface/example.dds']['action'], 'reference')
        self.assertFalse(plan['generates_mod'])
        self.assertFalse(plan['game_validated'])
        self.assertFalse(plan['changes_vanilla'])

    def test_namespace_remap_event_and_gfx(self):
        graph, recipe = self.fixture()
        recipe['decisions'] = {'event:demo.1': 'clone', 'file:gfx/interface/example.dds': 'clone'}
        plan = prepare(graph, recipe)
        names = {x['source']: x for x in plan['operations']}
        self.assertEqual(names['event:demo.1']['proposed_identifier'], 'cklib_sample_demo.1')
        self.assertEqual(names['file:gfx/interface/example.dds']['proposed_identifier'],
                         'gfx/interface/cklib_sample_example.dds')
        self.assertTrue(any('authorized asset' in c for c in names['file:gfx/interface/example.dds']['review_checks']))

    def test_proposed_clone_still_requires_manual_implementation(self):
        graph, recipe = self.fixture()
        recipe['decisions']['event:demo.1'] = 'clone'
        report = prepare(graph, recipe)
        self.assertTrue(any(x['requires_manual_implementation'] for x in report['operations']))
        self.assertNotEqual(report['status'], 'READY')

    def test_unknown_dependency_rejected(self):
        graph, recipe = self.fixture()
        recipe['decisions'] = {'event:other.2': 'clone'}
        with self.assertRaisesRegex(ValueError, 'out-of-closure'):
            prepare(graph, recipe)

    def test_root_policy_cannot_be_overridden(self):
        graph, recipe = self.fixture()
        recipe['decisions']['activity:activity_x'] = 'reference'
        with self.assertRaisesRegex(ValueError, 'out-of-closure'):
            prepare(graph, recipe)

    def test_stale_fingerprint_rejected(self):
        graph, recipe = self.fixture()
        graph['source_version_label'] = 'tampered'
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            prepare(graph, recipe)

    def test_rejects_unsafe_namespace(self):
        graph, recipe = self.fixture()
        recipe['namespace'] = '../bad'
        with self.assertRaisesRegex(ValueError, 'Namespace'):
            prepare(graph, recipe)

    def test_policy_fail_closed(self):
        graph, recipe = self.fixture()
        recipe['default_dependency_policy'] = 'clone'
        with self.assertRaisesRegex(ValueError, 'reference-by-default'):
            prepare(graph, recipe)
        recipe['default_dependency_policy'] = 'reference'
        recipe['decisions'] = {'event:demo.1': 'replace_vanilla'}
        with self.assertRaisesRegex(ValueError, 'Decisions'):
            prepare(graph, recipe)

    def test_rejects_extra_recipe_parameters(self):
        graph, recipe = self.fixture()
        recipe['override_vanilla'] = True
        with self.assertRaisesRegex(ValueError, 'six'):
            prepare(graph, recipe)

    def test_unresolved_reference_blocks_claim_of_safety(self):
        self.write('common/activities/activity_types/unknown.txt', 'activity_x = { trigger_event = missing.5 }')
        graph = scan(self.vanilla)
        recipe = {'version': 1, 'component': 'activity:activity_x', 'namespace': 'sample',
                  'graph_sha256': _fingerprint(graph), 'default_dependency_policy': 'reference', 'decisions': {}}
        report = prepare(graph, recipe)
        self.assertEqual(report['status'], 'STATIC_BLOCKERS_OR_GAPS')
        self.assertEqual(report['summary']['unresolved'], 1)

    def test_external_inbound_callsites_identified(self):
        self.write('common/activities/activity_types/a.txt', 'activity_a = { trigger_event = demo.1 }')
        self.write('common/activities/activity_types/b.txt', 'activity_b = { trigger_event = demo.1 }')
        self.write('events/sample.txt', 'character_event = { id = demo.1 }')
        graph = scan(self.vanilla)
        recipe = {'version': 1, 'component': 'activity:activity_a', 'namespace': 'sample',
                  'graph_sha256': _fingerprint(graph), 'default_dependency_policy': 'reference',
                  'decisions': {'event:demo.1': 'clone'}}
        report = prepare(graph, recipe)
        self.assertTrue(report['inbound_cloned_references'])
        self.assertTrue(any(x['reason'] == 'incoming_vanilla_references_require_review' for x in report['failures']))

    def test_init_recipe_command(self):
        graph, _ = self.fixture()
        g = self.root / 'graph.json'
        r = self.root / 'recipe.json'
        g.write_text(json.dumps(graph))
        main(['--graph', str(g), '--init-recipe', '--component', 'activity:activity_x',
              '--namespace', 'sample', '--output', str(r), '--vanilla-root', str(self.vanilla)])
        actual = json.loads(r.read_text())
        self.assertEqual(actual, make_recipe(graph, 'activity:activity_x', 'sample'))
        self.assertEqual(prepare(graph, actual)['summary']['clones_requested'], 1)

    def test_cli_creates_only_new_report(self):
        graph, recipe = self.fixture()
        g = self.root / 'graph.json'
        r = self.root / 'recipe.json'
        o = self.root / 'output.json'
        g.write_text(json.dumps(graph))
        r.write_text(json.dumps(recipe))
        main(['--graph', str(g), '--recipe', str(r), '--output', str(o), '--vanilla-root', str(self.vanilla)])
        self.assertFalse(json.loads(o.read_text())['generates_mod'])
        with self.assertRaises(SystemExit):
            main(['--graph', str(g), '--recipe', str(r), '--output', str(o), '--vanilla-root', str(self.vanilla)])
        with self.assertRaises(SystemExit):
            main(['--graph', str(g), '--recipe', str(r), '--output', str(g), '--vanilla-root', str(self.vanilla)])
        with self.assertRaises(SystemExit):
            main(['--graph', str(g), '--recipe', str(r), '--output', str(self.vanilla / 'report.json'), '--vanilla-root', str(self.vanilla)])


if __name__ == '__main__':
    unittest.main()
