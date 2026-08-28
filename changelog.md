# Changelog

## 2026-08-27 - Correctifs UI du portail et de l'administration

- Ajout d'un réglage « Afficher l'adresse email de support », activé par
  défaut, permettant de masquer entièrement le contact email dans la page
  Aide et support sans désactiver les messages rapides.
- Clarification des cartes d'accueil du portail: échéance et jours restants,
  compteurs séparés de serveurs et bibliothèques, lectures et durée totale
  formatées avec les mêmes agrégats dédupliqués que le monitoring.
- Correction responsive du profil de suivi personnel avec statistiques 2×2,
  libellés de périodes traduits, donuts plus petits et légendes entièrement
  contenues dans la carte Insights.
- Alignement immédiat du nom de marque à droite du logo dans les en-têtes admin
  mobile, menu mobile et sidebar; sans logo, le nom reprend sa place à gauche.
- Clarification des onglets Communications avec cinq clés i18n dédiées:
  Inbox, Campaigns, Templates, History et Settings, sans modification des
  routes ni des fonctionnalités associées.
- Placement uniforme du logo à gauche du nom de marque dans les navigations
  d'administration et du portail.
- Déplacement des suggestions de serveurs Plex sous le formulaire d'ajout
  manuel afin que celui-ci reste immédiatement accessible.
- Affichage de la langue réellement active dans le profil utilisateur; une
  sélection explicite est persistée comme préférence.
- Ajout des traductions des limites d'abonnement en allemand, anglais,
  espagnol, français et italien.
- Simplification de l'accès média du portail par retrait des liens de
  téléchargement et du message de gestion du profil Plex.
- Normalisation visuelle des valeurs d'abonnement numériques: `70.0` devient
  `70`, tandis que les décimales utiles et libellés personnalisés sont conservés.
- Ajout d'une option admin « Paiement et renouvellement », désactivée par
  défaut, qui contrôle l'affichage d'une modale provisoire dans le portail.
- Présentation sur la page abonnement des autres forfaits activés uniquement,
  sans exposer les templates désactivés ni répéter le forfait courant.
- Validation du parcours de suppression locale d'un utilisateur: nettoyage des
  comptes média, bibliothèques, policies, historiques d'enforcement, cadeaux,
  compte portail et jobs liés; les Owner Plex et Admin Jellyfin restent protégés.
- Ajout d'une devise globale pour les abonnements, sélectionnable dans leurs
  réglages et affichée avec les valeurs dans l'administration et le portail.
- Ajout de l'option « Masquer aux utilisateurs » sur chaque forfait. Les
  forfaits masqués ne sont pas proposés dans le portail, mais restent visibles
  par leurs abonnés actuels; les forfaits à vie activent cette option par défaut.
- Ajout d'un bouton de test dans l'éditeur de messages. Il envoie le sujet et le
  contenu actuellement saisis à l'adresse de contact/admin via la configuration
  SMTP active, sans enregistrer ni perdre le brouillon.
- Enrichissement du suivi personnel du portail avec quatre onglets: vue
  d'ensemble et graphique quotidien, répartition des médias et bibliothèques,
  utilisation par serveur et historique détaillé. Tous les agrégats restent
  filtrés côté serveur sur l'utilisateur connecté.
- Alignement des statistiques du suivi personnel sur les agrégations de la vue
  admin: déduplication des lectures par média et minute, durée plafonnée,
  classification identique des médias et graphiques calculés sur 30 jours.
- Reprise à l'identique de la présentation Profil du monitoring admin dans le
  portail: quatre périodes dont le cumul global, deux graphiques Insights en
  anneau, puis les courbes Lectures/jour et Temps de visionnage/jour sur 30 jours.
- Correction des libellés « Lectures » français et « Plays » anglais qui
  provenaient par erreur des traductions italienne et espagnole.
- Ajout dans les réglages du portail d'un bloc « Aide et support » permettant
  de personnaliser le texte d'introduction affiché aux utilisateurs et
  d'activer séparément le futur système de messages rapides.
