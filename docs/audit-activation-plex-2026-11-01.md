# Audit du parcours d'activation Plex - 1er novembre 2026

## Périmètre et limites

Analyse du code local, des tests et de quatre scénarios reproduits sur une base de test isolée. Aucun compte réel ni partage Plex modifié. Les logs locaux consultés ne contiennent pas de trace exploitable du cas signalé. La version déployée et l'état de cet utilisateur restent à vérifier : les constats ci-dessous ne constituent pas une attribution de son incident.

## Parcours réellement exécuté

1. En mode portail guidé, la création VODUM persiste les serveurs et bibliothèques à attribuer, mais ne crée pas encore le partage Plex (`app/blueprints/users.py`).
2. Le mail contient un lien personnel d'activation valable sept jours. Un renvoi invalide la génération précédente.
3. Le lien ouvre un flux Plex lié à la session du navigateur et à un état à usage unique, valable dix minutes. L'inscription Plex peut donc réussir alors que le flux VODUM expire ou ne revient jamais au portail.
4. Au retour de Plex, VODUM vérifie l'identité et, au premier rattachement, la correspondance de l'adresse e-mail. Une adresse Apple masquée ou un autre compte est rejeté.
5. Le compte du portail devient actif et une session est ouverte AVANT la préparation des accès Plex. Le statut actif du portail ne prouve donc pas que le partage est terminé.
6. Du JavaScript lance des POST protégés contre le CSRF, un serveur après l'autre. Sans exécution de ces POST, les accès restent en attente, même après un retour Plex réussi. Les formulaires permettent une action manuelle sans JavaScript.
7. Pour chaque serveur, VODUM crée ou met à jour le partage, tente d'accepter automatiquement l'invitation exacte avec le jeton de l'utilisateur, puis vérifie la présence du serveur exact dans ses ressources Plex.
8. Si le résultat est `pending`, la page affiche « Accepter dans Plex » et un formulaire de nouvelle vérification. Il faut revenir au portail après une acceptation manuelle.
9. L'activation n'est terminée que lorsque TOUS les serveurs sont `ready`. Le lien personnel et le jeton Plex temporaire sont alors invalidés.

Source Plex : https://support.plex.tv/articles/201105738-creating-and-managing-server-shares/ distingue également création de compte et acceptation de l'accès aux bibliothèques.

## Fragilités confirmées

### 1. Compte Plex créé sans retour au portail

La création du compte chez Plex n'est pas une preuve d'activation VODUM. Sans callback, `plex_subject` reste vide et aucun partage n'est lancé. Si l'utilisateur revient alors par le lien de connexion générique du mail, cela ne reprend pas le parcours guidé. Il doit reprendre le bouton « Activer mon accès ». Le paramètre d'inscription est encore activé tant que l'identité n'est pas liée : un utilisateur ayant déjà créé son compte peut devoir choisir explicitement la connexion.

### 2. Acceptation automatique silencieusement dégradée

`app/core/plex_activation.py` intercepte les erreurs réseau, HTTP et de format pendant la lecture/acceptation des invitations sans journaliser l'étape ni le statut HTTP. La vérification finale continue. Un `pending` ne permet donc pas de distinguer une acceptation utilisateur manquante, une erreur technique d'acceptation et un délai de propagation Plex. Aucun nouvel essai automatique de cette étape n'est prévu dans cette exécution.

### 3. Réponse HTTP trompeuse pendant la préparation

`app/routes/portal_activation.py` retourne `200 {"ok":true}` après `process_server`, même si cette fonction a enregistré `state=error`. Le navigateur recharge ensuite la page, qui affiche l'état persistant ; l'erreur n'est donc pas effacée, mais la réponse AJAX ne permet pas de la détecter correctement. Reproduction effectuée avec une panne fournisseur simulée.

### 4. Sortie possible avant la fin des accès

`templates/portal/access.html` propose « Ouvrir Plex » dès qu'un seul serveur Plex est prêt. Reproduction : premier serveur `ready`, second `pending`, activation non terminée, bouton déjà visible. L'utilisateur peut quitter la page sans remarquer que l'autre partage reste à accepter.

### 5. Vérification manuelle et jeton expiré

Le jeton utilisateur n'est conservé que quinze minutes. Une nouvelle vérification après ce délai enregistre `activation_reauthenticate`, sans appel Plex. Le bouton de reconnexion réapparaît ; le lien d'acceptation conditionné à `state=pending` disparaît si le serveur passe à `error`. Ce fonctionnement est sûr mais insuffisamment guidé pour quelqu'un qui revient après avoir lu un mail de vérification Plex.

### 6. Visibilité administrative incomplète

