# Indexeur CK3 — Spécification de la v0.2

## Objectif

Produire un **graphe de dépendances typées** à partir d'une arborescence CK3 disponible localement, sans changer le vanilla ni inclure les contenus protégés dans le dépôt. Distinguer les preuves syntaxiques de l'interprétation heuristique. Ce module n'est **pas** un compilateur complet CK3 ni un outil de validation en jeu.

## Conception et fichiers

- `src/ck3lib/indexer.py` : indexation en lecture seule, sérialisation JSON et interrogation du graphe.
- `schemas/graph.schema.json` : contrat d'échange JSON initial pour les futurs composants et adaptateurs.
- `tests/test_indexer.py` : tests hermétiques avec sources synthétiques.
- `src/ck3lib/composer.py` reste indépendant, non modifié ; aucune régression volontaire du prototype 0.1.

## Sources et contraintes

- Référence vérifiée : [`ck3-mod-base`](https://github.com/besbesbechir93-cyber/ck3-mod-base), état `1.20.0.3` dans les commits accessibles ; il n'est pas copié dans ce dépôt.
- L'utilisateur fournit `--vanilla-root` avec les dossiers `common/`, `events/`, `gui/`, `interface/`, `gfx/`, `localization/`.
- Aucun fichier `.dds`/asset binaire n'est ingéré : seul son chemin est vérifié ; les données sérialisées ne contiennent que les identifiants, chemins, positions de preuve et hachages des fichiers textuels.
- Les symlinks de fichiers/dossiers sortant du vanilla sont exclus ; encodages non UTF-8 et fichiers au-delà de 10 Mo sont signalés comme non analysés.
- Le paramètre `--version` est une **étiquette fournie**, pas une vérification automatique de l'installation. Ne jamais l'interpréter comme preuve de version.

## Utilisation

```bash
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root '/chemin/Crusader Kings III/game' \
  --version 1.20.0.3 \
  --output /tmp/ck3lib-index-12003.json \
  --query activity:activity_camp_party
```

Cette commande indexe les sources, puis fournit la fermeture transitive à partir de l'activité. Pour analyser les usages **en sens inverse** (impact potentiel d'un changement) :

```bash
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root '/chemin/Crusader Kings III/game' \
  --output /tmp/impact-clan.json \
  --query tax_slot:clan_tax_slot --reverse
```

Ne pas réutiliser un chemin de sortie existant : les fichiers sont protégés contre l'écrasement accidentel. Aucun chemin de sortie dans la racine vanilla n'est autorisé.

## Types de nœuds et preuves

| Nœud | Source | Statut |
|---|---|---|
| `file:…` | Fichier script ou chemin GFX référencé | Énumération du chemin / existence de la texture vérifiée |
| `government:…`, `tax_slot:…`, `house_unity:…` | Définitions racine dans `common/` | Support explicite |
| `activity:…`, `event:…`, `on_action:…` | Type d'activité, `id` d'événement, `on_action` | Support explicite |
| `scripted_effect:…`, `scripted_trigger:…` | Définition scriptée | Support explicite ; appel par heuristique |
| `government_flag:…` | Bloc `flags = { … }` d'un gouvernement | Support explicite |
| `gui:…`, `sprite:…` | Déclarations `name` sur widgets / sprites | Support limité aux formes reconnues |
| `localization:…` | Clés `*.yml` | Support limité aux lignes de localisation simples |

Chaque arête contient `source`, `target`, `relation`, `confidence` (`exact` ou `heuristic`) et `evidence: {path, line}`. Les types d'arêtes incluent `defines`, `declares_flag`, `references`, `calls_script`, `uses_asset`, `localizes`.

**Attention** : `exact` signifie que la relation a été observée via une forme syntaxique explicitement reconnue ; cela ne prouve **pas** la sémantique moteur, ni que le DLC / la version active l'utilise. `heuristic` signale des correspondances de nom où l'appel effectif n'est pas garanti.

## Dépendances directes, indirectes et inverses

- Directe : arête source → cible issue d'une référence reconnue.
- Indirecte : cible atteignable en traversant plusieurs arêtes, profondeur calculée par parcours en largeur.
- Inverse : tous les symboles / fichiers atteignables en suivant les arêtes à rebours ; ce résultat indique des **candidats** pour une revue d'impact, et non une preuve qu'ils cassent lors d'une modification.
- Cycles : arrêt garanti par l'ensemble des nœuds visités.
- Doublons : les identifiants définis à plusieurs emplacements déclenchent un avertissement ; ils ne sont pas supposés compatibles.

## Limitations connues

1. Pas de parseur Jomini exhaustif : opérateurs spéciaux, macro-substitutions, `scope`, variables et constructions complexes peuvent échapper à l'analyse.
2. Les dépendances indirectes dynamiques, événements déclenchés par le moteur, GUI data bindings, chaînes de textures définies hors des champs standards et DLC ne sont pas couvertes complètement.
3. La localisation indirecte et la sémantique de `trigger` ou `effect` ne sont pas vérifiées en jeu ; les références de localisation inférées sont classées `heuristic`.
4. Une référence non résolue signifie « pas de définition trouvée dans l'index » ; ce n'est **pas** une erreur CK3 démontrée.
5. Le graphe ne permet pas encore de produire une activité clonée complète et fonctionnelle ou de combiner des gouvernements en sécurité.
6. Aucune mesure de performance exhaustive ni vérification runtime CK3 n'a été faite sur une installation intégrale.

## Tests et validation

Commande : `PYTHONPATH=src python -m unittest discover -s tests -v`.

Tests : déclarations et références entre gouvernements / taxes / maisons ; flux événements imbriqués ; appels scriptés ; GUI, GFX, localisation ; chemins source et position ; relations directes / indirectes / inverses ; références manquantes ; collisions d'identifiants ; gestion des erreurs de syntaxe / encodage ; intégrité du vanilla et refus d'écrasement.

### Problèmes et prochaines étapes

- **À faire v0.3** : parseur de grammaire CK3 plus complet ; contextes d'exécution / symboles typés ; résolution dynamique ; couplage GUI↔mécanique ; recensement des références GFX implicites ; analyse de compatibilité multi-versions et DLC.
- **À faire après** : adaptateurs de clonage d'événements et de localisation, puis compilation composable sous contraintes ; tests en jeu et comparaison des journaux.
- **Décision d'architecture à valider** : faut-il imposer les preuves exactes pour toutes les dépendances bloquantes du résolveur ou autoriser un mode manuel explicitement justifié ? Tant que ce choix n'est pas validé, l'indexeur n'effectue pas de transformations automatiques.
