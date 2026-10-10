# Audit de référence : `activity_camp_party` (CK3 1.20.0.3)

## Source inspectée
`ck3-mod-base/base/game/common/activities/activity_types/camp_party.txt`, Git blob `8a3990c21ec7a84438696747aa368b2c1a67b0fe`, commit `0ec1335`.

## Constatations directes
- Racine : `activity_camp_party`.
- Restrictions : `has_ep3_dlc_trigger`, `landless_adventurer_government`.
- Coût : `standard_camp_party_activity_cost` et conditions/modificateurs.
- Cooldown : `standard_camp_party_cooldown_time`.
- Phases : `phase_camp_party` avec `trigger_event` (par exemple `ep3_camp_party.0001`, `ep3_camp_party.0009`) et `on_action = camp_party_destination_events`.
- Options : restauration et coûts propres ; autres dépendances à auditer plus loin.

## Proposition de clone
Créer `cklib_activity_camp_party_demo` avec `cooldown.years = 2` et `max_province_icons = 2`, tout en préservant le fichier vanilla. Si le hachage ne correspond pas : refus.

## Limites
Ce clone gardera des appels aux événements originaux, des descriptions et références vanilla ; aucune indépendance fonctionnelle complète garantie. Une activité autonome nécessite une exploration et une adaptation supplémentaires de ces références, ainsi que de la localisation et de l'interface.

## Tests et état
Tests uniquement sur source synthétique ; pas de test CK3 en jeu. Audit partiel, pas inventaire exhaustif de `camp_party.txt`.
