# v0.4 — Adaptateurs de réutilisation (planification uniquement)

## But

Transformer un graphe v0.3 et une demande de réutilisation en **propositions vérifiables** :
quels symboles sont conservés, exclus sous réserve d'audit ou candidats à un clonage
avec nouvel identifiant. L'outil ne copie jamais de fichiers vanilla, ne produit
pas de code CK3 et ne modifie ni `main` ni l'installation du jeu.

## Contrat

- Les noms propres sont préfixés `cklib_<namespace>_` ; les événements conservent
  la forme `namespace.integer`, les sprites `GFX_...` ; les chemins GFX copiable
  sont proposés à côté du nom original, mais **aucune copie n'est faite**.
- Le composant racine est toujours proposé au clonage ; dépendances en
  `reference` par défaut. Les demandes `clone` ou `exclude` nécessitent un
  choix explicite par identifiant indexé.
- La recette contient le SHA-256 canonique du graphe indexé. Si le graphe change,
  la recette est refusée, même si `--version` contient la même étiquette.
- Les identifiants inconnus, collisions avec le graphe, extensions non prévues,
  namespaces non conformes et chemins GFX suspects sont refusés ou signalés.
- Les références entrantes depuis des composants non clonés sont signalées pour
  éviter de casser leur fonctionnement par renommage. Les relations `defines`
  ne sont pas comptées comme des appels.
- Tous les résultats restent **REVIEW_REQUIRED** ou **STATIC_BLOCKERS_OR_GAPS**.
  « Aucun blocage statique » ne prouve jamais l'exécution correcte dans CK3.

## CLI (Python 3.10+, stdlib)

```bash
# Générer le graphe existant :
PYTHONPATH=src python -m ck3lib.indexer \
  --vanilla-root /path/to/CK3/game \
  --version 1.20.0.3 \
  --output /tmp/ck3lib-graph.json

# Produire une recette initiale, hors du dossier du jeu :
PYTHONPATH=src python -m ck3lib.adapters \
  --graph /tmp/ck3lib-graph.json \
  --init-recipe --component activity:activity_camp_party --namespace demo \
  --vanilla-root /path/to/CK3/game \
  --output /tmp/ck3lib-adapter-recipe.json

# Éditer « decisions » dans la recette pour demander les clonages utiles :
# "event:ep3_camp_party.0001": "clone"
# "file:gfx/interface/some_icon.dds": "clone"

# Simuler sans toucher aux fichiers sources :
PYTHONPATH=src python -m ck3lib.adapters \
  --graph /tmp/ck3lib-graph.json \
  --recipe /tmp/ck3lib-adapter-recipe.json \
  --vanilla-root /path/to/CK3/game \
  --output /tmp/ck3lib-adapter-plan.json
```

## Ce que la v0.4 ne fait pas

- Aucun clone réel d'événements, de phases, d'interfaces, de sprites ou de
  fichiers de localisation ; **les identifiants proposés ne créent pas ces objets**.
- Aucune réécriture aveugle de références ni de blocs de script Jomini.
- Aucune résolution des appels moteurs dynamiques, `DataContext`, substitutions
  de localisation ou fonctionnalités nécessitant un DLC.
- Aucun audit automatique du droit de redistribution des textures Paradox.
- Aucune preuve de compatibilité multijoueur, avec d'autres mods, ou en jeu.

## Prochain jalon

Développer, famille par famille, des adaptateurs *réels* testables sur un corpus
local autorisé : copie d'un objet sous nouvel ID, réécriture structurée de ses
références *déclarées*, validation des collisions, analyse différentielle
vanilla/mod, puis tests dans CK3. Chaque famille doit être livrée séparément et
approuvée ; aucune modification automatique des objets vanilla.