L'événement `activation_plex_verified` prouve le retour et le rattachement Plex, pas le partage ni son acceptation. Le contexte administratif des invitations locales lit `portal_account_tokens`, pas les états `user_activation_servers`. L'absence d'invitation locale en attente n'est pas une preuve de fin d'activation Plex. Les erreurs du callback d'activation sont affichées sous forme de flash mais ne sont pas auditées à chaque étape.

## Vérification du cas réel, sans exposer de secrets

Requête de lecture paramétrée par l'identifiant VODUM (ne jamais exporter les colonnes de jetons) :

```sql
SELECT a.id AS activation_id,a.vodum_user_id,a.mode,a.generation,
       a.created_at,a.expires_at,a.completed_at,
       CASE WHEN a.plex_subject IS NOT NULL THEN 1 ELSE 0 END AS plex_identity_bound,
       CASE WHEN a.plex_token IS NOT NULL AND a.plex_token_expires>strftime('%s','now')
            THEN 1 ELSE 0 END AS plex_token_current,
       t.server_id,s.name,t.state,t.error_key,t.lease_until
FROM user_activations a
LEFT JOIN user_activation_servers t ON t.activation_id=a.id
LEFT JOIN servers s ON s.id=t.server_id
WHERE a.vodum_user_id=?
ORDER BY t.server_id;
```

- Identité absente et serveurs `queued` : retour/rattachement Plex non terminé. Une erreur d'identité, de session ou de délai peut aussi l'expliquer.
- Identité présente et serveurs `queued` : partage non lancé ou interrompu avant son traitement.
- `pending` : partage non confirmé ; regarder les invitations reçues dans Plex avec le même compte et les demandes envoyées sur le serveur propriétaire.
- `error` : lire `error_key` et les événements `activation.validate_server_access` / `activation.apply_server_access`.
- Tous `ready` et `completed_at` renseigné : chercher du côté du compte Plex connecté, de la visibilité des bibliothèques et des favoris, plutôt que de l'invitation.

## Reprise conseillée

Ne pas recréer le compte Plex. Reprendre le bouton d'activation du mail le plus récent et se connecter avec le compte déjà créé, dans le même navigateur. Attendre le retour à VODUM et vérifier chaque serveur. Si nécessaire, accepter le partage dans Plex, puis revenir vérifier les accès. Si le lien personnel est expiré ou remplacé, renvoyer une activation depuis VODUM ; les anciens liens deviennent invalides. Ne pas confondre ce bouton avec le lien générique du portail.

## Correctifs à prioriser

1. Afficher une progression explicite : compte Plex vérifié, partage préparé, acceptation confirmée, accès prêts.
2. Rendre l'état incomplet visible lors d'une reconnexion normale au portail et proposer la reprise appropriée, en respectant génération, expiration et identité.
3. Journaliser les étapes et statuts HTTP de l'acceptation sans jetons ni réponses brutes.
4. Retourner le véritable état du serveur dans la réponse JSON.
5. Signaler clairement les accès partiels avant de proposer de quitter vers Plex.
6. Distinguer l'acceptation en attente et la nécessité de se reconnecter après expiration du jeton.

## Validation

39 tests existants réussis : activation utilisateur (22), API d'activation Plex (5), cookie de retour Plex (3), client d'authentification (4), état du flux (3), résolution d'identité (2).

Quatre reproductions supplémentaires sur base isolée : interruption avant callback ; vérification après expiration du jeton ; panne fournisseur retournant malgré tout `ok=true` ; sortie vers Plex proposée lors d'une activation partielle.

Ces tests simulent Plex. Ils ne valident pas une inscription réelle actuelle, ni l'état du compte signalé, ni le déploiement du correctif de cookie précédent.

## Vérification du cas réel après accès autorisé à Gmail et VODUM

Consultation en lecture de VODUM public (version affichée : `26.11.01 b2026`) et des mails envoyés/reçus. L'utilisateur concerné est la fiche VODUM 81. Aucun renvoi de mail, resynchronisation, fusion, modification des accès ou acceptation d'invitation n'a été effectué par l'assistant.

### Chronologie du 1er novembre 2026 (heure de Paris)

