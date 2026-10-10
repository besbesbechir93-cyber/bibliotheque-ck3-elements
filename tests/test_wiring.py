"""Hermetic v0.6 tests. All fixtures are synthetic, not redistributed game code."""
import json
import tempfile
import unittest
from pathlib import Path

from ck3lib.composer import CompositionError, git_blob_sha
from ck3lib.event_cloner import clone
from ck3lib.wiring import assemble

EVENTS = '''namespace = oldns
oldns.1 = { hidden = yes immediate = { trigger_event = oldns.2 } }
oldns.2 = { hidden = yes }
'''
ACTIVITY = '''activity_demo = {
    is_shown = { always = yes }
    phases = {
        phase_demo = {
            on_phase_active = { trigger_event = { id = oldns.1 days = 1 } }
            on_monthly_pulse = { trigger_event = { on_action = pulse } }
        }
    }
}
'''
ON_ACTION = '''pulse = {
    random_events = { 50 = oldns.2 }
}
'''


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.vanilla = self.root / 'game'
        self.vanilla.mkdir()
        self.events = self._source('events/demo.txt', EVENTS)
        self.activity = self._source('common/activities/activity_types/demo.txt', ACTIVITY)
        self.on_action = self._source('common/on_action/activities/demo.txt', ON_ACTION)
        event_recipe = {
            'version': 1, 'source_path': 'events/demo.txt',
            'source_git_blob_sha': git_blob_sha(self.events.read_bytes()),
            'source_namespace': 'oldns', 'expected_event_ids': ['oldns.1', 'oldns.2'],
            'namespace': 'demo', 'source_version_label': 'fixture-1',
        }
        self.fragment = self.root / 'event-fragment'
        clone(event_recipe, self.vanilla, self.fragment)
        self.recipe = {
            'version': 1,
            'activity': {'source_path': 'common/activities/activity_types/demo.txt',
                         'source_git_blob_sha': git_blob_sha(self.activity.read_bytes()),
                         'source_id': 'activity_demo', 'target_id': 'cklib_activity_demo'},
            'on_action': {'source_path': 'common/on_action/activities/demo.txt',
                          'source_git_blob_sha': git_blob_sha(self.on_action.read_bytes()),
                          'source_id': 'pulse', 'target_id': 'cklib_demo_pulse'},
        }
        self.out = self.root / 'composed-fragment'

    def _source(self, relative, content):
        p = self.vanilla / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8-sig')
        return p

    def _refresh(self, which):
        name = self.recipe[which]['source_git_blob_sha']
        p = self.activity if which == 'activity' else self.on_action
        self.recipe[which]['source_git_blob_sha'] = git_blob_sha(p.read_bytes())

    def test_links_activity_to_on_action_and_events(self):
        report = assemble(self.recipe, self.vanilla, self.fragment, self.out)
        act = (self.out / 'common/activities/activity_types/cklib_activity_demo.txt').read_text(encoding='utf-8-sig')
        oa = (self.out / 'common/on_action/cklib_demo_pulse.txt').read_text(encoding='utf-8-sig')
        ev = (self.out / 'events/cklib_demo_demo.txt').read_text(encoding='utf-8-sig')
        self.assertIn('cklib_activity_demo = {', act)
        self.assertIn('id = cklib_demo_oldns.1', act)
        self.assertIn('on_action = cklib_demo_pulse', act)
        self.assertIn('cklib_demo_pulse = {', oa)
        self.assertIn('50 = cklib_demo_oldns.2', oa)
        self.assertIn('namespace = cklib_demo_oldns', ev)
        self.assertEqual(report['status'], 'STATIC_LINKED_REVIEW_REQUIRED')
        self.assertFalse(report['game_validated'])
        self.assertEqual(len(report['files']), 3)
        self.assertEqual(self.activity.read_text(encoding='utf-8-sig'), ACTIVITY)
        self.assertEqual(self.on_action.read_text(encoding='utf-8-sig'), ON_ACTION)

    def test_reports_retained_external_event_ids(self):
        self.activity.write_text(ACTIVITY.replace('always = yes',
            'trigger_event = { id = externalns.404 }'), encoding='utf-8-sig')
        self._refresh('activity')
        report = assemble(self.recipe, self.vanilla, self.fragment, self.out)
        self.assertEqual(report['retained_external_event_ids'], ['externalns.404'])
        output = (self.out / 'common/activities/activity_types/cklib_activity_demo.txt').read_text(encoding='utf-8-sig')
        self.assertIn('id = externalns.404', output)

    def test_refuses_existing_output(self):
        assemble(self.recipe, self.vanilla, self.fragment, self.out)
        with self.assertRaises(CompositionError):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_refuses_output_under_vanilla(self):
        with self.assertRaises(CompositionError):
            assemble(self.recipe, self.vanilla, self.fragment, self.vanilla / 'bad')

    def test_refuses_output_under_event_fragment(self):
        with self.assertRaises(CompositionError):
            assemble(self.recipe, self.vanilla, self.fragment, self.fragment / 'bad')

    def test_activity_sha_mismatch(self):
        self.recipe['activity']['source_git_blob_sha'] = '0' * 40
        with self.assertRaisesRegex(CompositionError, 'SHA mismatch'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)
        self.assertFalse(self.out.exists())

    def test_on_action_sha_mismatch(self):
        self.recipe['on_action']['source_git_blob_sha'] = '0' * 40
        with self.assertRaisesRegex(CompositionError, 'SHA mismatch'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_event_clone_tampering_rejected(self):
        event = self.fragment / 'events/cklib_demo_demo.txt'
        event.write_bytes(event.read_bytes() + b'# fake\n')
        with self.assertRaisesRegex(CompositionError, 'does not match'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_event_report_tampering_rejected(self):
        rep = self.fragment / 'event-clone-report.json'
        obj = json.loads(rep.read_text())
        obj['id_map']['oldns.1'] = 'oldns.1'
        rep.write_text(json.dumps(obj))
        with self.assertRaisesRegex(CompositionError, 'diverges'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_refuses_outside_event_bundle(self):
        self.activity.write_text(ACTIVITY.replace('oldns.1', 'oldns.99'), encoding='utf-8-sig')
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'outside'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_refuses_unsupported_event_context(self):
        self.activity.write_text(ACTIVITY.replace('id = oldns.1', 'modifier = oldns.1'), encoding='utf-8-sig')
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'Unsupported event reference'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_requires_on_action_wiring(self):
        self.activity.write_text(ACTIVITY.replace('on_action = pulse', 'on_action = unrelated'), encoding='utf-8-sig')
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'Missing activity'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_requires_event_wiring_inside_on_action(self):
        self.on_action.write_text(ON_ACTION.replace('oldns.2', 'otherns.2'), encoding='utf-8-sig')
        self._refresh('on_action')
        with self.assertRaisesRegex(CompositionError, 'Missing activity'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_rejects_mixed_activity_roots(self):
        self.activity.write_text(ACTIVITY + '\nother_activity = { always = yes }', encoding='utf-8-sig')
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'exactly one'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_rejects_symlinked_source(self):
        other = self._source('common/activities/activity_types/real.txt', ACTIVITY)
        self.activity.unlink()
        self.activity.symlink_to(other)
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'symlink'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_rejects_quoted_old_event(self):
        self.activity.write_text(ACTIVITY.replace('always = yes', 'desc = "oldns.2"'), encoding='utf-8-sig')
        self._refresh('activity')
        with self.assertRaisesRegex(CompositionError, 'Quoted'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_rejects_target_activity_collision(self):
        self._source('common/activities/activity_types/other.txt', 'cklib_activity_demo = { always = yes }')
        with self.assertRaisesRegex(CompositionError, 'collides'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)

    def test_rejects_target_on_action_collision(self):
        self._source('common/on_action/other.txt', 'cklib_demo_pulse = { always = yes }')
        with self.assertRaisesRegex(CompositionError, 'collides'):
            assemble(self.recipe, self.vanilla, self.fragment, self.out)


if __name__ == '__main__':
    unittest.main()