- Mise en service des messages rapides entre chaque utilisateur et
  l'administration: fil de discussion dans le portail, nouvel onglet Messages
  dans Communications, réponses admin, états non lus, pastille rouge et email
  de notification à l'administrateur lors d'un nouveau message utilisateur.
- Le bloc de configuration Aide et support est désormais masqué lorsque cette
  section n'est pas activée dans les sections visibles du portail.

## 2026-08-24 - Fondations du portail utilisateurs

- Formalisation du perimetre du portail MVP: accueil, profil, abonnement, acces
  media, monitoring personnel, support et deconnexion; paiement integre,
  administration deleguee et personnalisation avancee restent hors MVP.
- Documentation du contrat de separation des interfaces: administration sur ses
  routes historiques, portail sous `/portal`, API privee sous `/api/portal/` et
  layout utilisateur dedie, avec classification serveur fermant les routes
  inconnues sur le perimetre admin.
- Definition d'une liste blanche des donnees personnelles visibles et
  modifiables; notes admin, IP completes, secrets, payloads provider, journaux
  techniques et donnees de tiers sont explicitement prives par defaut.
- Definition du modele de liaison et de fusion: une personne VODUM et un compte
  portail peuvent porter plusieurs identites, les sujets provider immuables sont
  uniques, les conflits exigent une resolution explicite et une fusion doit
  revoquer sessions et jetons sans creer de compte media supplementaire.
- Extension de la configuration admin avec hostname autorise, nom et logo du
  portail, liens CGU/confidentialite et choix des sections visibles. Les liens
  externes exigent HTTPS, le hostname est controle a la requete et une section
  masquee est egalement fermee cote serveur.
- Finalisation du contrat des methodes de connexion configurables. Les choix
  local/Plex/Jellyfin sont independants, mais l'ouverture reste conditionnee a
  une recuperation locale par email tant que les parcours provider U4 ne sont
  pas disponibles.
- Extension du diagnostic de publication avec confiance proxy restreinte et
  disponibilite des callbacks provider, en plus de HTTPS, hostname, cookies,
  email et recuperation, sans automatisation du DNS ou du reverse proxy.
- Finalisation du modele d'identite distinct des comptes media avec horodatage
  de validation/connexion, etat actif ou revoque, motif de revocation et
  contraintes d'unicite globales ou par serveur selon le provider.
- Application de permissions nommees cote serveur sur chaque page et API du
  portail, avec roles `admin`/`user` persistants et refus par defaut des roles ou
  permissions inconnus.
- Fin de l'ecriture des anciennes cles booleennes admin et migration des gardes
  Plex vers le principal versionne. Les sessions historiques sont encore lues
  une fois, converties puis nettoyees; les sessions portail restent revocables
  cote serveur.
- Simplification des reglages portail apres retour d'usage: reutilisation du nom
  de marque et du contact support globaux, hostname deduit de l'URL publique et
  retrait des champs logo/CGU/confidentialite en doublon. Ces derniers sont
  reportes a une future personnalisation globale.
- Fusion du catalogue historique des traductions comme complement du catalogue
  UI principal afin que les nouveaux libelles portail ne s'affichent plus sous
  forme de cles techniques.
- Isolation des gardes setup et maintenance: le portail ne redirige jamais vers
  l'installation admin et affiche un etat neutre pendant une maintenance.
- Ajout d'une politique de mot de passe configurable (longueur, majuscule,
  minuscule, chiffre et symbole), commune a l'activation et au reset. La TOTP
  utilisateur reste planifiee apres le MVP avec un secret distinct.
- Ajout du calcul central des etats portail invite, actif, suspendu, expire et
  supprime. Un abonnement expire invalide desormais aussi les sessions deja
  ouvertes et interdit une nouvelle connexion locale.
- Ajout du service de resolution d'identite Plex utilisateur par sujet provider
  immuable: liaison automatique uniquement avec un candidat unique et
  confirmation explicite obligatoire en cas d'ambiguite. Le branchement complet
  du callback PIN au portail avec `state` a usage unique, expiration, abandon du
  jeton apres lecture de l'identite et choix ambigu conserve uniquement en session.
