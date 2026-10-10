"""Integration review plans use synthetic data and do not write to CK3 sources."""
import json
from pathlib import Path
import tempfile
import unittest

from ck3lib.indexer import scan
from ck3lib.planner import assess, main


class PlannerTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.vanilla = self.root / 'game'
        self.vanilla.mkdir()

    def write(self, path, text):
        out = self.vanilla / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding='utf-8')
        return out

    def test_reports_indirect_provenance(self):
        self.write('common/activities/activity_types/test.txt', 'activity_x = { trigger_event = fake.001 }')
        self.write('events/test.txt', 'character_event = { id = fake.001 trigger_event = fake.002 }')
        self.write('events/second.txt', 'character_event = { id = fake.002 }')
        report = assess(scan(self.vanilla), 'activity:activity_x')
        self.assertEqual(report['status'], 'REVIEW_REQUIRED')
        self.assertEqual(report['summary']['unresolved'], 0)
        self.assertIn('event:fake.002', report['dependency_nodes'])
        self.assertIn('events/second.txt', [r['path'] for r in report['referenced_files']])
        self.assertTrue(all(f['read_only'] for f in report['referenced_files']))
        self.assertFalse(report['generates_mod'])

    def test_missing_reference_never_declares_safe(self):
        self.write('common/activities/activity_types/test.txt', 'activity_x = { trigger_event = fake.001 }')
        report = assess(scan(self.vanilla), 'activity:activity_x')
        self.assertEqual(report['status'], 'STATIC_BLOCKERS_OR_GAPS')
        self.assertEqual(report['unresolved'][0]['identifier'], 'fake.001')

    def test_duplicate_warning_scoped_to_component(self):
        self.write('common/activities/activity_types/a.txt', 'activity_x = {}')
        self.write('common/activities/activity_types/b.txt', 'activity_x = {}')
        self.write('common/holdings/other.txt', 'castle_holding = {}')
        report = assess(scan(self.vanilla), 'activity:activity_x')
        self.assertTrue(any(x['reason'] == 'duplicate_identifier' for x in report['warnings']))
        self.assertEqual(report['status'], 'STATIC_BLOCKERS_OR_GAPS')
        unrelated = assess(scan(self.vanilla), 'holding:castle_holding')
        self.assertFalse(any(x['reason'] == 'duplicate_identifier' for x in unrelated['warnings']))

    def test_rejects_bad_graph_and_component(self):
        graph = scan(self.vanilla)
        with self.assertRaisesRegex(ValueError, 'not indexed'):
            assess(graph, 'event:not_found')
        graph['schema_version'] = 55
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            assess(graph, 'event:not_found')

    def test_cli_no_overwrite_source_or_existing_output(self):
        self.write('common/activities/activity_types/test.txt', 'activity_x = {}')
        graph_file = self.root / 'graph.json'
        graph_file.write_text(json.dumps(scan(self.vanilla)))
        out = self.root / 'plan.json'
        main(['--graph', str(graph_file), '--component', 'activity:activity_x', '--output', str(out)])
        self.assertFalse(json.loads(out.read_text())['game_validated'])
        with self.assertRaises(SystemExit):
            main(['--graph', str(graph_file), '--component', 'activity:activity_x', '--output', str(out)])
        with self.assertRaises(SystemExit):
            main(['--graph', str(graph_file), '--component', 'activity:activity_x', '--output', str(graph_file)])


if __name__ == '__main__':
    unittest.main()
