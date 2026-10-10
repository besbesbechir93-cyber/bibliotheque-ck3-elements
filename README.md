# Bibliothèque CK3 Elements

**Statut : prototypes 0.1–0.5 expérimentaux — non validés en jeu.** Ce dépôt vise une bibliothèque composable de mécaniques CK3 et un futur compilateur de mods. Il ne contient aucun fichier vanilla ni texture propriétaire.

## Principes non négociables

1. Sources vanilla immuables : jamais d'écriture dans l'installation du jeu.
2. Identifiants nouveaux (`cklib_…`) ; aucun override vanilla implicite.
3. Version et empreinte Git du fichier source obligatoires avant transformation.
4. Paramètres sur liste blanche : toute transformation non connue est refusée.
5. Dépendances explicites, évaluation des conflits et statut des tests.
6. GFX vanilla référencés par défaut ; duplication locale uniquement sur déclaration explicite et avec source obtenue légalement.

## Prototype disponible

Clonage **structurel** d'une activité sous un identifiant distinct, modification de `cooldown.years` et `max_province_icons`, renvoi d'un rapport de dépendances externes (partiel), copie facultative de GFX à nouveau chemin. La génération n'implique pas que l'activité sera jouable : événements, GUI, localisations, scripts associés et comportement moteur ne sont PAS résolus.

### Utilisation (Python 3.10+)

```bash
PYTHONPATH=src python -m ck3lib.composer \
  --recipe examples/camp_party_clone.json \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --output /chemin/vers/cklib_generated_mod

PYTHONPATH=src python -m unittest discover -s tests -v
```

