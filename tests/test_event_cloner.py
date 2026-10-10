"""Synthetic, license-safe tests for event bundle cloning."""
import tempfile
import unittest
from pathlib import Path

from ck3lib.composer import CompositionError, git_blob_sha
from ck3lib.event_cloner import clone, _analyze


SOURCE = '''# oldns.3 comment must not be modified
namespace = oldns

oldns.1 = {
    title = oldns.1.t
    desc = oldns.1.desc
    immediate = {
        trigger_event = { id = oldns.2 days = 1 }
        random_events = { 10 = oldns.2 20 = oldns.3 }
        events = { oldns.2 oldns.3 }
    }
}

character_event = {
    id = oldns.2
    desc = "ordinary text"
    immediate = { trigger_event = oldns.3 }
}

oldns.3 = { hidden = yes }
'''


class EventClonerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vanilla = self.root / 'game'
        (self.vanilla / 'events').mkdir(parents=True)
        self.source = self.vanilla / 'events/demo.txt'
        self.source.write_text(SOURCE, encoding='utf-8-sig')
        self.recipe = dict(version=1, source_path='events/demo.txt',
                           source_git_blob_sha=git_blob_sha(self.source.read_bytes()),
                           source_namespace='oldns', expected_event_ids=['oldns.1', 'oldns.2', 'oldns.3'],
                           namespace='demo', source_version_label='1.20.0.3')
        self.dest = self.root / 'out'

    def test_clones_all_defs_and_known_calls_preserves_comments_and_loc(self):
        report = clone(self.recipe, self.vanilla, self.dest)
        out = (self.dest / report['generated_event_file']).read_text(encoding='utf-8-sig')
        self.assertIn('namespace = cklib_demo_oldns', out)
        self.assertIn('cklib_demo_oldns.1 = {', out)
        self.assertIn('id = cklib_demo_oldns.2', out)
        self.assertIn('trigger_event = cklib_demo_oldns.3', out)
        self.assertIn('10 = cklib_demo_oldns.2', out)
        self.assertIn('events = { cklib_demo_oldns.2 cklib_demo_oldns.3 }', out)
        self.assertIn('title = oldns.1.t', out)
        self.assertIn('# oldns.3 comment', out)
        self.assertEqual(self.source.read_text(encoding='utf-8-sig'), SOURCE)
        self.assertFalse(report['is_complete_mod'])
        self.assertFalse(report['game_validated'])
        self.assertTrue((self.dest / 'event-clone-report.json').exists())
        self.assertEqual(len(report['id_map']), 3)

    def test_rerun_refuses_to_overwrite(self):
        clone(self.recipe, self.vanilla, self.dest)
        with self.assertRaises(CompositionError):
            clone(self.recipe, self.vanilla, self.dest)

    def test_hash_required_and_correct(self):
        self.recipe['source_git_blob_sha'] = '0' * 40
        with self.assertRaisesRegex(CompositionError, 'SHA mismatch'):
            clone(self.recipe, self.vanilla, self.dest)
        self.assertFalse(self.dest.exists())

    def test_full_inventory_required(self):
        self.recipe['expected_event_ids'] = ['oldns.1']
        with self.assertRaisesRegex(CompositionError, 'inventory'):
            clone(self.recipe, self.vanilla, self.dest)
        self.assertFalse(self.dest.exists())

    def test_bad_namespace(self):
        self.recipe['namespace'] = '../escape'
        with self.assertRaisesRegex(CompositionError, 'Namespace'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_output_cannot_be_in_source(self):
        with self.assertRaisesRegex(CompositionError, 'overlaps'):
            clone(self.recipe, self.vanilla, self.vanilla / 'mods-out')

    def test_missing_event_reference_fail_closed(self):
        self.source.write_text(SOURCE.replace('oldns.2 days', 'oldns.99 days'), encoding='utf-8-sig')
        self.recipe['source_git_blob_sha'] = git_blob_sha(self.source.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'absent'):
            clone(self.recipe, self.vanilla, self.dest)
        self.assertFalse(self.dest.exists())

    def test_unsupported_expression_fail_closed(self):
        self.source.write_text(SOURCE.replace('title = oldns.1.t', 'effect = oldns.3'), encoding='utf-8-sig')
        self.recipe['source_git_blob_sha'] = git_blob_sha(self.source.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'Unsupported event reference'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_quoted_event_reference_fail_closed(self):
        self.source.write_text(SOURCE.replace('"ordinary text"', '"oldns.3"'), encoding='utf-8-sig')
        self.recipe['source_git_blob_sha'] = git_blob_sha(self.source.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'Quoted legacy'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_duplicate_event_id_detected(self):
        data = SOURCE + '\noldns.2 = { hidden = yes }\n'
        self.source.write_text(data, encoding='utf-8-sig')
        self.recipe['source_git_blob_sha'] = git_blob_sha(self.source.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'Duplicate'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_unrecognized_top_level_helpers_not_copied(self):
        data = SOURCE + '\nscripted_trigger test = { always = yes }\n'
        self.source.write_text(data, encoding='utf-8-sig')
        self.recipe['source_git_blob_sha'] = git_blob_sha(self.source.read_bytes())
        with self.assertRaises(CompositionError):
            clone(self.recipe, self.vanilla, self.dest)

    def test_target_namespace_collision(self):
        (self.vanilla / 'events/other.txt').write_text('namespace = cklib_demo_oldns\n')
        with self.assertRaisesRegex(CompositionError, 'collides'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_no_symlink_escape(self):
        self.source.unlink()
        outside = self.root / 'outside.txt'
        outside.write_text(SOURCE)
        self.source.symlink_to(outside)
        self.recipe['source_git_blob_sha'] = git_blob_sha(outside.read_bytes())
        with self.assertRaises(CompositionError):
            clone(self.recipe, self.vanilla, self.dest)

    def test_reject_symlink_within_source_root(self):
        other = self.vanilla / 'events/real.txt'
        other.write_text(SOURCE, encoding='utf-8-sig')
        self.source.unlink()
        self.source.symlink_to(other)
        self.recipe['source_git_blob_sha'] = git_blob_sha(other.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'Symlinked'):
            clone(self.recipe, self.vanilla, self.dest)

    def test_cloned_event_does_not_touch_other_event_files(self):
        untouched = self.vanilla / 'events/another.txt'
        untouched.write_text('namespace = another\nanother.1 = { hidden = yes }')
        before = untouched.read_bytes()
        clone(self.recipe, self.vanilla, self.dest)
        self.assertEqual(untouched.read_bytes(), before)

    def test_typed_event_only(self):
        data = 'namespace = oldns\ncharacter_event = { id = oldns.7 immediate = { trigger_event = oldns.7 } }\n'
        result, mapping, refs = _analyze(data, 'oldns', ['oldns.7'], 'cklib_demo_oldns')
        self.assertEqual(mapping['oldns.7'], 'cklib_demo_oldns.7')
        self.assertIn('trigger_event = cklib_demo_oldns.7', result)


if __name__ == '__main__':
    unittest.main()
