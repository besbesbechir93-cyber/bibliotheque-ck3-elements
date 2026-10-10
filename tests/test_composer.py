import tempfile
import unittest
from pathlib import Path
from ck3lib.composer import CompositionError, compose, git_blob_sha

SAMPLE = '''# activity_camp_party = { ignored = yes }
activity_camp_party = {
    cooldown = { years = 3 }
    max_province_icons = 1
    is_shown = { always = yes }
    can_start = { NOT = { is_activity_type_on_cooldown = activity_camp_party } }
    phases = { intro = { on_start = { trigger_event = test.1 } } }
    illustration = "gfx/interface/demo.dds"
    tooltip = "activity_camp_party"
}
'''

class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vanilla = self.root / 'vanilla'
        self.out = self.root / 'mod'
        source = self.vanilla / 'common/activities/activity_types/camp_party.txt'
        source.parent.mkdir(parents=True)
        source.write_bytes(SAMPLE.encode('utf-8'))
        self.original = source.read_bytes()
        self.recipe = dict(schema_version=1, kind='activity_clone', source_version='fixture', source_id='activity_camp_party', target_id='cklib_activity_demo', source_path='common/activities/activity_types/camp_party.txt', source_git_blob_sha=git_blob_sha(self.original), overrides={'cooldown.years': 2, 'max_province_icons': 3})
    def test_clone_parameters_and_unchanged_source(self):
        report = compose(self.recipe, self.vanilla, self.out)
        result = (self.out / report['generated_activity']).read_text(encoding='utf-8-sig')
        self.assertIn('cklib_activity_demo = {', result)
        self.assertIn('cooldown = { years = 2 }', result)
        self.assertIn('max_province_icons = 3', result)
        self.assertIn('is_activity_type_on_cooldown = cklib_activity_demo', result)
        self.assertIn('# activity_camp_party', result)
        self.assertIn('tooltip = "activity_camp_party"', result)
        self.assertEqual(self.original, (self.vanilla / self.recipe['source_path']).read_bytes())
        self.assertIn('test.1', report['external_references_sample'])
        self.assertEqual(report['status'], 'STATIC_ONLY_NOT_GAME_VALIDATED')
    def test_hash_mismatch_fails_closed(self):
        self.recipe['source_git_blob_sha'] = 'a'*40
        with self.assertRaisesRegex(CompositionError, 'hash mismatch'):
            compose(self.recipe, self.vanilla, self.out)
        self.assertFalse(self.out.exists())
    def test_missing_override_fails_closed(self):
        self.recipe['overrides'] = {'sort_order': 10}
        with self.assertRaisesRegex(CompositionError, 'Expected one field'):
            compose(self.recipe, self.vanilla, self.out)
    def test_unsupported_override_fails_closed(self):
        self.recipe['overrides'] = {'on_start.add_gold': 999}
        with self.assertRaisesRegex(CompositionError, 'Unsupported override'):
            compose(self.recipe, self.vanilla, self.out)
    def test_invalid_output_under_vanilla(self):
        with self.assertRaisesRegex(CompositionError, 'Output must not'):
            compose(self.recipe, self.vanilla, self.vanilla / 'mod')
    def test_source_traversal_rejected(self):
        self.recipe['source_path'] = 'common/activities/activity_types/../../secret.txt'
        with self.assertRaises(CompositionError):
            compose(self.recipe, self.vanilla, self.out)
    def test_asset_clone(self):
        gfx = self.vanilla / 'gfx/interface/demo.dds'
        gfx.parent.mkdir(parents=True)
        gfx.write_bytes(b'dummy texture bytes')
        self.recipe['assets'] = [{'mode':'clone','source':'gfx/interface/demo.dds','target':'gfx/interface/cklib/demo.dds'}]
        report = compose(self.recipe, self.vanilla, self.out)
        result = (self.out / report['generated_activity']).read_text(encoding='utf-8-sig')
        self.assertIn('gfx/interface/cklib/demo.dds', result)
        self.assertEqual((self.out / 'gfx/interface/cklib/demo.dds').read_bytes(), b'dummy texture bytes')
        self.assertEqual(gfx.read_bytes(), b'dummy texture bytes')
    def test_duplicate_or_broken_root_fails(self):
        src = self.vanilla / self.recipe['source_path']
        src.write_text(SAMPLE + 'another_activity = { }', encoding='utf-8')
        self.recipe['source_git_blob_sha'] = git_blob_sha(src.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'exactly one'):
            compose(self.recipe, self.vanilla, self.out)
    def test_repeat_generation_requires_opt_in(self):
        compose(self.recipe, self.vanilla, self.out)
        with self.assertRaisesRegex(CompositionError, 'exists'):
            compose(self.recipe, self.vanilla, self.out)

if __name__ == '__main__':
    unittest.main()
