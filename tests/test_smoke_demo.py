"""v0.9 minimal manually-testable CK3 mod, no proprietary input or assets."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ck3lib.composer import CompositionError
from ck3lib.smoke_demo import build, MOD_DIR, DECISION_FILE, EVENT_FILE, VANILLA_PICTURE
from ck3lib.validator import validate

RECIPE = {
    'version': 1, 'mod_name': 'CKLib v0.9 Smoke Test',
    'mod_version': '0.9.0', 'supported_version': '1.20.*',
    'cooldown_days': 30, 'prestige_reward': 1,
}


class SmokeDemoTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / 'build'

    def test_generated_mod_has_launcher_entry_and_distinct_namespace(self):
        result = build(RECIPE, self.out)
        self.assertFalse(result['game_validated'])
        self.assertFalse(result['vanilla_modified'])
        self.assertIn('path="mod/cklib_smoke_v09"', (self.out/'cklib_smoke_v09.mod').read_text())
        folder = self.out/MOD_DIR
        self.assertIn('trigger_event = cklib_smoke_v09.0001', (folder/DECISION_FILE).read_text(encoding='utf-8-sig'))
        self.assertIn('namespace = cklib_smoke_v09', (folder/EVENT_FILE).read_text(encoding='utf-8-sig'))
        self.assertEqual((folder/'localization/english/cklib_smoke_l_english.yml').read_bytes()[:3], b'\xef\xbb\xbf')
        self.assertEqual((folder/'localization/french/cklib_smoke_l_french.yml').read_bytes()[:3], b'\xef\xbb\xbf')
        self.assertIn('INSTALL_AND_TEST.md', [p.name for p in self.out.iterdir()])

    def test_v08_validator_accepts_two_languages_and_decision(self):
        build(RECIPE, self.out)
        mock_vanilla = self.root / 'game'
        gfx = mock_vanilla / VANILLA_PICTURE
        gfx.parent.mkdir(parents=True)
        gfx.write_bytes(b'FAKE_GFX_FILE_ONLY_FOR_TEST')
        report = validate(self.out/MOD_DIR, mock_vanilla)
        self.assertEqual(report['summary']['errors'], 0, report['diagnostics'])
        self.assertEqual(report['summary']['warnings'], 0, report['diagnostics'])
        self.assertEqual(report['summary']['event_calls_recognized'], 1)
        self.assertEqual(report['summary']['localizations'], 12)
        self.assertEqual(report['status'], 'STATIC_REVIEW_REQUIRED')
        self.assertFalse(report['game_validated'])

    def test_without_vanilla_gfx_reports_uncertainty(self):
        build(RECIPE, self.out)
        report = validate(self.out/MOD_DIR)
        self.assertEqual(report['summary']['errors'], 0)
        self.assertIn('GFX_UNRESOLVED', [d['code'] for d in report['diagnostics']])

    def test_bespoke_parameters_rendered_without_unlisted_modification(self):
        recipe = dict(RECIPE, cooldown_days=7, prestige_reward=4)
        build(recipe, self.out)
        contents = (self.out/MOD_DIR/DECISION_FILE).read_text(encoding='utf-8-sig')
        event = (self.out/MOD_DIR/EVENT_FILE).read_text(encoding='utf-8-sig')
        self.assertIn('days = 7', contents)
        self.assertIn('add_prestige = 4', event)
        self.assertNotIn('days = 30', contents)

    def test_unsafe_recipe_rejected_before_writes(self):
        cases = [
            dict(RECIPE, cooldown_days=True),
            dict(RECIPE, prestige_reward=-1),
            dict(RECIPE, mod_name='bad"\npath="evil'),
            dict(RECIPE, supported_version='1.20.*\nreplace_path'),
            dict(RECIPE, invalid='other'),
            dict(RECIPE, version=2),
        ]
        for candidate in cases:
            with self.subTest(case=candidate):
                with self.assertRaises(CompositionError):
                    build(candidate, self.out)
                self.assertFalse(self.out.exists())

    def test_refuses_overwriting_existing_output(self):
        build(RECIPE, self.out)
        with self.assertRaisesRegex(CompositionError, 'exists'):
            build(RECIPE, self.out)

    def test_refuses_output_inside_vanilla(self):
        vanilla = self.root / 'game'
        vanilla.mkdir()
        with self.assertRaisesRegex(CompositionError, 'vanilla'):
            build(RECIPE, vanilla / 'bad_mod', vanilla)
        self.assertFalse((vanilla/'bad_mod').exists())

    def test_refuses_output_symlink(self):
        (self.root/'target').mkdir()
        self.out.symlink_to(self.root/'target', target_is_directory=True)
        with self.assertRaisesRegex(CompositionError, 'exists'):
            build(RECIPE, self.out)

    def test_independent_no_vanilla_assets_in_result(self):
        build(RECIPE, self.out)
        self.assertEqual(list(self.out.rglob('*.dds')), [])
        report = json.loads((self.out/MOD_DIR/'cklib-package-report.json').read_text())
        self.assertFalse(report['changes_vanilla'])
        self.assertFalse(report['game_validated'])
        self.assertEqual(len(report['generated_files']), 5)


if __name__ == '__main__':
    unittest.main()
