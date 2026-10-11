"""v1.0 experimental CK3 ACTIVITY smoke probe, independent of the vanilla sources.

Only generates new cklib_ script IDs; it does not clone vanilla or claim
engine compatibility. The player's *manual* CK3 test is authoritative.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .composer import CompositionError, git_blob_sha
from .smoke_demo import NAME, VERSION, SUPPORTED

MOD_DIR = 'cklib_activity_probe_v10'
MOD_FILE = MOD_DIR + '.mod'
ACTIVITY_ID = 'activity_cklib_probe_v10'
EVENT_NS = 'cklib_activity_probe_v10'
PHASE_ID = 'cklib_probe_phase_v10'
DECISION_ID = 'cklib_probe_control_v10_decision'
GFX = 'gfx/interface/illustrations/activity_header_backgrounds/activity_feast.dds'
DECISION_GFX = 'gfx/interface/illustrations/decisions/decision_misc.dds'
FILES = (
    'descriptor.mod',
    'common/activities/activity_types/cklib_activity_probe_v10.txt',
    'common/decisions/cklib_activity_probe_v10.txt',
    'events/cklib_activity_probe_v10.txt',
    'localization/english/cklib_activity_probe_l_english.yml',
    'localization/french/cklib_activity_probe_l_french.yml',
)


def validate_recipe(recipe: dict) -> dict:
    wanted = {'version', 'mod_name', 'mod_version', 'supported_version',
              'cooldown_days', 'gold_cost', 'prestige_reward'}
    if not isinstance(recipe, dict) or set(recipe) != wanted or recipe.get('version') != 1:
        raise CompositionError('Invalid activity probe recipe')
    if not isinstance(recipe['mod_name'], str) or not NAME.fullmatch(recipe['mod_name']):
        raise CompositionError('Invalid mod name')
    if not isinstance(recipe['mod_version'], str) or not VERSION.fullmatch(recipe['mod_version']):
        raise CompositionError('Invalid mod version')
    if not isinstance(recipe['supported_version'], str) or not SUPPORTED.fullmatch(recipe['supported_version']):
        raise CompositionError('Invalid game version')
    for key, lower, upper in [('cooldown_days', 1, 3650), ('gold_cost', 0, 1000),
                              ('prestige_reward', 0, 100)]:
        if type(recipe[key]) is not int or not lower <= recipe[key] <= upper:
            raise CompositionError(f'Invalid {key}')
    return recipe


def render(recipe: dict) -> dict[str, bytes]:
    validate_recipe(recipe)
    cd, gold, prestige = (recipe[k] for k in ('cooldown_days', 'gold_cost', 'prestige_reward'))
    descriptor = (f'name="{recipe["mod_name"]}"\n'
                  f'version="{recipe["mod_version"]}"\n'
                  f'supported_version="{recipe["supported_version"]}"\n')
    activity = f'''# CKLib experimental original activity, not a vanilla clone.
{ACTIVITY_ID} = {{
    activity_group_type = activities
    is_shown = {{ is_ai = no is_adult = yes is_landed = yes }}
    can_start_showing_failures_only = {{
        NOT = {{ is_activity_type_on_cooldown = {ACTIVITY_ID} }}
        is_available = yes
    }}
    is_valid = {{
        scope:host = {{ is_alive = yes is_imprisoned = no }}
    }}
    on_invalidated = {{
        invalidation_imprisoned_effect = yes
        invalidation_nobody_present_effect = yes
    }}
    province_filter = capital
    ai_province_filter = capital
    max_province_icons = 1
    allow_zero_guest_invites = yes
    open_invite = no
    cost = {{ gold = {{ value = {gold} }} }}
    ui_predicted_cost = {{ gold = {{ value = {gold} }} }}
    cooldown = {{ days = {cd} }}
    phases = {{
        {PHASE_ID} = {{
            is_predefined = yes
            location_source = pickable
            on_phase_active = {{
                if = {{
                    limit = {{ this = scope:host }}
                    trigger_event = {EVENT_NS}.0001
                    scope:activity = {{ progress_activity_phase_after = {{ days = 2 }} }}
                }}
            }}
        }}
    }}
    ai_will_do = {{ value = 0 }}
    ai_check_interval = 0
    header_background = "{GFX}"
}}
'''
    # Control decision is a separately observable loader probe. It must NOT
    # trigger the same activity-specific event, or the test is ambiguous.
    decision = f'''# Independent loader control: event .9001 is NEVER used by the activity.
{DECISION_ID} = {{
    ai_check_interval = 0
    sort_order = 100
    picture = {{ reference = "{DECISION_GFX}" }}
    desc = {DECISION_ID}_desc
    selection_tooltip = {DECISION_ID}_tooltip
    is_shown = {{ is_ai = no }}
    is_valid_showing_failures_only = {{ is_adult = yes }}
    effect = {{ trigger_event = {EVENT_NS}.9001 }}
    ai_potential = {{ always = no }}
    ai_will_do = {{ base = 0 }}
}}
'''
    events = f'''# Two distinct outcomes: .0001 proves activity phase execution;
# .9001 proves only that decision/event scripts loaded.
namespace = {EVENT_NS}
{EVENT_NS}.0001 = {{
    type = character_event
    title = {EVENT_NS}.0001.t
    desc = {EVENT_NS}.0001.desc
    option = {{
        name = {EVENT_NS}.0001.a
        add_prestige = {prestige}
    }}
}}
{EVENT_NS}.9001 = {{
    type = character_event
    title = {EVENT_NS}.9001.t
    desc = {EVENT_NS}.9001.desc
    option = {{ name = {EVENT_NS}.9001.a }}
}}
'''
    en = f'''\ufeffl_english:
 {ACTIVITY_ID}:0 "CKLib phase test"
 {ACTIVITY_ID}_desc:0 "An experimental activity to verify an independent phase and event."
 {PHASE_ID}:0 "Probe phase"
 {DECISION_ID}:0 "CKLib loader control"
 {DECISION_ID}_desc:0 "Checks script loading separately from the activity."
 {DECISION_ID}_tooltip:0 "Open the loader control event"
 {EVENT_NS}.0001.t:0 "CKLib activity phase detected"
 {EVENT_NS}.0001.desc:0 "This event can be called by the new activity phase. Record the result."
 {EVENT_NS}.0001.a:0 "Record activity result"
 {EVENT_NS}.9001.t:0 "CKLib loader control"
 {EVENT_NS}.9001.desc:0 "The decision script loaded; this does NOT verify the activity."
 {EVENT_NS}.9001.a:0 "Record loader result"
'''
    fr = f'''\ufeffl_french:
 {ACTIVITY_ID}:0 "Test de phase CKLib"
 {ACTIVITY_ID}_desc:0 "Activité expérimentale pour vérifier une phase et son événement indépendants."
 {PHASE_ID}:0 "Phase de test"
 {DECISION_ID}:0 "Contrôle de chargement CKLib"
 {DECISION_ID}_desc:0 "Vérifie le chargement des scripts indépendamment de l'activité."
 {DECISION_ID}_tooltip:0 "Ouvrir l'événement de contrôle"
 {EVENT_NS}.0001.t:0 "Phase d'activité CKLib détectée"
 {EVENT_NS}.0001.desc:0 "Cet événement peut être déclenché par la nouvelle phase. Notez le résultat."
 {EVENT_NS}.0001.a:0 "Enregistrer le résultat"
 {EVENT_NS}.9001.t:0 "Contrôle de chargement CKLib"
 {EVENT_NS}.9001.desc:0 "La décision fonctionne, mais cela ne prouve pas le fonctionnement de l'activité."
 {EVENT_NS}.9001.a:0 "Enregistrer le contrôle"
'''
    sources = (descriptor, activity, decision, events, en, fr)
    return {path: data.encode('utf-8-sig') if path.endswith('.txt') else data.encode('utf-8')
            for path, data in zip(FILES, sources)}


PROTOCOL = '''# CKLib v1.0 — vérification CK3 de l'activité

Cette activité est un **prototype original expérimental**. Elle n'est ni une
copie de `activity_feast` ni un assemblage vérifié de ses dépendances.

1. Copier `cklib_activity_probe_v10` et `cklib_activity_probe_v10.mod` dans
   `Documents/Paradox Interactive/Crusader Kings III/mod/` (sous Windows,
   Documents peut être redirigé vers OneDrive).
2. Utiliser un nouveau playset CK3 avec ce mod seul. Utiliser un personnage
   adulte et doté de terres; noter version CK3 et DLC activés.
3. **Contrôle distinct** : ouvrir Décisions > « Contrôle de chargement CKLib »;
   l'événement « Contrôle de chargement CKLib » confirme seulement le
   chargement des scripts de décision et d'événement.
4. Ouvrir ensuite le planificateur **Activités** et chercher
   « Test de phase CKLib ». Noter si elle apparaît et si la sélection de la
   capitale ainsi que le démarrage sont possibles.
5. **Preuve recherchée** : une fois la phase commencée, voir l'événement
   « Phase d'activité CKLib détectée ». Cet événement est distinct de celui
   de contrôle. Si absent, ne PAS déclarer le test réussi.
6. Après le jeu, récupérer `Documents/Paradox Interactive/Crusader Kings III/logs/error.log`
   et éventuellement `game.log`; conserver la date/heure du lancement.
7. Si absent du planificateur, vérifier d'abord les erreurs `activity`,
   `phase`, `gfx` ou `localization`; le schéma d'activité CK3 et des hooks de
   moteur non documentés peuvent imposer des propriétés supplémentaires.

Le résultat `STATIC_REVIEW_REQUIRED` n'est **jamais** une validation en jeu.
Le seul statut de succès doit être consigné après observation effective.
'''


def build(recipe: dict, output: Path, vanilla_root: Path | None = None) -> dict:
    files = render(recipe)
    if not isinstance(output, Path):
        raise CompositionError('Output must be a Path')
    if output.is_symlink() or output.exists():
        raise CompositionError('Output directory already exists')
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise CompositionError('Output parent is not a safe directory')
    parent = output.parent.resolve(strict=True)
    dest = parent / output.name
    if vanilla_root is not None:
        if vanilla_root.is_symlink() or not vanilla_root.is_dir():
            raise CompositionError('Invalid vanilla root')
        vanilla = vanilla_root.resolve(strict=True)
        if dest == vanilla or dest.is_relative_to(vanilla) or vanilla.is_relative_to(dest):
            raise CompositionError('Cannot write into or over vanilla source')
    launcher = (f'name="{recipe["mod_name"]}"\nversion="{recipe["mod_version"]}"\n'
                f'supported_version="{recipe["supported_version"]}"\n'
                f'path="mod/{MOD_DIR}"\n').encode('utf-8')
    report = {
        'version': 1, 'status': 'PACKAGED_UNVALIDATED', 'game_validated': False,
        'changes_vanilla': False, 'is_complete_mod': False,
        'id_activity': ACTIVITY_ID, 'id_event_phase': f'{EVENT_NS}.0001',
        'id_event_loader': f'{EVENT_NS}.9001', 'source_type': 'original_CKLib_script',
        'gfx_vanilla_references': [GFX, DECISION_GFX],
        'generated_files': sorted(files),
        'generated_file_sha': {p: git_blob_sha(v) for p,v in sorted(files.items())},
        'runtime_tests_required': ['launcher', 'loader_control', 'activity_visible',
                                   'activity_start', 'phase_event', 'error_log_review'],
        'limitations': ['CK3 runtime not exercised', 'CK3 activity UI/engine semantics not verified',
                        'No standalone GFX copies', 'No vanilla overwrites'],
    }
    try:
        dest.mkdir()
        mod = dest / MOD_DIR
        mod.mkdir()
        for rel, data in files.items():
            path = mod / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (mod / 'cklib-package-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (dest / MOD_FILE).write_bytes(launcher)
        (dest / 'INSTALL_AND_TEST.md').write_text(PROTOCOL, encoding='utf-8')
    except Exception:
        if dest.exists():
            shutil.rmtree(dest)
        raise
    return {'status': 'STATIC_REVIEW_REQUIRED', 'game_validated': False, 'mod_dir': str(mod),
            'files': sorted(files), 'launcher_file': MOD_FILE, 'vanilla_modified': False}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description='Build an experimental CK3 activity-phase probe')
    p.add_argument('--recipe', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--vanilla-root', type=Path)
    args = p.parse_args(argv)
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    print(json.dumps(build(recipe, args.output, args.vanilla_root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