L'exemple est **verrouillé sur la version 1.20.0.3** (`source_git_blob_sha`). Si les octets locaux diffèrent, la génération s'arrête : il faut vérifier et mettre à jour la recette, pas contourner ce contrôle. Le miroir de référence accessible est [`ck3-mod-base`](https://github.com/besbesbechir93-cyber/ck3-mod-base), commit [`0ec1335`](https://github.com/besbesbechir93-cyber/ck3-mod-base/commit/0ec13350cde9e410b37a46d3616966838f4ba994).

Le dossier généré contient `descriptor.mod`, le script d'activité et `composition-report.json`. Pour installation réelle, utiliser le lanceur Paradox pour préparer les fichiers `.mod` et valider en jeu ; ce prototype ne les configure pas automatiquement.

## Analyse des dépendances — v0.2 (statique, partielle)

L'indexeur lit en **lecture seule** les scripts, définitions, GUI/GFX textuels et clés de localisation, puis produit un graphe JSON avec les références typées, leurs preuves (fichier/ligne), les avertissements et les références non résolues.

```bash
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --output /tmp/ck3lib-graph.json \
  --version 1.20.0.3 \
  --query activity:activity_camp_party

# Analyse inverse : quels composants indexés dépendent d'une capacité ?
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --output /tmp/ck3lib-impact.json \
  --query tax_slot:clan_tax_slot --reverse
```

**Important :** ce n'est ni un parseur CK3 exhaustif, ni une preuve de compatibilité en jeu ; les références dynamiques, nombreuses liaisons GUI et comportements hardcodés restent non résolus. Les « références non résolues » ne démontrent pas un défaut du jeu. Une version indiquée par `--version` est uniquement une étiquette. Voir [la spécification v0.2](docs/dependency-indexer.md).

## Préparation de composition — v0.3 (revue seulement)

L'indexeur reconnaît désormais certaines listes d'événements des `on_action` (`events`, `random_events`, `on_actions`). Il enregistre aussi des **indices de liaisons GUI dynamiques non résolues** sans exposer le contenu des expressions. Le nouveau planificateur fournit un rapport de dépendances et de risques par composant, **sans générer ni modifier de mod** :

```bash
PYTHONPATH=src python -m ck3lib.planner \
  --graph /tmp/ck3lib-graph.json \
  --component activity:activity_camp_party \
  --output /tmp/ck3lib-camp-party-plan.json
```

Tous les statuts demandent une validation manuelle ; `REVIEW_REQUIRED` ne signifie jamais compatible avec CK3. Les dépendances hardcodées, la plupart des data bindings GUI, les DPI des sprites et les contenus DLC conditionnels restent hors couverture. Voir [la spécification v0.3](docs/integration-planner.md).

## Adaptateurs de dépendances — v0.4 (simulation, aucun mod généré)

L'outil `ck3lib.adapters` transforme un graphe existant et une recette versionnée
en **intentions de référence, exclusion ou clonage**. Il propose des nouveaux
identifiants pour événements, GUI, GFX et localisation, détecte certaines
collisions et références entrantes, et interdit les surcharges vanilla.
**Il ne recopie aucun asset, ne modifie aucun script et ne génère aucun mod.**

```bash
PYTHONPATH=src python -m ck3lib.adapters \
  --graph /tmp/ck3lib-graph.json \
  --init-recipe --component activity:activity_camp_party --namespace demo \
  --vanilla-root /path/to/CK3/game \
  --output /tmp/ck3lib-adapter-recipe.json

PYTHONPATH=src python -m ck3lib.adapters \
  --graph /tmp/ck3lib-graph.json \
  --recipe /tmp/ck3lib-adapter-recipe.json \
  --vanilla-root /path/to/CK3/game \
  --output /tmp/ck3lib-adapter-plan.json
```

Voir [le guide v0.4](docs/adapter-dry-run.md) pour les risques et limites.

## Clonage d’événements — v0.5 (fragment exécutable, strict)

Le module `ck3lib.event_cloner` est le premier **exécuteur** du pipeline : il
clone un **fichier d'événements complet** dans un dossier neuf, avec un namespace
propre, un inventaire de ses événements et une empreinte de source obligatoires.
Il ne remplace jamais de scripts vanilla et ne modifie pas les fichiers du jeu.

```bash
PYTHONPATH=src python -m ck3lib.event_cloner \
  --recipe /chemin/vers/event-recipe.json \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --output /chemin/vers/nouveau_fragment_evenements
```

**Important :** sorties = fragment de mod + rapport, *sans* activation d'événements
ni connexion des `on_action`. Les GUI, GFX, localisations et dépendances
externes ne sont ni copiés ni garantis. Le parseur refuse les fichiers avec des
déclarations ou références qu'il ne sait pas traiter. Voir
[le guide v0.5](docs/event-file-cloner.md).

## Structure

- `docs/architecture.md` : architecture et politiques de composition.
- `docs/activity-camp-party.md` : audit initial du cas pilote et limites.
- `schemas/component.schema.json` : contrat de composant (brouillon, distinct de la recette).
- `examples/` : recette d'activité et contrat de composant.
- `src/ck3lib/composer.py` : compilateur expérimental en lecture seule côté vanilla.
- `src/ck3lib/indexer.py` : indexeur statique, traversée de graphe et analyse inverse.
- `src/ck3lib/planner.py` : audit de composition sans génération de mod.
- `src/ck3lib/adapters.py` : planification de réutilisation/clonage, sans génération.
- `src/ck3lib/event_cloner.py` : clonage strict de fichiers d’événements entiers vers un fragment neuf.
- `schemas/event-clone-recipe.schema.json` et `docs/event-file-cloner.md` : recette et limitations v0.5.
- `schemas/adapter-recipe.schema.json` et `schemas/adapter-plan.schema.json` : contrats v0.4.
- `schemas/integration-plan.schema.json` : contrat du rapport d'intégration.
- `docs/integration-planner.md` : spécification et limites v0.3.
- `schemas/graph.schema.json` : contrat du graphe JSON.
- `docs/dependency-indexer.md` : spécification, limites, tests et prochaines étapes.
- `tests/` : tests avec données synthétiques, aucun asset Paradox.

## Étapes suivantes

À partir de la v0.3 : adaptateurs d'événements / localisation / GUI, mécanisme de clonage des dépendances optionnelles, validation CK3 1.20.x et DLC, rapports de conflits et diff, puis composition multi-composants (fiscalité, mérite, maisons, blocs).

## Assemblage activité + événements + `on_action` — v0.6 (fragment lié, expérimental)

Le module `ck3lib.wiring` part d'un fragment de clone d'événements v0.5
et de deux sources vanilla à SHA Git verrouillé (un fichier d'activité et
un fichier `on_action`, chacun à déclaration unique). Il produit un **nouveau
fragment** avec une activité, un `on_action` privés et les événements clonés,
en redirigeant uniquement les appels statiques reconnus. Il ne modifie ni
les sources du jeu ni le fragment v0.5 d'origine.

```bash
PYTHONPATH=src python -m ck3lib.wiring \
  --recipe /chemin/vers/wiring.json \
  --vanilla-root /chemin/vers/CK3/game \
  --event-fragment /tmp/cklib-events-v05 \
  --output /tmp/cklib-linked-v06
```

**Attention :** ce n'est pas un mod complet et rien n'a été validé en jeu.
Les fichiers vanilla regroupant plusieurs définitions et les dépendances
GUI/GFX/localisation nécessitent d'autres adaptateurs. Voir
[le guide v0.6](docs/activity-on-action-wiring.md).