- Ajout du schema idempotent des comptes portail, identites locales/Plex/Jellyfin,
  roles extensibles et associations compte-role.
- Ajout des roles systeme `admin` et `user` et du contrat de permissions cote
  serveur pour les futures routes du portail.
- Ajout des reglages du portail, tous desactives par defaut, sans ouverture de
  route publique a ce stade.
- Ajout de la matrice d'autorisation documentee et de tests d'isolation du schema,
  des contraintes provider et des permissions.
- Ajout du menu et de la page admin "Portail utilisateurs" pour preparer l'URL
  publique, le contact support et les methodes locale/Plex/Jellyfin.
- Ajout de validations serveur de l'URL et de l'email, des traductions dans les
  cinq langues et d'un verrou empechant toute activation avant que les flux de
  connexion et de recuperation soient disponibles.
- Ajout d'un principal de session versionne (`account_type`, `account_id`, role,
  niveau et date d'authentification) avec compatibilite des anciennes sessions.
- Centralisation de l'ouverture des sessions admin locales, Plex et wizard avec
  rotation de session, et mise a jour coherente lors d'un changement d'email.
- Ajout des gardes `admin_required`, `portal_login_required` et du controle de
  propriete d'un `vodum_user`; la configuration du portail exige desormais le
  role admin explicitement.
- Classification centrale des chemins en `public`, `admin_auth`, `setup`,
  `portal_auth`, `portal` ou `admin`, avec repli securise vers `admin` pour toute
  nouvelle route inconnue.
- Adaptation du garde global: les comptes portail ne peuvent atteindre aucune
  page/API admin, et les futures routes portail exigent un role user ou admin.
- Ajout des sessions portail persistantes et revocables: jeton aleatoire cote
  navigateur, hash SHA-256 uniquement en base, expiration, derniere activite et
  revocation ciblee ou globale par compte.
- Validation de la session portail et de sa correspondance compte/utilisateur a
  chaque acces `/portal`; une session expiree, suspendue, revoquee ou incoherente
  est retiree puis redirigee vers la future connexion utilisateur.
- Ajout d'une primitive transactionnelle DB pour rendre atomiques les parcours
  sensibles multi-requetes.
- Ajout du backend d'invitation locale: jeton hashe, expiration a sept jours,
  usage unique, revocation automatique de l'invitation precedente et unicite de
  l'email entre comptes portail.
- Ajout de l'activation atomique du compte avec hash Werkzeug et de
  l'authentification locale non enumerante creant une session portail revocable.
- Ajout, sur la fiche utilisateur admin, de l'etat du compte portail et de
  l'envoi/renvoi d'une invitation; l'envoi exige une URL publique, la methode
  locale et une configuration email operationnelle.
- Ajout des pages publiques d'activation et de connexion locale, avec confirmation
  du mot de passe, erreurs generiques et redirections internes securisees.
- Ajout de la deconnexion portail avec revocation immediate de la session en base.
  La connexion reste indisponible tant que le portail global n'est pas active;
  l'activation par invitation valide reste possible pour preparer les comptes.
- Ajout d'un anti-bruteforce portail distinct par IP et email: cinq echecs sur
  quinze minutes, verrou de quinze minutes et stockage exclusif d'empreintes des
  valeurs de scope.
- Ajout du parcours mot de passe oublie avec reponse non enumerante, lien a usage
  unique valable une heure, rejeu refuse et revocation de toutes les sessions du
  compte apres modification du mot de passe.
- Ajout du journal d'audit portail pour activation, invitation, connexions,
  blocages, deconnexion et resets; IP et user-agent sont uniquement conserves
  sous forme d'empreintes et les details sensibles sont filtres.
- Remplacement du verrou d'activation permanent par un diagnostic serveur:
  authentification locale, URL HTTPS, support, email operationnel, cookies Secure
  et recuperation doivent tous etre valides avant activation.
- Affichage de chaque controle de readiness dans la page admin; le portail reste
  desactive par defaut et montre une page neutre lorsqu'il est ferme.
