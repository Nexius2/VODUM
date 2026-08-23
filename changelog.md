# Changelog

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
