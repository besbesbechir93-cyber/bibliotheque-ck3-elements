# Version 0.7 — Paquet de mod, localisations, GFX (strict)

## Périmètre

`ck3lib.package_mod` transforme un **fragment de raccordement v0.6** en un dossier de mod neuf avec `descriptor.mod`. Il clone, si demandé, **des clés de localisation précises** depuis des fichiers `.yml` vanilla et des textures GFX depuis l'installation locale autorisée. Le dépôt GitHub ne contient **aucun asset CK3**.

Il **ne** modifie pas le jeu, ne remplace pas de fichiers vanilla, ne publie pas de textures et ne garantit pas le fonctionnement en jeu. Le terme *paquet* signifie seulement que l'arborescence contient un descripteur et les scripts produits précédemment. L'outil ne crée pas de fichier `.mod` du lanceur.

## Commande

```bash
PYTHONPATH=src python -m ck3lib.package_mod \
  --recipe /tmp/cklib-package-recipe.json \
  --vanilla-root '/chemin/vers/Crusader Kings III/game' \
  --wired-fragment /tmp/cklib-linked-v06 \
  --output /tmp/cklib-mod-v07
```

La sortie doit être un dossier **inexistant** en dehors du vanilla et du fragment d'origine.

## Recette minimale (exemple conceptuel à adapter à vos vrais SHA)

```json
{
  "version": 1,
  "name": "CKLib Demo Activity",
  "mod_version": "0.7.0",
  "supported_version": "1.20.*",
  "localizations": [
    {
      "source_path": "localization/english/demo_l_english.yml",
      "source_git_blob_sha": "0000000000000000000000000000000000000000",
      "language": "english",
      "renames": {"oldns.1.t": "cklib_demo_oldns.1.t"}
    }
  ],
  "gfx": [
    {
      "mode": "reference",
      "source_path": "gfx/interface/icons/example.dds",
      "source_git_blob_sha": "0000000000000000000000000000000000000000"
    }
  ]
}
```

Les SHA de zéro ne sont que des **espaces réservés** et provoquent un refus de compilation. Les remplacements doivent venir des octets réels des fichiers locaux. Pour `mode=clone`, ajouter `target_path` sous `gfx/cklib/…`; seule une référence **textuelle et exactement entre guillemets** dans les scripts clonés sera réécrite. Pour `mode=reference`, aucune texture n'est copiée : on continue à utiliser la ressource du jeu.

Les `renames` de localisation sont appliqués seulement aux valeurs scalaires de champs explicitement autorisés (`title`, `desc`, `name`, `text`, `tooltip`, `description`, `custom_tooltip`). Les commentaires, valeurs de textes et références à d'autres localisations ne sont pas réécrits ; ils peuvent garder des dépendances vanilla. Le `.yml` produit commence par un BOM UTF-8 et un en-tête `l_<langue>:`. Les entrées locales de forme `clé: "texte"`, `clé:0 "texte"` et `clé:1 "texte"` sont acceptées ; leur marqueur original est préservé.

## Contrôles et limites

- Vérification des empreintes Git des localisations et textures sources ; source et fragment en lecture seule ; refus des chemins sortants et liens symboliques.
- Clonage des **clés spécifiées seulement** et refus des doublons ; garde-fou sur les contextes non reconnus et changements inutilisés.
- Refus de sortie existante ; aucune substitution de texte libre, aucun override implicite ; rapport `cklib-package-report.json`.
- L'outil accepte un nombre borné de fichiers/bytes et refuse les collisions locales. Il ne vérifie pas les conflits avec les autres mods installés.
- **Pas encore pris en charge :** clonage GUI, déclarations de sprites `*.gfx`, résolution des références dynamiques, multi-fichier d'activité, dépendances DLC, génération du `.mod` launcher ou tests dans CK3.

**Validation nécessaire en jeu :** configuration du mod dans le lanceur Paradox, exécution de CK3 sur la version prévue, contrôle des fichiers de logs, affichage correct de l'activité, lancement des événements et rendu GUI/GFX/localisation. Aucun des tests unitaires ne remplace ces étapes.