- Ajout du layout responsive distinct du portail et de son accueil personnel:
  statut, abonnement, echeance, acces media et activite sont strictement limites
  au `vodum_user` porte par la session, sans statistique globale.
- Ajout du premier formulaire de profil en libre-service. Seuls le prenom, le nom
  et l'email secondaire valide sont modifiables; tout identifiant utilisateur
  soumis par le navigateur est ignore et les comptes admin sont refuses.
- Ajout de la page d'abonnement personnelle: formule, valeur, statut, echeances
  et limites connues sont presentees sans exposer les details internes des regles.
  Une methode de renouvellement n'est transformee en lien que si elle est HTTPS.
- Ajout de la page d'acces media regroupant, pour le seul utilisateur connecte,
  ses comptes Plex/Jellyfin, serveurs, bibliotheques, invitations en attente et
  liens officiels vers les applications clientes.
- Ajout du monitoring personnel avec statistiques sur 24 heures, 7 jours et 30
  jours, puis les vingt lectures recentes. Le filtrage SQL part exclusivement du
  `vodum_user` en session et n'expose ni IP ni donnees brutes des providers.
- Ajout de la page Support avec contact configure, aide integree et diagnostic
  partageable minimal (version, statuts et nombre de serveurs lies), sans logs,
  secrets, jetons, adresses IP ou URL internes.
- Enrichissement de la fiche utilisateur admin avec le compte portail, ses roles,
  identites, derniere connexion, sessions actives, invitations en attente et les
  25 derniers evenements d'audit cibles.
- Ajout des actions admin transactionnelles de revocation d'invitation,
  suspension/reactivation, deconnexion forcee et reinitialisation complete des
  methodes d'authentification. Les comptes existants recoivent idempotemment le
  role `user`, et une reinitialisation exige une nouvelle invitation.
- Validation et reutilisation de l'orchestration provider existante du parcours
  de creation controlee: invitation Plex classee ami/en attente et partage par
  serveur, creation Jellyfin avec politique de mot de passe et bibliotheques;
  les identites et liens locaux utilisent des insertions idempotentes.
- Ajout des emails portail traduits dans les cinq langues de communication pour
  invitation, reset, changement d'authentification, suspension, reactivation et
  nouvelle connexion. La preference media de l'utilisateur prime sur la langue
  de communication globale, avec repli anglais.
- Durcissement HTTP du portail: limite de requete a 64 Kio, CSRF global conserve,
  rate limiting persistant par route/IP hashee, CSP dediee, `no-store`, en-tetes
  de securite et cookies `HttpOnly`/`SameSite`/`Secure` selon la publication HTTPS.
- Ajout de Cloudflare Turnstile optionnel pour les connexions admin/utilisateur
  et le reset utilisateur: cles masquees/chiffrees, modes compact/invisible,
  verification `siteverify` avec timeout et hostname strict. Une panne echoue
  fermee a distance mais autorise la recuperation depuis l'interface loopback;
  CSRF, anti-bruteforce et 2FA restent independants.
- Ajout du test interactif Turnstile dans la modale de securite. Il valide un
  jeton reel, les cles et le hostname; une recuperation loopback en mode degrade
  ne peut jamais etre affichee comme un test de configuration reussi.
- Durcissement du journal d'audit portail par liste blanche des seules metadonnees
  `reason`, `method`, `provider`, `action` et `status`. Les IP et user-agents
  restent uniquement empreintes; emails, jetons, secrets et titres prives sont
  ignores meme lorsque leur nom de champ est inattendu.
- Ajout de l'export JSON des donnees portail sans hashes de mot de passe, session
  ou jeton, et d'une purge admin ciblee supprimant compte, identites, sessions,
  jetons et audit tout en conservant l'utilisateur VODUM et ses comptes media.
- Extension de la retention aux sessions et jetons expires, audits, limites de
  requetes et tentatives anciennes. La documentation precise que les sauvegardes
  historiques peuvent restaurer des donnees effacees jusqu'a expiration et que
  la purge doit alors etre reappliquee apres rollback.
