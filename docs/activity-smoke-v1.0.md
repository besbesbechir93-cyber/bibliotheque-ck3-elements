# v1.0 — Sonde d'activité CK3 (expérimentale)

## Objectif

Après le test décision/événement v0.9, produire une **nouvelle activité** comportant une phase prédéfinie. Cette phase déclenche un événement `cklib_activity_probe_v10.0001` distinct du contrôle de chargement `cklib_activity_probe_v10.9001`.

La recette est paramétrable (`cooldown_days`, `gold_cost`, `prestige_reward`) et génère un mod complet dans un **nouveau dossier** : `descriptor.mod`, scripts d'activité, de décision et d'événements, localisations en anglais/français, fichier `.mod` du launcher et protocole d'essai. Les GFX sont référencés par chemins vanilla (pas de copie dans GitHub).

## Vérifications et statut

Le compilateur vérifie les types des paramètres, les bornes numériques, l'existence de la destination, les symlinks parents et le non-chevauchement du dossier vanilla. L'ensemble des tests automatisés ne peut **pas confirmer** que CK3 rendra correctement l'activité. Le comportement `on_phase_active` provient du schéma `_activity_type.info` et du script vanilla `camp_party.txt` de la version de référence 1.20.0.3, sans reprise du code propriétaire dans le projet.

La décision de contrôle est séparée du déclencheur d'activité. Succès de la décision = chargement partiel seulement ; apparition de l'activité = affichage seulement ; **événement `.0001` déclenché par la phase** = test d'intégration plus convaincant, à croiser avec les logs d'erreur.

## Utilisation

```bash
PYTHONPATH=src python -m ck3lib.activity_smoke \
  --recipe examples/activity-smoke-v1.0.json \
  --output /tmp/cklib-v1-activity
PYTHONPATH=src python -m unittest discover -s tests -q
```

Dans le dossier de sortie, consulter `INSTALL_AND_TEST.md` et copier le dossier `cklib_activity_probe_v10` et `cklib_activity_probe_v10.mod` dans le répertoire CK3 `mod/`.

## Non-objectifs et risques

- Pas un clonage intégral d'une activité vanilla, ni une preuve d'assemblage de gouvernements.
- Aucune adaptation profonde GUI, DLC ou localisation dynamique.
- Le mod peut nécessiter des propriétés additionnelles propres au moteur ; noter toute erreur réelle et ne pas considérer le statut statique comme un succès.
- Aucun contenu GFX ou script vanilla n'est redistribué.
