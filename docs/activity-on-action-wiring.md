# v0.6 — Connecter un clone d'événements à une activité et à un `on_action` privés

Statut : **prototype limité, aucun test dans CK3**. L'outil fabrique un **nouveau fragment de mod**, et ne patch jamais le vanilla. Aucun GFX, localisation ou GUI n'est dupliqué.

## Pourquoi l'assemblage est strict

Le résultat du clone v0.5 ne suffit pas à rendre des événements autonomes. Un type d'activité peut appeler un événement directement (`trigger_event = { id = ... }`) ou indirectement (`trigger_event = { on_action = ... }`). Un `on_action` peut ensuite sélectionner les événements dans `random_events` ou `events`. Le raccordement entre ces trois niveaux est nécessaire pour un cas de composition limité.

Le script `ck3lib.wiring` lit un dossier d'événements **déjà généré avec v0.5**, son manifeste `event-clone-report.json` et les trois fichiers sources originaux depuis l'installation CK3 : événements, activité et `on_action`. Les sources sont en lecture seule. Le générateur vérifie à nouveau le SHA Git des sources et recalcule intégralement la sortie d'événements v0.5 pour écarter un fragment altéré.

La v0.6 n'accepte **qu'un fichier d'activité à déclaration unique** et **un fichier `on_action` à déclaration unique**. Les fichiers contenant plusieurs déclarations (fréquents dans CK3), les références symboliques dynamiques et les appels non reconnus nécessitent un adaptateur ultérieur. Un appel à un événement extérieur au bundle reste inchangé et doit être revu manuellement.

## Recette

```json
{
  "version": 1,
  "activity": {
    "source_path": "common/activities/activity_types/example.txt",
    "source_git_blob_sha": "<SHA_GIT_40_CARACTERES>",
    "source_id": "activity_example",
    "target_id": "cklib_activity_example"
  },
  "on_action": {
    "source_path": "common/on_action/activities/example.txt",
    "source_git_blob_sha": "<SHA_GIT_40_CARACTERES>",
    "source_id": "example_random_pulse",
    "target_id": "cklib_example_random_pulse"
  }
}
```

Cette recette est illustrative : aucun de ces chemins ou noms n'est supposé présent dans le vanilla. Les identifiants réels et les empreintes doivent être déterminés à partir des fichiers locaux.

## Utilisation

```bash
PYTHONPATH=src python -m ck3lib.event_cloner \
  --recipe /mes_recettes/event-clone.json \
  --vanilla-root /chemin/vers/CK3/game \
  --output /tmp/cklib-events-v05

PYTHONPATH=src python -m ck3lib.wiring \
  --recipe /mes_recettes/wiring.json \
  --vanilla-root /chemin/vers/CK3/game \
  --event-fragment /tmp/cklib-events-v05 \
  --output /tmp/cklib-linked-v06
```

Sortie dans **un nouveau dossier** : `events/...`, `common/activities/activity_types/...`, `common/on_action/...`, `wiring-report.json`. Le dossier cible ne doit ni préexister ni chevaucher le vanilla ou le fragment d'événements utilisé comme entrée. Aucun `descriptor.mod` n'est créé : ce n'est **pas** un mod complet prêt à charger.

## Autorisations de transformation

- Déclaration racine du nouvel identifiant d'activité.
- Déclaration racine du nouveau `on_action`.
- `trigger_event = ancien.123` et `trigger_event = { id = ancien.123 }`.
- Valeurs numériques de `random_events = { 100 = ancien.123 }` et événements simples de `events = { ancien.123 }`.
- `on_action = ancien_on_action` dans l'activité, remplacé uniquement dans ce champ.

Toute occurrence de l'ancien namespace d'événements dans un contexte non reconnu, un identifiant ancien absent du clone ou des chaînes citées conduit au rejet. Les collisions avec les définitions de jeu cibles sont contrôlées, y compris pour les fichiers avec BOM UTF-8. Aucun ID vanilla n'est remplacé volontairement.

## Limites critiques

Le générateur ne découvre **pas** tous les appels entrants, ni tous les événements appelés indirectement ; la vérification des références CK3 n'est pas exhaustive. Les expressions GUI, descriptions localisées, effets scriptés indirects, paramètres DLC, moteur hardcodé et conflits de mods ne sont pas résolus. La détection des collisions ne remplace pas une analyse globale du chargeur CK3.

Les tests fournis sont **synthétiques** et ne démontrent ni compatibilité ni fonctionnement en jeu. Les fragments doivent être audités, raccordés aux localisations et interfaces et testés dans une installation CK3 correspondant aux empreintes retenues avant diffusion.