- Ajout de contrats de securite portail pour rotation anti-fixation de session,
  CSRF et propriete horizontale, completes par les tests existants de roles,
  revocation, non-enumeration, callbacks provider et indisponibilite Turnstile.
- Ajout des tests de publication derriere proxy: les en-tetes `Forwarded` ne sont
  acceptes que depuis les CIDR declares, et HTTPS/hostname/readiness sont verifies.
  La documentation fournit la checklist de publication, recuperation locale et
  rollback; un essai manuel sur le reverse proxy final reste requis avant Internet.
- Ajout de l'edition du nom local Jellyfin depuis le portail, idempotente et
  bornee au compte media appartenant au principal de session. Le profil Plex,
  non modifiable par un proprietaire de serveur, reste en lecture seule et renvoie
  explicitement vers la gestion du compte Plex.
- Ajout du reglage admin de paiement/renouvellement avec URL HTTPS validee et
  libelle personnalisable. Le lien configure est affiche dans l'abonnement et
  prend proprement le pas sur l'ancienne methode de renouvellement textuelle.
- Ajout de `GET /api/portal/v1/me`, API v1 en lecture seule authentifiee par la
  session portail revocable. Elle expose uniquement profil, abonnement et acces
  media du principal, sans identifiants providers ni secrets, avec `no-store`,
  quota 120/15 minutes, HTTP 429 et contrat documente.

- Dans Settings, la carte de connexion administrateur Plex est maintenant
  masquée lorsqu'aucun serveur Plex n'est configuré. Les installations
  exclusivement Jellyfin ne voient donc plus cette proposition; le wizard et
  la méthode de connexion Plex déjà configurée restent inchangés.
- L'étape Abonnements du wizard devient un véritable éditeur : les forfaits
  existants peuvent être ouverts et modifiés au lieu d'être seulement listés.
  Création et modification couvrent désormais les mêmes critères principaux que
  l'interface dédiée : durée, valeur, défaut, activation, durée à vie, limites
  de flux et d'IP, action, réseau local, débit et appareils autorisés.
- Quand l'administrateur a choisi Plex pendant l'installation, l'adresse email
  renvoyée par Plex préremplit désormais le nom d'utilisateur SMTP et l'adresse
  d'expédition. Une configuration déjà personnalisée reste toujours prioritaire.
- Le garde global considère maintenant une identité Plex active comme une
  configuration administrateur valide, même sans mot de passe local. Il
  n'intercepte donc plus l'ajout des serveurs détectés, les étapes suivantes du
  wizard ni la future page de connexion d'une installation « Plex uniquement ».
- L'ajout des serveurs Plex suggérés depuis l'étape 4 reprend maintenant
  explicitement cette étape au lieu d'être interprété comme une ouverture neuve
  du wizard et de revenir à l'étape 1. Le même contrat de reprise est appliqué
  aux erreurs/expirations de découverte, à l'annulation, à la connexion locale
  pendant l'installation et aux redirections automatiques sans serveur.
- Correction de la boucle réelle après validation Plex dans une installation
  sans compte local : le garde d'authentification global n'intercepte plus le
  démarrage, le callback et la confirmation Plex du wizard avant leurs propres
  contrôles d'état, d'expiration et d'usage unique.
- Le flux Plex d'une installation neuve ne dépend plus uniquement du cookie du
  navigateur pendant l'aller-retour externe. Son état temporaire est également
  conservé côté serveur sous forme hachée, avec expiration de dix minutes et
  consommation unique; le callback peut donc reprendre le wizard même si le
  proxy, le domaine public ou le navigateur n'a pas renvoyé l'ancien cookie.
- Le retour du fournisseur Plex vers une installation en cours utilise maintenant
  une reprise explicite à usage unique : l'étape attendue est affichée même si le
  navigateur ou le proxy renouvelle le cookie de session pendant le trajet, puis
  l'URL est nettoyée pour qu'un rechargement manuel reparte bien à l'étape 1.
