"""v1.0 activity probe unit tests are synthetic; never a CK3 runtime certification."""
import json
import tempfile
import unittest
from pathlib import Path

from ck3lib.activity_smoke import (
    ACTIVITY_ID, EVENT_NS, DECISION_ID, FILES, MOD_DIR, MOD_FILE,
    build, render, validate_recipe, GFX,
)
from ck3lib.composer import CompositionError, tokenize, matching_braces


RECIPE = {
    'version': 1, 'mod_name': 'CKLib v1.0 Activity Probe',
    'mod_version': '1.0.0', 'supported_version': '1.20.*',
    'cooldown_days': 30, 'gold_cost': 0, 'prestige_reward': 5,
}


class ActivitySmokeTests(unittest.TestCase):
    def test_valid_recipe(self):
        self.assertEqual(validate_recipe(RECIPE), RECIPE)

    def test_ban_extra_fields(self):
        with self.assertRaises(CompositionError):
            validate_recipe({**RECIPE, 'evil': 'replace_path'})

    def test_ban_missing_fields(self):
        x = RECIPE.copy(); x.pop('cooldown_days')
        with self.assertRaises(CompositionError):
            validate_recipe(x)

    def test_ban_bool_as_number(self):
        for field in ('cooldown_days', 'gold_cost', 'prestige_reward'):
            with self.subTest(field=field), self.assertRaises(CompositionError):
                validate_recipe({**RECIPE, field: True})

    def test_bounds(self):
        for field, bad in [('cooldown_days',0),('cooldown_days',3651),('gold_cost',-1),
                           ('gold_cost',1001),('prestige_reward',-1),('prestige_reward',101)]:
            with self.subTest(field=field,bad=bad), self.assertRaises(CompositionError):
                validate_recipe({**RECIPE,field:bad})

    def test_ban_bad_names_versions(self):
        for field, bad in [('mod_name','x\npath="/bad"'),('mod_version','../1'),
                           ('supported_version','1.20.*\nreplace_path="common"')]:
            with self.subTest(field=field), self.assertRaises(CompositionError):
                validate_recipe({**RECIPE,field:bad})

    def test_exact_file_set(self):
        self.assertEqual(set(render(RECIPE)), set(FILES))

    def test_valid_braces(self):
        for path,data in render(RECIPE).items():
            if path.endswith('.txt'):
                with self.subTest(path=path):
                    ts = tokenize(data.decode('utf-8-sig'))
                    matching_braces(ts)

    def test_activity_and_control_separated(self):
        files = render(RECIPE)
        activity = files['common/activities/activity_types/cklib_activity_probe_v10.txt'].decode('utf-8-sig')
        control = files['common/decisions/cklib_activity_probe_v10.txt'].decode('utf-8-sig')
        self.assertIn(f'{ACTIVITY_ID} =',activity)
        self.assertIn(f'trigger_event = {EVENT_NS}.0001',activity)
        self.assertNotIn(f'{EVENT_NS}.9001',activity)
        self.assertIn(f'{DECISION_ID} =',control)
        self.assertIn(f'trigger_event = {EVENT_NS}.9001',control)
        self.assertNotIn(f'{EVENT_NS}.0001',control)

    def test_event_contents(self):
        src = render(RECIPE)['events/cklib_activity_probe_v10.txt'].decode('utf-8-sig')
        self.assertEqual(src.count(f'{EVENT_NS}.0001 ='),1)
        self.assertEqual(src.count(f'{EVENT_NS}.9001 ='),1)
        self.assertIn('add_prestige = 5',src)

    def test_recipe_params_render(self):
        x = {**RECIPE,'cooldown_days':400,'gold_cost':17,'prestige_reward':30}
        files = render(x)
        a = files['common/activities/activity_types/cklib_activity_probe_v10.txt'].decode('utf-8-sig')
        e = files['events/cklib_activity_probe_v10.txt'].decode('utf-8-sig')
        self.assertIn('days = 400',a)
        self.assertIn('value = 17',a)
        self.assertIn('add_prestige = 30',e)

    def test_localization_boms_languages(self):
        for lang in ('english','french'):
            path=f'localization/{lang}/cklib_activity_probe_l_{lang}.yml'
            data=render(RECIPE)[path]
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
            self.assertIn(f'l_{lang}:', data.decode('utf-8-sig'))
            self.assertIn(ACTIVITY_ID,data.decode('utf-8-sig'))

    def test_reuse_vanilla_gfx_by_reference_only(self):
        files=render(RECIPE)
        self.assertTrue(all(not k.startswith('gfx/') for k in files))
        self.assertIn(GFX,files['common/activities/activity_types/cklib_activity_probe_v10.txt'].decode('utf-8-sig'))

    def test_safe_new_directory_and_metadata(self):
        with tempfile.TemporaryDirectory() as base:
            d=Path(base)/'generated'
            output=build(RECIPE,d)
            self.assertFalse(output['game_validated'])
            self.assertEqual(output['status'],'STATIC_REVIEW_REQUIRED')
            self.assertTrue((d/MOD_DIR/'descriptor.mod').is_file())
            self.assertTrue((d/MOD_FILE).is_file())
            self.assertIn(f'path="mod/{MOD_DIR}"',(d/MOD_FILE).read_text())
            r=json.loads((d/MOD_DIR/'cklib-package-report.json').read_text())
            self.assertFalse(r['game_validated'])
            self.assertFalse(r['changes_vanilla'])
            self.assertEqual(len(r['generated_file_sha']),len(FILES))

    def test_existing_validator_reports_no_static_errors(self):
        from ck3lib.validator import validate
        with tempfile.TemporaryDirectory() as base:
            folder=Path(base)/'activity'
            build(RECIPE, folder)
            report=validate(folder/MOD_DIR)
            self.assertEqual(report['summary']['errors'], 0)
            self.assertFalse(report['game_validated'])
            self.assertIn(f'{EVENT_NS}.0001', report['summary']['events_defined'])
            self.assertEqual(report['summary']['event_calls_recognized'], 2)
            self.assertEqual({x['code'] for x in report['diagnostics']}, {'GFX_UNRESOLVED'})

    def test_do_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as base:
            d=Path(base)/'exists'; d.mkdir()
            (d/'important.txt').write_text('untouched')
            with self.assertRaises(CompositionError):build(RECIPE,d)
            self.assertEqual((d/'important.txt').read_text(),'untouched')

    def test_do_not_write_inside_vanilla(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'game';root.mkdir()
            with self.assertRaises(CompositionError):build(RECIPE,root/'generated',root)
            self.assertEqual(list(root.iterdir()),[])

    def test_do_not_write_over_vanilla(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/'game';root.mkdir()
            with self.assertRaises(CompositionError):build(RECIPE,root,root)

    def test_no_symlink_output_or_parent(self):
        with tempfile.TemporaryDirectory() as base:
            b=Path(base); source=b/'target';source.mkdir()
            link=b/'symlink';link.symlink_to(source,target_is_directory=True)
            with self.assertRaises(CompositionError):build(RECIPE,link/'child')
            with self.assertRaises(CompositionError):build(RECIPE,link)

    def test_repeatability(self):
        self.assertEqual(render(RECIPE),render(RECIPE))

    def test_valid_json_schema(self):
        src=Path(__file__).resolve().parents[1]/'schemas/activity-smoke-recipe.schema.json'
        schema=json.loads(src.read_text())
        self.assertEqual(schema['properties']['version']['const'],1)
        self.assertEqual(set(schema['required']),set(RECIPE))


if __name__=='__main__':
    unittest.main()
