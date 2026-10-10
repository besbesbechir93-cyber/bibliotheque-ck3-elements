# v0.8 — Banc de validation statique CK3

## Objectif et statut

Le validateur **ne lance pas Crusader Kings III**. Il analyse en lecture seule le dossier de mod produit par `ck3lib.package_mod` (v0.7), un dossier vanilla facultatif et des journaux `error.log`/`game.log` facultatifs. Il produit un **rapport JSON** écrit dans un nouvel emplacement indépendant.

Il n'affirme **jamais** qu'un mod a chargé ou fonctionné dans le jeu : le champ `game_validated` reste `false`, même si aucune erreur n'est détectée. Deux états sont possibles : `STATIC_REVIEW_REQUIRED` et `STATIC_FINDINGS_REVIEW_REQUIRED`.

## Commandes

```bash
PYTHONPATH=src python -m ck3lib.validator \
  --mod-dir /chemin/vers/mon_mod_genere \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --report-out /tmp/cklib-validation.json

# Après un lancement manuel du jeu, en fournissant les journaux correspondants :
PYTHONPATH=src python -m ck3lib.validator \
  --mod-dir /chemin/vers/mon_mod_genere \
  --vanilla-root /chemin/vers/Crusader\ Kings\ III/game \
  --log-dir /chemin/vers/Crusader\ Kings\ III/logs \
  --report-out /tmp/cklib-validation-apres-test.json
```

Le chemin `--report-out` doit désigner **un nouveau fichier** dans un dossier existant, extérieur au mod, au jeu et aux logs. Aucun des fichiers d'entrée n'est réécrit.

## Couverture (explicite et limitée)

| Contrôle | Preuve produite | Ce qui n'est **pas** démontré |
|---|---|---|
| Manifeste/descriptor | présence, champs, version, fichiers déclarés | activabilité dans le launcher |
| Arborescence | refus des chemins inconnus, symlinks et fichiers trop volumineux | compatibilité intermods |
| Scripts `cklib_` | chaînes valides, accolades équilibrées, identifiants et namespaces | syntaxe CK3 complète ou exécution des effets |
| Événements et `on_action` | déclarations, certains appels de `trigger_event` | appels dynamiques ou requêtes moteur |
| Localisation | UTF-8 BOM, en-tête, doublons, clés `cklib_` directes | évaluation de la localisation dynamique |
| GFX | présence des fichiers cités sous forme de chemins explicites | bon rendu, sprites, GUI ou DPI |
| Logs | lignes avec erreurs liées aux identifiants `cklib_` ou aux fichiers générés | date, version, ordre de chargement, causalité certaine |

Les appels à des événements vanilla ou externes sont des **avertissements** tant que leur présence réelle n'est pas prouvée ; une référence `cklib_` manquante est une **erreur statique**. Une référence dynamique inconnue peut ne pas être détectée.

## Critères de validation réelle en jeu

Pour établir un test d'intégration, documenter séparément :

1. Version exacte de CK3, extensions activées et empreinte du mod chargé.
2. Ordre de chargement des mods et profil launcher.
3. Heure ou session de jeu associée aux journaux collectés.
4. Lancement d'une partie de test, affichage de l'activité, déclenchement de l'événement et inspection des GUI/GFX.
5. Erreurs avant et après chargement, ainsi que toute référence résiduelle au vanilla.

**Ce dispositif n'automatise pas ces étapes.** Une absence de ligne d'erreur n'est pas une certification. Ne pas fusionner de mécanismes de gouvernements complexes sur la seule base d'une validation statique.

## Compatibilité et provenance

Source de travail : dépôt `bibliotheque-ck3-elements` v0.7 fusionné ; toutes les vérifications v0.8 utilisent des fixtures synthétiques. Aucun asset vanilla ne figure dans le dépôt. Le module n'exécute aucun script du jeu et n'écrit jamais dans son répertoire.
