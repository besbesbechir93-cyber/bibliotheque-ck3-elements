"""Hermetic CK3 v0.8 validator tests. No proprietary game files."""
import json
import tempfile
import unittest
from pathlib import Path

from ck3lib.composer import CompositionError
from ck3lib.validator import validate, main


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mod = self.root / 'mod'
        self.mod.mkdir()
        self.vanilla = self.root / 'game'
        self.vanilla.mkdir()
        self.write('descriptor.mod', 'name="CKLib Test"\nversion="0.8.0"\nsupported_version="1.20.*"\n')
        self.write('events/cklib_test.txt', '''namespace = cklib_test
cklib_test.1 = { title = cklib_test_title immediate = { trigger_event = cklib_test.2 } }
cklib_test.2 = { hidden = yes }
''')
        self.write('common/activities/activity_types/cklib_demo.txt',
                   'cklib_activity = { desc = cklib_activity_desc icon_path = "gfx/cklib/icon.dds" }\n')
        self.write('common/on_action/cklib_pulse.txt',
                   'cklib_pulse = { effect = { trigger_event = cklib_test.1 } }\n')
        self.write('localization/english/cklib_generated_l_english.yml',
                   '\ufeffl_english:\n cklib_test_title:0 "Demo"\n cklib_activity_desc:0 "Activity"\n')
        self.write('gfx/cklib/icon.dds', b'SYNTHETIC_ONLY')
        self.manifest()

    def write(self, rel, contents):
        p = self.mod / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contents if isinstance(contents, bytes) else contents.encode('utf-8'))
        return p

    def manifest(self):
        files = sorted(p.relative_to(self.mod).as_posix()
                       for p in self.mod.rglob('*') if p.is_file() and p.name != 'cklib-package-report.json')
        self.write('cklib-package-report.json', json.dumps({
            'version': 1, 'status': 'PACKAGED_UNVALIDATED', 'game_validated': False,
            'changes_vanilla': False, 'generated_files': files
        }))

    def codes(self, report):
        return [issue['code'] for issue in report['diagnostics']]

    def test_valid_structure_is_not_game_validation(self):
        report = validate(self.mod, self.vanilla)
        self.assertEqual(report['status'], 'STATIC_REVIEW_REQUIRED')
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual(report['summary']['events_defined'], ['cklib_test.1', 'cklib_test.2'])
        self.assertFalse(report['game_validated'])

    def test_script_braces_detected(self):
        self.write('events/cklib_test.txt', 'namespace = cklib_test\ncklib_test.1 = {')
        self.assertIn('SCRIPT_SYNTAX', self.codes(validate(self.mod)))

    def test_event_namespace_mismatch(self):
        self.write('events/cklib_test.txt', 'namespace = other\ncklib_test.1 = { hidden = yes }')
        self.assertIn('EVENT_NAMESPACE_MISMATCH', self.codes(validate(self.mod)))

    def test_missing_cloned_event_is_error(self):
        self.write('common/on_action/cklib_pulse.txt', 'cklib_pulse = { effect = { trigger_event = cklib_missing.3 } }')
        report = validate(self.mod)
        self.assertIn('EVENT_EXTERNAL_REFERENCE', self.codes(report))
        self.assertEqual(report['status'], 'STATIC_FINDINGS_REVIEW_REQUIRED')

    def test_external_vanilla_event_is_warning(self):
        self.write('common/on_action/cklib_pulse.txt', 'cklib_pulse = { effect = { trigger_event = vanilla.10 } }')
        report = validate(self.mod)
        self.assertEqual(report['summary']['errors'], 0)
        self.assertIn('EVENT_EXTERNAL_REFERENCE', self.codes(report))

    def test_missing_localization_is_warning(self):
        self.write('common/activities/activity_types/cklib_demo.txt', 'cklib_activity = { desc = cklib_missing_key }')
        self.assertIn('LOC_UNRESOLVED', self.codes(validate(self.mod)))

    def test_localization_bom_required(self):
        self.write('localization/english/cklib_generated_l_english.yml',
                   'l_english:\n cklib_test_title:0 "Demo"\n')
        self.assertIn('LOC_BOM', self.codes(validate(self.mod)))

    def test_duplicate_localization_detected(self):
        self.write('localization/english/cklib_generated_l_english.yml',
                   '\ufeffl_english:\n duplicate:0 "1"\n duplicate:0 "2"\n')
        self.assertIn('LOC_DUPLICATE', self.codes(validate(self.mod)))

    def test_missing_cloned_asset_detected(self):
        (self.mod / 'gfx/cklib/icon.dds').unlink()
        self.manifest()
        report = validate(self.mod, self.vanilla)
        self.assertIn('GFX_UNRESOLVED', self.codes(report))
        self.assertGreater(report['summary']['errors'], 0)

    def test_asset_can_be_resolved_from_vanilla(self):
        (self.mod / 'gfx/cklib/icon.dds').unlink()
        self.write('common/activities/activity_types/cklib_demo.txt',
                   'cklib_activity = { icon_path = "gfx/interface/vanilla.dds" }')
        vanilla_gfx = self.vanilla / 'gfx/interface/vanilla.dds'
        vanilla_gfx.parent.mkdir(parents=True)
        vanilla_gfx.write_bytes(b'SYNTHETIC')
        self.manifest()
        self.assertNotIn('GFX_UNRESOLVED', self.codes(validate(self.mod, self.vanilla)))

    def test_manifest_mismatch(self):
        self.write('cklib-package-report.json', json.dumps({'status': 'PACKAGED_UNVALIDATED',
                   'game_validated': False, 'changes_vanilla': False, 'generated_files': []}))
        self.assertIn('MANIFEST_MISMATCH', self.codes(validate(self.mod)))

    def test_missing_descriptor(self):
        (self.mod / 'descriptor.mod').unlink()
        self.assertIn('DESCRIPTOR_MISSING', self.codes(validate(self.mod)))

    def test_duplicate_descriptor_field(self):
        self.write('descriptor.mod', 'name="Test"\nname="Duplicate"\nversion="0.8.0"\nsupported_version="1.20.*"')
        self.assertIn('DESCRIPTOR_DUPLICATE', self.codes(validate(self.mod)))

    def test_mod_in_vanilla_rejected(self):
        with self.assertRaisesRegex(CompositionError, 'overlap'):
            validate(self.mod, self.root)

    def test_symlink_refused(self):
        (self.mod / 'events/link.txt').symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(CompositionError, 'symlink'):
            validate(self.mod)

    def test_unknown_override_file_rejected(self):
        self.write('events/vanilla_name.txt', 'namespace = x')
        with self.assertRaisesRegex(CompositionError, 'Unexpected'):
            validate(self.mod)

    def test_logs_errors_attributed_and_other_separate(self):
        logdir = self.root / 'logs'
        logdir.mkdir()
        (logdir / 'error.log').write_text('[15:05:02] Error: cklib_test.1 does not exist\n'
                                          '[15:05:02] Error: other_mod missing\n')
        report = validate(self.mod, self.vanilla, logdir)
        self.assertEqual(len(report['log_triage']['attributable_errors']), 1)
        self.assertEqual(report['log_triage']['other_errors'], 1)
        self.assertIn('LOG_ATTRIBUTABLE_ERRORS', self.codes(report))
        self.assertFalse(report['game_validated'])

    def test_log_symlink_refused(self):
        logdir = self.root / 'logs'
        logdir.mkdir()
        (logdir / 'error.log').symlink_to(self.mod / 'descriptor.mod')
        with self.assertRaisesRegex(CompositionError, 'Log symlink'):
            validate(self.mod, log_root=logdir)

    def test_cli_writes_new_outside_mod(self):
        out = self.root / 'report.json'
        main(['--mod-dir', str(self.mod), '--report-out', str(out)])
        self.assertFalse(json.loads(out.read_text())['game_validated'])
        with self.assertRaises(SystemExit):
            main(['--mod-dir', str(self.mod), '--report-out', str(out)])

    def test_cli_wont_write_into_vanilla(self):
        with self.assertRaises(SystemExit):
            main(['--mod-dir', str(self.mod), '--vanilla-root', str(self.vanilla),
                  '--report-out', str(self.vanilla / 'report.json')])
        self.assertFalse((self.vanilla / 'report.json').exists())

    def test_real_package_v07_compatible(self):
        # Reuse the end-to-end synthetic source + v0.5/v0.6/v0.7 pipeline fixture.
        from test_package_mod import PackageTests
        fixture = PackageTests('test_complete_package_with_localization_and_gfx')
        try:
            fixture.setUp()
            from ck3lib.package_mod import package
            package(fixture.recipe, fixture.vanilla, fixture.wired, fixture.output)
            report = validate(fixture.output, fixture.vanilla)
            self.assertEqual(report['status'], 'STATIC_REVIEW_REQUIRED')
            self.assertEqual(report['summary']['errors'], 0)
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