- L'étape administrateur d'une nouvelle installation propose désormais un vrai
  choix exclusif : connexion Plex seule, sélectionnée par défaut, ou compte local
  VODUM. Le parcours Plex ne demande plus d'email, de mot de passe ni de 2FA
  VODUM; l'identité confirmée chez Plex devient directement l'accès administrateur.
- Une ouverture directe ou un rechargement du wizard revient désormais toujours
  au choix initial « nouvelle installation / restauration ». La progression et
  les valeurs déjà enregistrées restent mémorisées; les redirections internes,
  y compris le retour de Plex, continuent normalement vers l'étape attendue.
- Le build Docker refuse maintenant explicitement une image qui ne contient pas
  l'option Plex de l'étape administrateur et son texte d'aide. Cela évite qu'un
  conteneur apparemment reconstruit affiche encore l'ancien écran sans Plex.
- Sur une installation neuve, l'étape administrateur affiche maintenant Plex
  comme choix par défaut. Après « Continuer », Plex s'ouvre directement;
  le retour reprend le wizard et permet la suggestion automatique des serveurs.
- L'étape suivante conserve également l'action Plex lorsque l'option a été
  décochée, annulée ou interrompue, afin que la liaison reste récupérable sans
  recommencer l'installation.
- Les serveurs accessibles par le compte Plex lié sont maintenant proposés
  automatiquement dans le wizard et la page Serveurs, sans bouton de recherche
  et sans nouvelle connexion Plex. Les serveurs dont le `machineIdentifier` est
  déjà enregistré dans VODUM sont entièrement masqués.
- L'autorisation du compte Plex est conservée chiffrée avec l'identité liée,
  renouvelée après une connexion Plex valide et supprimée avec cette identité.
  Pour les installations déjà liées, VODUM peut la récupérer sans reconnexion à
  partir d'un serveur existant seulement après avoir vérifié le même compte Plex.
  Les résultats et jetons propres aux ressources restent temporaires dix minutes.
- La prévisualisation intégrée distingue les serveurs possédés, partagés,
  disponibles, hors ligne et déjà configurés. Aucun serveur n'est présélectionné;
  l'administrateur choisit chaque serveur et l'adresse locale, publique ou relay
  à essayer en priorité avant l'ajout.
- Chaque ajout découvert repasse par le validateur Plex normal, vérifie le
  `machineIdentifier`, refuse les doublons et les résultats issus d'un autre
  compte lié, puis réutilise le pipeline habituel de contrôle et synchronisation.
  Un échec n'annule pas les autres ajouts et les formulaires manuels Plex et
  Jellyfin restent toujours disponibles.
- Ajout de tests sur le classement et le filtrage des connexions, la déduplication,
  le chiffrement temporaire, l'isolation par session, l'absence de jeton dans la
  page, la sélection explicite et les changements d'identité Plex. Le smoke test
  couvre désormais 91 templates et les nouvelles routes protégées/CSRF.
- Revue renforcée avant validation manuelle : les serveurs découverts sont
  maintenant inscrits dans l'état du wizard, une validation réseau redondante a
  été supprimée, les doublons concurrents sont bloqués atomiquement et chaque
  serveur d'un ajout multiple est isolé afin qu'une erreur inattendue n'arrête
  pas les suivants.
- Les recherches et connexions proposées sont désormais bornées, les URL avec
  identifiants, chemin ou paramètres sont rejetées, les résultats expirés sont
  supprimés et une identité Plex devenue inactive est refusée au retour. Le
  Dockerfile vérifie aussi la présence de l'intégration dans le wizard, la page
  Serveurs et l'écran de prévisualisation.
- Le bouton « Connecter Plex » adopte maintenant une taille compacte ajustée à
  son libellé au lieu d'occuper toute la largeur de la carte, sur ordinateur
  comme sur mobile.
- Suppression de la page intermédiaire « Compte Plex vérifié » lors de la
  connexion. Après un retour Plex valide et la correspondance exacte avec le
  compte lié, VODUM ouvre maintenant directement la session administrateur et
  redirige vers le tableau de bord. Seule la 2FA VODUM avancée, lorsqu'elle a été
  explicitement activée après Plex, peut encore ajouter une étape.
