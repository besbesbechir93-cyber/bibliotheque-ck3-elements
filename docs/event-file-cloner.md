# v0.5 — Clonage strict d'un fichier d'événements CK3

**Prototype exécutable, mais pas générateur de mod complet.** Le moteur lit une source vanilla locale en lecture seule, vérifie son empreinte Git exacte, duplique son contenu dans un **nouveau dossier** avec un namespace neuf, puis écrit un manifeste de migration. Aucun changement dans `game/`.

## Ce qui fonctionne

- Une source `game/events/.../*.txt` avec **un seul `namespace`** et **uniquement des définitions d'événements** à la racine ; les fichiers contenant des helpers/scripts supplémentaires sont refusés.
- Définitions à la racine (`foo.123 = { … }`) ou blocs `character_event = { id = foo.123 … }` et quelques types analogues.
- Renommage structurel de toutes les déclarations et des références internes **connues** : `trigger_event = foo.2`, `trigger_event = { id = foo.2 }`, `random_events = { 50 = foo.2 }` et `events = { foo.2 }`.
- Les commentaires, chaînes et clés de localisation ne sont pas remplacés aveuglément. Une référence numérique présente dans une chaîne entre guillemets fait échouer le traitement.
- La liste exacte des événements attendus et le `source_git_blob_sha` sont obligatoires. Une référence au même namespace, mais absente du bundle, bloque le clonage.
- Refus de tout chemin de sortie déjà existant, des sources symlinkées, d'un chemin inclus dans la source vanilla, et des noms de namespace déjà présents dans `game/events`.

## Exemple de recette (fichier local synthétique)

```json
{
  "version": 1,
  "source_path": "events/my_test_events.txt",
  "source_git_blob_sha": "REMPLACER_PAR_SHA_GIT_EXACT_DE_LA_SOURCE",
  "source_namespace": "my_test",
  "expected_event_ids": ["my_test.1", "my_test.2"],
  "namespace": "demo",
  "source_version_label": "1.20.0.3"
}
```

L'empreinte se calcule sur les **octets originaux** du fichier :

```bash
python -c 'from pathlib import Path; from ck3lib.composer import git_blob_sha; print(git_blob_sha(Path("/chemin/CK3/game/events/my_test_events.txt").read_bytes()))'

PYTHONPATH=src python -m ck3lib.event_cloner \
  --recipe /chemin/vers/recipe.json \
  --vanilla-root /chemin/vers/CK3/game \
  --output /chemin/vers/nouveau_fragment
```

Résultat : `nouveau_fragment/events/cklib_demo_my_test_events.txt` et `nouveau_fragment/event-clone-report.json`.

## Limites importantes

1. **Aucune connexion des événements clonés aux `on_action`, activités, interactions ou scripts vanilla externes.** Ces appels continueront à viser les identifiants originaux tant que des adaptateurs additionnels ne seront pas générés.
2. Aucun clonage de `gui/`, `gfx/`, `localization/`, scripts, sons, icônes ou DLC. Les textes éventuels peuvent continuer à référencer des clés de localisation vanilla ; ceci doit être revu.
3. Le parseur est volontairement restreint : plusieurs formes Jomini/CK3 réellement valides restent incompatibles. En cas de forme ambiguë, il échoue au lieu de deviner.
4. Le fichier de sortie constitue un **fragment de mod**, sans `descriptor.mod`. Sa compilation avec d'autres composants et sa validation **en jeu** sont des étapes ultérieures.
5. Il ne faut pas publier les fichiers de source vanilla ou assets propriétaires du jeu dans ce dépôt ; les tests utilisent uniquement des exemples synthétiques.
6. Ce prototype ne garantit ni compatibilité avec les autres mods, ni l'exécution correcte des événements dans le moteur CK3.

## Relation avec la v0.4

`ck3lib.adapters` produit toujours une **intention de clonage**, tandis que `ck3lib.event_cloner` fournit un premier exécuteur **limité à un fichier d'événements entier**. La recette v0.5 est séparée et exige un inventaire manuel ; sa liaison automatique au graphe et à la recette de composition reste à réaliser.
