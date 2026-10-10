"""Hermetic v0.7 package tests: only synthetic source, scripts and images."""
import json
import tempfile
import unittest
from pathlib import Path

from ck3lib.composer import CompositionError, git_blob_sha
from ck3lib.event_cloner import clone
from ck3lib.wiring import assemble
from ck3lib.package_mod import package

EV = '''namespace = oldns
oldns.1 = { title = oldns.1.t desc = oldns.1.desc immediate = { trigger_event = oldns.2 } }
oldns.2 = { hidden = yes }
'''
ACT = '''activity_demo = {
    is_shown = { always = yes }
    desc = old_activity_desc
    icon_path = "gfx/interface/icons/activity_icon.dds"
    phases = { phase_demo = { on_phase_active = { trigger_event = oldns.1 }
       on_monthly_pulse = { trigger_event = { on_action = pulse } } } }
}
'''
OA = '''pulse = { random_events = { 50 = oldns.2 } }
'''
LOC = '\ufeffl_english:\n oldns.1.t:0 "First Event"\n oldns.1.desc:1 "Description"\n old_activity_desc: "Activity"\n other_key:0 "Unrelated"\n'


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vanilla = self.root / 'game'
        self.vanilla.mkdir()
        ev = self._text('events/demo.txt', EV)
        act = self._text('common/activities/activity_types/demo.txt', ACT)
        oa = self._text('common/on_action/activities/demo.txt', OA)
        loc = self._text('localization/english/demo_l_english.yml', LOC, bom=False)
        gfx = self.vanilla / 'gfx/interface/icons/activity_icon.dds'
        gfx.parent.mkdir(parents=True)
        gfx.write_bytes(b'FAKE_SYNTHETIC_DDS_ONLY')
        self.gfx_path = gfx
        self.loc_path = loc
        self.ev_fragment = self.root / 'events-out'
        clone({
            'version': 1, 'source_path': 'events/demo.txt',
            'source_git_blob_sha': git_blob_sha(ev.read_bytes()),
            'source_namespace': 'oldns', 'expected_event_ids': ['oldns.1', 'oldns.2'],
            'namespace': 'demo', 'source_version_label': 'fixture'
        }, self.vanilla, self.ev_fragment)
        self.wired = self.root / 'wired-out'
        assemble({
            'version': 1,
            'activity': {'source_path': 'common/activities/activity_types/demo.txt',
                         'source_git_blob_sha': git_blob_sha(act.read_bytes()),
                         'source_id': 'activity_demo', 'target_id': 'cklib_activity_demo'},
            'on_action': {'source_path': 'common/on_action/activities/demo.txt',
                          'source_git_blob_sha': git_blob_sha(oa.read_bytes()),
                          'source_id': 'pulse', 'target_id': 'cklib_demo_pulse'},
        }, self.vanilla, self.ev_fragment, self.wired)
        self.recipe = {
            'version': 1, 'name': 'CKLib Safe Demo', 'mod_version': '0.7.0',
            'supported_version': '1.20.*',
            'localizations': [{'source_path': 'localization/english/demo_l_english.yml',
                               'source_git_blob_sha': git_blob_sha(loc.read_bytes()),
                               'language': 'english',
                               'renames': {'oldns.1.t': 'cklib_demo_oldns.1.t',
                                           'oldns.1.desc': 'cklib_demo_oldns.1.desc',
                                           'old_activity_desc': 'cklib_activity_desc'}}],
            'gfx': [{'mode': 'clone', 'source_path': 'gfx/interface/icons/activity_icon.dds',
                     'source_git_blob_sha': git_blob_sha(gfx.read_bytes()),
                     'target_path': 'gfx/cklib/activity_icon.dds'}]
        }
        self.output = self.root / 'packaged'

    def _text(self, rel, content, bom=True):
        p = self.vanilla / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8-sig' if bom else 'utf-8')
        return p

    def test_complete_package_with_localization_and_gfx(self):
        report = package(self.recipe, self.vanilla, self.wired, self.output)
        self.assertEqual(report['status'], 'PACKAGED_UNVALIDATED')
        self.assertFalse(report['game_validated'])
        self.assertFalse(report['is_complete_mod'])
        self.assertEqual(report['rewritten_references']['localization']['oldns.1.t'], 1)
        self.assertEqual(report['rewritten_references']['gfx']['gfx/interface/icons/activity_icon.dds'], 1)
        event = (self.output / 'events/cklib_demo_demo.txt').read_text(encoding='utf-8-sig')
        self.assertIn('title = cklib_demo_oldns.1.t', event)
        act = (self.output / 'common/activities/activity_types/cklib_activity_demo.txt').read_text(encoding='utf-8-sig')
        self.assertIn('desc = cklib_activity_desc', act)
        self.assertIn('"gfx/cklib/activity_icon.dds"', act)
        loc = self.output / 'localization/english/cklib_generated_l_english.yml'
        self.assertTrue(loc.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn('cklib_demo_oldns.1.t:0 "First Event"', loc.read_text(encoding='utf-8-sig'))
        self.assertNotIn('other_key', loc.read_text(encoding='utf-8-sig'))
        self.assertIn('cklib_demo_oldns.1.desc:1', loc.read_text(encoding='utf-8-sig'))
        self.assertIn('cklib_activity_desc: \"Activity\"', loc.read_text(encoding='utf-8-sig'))
        self.assertEqual((self.output / 'gfx/cklib/activity_icon.dds').read_bytes(), b'FAKE_SYNTHETIC_DDS_ONLY')
        self.assertIn('supported_version="1.20.*"', (self.output / 'descriptor.mod').read_text())
        self.assertEqual(self.gfx_path.read_bytes(), b'FAKE_SYNTHETIC_DDS_ONLY')
        self.assertEqual(self.loc_path.read_text(encoding='utf-8'), LOC)

    def test_empty_adapters_still_packages(self):
        self.recipe['localizations'] = []
        self.recipe['gfx'] = []
        report = package(self.recipe, self.vanilla, self.wired, self.output)
        self.assertEqual(report['rewritten_references']['localization'], {})
        self.assertTrue((self.output / 'descriptor.mod').exists())

    def test_reference_mode_no_asset_copy(self):
        del self.recipe['gfx'][0]['target_path']
        self.recipe['gfx'][0]['mode'] = 'reference'
        package(self.recipe, self.vanilla, self.wired, self.output)
        self.assertFalse((self.output / 'gfx').exists())
        a = (self.output / 'common/activities/activity_types/cklib_activity_demo.txt').read_text(encoding='utf-8-sig')
        self.assertIn('"gfx/interface/icons/activity_icon.dds"', a)

    def test_refuse_bad_source_hash(self):
        self.recipe['localizations'][0]['source_git_blob_sha'] = '0' * 40
        with self.assertRaisesRegex(CompositionError, 'SHA mismatch'):
            package(self.recipe, self.vanilla, self.wired, self.output)
        self.assertFalse(self.output.exists())

    def test_refuse_source_gfx_hash(self):
        self.recipe['gfx'][0]['source_git_blob_sha'] = '0' * 40
        with self.assertRaises(CompositionError):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_unsafe_target_asset(self):
        self.recipe['gfx'][0]['target_path'] = '../outside.dds'
        with self.assertRaises(CompositionError):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_missing_loc_key(self):
        self.recipe['localizations'][0]['renames']['not_exist'] = 'cklib_not_exist'
        with self.assertRaisesRegex(CompositionError, 'absent'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_unused_loc_rewrite(self):
        self.recipe['localizations'][0]['renames']['other_key'] = 'cklib_unused'
        with self.assertRaisesRegex(CompositionError, 'Unused localization'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_bad_localization_header(self):
        self.loc_path.write_text(LOC.replace('l_english:', 'l_french:'), encoding='utf-8')
        self.recipe['localizations'][0]['source_git_blob_sha'] = git_blob_sha(self.loc_path.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'header mismatch'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_missing_localization_bom(self):
        self.loc_path.write_text(LOC.lstrip('\ufeff'), encoding='utf-8')
        self.recipe['localizations'][0]['source_git_blob_sha'] = git_blob_sha(self.loc_path.read_bytes())
        with self.assertRaisesRegex(CompositionError, 'UTF-8 BOM'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_unquoted_gfx_in_script(self):
        act = self.wired / 'common/activities/activity_types/cklib_activity_demo.txt'
        act.write_text(act.read_text(encoding='utf-8-sig').replace('"gfx/interface/icons/activity_icon.dds"', 'gfx/interface/icons/activity_icon.dds'), encoding='utf-8-sig')
        with self.assertRaisesRegex(CompositionError, 'Unquoted'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_unsupported_loc_context(self):
        act = self.wired / 'common/activities/activity_types/cklib_activity_demo.txt'
        act.write_text(act.read_text(encoding='utf-8-sig').replace('desc = old_activity_desc', 'script_value = old_activity_desc'), encoding='utf-8-sig')
        with self.assertRaisesRegex(CompositionError, 'unsafe script context'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_duplicate_generated_localization_key(self):
        self.recipe['localizations'][0]['renames']['oldns.1.desc'] = 'cklib_demo_oldns.1.t'
        with self.assertRaisesRegex(CompositionError, 'target-key collision'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_fragment_symlink(self):
        p = self.wired / 'events/cklib_demo_demo.txt'
        data = p.read_bytes()
        p.unlink()
        elsewhere = self.root / 'elsewhere.txt'
        elsewhere.write_bytes(data)
        p.symlink_to(elsewhere)
        with self.assertRaisesRegex(CompositionError, 'symlink'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_fragment_extra_file(self):
        (self.wired / 'unexpected.txt').write_text('tampered')
        with self.assertRaisesRegex(CompositionError, 'unexpected'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_output_inside_vanilla(self):
        with self.assertRaisesRegex(CompositionError, 'isolated'):
            package(self.recipe, self.vanilla, self.wired, self.vanilla / 'somewhere')

    def test_refuse_output_inside_wired(self):
        with self.assertRaisesRegex(CompositionError, 'isolated'):
            package(self.recipe, self.vanilla, self.wired, self.wired / 'somewhere')

    def test_refuse_existing_output(self):
        self.output.mkdir()
        with self.assertRaisesRegex(CompositionError, 'isolated'):
            package(self.recipe, self.vanilla, self.wired, self.output)

    def test_refuse_malicious_descriptor_field(self):
        self.recipe['name'] = 'Demo"\npath="/game'
        with self.assertRaisesRegex(CompositionError, 'descriptor'):
            package(self.recipe, self.vanilla, self.wired, self.output)


if __name__ == '__main__':
    unittest.main()