- La confirmation de l'identité retournée par Plex s'affiche maintenant dans une
  véritable modale centrée et responsive au lieu d'une page presque vide. Le
  compte détecté, l'effet de la confirmation et les actions Confirmer/Annuler
  sont clairement séparés; la modale expose aussi les attributs d'accessibilité
  `dialog` et `aria-modal`.
- Correction d'un formulaire HTML imbriqué dans les paramètres : le navigateur
  associait le bouton Plex au formulaire global et affichait « Paramètres
  enregistrés » sans ouvrir Plex. Le formulaire Plex est maintenant placé hors
  du formulaire Settings et ciblé explicitement par le bouton court « Connecter
  Plex ». Un smoke test bloque toute régression de cette structure.
- Simplification complète de la liaison Plex : une carte dédiée dans les
  paramètres affiche l'état et propose directement « Utiliser un compte Plex
  pour se connecter à VODUM ». Le clic ouvre Plex sans modale intermédiaire et
  sans redemander le mot de passe ou la 2FA VODUM à l'administrateur déjà
  connecté. La session authentifiée, le CSRF, l'état à usage unique et la
  confirmation de l'identité retournée restent appliqués.
- Le wizard utilise le même bouton direct après la création du compte local,
  sans nouvelle saisie de mot de passe ou de code 2FA. La liaison reste
  facultative et peut être ignorée.
- Le smoke test vérifie désormais dans le HTML authentifié la présence de cette
  carte, l'action `POST /auth/plex/link`, l'absence de champs mot de passe/2FA
  dans celle-ci et l'absence du formulaire Plex dans la fenêtre du compte local.
  La construction Docker échoue si le nouveau contrôle n'est pas embarqué.
- Revue de durcissement du nouveau parcours Plex : l'identite locale est
  desormais synchronisee apres une installation neuve ou un changement d'email,
  les redirections HTTP du client Plex sont limitees aux origines officielles,
  et un callback `GET` ne peut plus ouvrir une session ni modifier la date de
  derniere connexion. La connexion est finalisee par un `POST` protege par CSRF.
- Correction des gardes globaux Flask qui pouvaient intercepter la connexion
  Plex anonyme ou son retour dans le wizard avant l'ajout du premier serveur.
  Les routes publiques sont maintenant enumerees strictement afin que les
  actions de liaison, remplacement et deliaison restent protegees.
- Nettoyage des traces anti-abus liees aux etats Plex apres succes et purge des
  entrees anciennes pour eviter leur accumulation. Le bootstrap ne cree plus
  d'identite locale active a partir d'un email seul lorsqu'aucun mot de passe
  administrateur n'est configure.
- Les nouveaux messages Plex sont complets en allemand, anglais, espagnol,
  francais et italien. Le moteur i18n utilise aussi l'anglais comme repli pour
  une cle absente d'un catalogue actif, avant d'afficher la cle brute.
- Ajout d'un domaine d'authentification administrateur extensible et distinct
  des comptes media : le bootstrap cree un compte admin singleton, migre
  l'identite locale existante sans changer son comportement et conserve les
  identites externes sans `server_id`, jeton de serveur ou acces media implicite.
- Ajout de la liaison optionnelle d'une identite Plex depuis les parametres de
  securite. Le flux PIN Plex utilise un identifiant d'instance stable, des
  timeouts bornes, un etat aleatoire lie a la session et a usage unique, une
  reauthentification locale avec 2FA lorsqu'elle est active, puis affiche
  l'identite retournee avant confirmation. Aucun jeton Plex n'est persiste ni
  place dans le cookie de session, et un compte deja lie ne peut pas etre
  remplace silencieusement.
- L'identite Plex liee est maintenant visible dans les parametres et peut etre
  remplacee ou deliee uniquement apres une nouvelle verification du mot de
  passe local et de la 2FA active. Ces actions restent limitees a la methode
  d'authentification et ne modifient ni serveurs, ni utilisateurs, ni jetons
  media; la connexion locale demeure disponible comme voie de recuperation.