- 12:14:38 : création de l'utilisateur 81 dans les logs.
- 12:14:39 : premier mail de bienvenue envoyé à son adresse.
- 12:25:33 et 12:44:33 : callbacks d'activation signalés `outcome=failed` dans les logs disponibles. Ces événements ne portent pas d'identifiant utilisateur ; leur attribution individuelle n'est pas démontrée.
- 19:27:59 : accès au parcours `/portal/access` dans le créneau signalé.
- 19:28:10 et 19:28:25 : retours `/portal/access/plex/callback` marqués `outcome=failed`, avec redirection vers la page d'activation.
- 19:37:29 : nouveau départ du parcours d'activation Plex.
- À partir de 19:37:30 : départs du parcours de CONNEXION ordinaire `/portal/auth/plex`, distinct de l'activation.
- 19:37:39, 19:37:48, 19:44:54, 19:49:34 et 19:49:44 : callbacks de connexion ordinaire rejetés avec HTTP 400 et événements `login_failed`, sans utilisateur identifié dans l'audit.
- 19:37:48 : demande de renvoi d'activation pour l'utilisateur 81.
- 19:37:52 : second mail de bienvenue envoyé, avec un lien personnel différent. Le renvoi invalide les anciens liens et contextes selon le code audité.
- 19:58:57 : mail Plex reçu par l'administrateur indiquant que `nicolasmag2` a accepté une demande d'ami. Ce mail ne prouve pas à lui seul l'acceptation des bibliothèques. L'utilisateur administrateur indique avoir dû intervenir directement dans Plex pour débloquer les accès.
- Vers 20:32 : fiche 81 toujours sans serveur ni bibliothèque associés. Aucun second utilisateur correspondant à la recherche `nicolasmag` dans la liste VODUM à ce moment. Le monitoring de la fiche indique qu'aucun `media_user` n'est lié. Une intervention côté Plex n'a donc pas encore été rapprochée de cette fiche par VODUM.

### Défauts concrets du mail réellement envoyé

Les deux mails disent d'ouvrir l'application Plex et de se connecter, puis affichent le lien générique `/portal/login`. Le bouton personnel « Activer mon accès » arrive ensuite, après la signature. Ces instructions mélangent le parcours de première activation et la connexion ordinaire ; les logs du créneau montrent justement un passage du premier au second parcours.

La version texte brut du mail affiche « Activer mon accès » sans inclure l'URL personnelle correspondante. Un lecteur de mail en texte brut ne reçoit donc pas de lien d'activation exploitable et ne voit que le lien générique de connexion. Cela ne prouve pas que Nicolas a utilisé ce mode de lecture.

### Conclusion révisée

Les éléments recueillis pointent vers un échec de retour/authentification VODUM et une reprise par la connexion ordinaire, avant la fin du provisionnement. Ils ne permettent pas de réduire l'incident à un oubli d'acceptation par l'utilisateur. Les logs anciens n'enregistrent pas la classe/raison du rejet du callback d'activation : impossible de trancher rétrospectivement entre session perdue, état remplacé, identité rejetée et erreur Plex. L'absence d'association à la fiche 81 doit aussi être prise en compte avant de considérer le cas entièrement réparé côté VODUM.

Priorités mises à jour : clarifier le mail et sa version texte, journaliser les raisons sûres de rejet du callback avec l'identifiant d'activation, et proposer une reprise contrôlée depuis la connexion ordinaire. Vérifier le rapprochement de l'identité Plex créée manuellement avant toute fusion ou action de resynchronisation.

## Correctifs locaux réalisés après l'audit

- Bouton d'activation placé avant le contenu personnalisé, avec consignes Plex traduites en cinq langues. Le contenu et les liens personnalisés sont conservés.
- Liens HTTP(S) conservés dans les versions texte des mails, y compris le lien personnel d'activation.
- Diagnostic `vodum.activation` pour l'envoi en file, l'ouverture du lien, le début Plex, les étapes du callback, les partages et leur acceptation, le résultat par serveur et la fin de l'activation.
- Chaque trace inclut les identifiants internes disponibles (`activation_id`, `user_id`, `generation`, `server_id`), la classe d'exception, une raison interne autorisée et le statut HTTP disponible. Aucun jeton, état OAuth, mot de passe, adresse e-mail, réponse fournisseur brute ou message d'exception arbitraire n'est enregistré par ces traces.
- L'échec de connexion ordinaire distingue lui aussi l'état du flux, la récupération du jeton, l'identité et la résolution du compte. Un contexte d'activation encore présent est corrélé par son identifiant.
- Une erreur serveur de préparation renvoie maintenant HTTP 422 avec `ok=false` et l'état persistant ; une invitation en attente reste un état `pending`, distinct d'une erreur.
- « Ouvrir Plex » est réservé à la fin de l'activation de tous les serveurs.

Pour un prochain incident, chercher `user_id=81` ou l'identifiant concerné dans les logs, relever `activation_id`, puis rechercher cet identifiant pour suivre le parcours. Si la session a été entièrement perdue, la trace peut ne plus avoir d'identifiant : corréler alors l'heure et `stage=callback_state` / la classe `PlexFlowMissing`. Une entrée `callback_bind` avec `activation_wrong_account` distingue un refus d'identité d'une session absente. `invitation_accept` avec un HTTP indique un échec d'acceptation ; `server_pending` indique seulement que les accès ne sont pas encore confirmés.

Ces changements ne réparent pas rétroactivement les données du compte 81 et ne constituent pas un déploiement en production. La reprise automatique depuis la connexion ordinaire n'a pas été ajoutée dans ce correctif : aucune nouvelle autorisation de partage n'est déduite d'une simple connexion.
