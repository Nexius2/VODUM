# Audit de journalisation — 21 octobre 2026

## Périmètre et résultat

Inventaire statique de **368 modules Python, 1 975 fonctions et 855 blocs d'exception**, sans erreur d'analyse. Revue des routes, API, tâches, services Plex/Jellyfin/ARR, communications, activation, migrations, sauvegardes, monitoring et scripts de l'interface.

Ajout de **156 points de journalisation d'échecs interceptés dans 76 modules**, en complément des logs existants et des protections centrales décrites ci-dessous. Les comportements de repli restent conservés : cet audit ajoute de la visibilité sans transformer chaque échec partiel en interruption du traitement.

## Couverture centrale

| Situation | Trace produite |
| --- | --- |
| Exception Flask non interceptée | ERROR avec traceback, méthode et modèle de route ; pas de valeur de jeton issue de l'URL |
| Exception non interceptée d'un thread | ERROR avec nom du thread et traceback, mécanisme existant conservé |
| Action POST/PUT/PATCH/DELETE réussie | INFO avec endpoint, code HTTP et identifiants numériques de route |
| Réponse HTTP 4xx / 5xx, même sans exception | WARNING / ERROR, y compris pour GET |
| Réponse JSON HTTP 200 indiquant un échec | WARNING pour `ok=false`, `success=false`, `error`, `errors`, ou `status=error/failed` |
| Redirection accompagnée d'un nouveau flash d'erreur | WARNING ; le texte du flash n'est pas enregistré |
| Erreur JavaScript, promesse non gérée ou `console.error` | ERROR envoyé au serveur avec type, fichier JS et numéro de ligne disponibles |
| Impossible d'écrire ou de maintenir les logs | Alerte `VODUM LOGGING FAILURE` sur stderr, même avec `logging.raiseExceptions=False` |

Les réponses JSON sont inspectées avant compression. Les lectures saines ne produisent pas de log d'action supplémentaire. Un ancien flash d'erreur ne déclenche pas une nouvelle alerte à chaque lecture.

## Échecs locaux désormais visibles

- Communications : SMTP, pièce jointe illisible, validation Discord, chargement des modèles et traductions, contexte d'abonnement, invitation et message de bienvenue.
- Comptes et accès : activation Plex, présence des comptes et invitations, application des accès, réveil du worker, données d'identité invalides.
- Migrations : analyse, pause/reprise, exclusions, relance, changements d'accès, validation de destination, suivi des jobs, livraison des identifiants et décodage de données persistées.
- Sauvegardes/import : checkpoint SQLite, validation, paramètres, nettoyage et fermeture pendant restauration, statut d'import Tautulli et index de déduplication.
- Monitoring : statistiques de ressources, collecte et persistance, cache d'affiches, WebSocket Plex indisponible, déclenchement du contrôle des lectures.
- Politiques : règles ou instantanés invalides, exceptions de lecture des dérogations, extraction d'identifiants de session et de lecteur.
- Infrastructure : persistance de la clé de session, paramètres de cookies et proxy, migrations de schéma, lecture du commutateur cron et serveur déclaré indisponible.
- Interface : échecs interceptés dans les sauvegardes, communications, migrations, graphiques, abonnements, gestion des utilisateurs et portail.

Un POST AJAX recevant une page HTML à la place du JSON attendu lève maintenant une erreur ; il ne renvoie plus artificiellement `ok=true`.

## Contenu et volume des nouveaux logs

`log_handled_failure` conserve le nom de l'opération, le type d'exception, les emplacements de pile et les identifiants internes numériques explicitement fournis. Il ne copie ni le message de l'exception externe ni ses variables locales : ceux-ci peuvent contenir un mot de passe ou une URL avec jeton sans marqueur permettant de les masquer.

Les rapports navigateur passent par les contrôles d'accès admin/portail et CSRF existants. Le serveur n'accepte que des types d'événements connus et des chemins de scripts statiques validés ; il ignore messages, corps de réponse, mots de passe et piles envoyées par le client. Limites : cinq rapports par chargement de page et soixante par minute par processus. Les échecs du système de logs sont signalés au maximum une fois par minute sur stderr.

## Reproduire l'inventaire

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'app')
.\.venv\Scripts\python.exe tools/audit_exception_logging.py app --json "$env:TEMP/vodum-logging-inventory.json"
```

L'outil répertorie chaque fonction et bloc d'exception, avec son code et son emplacement. Il détecte maintenant les affectations, `continue` et `break` silencieux, et ne considère plus un log uniquement DEBUG ou un log situé dans un gestionnaire imbriqué comme une couverture suffisante.

L'inventaire final classe 372 gestionnaires avec log direct, 53 avec remontée d'exception et 430 sans log direct. Cette dernière catégorie est une piste de revue, **pas un décompte d'incidents invisibles** : elle inclut les formats de date alternatifs, conversions de saisie, valeurs optionnelles, recherches successives et erreurs métier déjà exposées à la frontière HTTP ou à la tâche appelante. Un helper de conversion n'a pas besoin d'un log d'action à chaque appel. L'analyse statique ne prouve pas à elle seule l'exécution de toutes les branches.

## Vérifications

- Suite Python exécutée par module, en processus séparés pour isoler les doublures d'import : 1 150 tests tentés dans 234 modules ; 229 modules passent, cinq restent en échec.
- Tests ciblés relancés après les derniers ajouts : journalisation HTTP, SMTP, CSRF et authentification des rapports navigateur, politiques, activation, synchronisation Plex, schéma, migrations et cache du portail passent.
- Six suites JavaScript passent ; les 35 scripts JavaScript de l'application passent le contrôle syntaxique.
- Injection d'erreurs testée : exception HTTP, échec JSON sous HTTP 200, erreur puis redirection, panne SMTP, fichier de logs inaccessible, panne de réseau du rapport navigateur. Vérification de l'absence de secrets et des limites de fréquence.
- Audit des routes GET : aucune action à revoir signalée.

Les cinq modules de tests existants en échec sont `test_cron_human.py` (doublure Flask incomplète), `test_library_request_routing.py` et `test_portal_media_request_routes.py` (assertions de templates), `test_sql_literal_interpolation.py` (schéma d'activation), et `test_sqlite_connection_policy.py` (fabriques de connexions hors liste attendue). Ils échouaient également au premier passage et les fichiers concernés par leurs constats n'ont pas été modifiés pour cette journalisation.

Les vérifications ont été faites localement, sans déployer ni tester les services réels de production. Une panne réseau du navigateur ne peut pas être transmise au serveur pendant cette même panne ; elle reste visible dans sa console. Les clés de repli attendues et les tentatives intermédiaires aboutissant ensuite ne sont pas systématiquement promues en erreurs.