- La page de connexion propose desormais Plex uniquement lorsqu'une identite
  active est liee. Le compte retourne doit correspondre exactement a son
  identifiant stable avant l'ouverture de la session admin; la 2FA VODUM n'est
  pas redemandee par defaut apres l'authentification Plex, et la date de derniere
  connexion de l'identite est actualisee.
- Une option de securite avancee, desactivee par defaut et disponible uniquement
  lorsque la 2FA VODUM est configuree, permet d'exiger aussi le code VODUM apres
  une authentification Plex reussie. La preuve intermediaire expire apres cinq
  minutes, ne contient aucun jeton Plex et l'identite liee est reverifiee avant
  l'ouverture de la session.
- Les demarrages, callbacks invalides et echecs de 2FA des parcours Plex sont
  maintenant raccordes a la protection anti-bruteforce existante. Les appels a
  Plex sont bloques avant creation du PIN lorsque le seuil est atteint, les
  alertes suivent le meme circuit que la connexion locale et les etats ou
  identifiants externes sont remplaces par une empreinte avant stockage; aucun
  PIN, etat brut ou jeton n'est journalise.
- Le wizard propose maintenant la liaison Plex facultative juste apres la
  creation du compte local, sans renumeroter les etapes existantes ni casser
  une progression deja enregistree. La liaison reutilise le flux securise,
  exige une creation locale datant de moins de dix minutes, revient au wizard
  apres confirmation et peut etre ignoree sans bloquer l'installation; elle
  reste alors disponible plus tard dans les parametres de securite.
- Les retours Plex distinguent maintenant l'annulation ou l'autorisation non
  terminee, le PIN expire, la session expiree, invalide ou rejouee, le compte
  inattendu et l'indisponibilite reseau. Une page responsive fournit une action
  de retour adaptee avec des statuts HTTP 400, 403 ou 502 et confirme qu'aucune
  identite, aucun serveur et aucun jeton media n'a ete modifie; les details
  techniques et secrets ne sont jamais affiches.
- Les operations sensibles liees aux methodes de connexion exigent une preuve
  locale recente : mot de passe et 2FA active pour lier, remplacer ou delier
  Plex depuis les parametres, verification de creation locale recente dans le
  wizard, et mot de passe actuel pour modifier le mot de passe ou retirer la
  2FA VODUM.
- La couverture automatisee du parcours Plex inclut le client PIN, la migration
  idempotente, les sessions et rejeux, la liaison, le remplacement, le
  deliaisonnement, le wizard, la connexion sans double 2FA par defaut et son
  mode avance. Un test d'architecture interdit explicitement aux routes
  d'authentification les dependances de synchronisation, serveurs, fournisseurs
  et Jellyfin ainsi que toute ecriture vers `servers`, `user_identities` ou
  `media_jobs`.
- Enrichissement des diagnostics Discord : les erreurs distinguent désormais
  les problèmes permanents de configuration, destinataire ou permissions des
  incidents temporaires de réseau, disponibilité et rate limit. Les réponses
  brutes de l'API ne sont plus enregistrées dans l'historique, et les campagnes
  évitent les retries inutiles lorsqu'aucune erreur n'est récupérable.
- Les messages Discord longs ne sont plus tronqués silencieusement : ils sont
  découpés sans perte en plusieurs messages de taille sûre, avec retry par
  partie. Les éditeurs affichent une estimation du nombre de messages et
  précisent que le sujet et les pièces jointes concernent uniquement l'email.
- Les templates et campagnes peuvent désormais hériter de la configuration
  globale ou imposer l'email, Discord, ou les deux canaux. Ce ciblage est
  appliqué par les workers et un canal requis mais indisponible produit un
  diagnostic définitif au lieu d'être silencieusement ignoré. Les anciennes
  campagnes conservent leur canal d'origine pendant la migration, tandis que
  le mode campagne de test reste explicitement envoyé à l'email de contact.
