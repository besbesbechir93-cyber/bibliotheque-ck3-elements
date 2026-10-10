"""v0.9 — reproducible, vanilla-safe CK3 decision-to-event smoke-test mod.

This is a minimal game integration probe, not an activity clone, nor evidence
of successful game execution. No proprietary Paradox assets are redistributed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .composer import CompositionError, git_blob_sha

MOD_DIR = 'cklib_smoke_v09'
MOD_FILE = MOD_DIR + '.mod'
MOD_DESCRIPTOR = 'descriptor.mod'
DECISION_FILE = 'common/decisions/cklib_smoke_v09.txt'
EVENT_FILE = 'events/cklib_smoke_v09.txt'
ENGLISH_LOC = 'localization/english/cklib_smoke_l_english.yml'
FRENCH_LOC = 'localization/french/cklib_smoke_l_french.yml'
VANILLA_PICTURE = 'gfx/interface/illustrations/decisions/decision_misc.dds'
VERSION = re.compile(r'\d+\.\d+\.\d+\Z')
SUPPORTED = re.compile(r'\d+\.\d+\.\*\Z')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._-]{2,64}\Z')


def _validate_recipe(recipe: dict) -> dict:
    fields = {'version', 'mod_name', 'mod_version', 'supported_version',
              'cooldown_days', 'prestige_reward'}
    if not isinstance(recipe, dict) or set(recipe) != fields or recipe['version'] != 1:
        raise CompositionError('Invalid smoke-demo recipe fields/version')
    if not isinstance(recipe['mod_name'], str) or not NAME.fullmatch(recipe['mod_name']):
        raise CompositionError('Invalid mod name')
    if not isinstance(recipe['mod_version'], str) or not VERSION.fullmatch(recipe['mod_version']):
        raise CompositionError('Invalid version string')
    if not isinstance(recipe['supported_version'], str) or not SUPPORTED.fullmatch(recipe['supported_version']):
        raise CompositionError('Invalid supported game version')
    if type(recipe['cooldown_days']) is not int or not 1 <= recipe['cooldown_days'] <= 3650:
        raise CompositionError('Cooldown must be between 1 and 3650 days')
    if type(recipe['prestige_reward']) is not int or not 0 <= recipe['prestige_reward'] <= 100:
        raise CompositionError('Prestige reward must be between 0 and 100')
    return recipe


def _files(recipe: dict) -> dict[str, bytes]:
    name, version, supported = (recipe[k] for k in ('mod_name', 'mod_version', 'supported_version'))
    descriptor = (f'name="{name}"\nversion="{version}"\nsupported_version="{supported}"\n')
    decision = f'''# CKLib v0.9 smoke probe. Does not override any vanilla key.
cklib_smoke_v09_decision = {{
    ai_check_interval = 0
    sort_order = 100
    picture = {{ reference = "{VANILLA_PICTURE}" }}
    desc = cklib_smoke_v09_decision_desc
    selection_tooltip = cklib_smoke_v09_decision_tooltip
    cooldown = {{ days = {recipe['cooldown_days']} }}
    is_shown = {{ is_ai = no }}
    is_valid_showing_failures_only = {{ is_adult = yes }}
    effect = {{ trigger_event = cklib_smoke_v09.0001 }}
    ai_potential = {{ always = no }}
    ai_will_do = {{ base = 0 }}
}}
'''
    event = f'''# Standalone character event; a new namespace and an explicit entrypoint.
namespace = cklib_smoke_v09

cklib_smoke_v09.0001 = {{
    type = character_event
    title = cklib_smoke_v09.0001.t
    desc = cklib_smoke_v09.0001.desc
    option = {{
        name = cklib_smoke_v09.0001.a
        add_prestige = {recipe['prestige_reward']}
    }}
}}
'''
    english = '''\ufeffl_english:
 cklib_smoke_v09_decision:0 "CKLib integration test"
 cklib_smoke_v09_decision_desc:0 "Trigger a small test event to check whether CKLib content loads."
 cklib_smoke_v09_decision_tooltip:0 "Show the CKLib test event"
 cklib_smoke_v09.0001.t:0 "CKLib test event"
 cklib_smoke_v09.0001.desc:0 "The test event opened. Record this result for validation."
 cklib_smoke_v09.0001.a:0 "Continue"
'''
    french = '''\ufeffl_french:
 cklib_smoke_v09_decision:0 "Test d'intégration CKLib"
 cklib_smoke_v09_decision_desc:0 "Déclenche un événement de test pour vérifier le chargement de CKLib."
 cklib_smoke_v09_decision_tooltip:0 "Afficher l'événement de test CKLib"
 cklib_smoke_v09.0001.t:0 "Événement de test CKLib"
 cklib_smoke_v09.0001.desc:0 "L'événement de test est apparu. Consignez ce résultat pour la validation."
 cklib_smoke_v09.0001.a:0 "Continuer"
'''
    return {
        MOD_DESCRIPTOR: descriptor.encode('utf-8'),
        DECISION_FILE: decision.encode('utf-8-sig'),
        EVENT_FILE: event.encode('utf-8-sig'),
        ENGLISH_LOC: english.encode('utf-8'),
        FRENCH_LOC: french.encode('utf-8'),
    }


def build(recipe: dict, output: Path, vanilla_root: Path | None = None) -> dict:
    """Create a *new* install bundle; never overwrite, never edit game files."""
    _validate_recipe(recipe)
    dest = output.absolute()
    if dest.exists() or dest.is_symlink():
        raise CompositionError('Output already exists')
    if not dest.parent.is_dir() or dest.parent.is_symlink():
        raise CompositionError('Output parent must exist and must not be a symlink')
    parent = dest.parent.resolve(strict=True)
    dest = parent / dest.name
    if vanilla_root is not None:
        if vanilla_root.is_symlink() or not vanilla_root.is_dir():
            raise CompositionError('Invalid vanilla root')
        vanilla = vanilla_root.resolve(strict=True)
        if dest == vanilla or dest.is_relative_to(vanilla) or vanilla.is_relative_to(dest):
            raise CompositionError('Output overlaps vanilla')
    content = _files(recipe)
    report = {
        'version': 1, 'status': 'PACKAGED_UNVALIDATED', 'game_validated': False,
        'changes_vanilla': False, 'is_complete_mod': False,
        'source': 'CKLib v0.9 generated smoke test (not a vanilla clone)',
        'generated_files': sorted(content),
        'file_sha': {path: git_blob_sha(data) for path, data in sorted(content.items())},
        'test': 'player decision -> custom character_event -> option',
        'limitations': ['No CK3 runtime test performed', 'Decision/event smoke test, not an activity clone'],
    }
    content['cklib-package-report.json'] = (json.dumps(report, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    launcher = (
        f'name="{recipe["mod_name"]}"\nversion="{recipe["mod_version"]}"\n'
        f'supported_version="{recipe["supported_version"]}"\npath="mod/{MOD_DIR}"\n'
    ).encode('utf-8')
    try:
        dest.mkdir()
        folder = dest / MOD_DIR
        folder.mkdir()
        for rel, data in content.items():
            path = folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (dest / MOD_FILE).write_bytes(launcher)
        (dest / 'INSTALL_AND_TEST.md').write_text(TEST_PROTOCOL, encoding='utf-8')
    except Exception:
        if dest.exists():
            shutil.rmtree(dest)
        raise
    return {'status': 'PACKAGED_UNVALIDATED', 'game_validated': False,
            'mod_dir': str(folder), 'files': sorted(content),
            'launcher_file': MOD_FILE, 'vanilla_modified': False}


TEST_PROTOCOL = '''# CKLib v0.9 — protocole de test manuel

**Aucun essai dans CK3 n'a encore été effectué.** Le test est une décision qui
ouvre un événement, et non une activité complète.

1. Copier le dossier `cklib_smoke_v09` **et** le fichier `cklib_smoke_v09.mod`
   dans `Documents/Paradox Interactive/Crusader Kings III/mod/`. Sur certains
   systèmes, le dossier Documents peut être redirigé vers OneDrive.
2. Activer « CKLib v0.9 Smoke Test » dans le launcher CK3 (profil/playset dédié).
   Ne pas activer d'autres mods pour ce premier essai.
3. Lancer CK3 1.20.x, charger une partie de test avec un personnage adulte.
4. Ouvrir **Décisions** ; chercher « Test d'intégration CKLib » (ou son nom anglais).
5. Cliquer sur la décision et vérifier l'ouverture de l'événement « Événement de test CKLib ».
6. Choisir « Continuer ». Noter l'heure, la version du jeu, l'ID du mod, le succès/échec.
7. Consulter `Documents/Paradox Interactive/Crusader Kings III/logs/error.log`
   et `game.log` après le test, puis les passer au validateur CKLib v0.8.
8. Si la décision est absente, relever la présence du mod dans le launcher, les
   éventuelles erreurs de parsing et les clés non localisées.

La présence d'un événement est une observation manuelle ; un rapport statique
ne prouve pas que CK3 a chargé le mod. Aucun override vanilla, aucune ressource
GFX copiée : l'illustration de décision référence un chemin GFX vanilla.
'''


def main(argv=None):
    p = argparse.ArgumentParser(description='Generate the standalone CKLib v0.9 smoke-test mod bundle')
    p.add_argument('--recipe', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--vanilla-root', type=Path)
    args = p.parse_args(argv)
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    print(json.dumps(build(recipe, args.output, args.vanilla_root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
