# Analyse d'intégration CK3 — spécification v0.3

## Objectif

Préparer la composition de mécaniques à partir du graphe v0.2 **sans jamais modifier le vanilla** : documenter les dépendances prouvées, les références non résolues, les liaisons dynamiques (notamment GUI et ID d’événement calculé) et les sources nécessaires, et imposer une revue explicite avant toute génération de mod.

## Conception

Deux modules complémentaires :

- **Indexeur amélioré** (`src/ck3lib/indexer.py`) : reconnaissance des listes `events`, `random_events` et `on_actions` **directement** dans une définition `common/on_action`. Les listes d'événements à poids numérique sont traitées comme des références aux IDs d'événement, et non comme des symboles indépendants. Un événement ne devient une arête `exact` que si sa définition est indexée ; autrement il apparaît dans `unresolved`.
- **Diagnostic GUI** : les expressions textuelles dynamiques reconnues dans un nombre limité de propriétés GUI alimentent `dynamic_references` avec chemin, ligne et catégorie. Leur corps n'est **pas** enregistré dans le graphe, qui ne résout pas les appels runtime GUI.
- **Planificateur** (`src/ck3lib/planner.py`) : parcours de dépendances depuis un symbole, collecte des définitions sources et empreintes SHA-256 existantes, références suspectes et contrôles manuels. Ce module n'écrit pas de scripts, ne clone pas d'assets et ne crée aucun override.

Il ne s'agit **pas** encore d'un parseur complet du langage CK3, ni d'une résolution automatique des dépendances indirectes hardcodées.

## Exemple fondé sur les sources (CK3 1.20.0.3)

Dans `ck3-mod-base`, `common/on_action/activities/festival_on_actions.txt` contient `festival_random_pulse`, puis `random_events = { 50 = festival.001 ... }`. Cette forme ne produisait aucune arête événement avant la v0.3. Le nouvel indexeur prend en charge les listes simples de ce type. La présence effective de ces événements dans la source analysée doit être vérifiée localement avant résolution ; les événements absents restent `unresolved`.

Un `trigger_event = { id = ... }` dont l’ID n’a pas une forme littérale reconnue fait apparaître un diagnostic `dynamic_event_id_unresolved` sans conserver la valeur brute. Les graphismes `gfx/...` ne sont toujours **que référencés**, jamais dupliqués dans l'index. Le clonage GFX existant dans le prototype v0.1 reste isolé ; il n'est pas activé par le planificateur.

## Utilisation

```bash
# Index JSON dans un dossier extérieur à l'installation CK3.
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root '/chemin/Crusader Kings III/game' \
  --version 1.20.0.3 \
  --output /tmp/ck3-graph-v03.json

# Audit d'intégration d'un composant. Ne produit aucun mod.
PYTHONPATH=src python -m ck3lib.planner \
  --graph /tmp/ck3-graph-v03.json \
  --component activity:activity_camp_party \
  --output /tmp/ck3-camp-party-plan.json
```

Les sorties ne sont jamais écrasées. Les sorties JSON doivent être placées **hors du dossier du jeu**. La valeur `--version` est une étiquette et non une vérification de version.

## Contrat de données

`schemas/graph.schema.json` conserve `schema_version = 1` ; `dynamic_references` est une extension facultative compatible avec la v0.2. Chaque entrée mentionne uniquement la catégorie, la propriété, la source et sa position. La valeur originale de l'expression GUI n'est pas reproduite.

`schemas/integration-plan.schema.json` définit un plan avec les champs :

- `component` et `dependency_nodes` (fermeture transitive statique) ;
- `referenced_files` : chemins sources (et SHA-256 si fichier textuel indexé), toujours en lecture seule ;
- `unresolved` et `warnings` : défauts potentiels non prouvés ;
- `dynamic_references` et `heuristic_edges` : éléments à inspecter manuellement ;
- `review_requirements`, `game_validated = false`, `generates_mod = false` ;
- `status = STATIC_BLOCKERS_OR_GAPS` si une référence explicite non trouvée dans l'index ou un doublon / échec de parse / asset non vérifié touche le composant. Sinon `REVIEW_REQUIRED` **jamais SAFE**.

## Décisions et restrictions

1. Les listes `on_action` ne couvrent que les formes simples documentées et vérifiées. Les dispatchs moteur, générateurs d'événements dynamiques, listes conditionnelles imbriquées, substitutions et macros nécessitent encore une analyse manuelle.
2. Les diagnostics GUI sont des **signaux**, non des dépendances effectivement résolues.
3. Aucun `on_action` n'est automatiquement copié ou remplacé. Les noms et IDs de code vanilla demeurent intacts.
4. Les composants avec références manquantes ne doivent pas être composés automatiquement ; tous les autres restent soumis à validation en jeu et à la revue des DLC.
5. Les fichiers propriétaires CK3 n'entrent pas dans le dépôt ; les tests utilisent des fixtures synthétiques.

## Fichiers concernés

- `src/ck3lib/indexer.py` — enrichissements v0.3.
- `src/ck3lib/planner.py` — nouveau rapport de revue.
- `schemas/graph.schema.json` et `schemas/integration-plan.schema.json` — contrats JSON.
- `tests/test_indexer.py`, `tests/test_planner.py` — tests unitaires.
- `README.md` — commande utilisateur, limites et statut.

## Tests

Exécuter `PYTHONPATH=src python -m unittest discover -s tests -v` et `python -m compileall -q src tests`. Couverture : poids d'événements, listes `on_actions`, références non résolues, événements dans des blocs imbriqués ignorés, classification GUI dynamique, transitive, collisions d'identifiants, sortie protégée, absence de génération de mods.

## Problèmes et prochaines étapes

- Tests en jeu non réalisés ; analyse complète du vanilla 1.20.x non réalisée ; propriétés GUI et GFX pas exhaustives.
- Définir et valider des adaptateurs explicites pour les événements, GUI, localisations et GFX ; différencier dépendances nécessaires et optionnelles ; supporter les DLC et les versions par empreinte.
- Préparer un mode *dry-run* de la future compilation qui générera d'abord les changements attendus sans modifier le jeu.
