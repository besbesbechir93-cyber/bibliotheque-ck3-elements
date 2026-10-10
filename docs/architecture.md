# Architecture — Proposition 0.1

## Objectif
Passer d'un inventaire descriptif à des composants recomposables : capacités, exigences, paramètres, intégrations et vérifications.

## Conception
1. **Catalogue vanilla versionné** : fichiers, SHA, identifiants, définitions, chemin, DLC, GUI/GFX/localisation. Lecture seule.
2. **Graphe typé** : `declares`, `references`, `triggers`, `uses_asset`, `requires_dlc`, `overrides`, `conflicts` avec preuve (chemin + ligne) et confiance.
3. **Composants** : contrat (schéma), capacités `provides`, `requires`, `conflicts`, paramètres autorisés et tests.
4. **Adaptateurs** : ponts explicites entre capacités (ex. `clan_tax_slot` dans un gouvernement non clanique). Jamais inférer qu'un simple flag suffit.
5. **Résolveur** : fermeture transitive, cycles, collisions de noms, vérification version et dépendances moteur/hardcoded.
6. **Générateur** : réutiliser une référence vanilla, étendre par nom nouveau, cloner puis réécrire les références contrôlées, ou override **seulement avec acceptation**.
7. **Vérification** : validation syntaxique, scan de références, tests d'intégration et rapport des conflits (`error.log`, `database_conflicts.log`).

## Stratégies et risque
| Stratégie | Usage | Risque |
|---|---|---|
| `reference` | Pointer sur le vanilla | faible |
| `extend` | Ajouter identifiants/scripts séparés | faible à moyen |
| `clone` | Nouvelle définition + références réécrites | moyen/élevé |
| `override_review_required` | Modifier définitions/fichiers remplacés au chargement | élevé |

La priorité est l'absence d'override, **pas une promesse de compatibilité parfaite**. CK3 applique des règles de chargement différentes selon les catégories (définitions, événements, `on_action`, GUI, localisation). Tout adaptateur porte une règle par version.

## Décisions actives du prototype
- Type traité : `activity_clone` uniquement.
- Source : `common/activities/activity_types/camp_party.txt` dans le jeu local ou miroir obtenu séparément.
- Le SHA Git du fichier source doit correspondre exactement.
- Deux paramètres permis : `cooldown.years`, `max_province_icons` ; `sort_order` si déjà présent.
- Seules les références identiques à l'identifiant racine sont renommées ; chaînes et commentaires préservés. Les références externes demeurent vanilla et **ne sont pas résolues**.
- GFX : possibilité de copier un fichier local avec nouvelle référence entre guillemets. Pas de redistribution de fichiers du jeu dans le dépôt.
- Pas de mise en jeu automatique ; l'activité clonée est **expérimentale**, non certifiée.

## Dépendances et risques connus
Cloner une définition d'activité ne suffit pas à cloner ses `events`, `on_actions`, localisations, icônes, phases et effets ; une phase peut invoquer un événement qui cherche l'identifiant original. Tout ajout de gouvernement doit contrôler les flags *et* les conditions scriptées et moteur.

## Tests
Tests unitaires sur fixture synthétique ; à compléter par vérification syntaxique dans l'environnement CK3, inspection des logs, test en partie et test de régression sur plusieurs DLC/mises à jour.

## Problèmes
Un lexer conservateur n'est pas un parseur CK3 complet. Les dépendances dans `trigger_event` sont recensées partiellement, sans garantie d'exhaustivité. Les modifications de la recette échouent volontairement si le fichier de base change.

## Prochaines étapes
Implémenter AST complet, identifiants typés, graphe avec preuve source, mode dry-run et adaptateurs de clonage d'événements/localisation/GUI ; seulement ensuite système de compositions gouvernementales.
