# Diagnostic des coupures de lecture

Chaque appel de coupure du moteur produit une ligne structurée
`Stream termination diagnostic` dans les logs, au niveau warning en cas d'échec,
info en cas de succès. Aucun mode debug n'est nécessaire.

Dans Monitoring > Policies, ouvrir le détail d'une intervention : le JSON
existant contient désormais `termination`, avec le même `attempt_id` que le log.
Les anciennes interventions ne disposent pas de ces informations rétroactivement.

Le diagnostic contient le serveur, la clé de session, la durée totale, le résultat,
les événements HTTP de terminaison et les observations de vérification Plex.
Les exceptions réseau/HTTP produisent également une ligne `kill_failed` dans
l'historique, au lieu de sortir avant son enregistrement.

Résultats Plex :

- `target_absent` : la clé ciblée n'est plus dans le relevé initial.
- `missing_session_id` : la lecture existe mais Plex n'expose pas son identifiant de coupure.
- `command_not_accepted` : l'adaptateur n'a pas accepté la commande.
- `stop_confirmed` : disparition confirmée selon les vérifications existantes.
- `absent_after_not_found` : commande introuvable puis absence constatée, sans identité permettant de suivre une reconnexion.
- `still_present_after_retries` : session toujours présente au terme des vérifications.
- `exception` : appel interrompu ; consulter le type, sa cause, son statut HTTP
  éventuel et le dernier événement pour identifier l'étape.

`analysis` résume le nombre de vérifications, le dernier état observé, les
recréations d'identifiant de session, les statuts HTTP et les augmentations de
position. Une position qui augmente peut aussi correspondre à un déplacement
manuel ; elle ne prouve pas à elle seule une lecture continue. Une session en
pause toujours présente reste un arrêt non confirmé.

Les événements HTTP indiquent la méthode et l'index de l'adresse configurée
essayée (zéro pour la première), sans exposer l'adresse. Les corps de réponse,
tokens, en-têtes et textes d'exception ne sont pas ajoutés au diagnostic.
Les événements sont bornés à 100 par tentative. Chaque tentative est isolée
dans son contexte d'exécution et consommée lors de l'écriture de l'intervention.

Pour analyser un incident, comparer les interventions successives du même
compte et serveur : une coupure confirmée suivie d'une nouvelle clé suggère une
relance ultérieure ; une recréation pendant la vérification est directement
signalée dans les événements. Le diagnostic décrit uniquement la fenêtre
observée et ne garantit pas l'absence de relance après cette fenêtre.

Cette instrumentation conserve les délais, méthodes et critères d'arrêt
existants. Elle ne suspend aucun accès et ne lance aucun appel supplémentaire.
