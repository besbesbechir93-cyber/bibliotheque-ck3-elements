# Bibliothèque CK3 Elements

**Statut : prototype expérimental 0.1 — non validé en jeu.** Ce dépôt vise une bibliothèque composable de mécaniques CK3 et un futur compilateur de mods. Il ne contient aucun fichier vanilla ni texture propriétaire.

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

## Structure

- `docs/architecture.md` : architecture et politiques de composition.
- `docs/activity-camp-party.md` : audit initial du cas pilote et limites.
- `schemas/component.schema.json` : contrat de composant (brouillon, distinct de la recette).
- `examples/` : recette d'activité et contrat de composant.
- `src/ck3lib/composer.py` : compilateur expérimental en lecture seule côté vanilla.
- `tests/` : tests avec données synthétiques, aucun asset Paradox.

## Étapes suivantes

Analyseur CK3 robuste et graphe de références typées ; adaptateurs d'événements / localisation / GUI ; clonage de dépendances optionnelles ; validation CK3 1.20.x et DLC ; rapports de conflits et diff; puis composition multi-composants (fiscalité, mérite, maisons, blocs, etc.).
