# v1.0.1 — Reprise et correction du bloc localisation

## Objectif

Compléter les textes de la sonde d'activité v1.0 et empêcher qu'une traduction
présente dans une langue masque une référence privée absente dans une autre.
Ce correctif ne change ni les règles de l'activité, ni les identifiants publics
de la sonde, ni ses dépendances de jeu.

## Conception et décisions conservées

- Sources vanilla en lecture seule ; aucun script ni asset du jeu ajouté au dépôt.
- Références explicites contrôlées pour chaque langue déclarée par un fichier
  de localisation du mod, y compris un fichier dont l'en-tête est seul présent.
- Sans fichier de langue, diagnostic de revue sous `english`.
- Champs reconnus : `title`, `desc`, `name`, `text`, `tooltip`, `description`,
  `custom_tooltip`, `selection_tooltip`. Les clés privées exactes `cklib_…` et
  `activity_cklib_…`, entre guillemets ou non, sont contrôlées.
- Les phrases littérales, clés externes et expressions dynamiques restent hors
  couverture. Les avertissements ne prétendent pas modéliser les replis de langue CK3.
- Le statut `game_validated` reste toujours `false`.

## Sources réellement consultées

Miroir fourni : `besbesbechir93-cyber/ck3-mod-base`, commit
[`d4cbb838b565a9f380a4bbee3c78281099fe0576`](https://github.com/besbesbechir93-cyber/ck3-mod-base/commit/d4cbb838b565a9f380a4bbee3c78281099fe0576).

| Source | Observation |
|---|---|
| [`_activity_type.info`](https://github.com/besbesbechir93-cyber/ck3-mod-base/blob/d4cbb838b565a9f380a4bbee3c78281099fe0576/base/game/common/activities/activity_types/_activity_type.info#L1089) | Valeurs par défaut documentées : suffixes `_province_desc`, `_host_desc`, `_guest_desc`, `_conclusion_desc`. |
| [`playdate_activity_l_english.yml`](https://github.com/besbesbechir93-cyber/ck3-mod-base/blob/d4cbb838b565a9f380a4bbee3c78281099fe0576/base/game/localization/english/activities/playdate_activity_l_english.yml#L22) | Convention de description de phase avec suffixe `_desc`. |
| [`camp_party.txt`](https://github.com/besbesbechir93-cyber/ck3-mod-base/blob/d4cbb838b565a9f380a4bbee3c78281099fe0576/base/game/common/activities/activity_types/camp_party.txt) | Comparaison du hook de phase ; aucune modification du hook de la sonde dans ce correctif. |

Le miroir n'est pas une preuve de la version installée chez l'utilisateur.
La recette historique de clonage reste verrouillée sur sa propre source.

## Fichiers concernés et développement

- `src/ck3lib/activity_smoke.py` : ajout de cinq descriptions dans chacune des
  deux langues générées ; structure du mod et namespace conservés.
- `src/ck3lib/validator.py` : suppression de l'union des clés de toutes les
  langues ; contrôle des références privées explicites par langue.
- `tests/test_activity_smoke.py`, `tests/test_validator.py` : régressions sur
  descriptions implicites, langue vide, absence de fichiers de langue, clés
  entre guillemets, préfixe d'activité et phrases littérales.
- `README.md` : état du prototype et limites du correctif.
- `examples/activity-smoke-v1.0.json` : métadonnée de version du mod à `1.0.1` ;
  version de recette inchangée.

## Tests

Base : 151 tests réussis avant modification. Les nouveaux tests ont reproduit
les descriptions manquantes et les références non signalées avant correction.

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
```

Résultat après correction : **157 tests réussis**. Les messages d'erreur CLI
dans la suite sont attendus par les tests de refus de destinations dangereuses.
Le test de la sonde génère un mod dans un dossier temporaire et le soumet au
validateur existant ; aucune erreur statique, avertissements GFX sans source locale.

## Problèmes et limites

- Pas d'exécution de CK3, pas de logs de partie fournis, pas de validation visuelle.
- Le validateur ne découvre toujours pas automatiquement les clés implicites
  générées par le moteur ; le test de la sonde couvre les cinq clés ajoutées.
- La présence d'un texte n'établit pas que le moteur ou la GUI appelle cette clé.
- Aucune vérification exhaustive des intentions, GFX, DLC ou de l'ordre des mods.

## Prochaines étapes

Exécuter le protocole manuel de `docs/activity-smoke-v1.0.md`, conserver les logs
et la version exacte du jeu, puis traiter les erreurs observées avant de passer
à un assemblage d'activités ou de gouvernements plus large.
