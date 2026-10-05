# Changelog

## 2026-10-05 - Sauvegarde de l'option d'invitation du portail

- Ajout du champ `portal_show_invitations` dans la requete de sauvegarde des
  reglages du portail : la case etait transmise mais ignoree par l'UPDATE SQL.
- Regression verifiee par un POST admin sur une base SQLite : activation,
  desactivation et lecture du reglage par le portail utilisateur.

## 2026-10-05 - Affiches des citations sur le dashboard et au login

- Verification et prechargement de l'affiche via le proxy/cache commun avant
  de retenir une citation de film ou de serie. Si l'image est indisponible,
  recherche d'une autre source ; une reponse HTML ne vaut pas une affiche.
- Reconstruction des caches anciens non verifies, avec tentative de conserver
  la citation du jour. Un echec de recherche n'est plus definitif pour la journee.
  Conservation de la derniere citation avec affiche verifiee en cas d'echec
  temporaire, et utilisation commune au dashboard et au login avant le refresh.
- Prechargement du fond de connexion et repli sur l'affiche quand le backdrop
  est indisponible. Ecriture atomique du cache des citations pour eviter une
  lecture de fichier partiellement ecrit.
- Correction du clignotement HTMX : les nouvelles tentatives se font hors ecran,
  au maximum une fois par minute. L'image apparait uniquement apres chargement
  reussi ; un changement de source d'image remplace egalement la carte.
- Diagnostic du proxy : journalisation du fournisseur, serveur, type d'erreur
  et statut HTTP, sans URL ni identifiants. Sur l'installation reelle, l'ancien
  cache ciblait JellySerieEmpire hors ligne. Reconstruction declenchee et affiche
  de The Batman confirmee dans le dashboard. Recherche Plex filtree par GUID pour
  eviter le timeout observe sur le parcours complet de la bibliotheque.
- Validation : 24 tests dashboard et un scenario JavaScript reussis, incluant
  The Office comme serie Plex, les routes d'image dashboard/login pour Plex
  et Jellyfin, les echecs de telechargement et la reprise d'affichage.
  Echanges fournisseurs simules ; affichage sur l'installation reelle a verifier.

## 2026-10-05 - Invitations d'amis depuis le portail et identifiants Jellyfin

- Correction du blocage au demarrage : la nouvelle route d'invitation d'ami
  utilisait le meme nom Flask que l'invitation administrateur. Renommage en
  `portal_friend_invite`, mise a jour du formulaire et ajout de regressions
  couvrant l'enregistrement de toutes les routes et la fabrique d'application.
- Ajout de la case « Inviter un ami » dans les sections visibles du portail,
  desactivee par defaut. Une fois activee, une nouvelle carte apparait dans
  Abonnement avec email obligatoire, prenom, nom et telephone facultatifs.
- Reutilisation du parcours de creation et d'activation existant. Les serveurs,
  bibliotheques, options de partage Plex, forfait, limites personnalisees et
  echeance sont repris cote serveur depuis le compte invitant ; celui-ci est
  automatiquement enregistre comme parrain du nouveau compte.
- Refus des adresses email deja associees a un compte et des parrains inactifs,
  controle des sections activees, protection CSRF et limite de cinq demandes
  d'invitation par utilisateur sur quinze minutes.
- Jellyfin : generation automatique du mot de passe lorsqu'aucun n'est fourni
  a la creation. Les invitations d'amis utilisent le meme mot de passe genere
  sur leurs serveurs Jellyfin. L'activation demande de se connecter avec les
  identifiants envoyes par email, sans choisir un nouveau mot de passe.
- Ajout des variables explicites `{jellyfin_password}` et `{jellyfin_username}`
  dans l'editeur de communications et les modeles de bienvenue par defaut.
  Les anciens modeles par defaut non personnalises sont mis a jour ; les
  contenus personnalises sont conserves et peuvent utiliser ces variables.
- Transmission des identifiants dans les emails de creation, y compris avec
  activation differee et comptes mixtes. Les mots de passe sont chiffres dans
  la file d'envoi, conserves pour les reprises puis retires apres envoi reussi ;
  ils sont masques dans l'historique des notifications.
- Validation : 186 tests automatises reussis couvrant portail, activation,
  communications, provisionnement et bootstrap, dont les invitations et la
  livraison des identifiants Jellyfin. Appels fournisseurs et envois simules ;
  validation sur une installation et un serveur SMTP reels restant a faire.

## 2026-09-24 - Alignement Jellyfin sur la version publiée GitHub

- Référence fournie par l'utilisateur : `origin/main`, commit
  `e5fbc501f061ad0872897af078798b91d7f70b46`, version 26.09.16 b0539.
- Restauration exacte de `core/jellyfin_auth.py`, `core/jellyfin_http.py` et
  `tasks/sync_jellyfin.py` depuis cette référence. Ce changement remplace les
  tentatives précédentes de retour arrière fondées sur le HEAD local d'août.
- Vérification : les neuf autres fichiers de transport, fournisseurs,
  monitoring, contrôle serveur et stockage des secrets comparés sont déjà
  identiques à cette référence. Les modifications d'expiration sont conservées.
- 44 tests locaux réussis. Cette comparaison explique les écarts introduits
  par les derniers correctifs, mais ne démontre pas la cause des timeouts
  initiaux ni l'identité de la configuration et de l'image réellement exécutée.

## 2026-09-24 - Retour au parcours de synchronisation Jellyfin antérieur

- Annulation des changements récents du comptage Jellyfin : restauration de
  la séquence `/Items/Counts`, puis `/Items`, et des requêtes par utilisateur
  lorsque le comptage sans utilisateur ne fournit pas de résultat exploitable.
- Restauration de la lecture dédiée `/Users/{id}` pour les politiques, avec
  le délai historique de 30 secondes. Conservation de l'arrêt sur réponse
  invalide ou incomplète pour ne pas effacer des droits ou identités par erreur.
- Authentification : envoi de la même clé déchiffrée dans `Authorization` et
  `X-Emby-Token`. Le retour à `X-Emby-Token` seul avait produit des HTTP 401
  sur les installations signalées ; ce retour est annulé.
- Retour ciblé construit à partir des fonctions suivies dans Git (6d73efd),
  sans prétendre restaurer une image exacte du 22 septembre : aucun commit de
  cette date n'est disponible. Sauvegarde locale préalable dans `.tmp`.
- Validation : 45 tests locaux réussis, incluant deux serveurs HTTP de test
  exigeant respectivement chaque format d'authentification, le repli de
  comptage et la préservation des données lors d'un timeout. Déploiement et
  fonctionnement sur l'installation réelle non vérifiés depuis ce poste.

## 2026-09-23 - Retour aux requêtes Jellyfin antérieures

- Rétablissement de `X-Emby-Token` pour les appels API Jellyfin, à la place
  de l'en-tête Authorization introduit récemment. Conservation du déchiffrement
  des clés enregistrées et de la validation des caractères d'en-tête.
- Rétablissement de 20 secondes par comptage de bibliothèque au lieu de 5,
  suppression du budget global de 15 secondes qui pouvait laisser les dernières
  bibliothèques sans mise à jour. Le premier échec réseau interrompt toujours
  les comptages suivants et préserve les valeurs précédentes.
- Maintien des 30 secondes pour les utilisateurs, de la réutilisation des
  politiques incluses dans leur liste et des protections en cas de réponse
  incomplète. Les échecs restent signalés.
- Validation locale : 41 tests réussis, dont un parcours HTTP avec clé chiffrée
  et le comptage simulé de plusieurs bibliothèques lentes. Retour de compatibilité
  appliqué ; résolution sur l'installation réelle non vérifiée à distance.

## 2026-09-23 - Diagnostic des lenteurs Jellyfin

- Comparaison optionnelle `--compare-auth` entre l'ancien en-tête
  `X-Emby-Token` et le nouvel en-tête `Authorization`, sur les mêmes appels
  utilisateurs/comptage et avec des connexions séparées. Trois tests ciblés
  réussis ; résultat sur le serveur réel encore nécessaire pour conclure.

- Ajout de `python -m diagnose_jellyfin 7`, à exécuter dans le conteneur VODUM :
  mesure séparée des utilisateurs, sessions, bibliothèques et d'un comptage,
  sur les adresses configurées, avec les accès enregistrés.
- Base ouverte en lecture seule ; aucune modification des comptes. Le rapport
  affiche les durées, codes HTTP et types d'erreurs, sans adresse, clé API ni
  contenu des utilisateurs. Deux tests ciblés réussis.
- Diagnostic ajouté pour poursuivre l'investigation des timeouts signalés ;
  leur cause sur l'installation réelle n'est pas encore confirmée.

## 2026-09-23 - Correction du délai de synchronisation Jellyfin

- Rétablissement du délai de 30 secondes pour la récupération de la liste des
  utilisateurs et des politiques individuelles. La réduction à 15 secondes
  pouvait interrompre la synchronisation de serveurs plus lents ou chargés.
- Conservation des optimisations de comptage des bibliothèques et de lecture
  des politiques déjà incluses dans la liste des utilisateurs.
- Un échec de récupération reste signalé et ne déclenche pas de nettoyage des
  utilisateurs absents ni de leurs accès sur la base d'une liste incomplète.
- Validation : 17 tests ciblés réussis, dont une réponse simulée à 20 secondes
  et la conservation des données lors d'un dépassement du délai. Aucun appel
  au serveur réel ; le bon déroulement sur celui-ci reste à vérifier.

## 2026-09-23 - Règles d'expiration communes et comptes mixtes

- L'abonnement reste valable pendant toute sa date d'expiration : le statut
  devient expiré le lendemain, comme les actions de retrait et de suppression.
- Protections communes pour les abonnements à vie, overrides, propriétaires
  Plex et administrateurs Jellyfin ; préservation des statuts manuels et
  exclusion des notifications automatiques d'expiration pour ces fiches.
- Une invitation Plex en attente exclut uniquement ce compte des blocages et
  retraits d'accès. Elle ne décale plus l'expiration d'une fiche possédant aussi
  un compte actif Jellyfin ou Plex. Les règles de lecture ciblent les comptes
  éligibles et les retraits de bibliothèques restent limités à leur serveur.
- Nettoyage des anciens blocages système lors d'une exemption ou d'un
  renouvellement, et suppression des doublons sans modifier les règles manuelles.
- La suppression complète conserve ses protections plus strictes : toutes les
  cibles doivent être éligibles et confirmées avant de supprimer la fiche VODUM.
- Validation : 61 tests ciblés réussis, dont 8 nouveaux scénarios de régression.
  Appels natifs simulés ; aucun compte réel modifié pendant ces contrôles.
- Détails : [règles d'expiration](docs/regles-expiration-2026-09-23.md).

## 2026-09-23 - Suppression des utilisateurs après expiration

- Nouvelle option « Supprimer l'utilisateur après expiration » dans Expiration
  behavior, avec délai configurable de 1 à 3 650 jours. Elle ne bloque pas les
  lectures pendant le délai et reste désactivée tant qu'elle n'est pas choisie.
- Suppression native du compte Jellyfin ou retrait des partages des serveurs
  Plex concernés, puis suppression de la fiche VODUM après confirmation de
  toutes les cibles. Aucun compte Plex personnel n'est supprimé.
- Ajout du petit « ? » demandé : sans le mode d'import limité aux utilisateurs
  partagés, une identité Plex peut être réimportée après sa suppression locale.
  Aide utilisable au clavier et au clic, traduite dans les cinq langues.
- Protections des propriétaires, administrateurs, Plex Home, invitations en
  attente, abonnements à vie et exemptions d'expiration. Relecture de la date
  et du mode avant suppression, respect de l'arrêt du planificateur.
- En cas d'échec partiel, conservation de la fiche locale, journalisation et
  reprise idempotente. Les anciens jobs d'accès en file sont annulés pour ne
  pas rétablir un partage retiré ; les jobs en cours reportent la suppression.
- Validation : 35 tests ciblés réussis, dont les deux formulaires et le parcours
  de suppression sur base temporaire avec le vrai bootstrap. Les appels natifs
  sont simulés ; aucun compte réel n'a été supprimé.
- Détails et limites dans `docs/suppression-expiration-2026-09-23.md`.

## 2026-09-23 - Import Plex limité aux partages par défaut

- Le mode `shared_only` devient le défaut pour les nouvelles installations et
  les paramètres absents ou invalides. Les choix existants valides, notamment
  `global`, sont conservés lors des mises à jour et des sauvegardes de formulaire
  qui ne transmettent pas ce champ.
- Mise à jour des libellés dans les cinq langues : le mode partagé est identifié
  comme défaut et l'aide précise que changer de mode ne supprime pas les fiches
  et historiques déjà présents dans VODUM.
- Correction du parsing Plex : l'identifiant d'un partage n'est plus utilisé
  comme identifiant utilisateur lorsque `userID`/`userId` manque ou vaut zéro.
- Vérification sur base temporaire du vrai traitement de synchronisation :
  utilisateur partagé sur deux serveurs, absence de réimport après retrait du
  partage et suppression locale, absence de repli vers l'import global et
  conservation des données locales en cas de réponse vide.
- Validation : 13 tests ciblés réussis, dont bootstrap initial et répété.
  Les réponses Plex sont simulées ; aucun compte réel n'a été modifié.

## 2026-09-22 - Cycle de vie : cartographie et réglages d'expiration

- Cartographie des modes d'expiration, suppressions locales, exceptions et
  renouvellements dans `docs/cycle-vie-utilisateurs-2026-09-22.md`. La TODO
  précise les écarts à traiter avant les nouvelles actions natives Jellyfin.
- Retrait du champ « supprimer après X jours », qui n'était relié à aucun
  traitement. Une explication remplace le champ ; la valeur historique reste
  conservée en base, sans activer de suppression automatique.
- Le passage à « aucune action » ou au retrait direct des accès nettoie les
  anciennes règles système de blocage depuis les deux pages de réglages,
  sans supprimer les règles manuelles.
- Les réglages d'abonnement et l'activation automatique respectent désormais
  l'arrêt du planificateur. Une date d'expiration supprimée ne laisse plus de
  règle de blocage résiduelle au prochain passage du gestionnaire.
- Ajout de régressions sur les changements de mode, la préservation des règles
  manuelles, l'arrêt du planificateur et la suppression de la date d'expiration.
- Correction complémentaire repérée pendant les tests : le nettoyage des logs
  accepte les dates anciennes hors de la plage des timestamps Windows.
- Validation : 28 tests ciblés réussis, contrôle des deux formulaires sur une
  base temporaire avec le vrai bootstrap et compilation Python réussie.

## 2026-09-22 - Clôture des validations fonctionnelles

- Validations fonctionnelles et sur l'installation réelle considérées comme
  terminées sur confirmation de l'utilisateur : mots de passe et coupure de
  lecture Jellyfin, restauration sur une instance neuve et checklist manuelle
  de publication derrière le reverse proxy HTTPS.
- Retrait de ces validations de la TODO. Cette clôture ne constitue pas une
  nouvelle exécution des tests par l'agent ; les audits restant à réaliser et
  les problèmes identifiés dans les tests automatisés restent à traiter.

## 2026-09-21 - Conservation configurable des logs

- Ajout des réglages de logs dans Settings > Système : conservation de 7, 14,
  30 ou 90 jours, avec 30 jours par défaut.
- Plafond de stockage de 50 Mo par défaut, configurable de 5 à 1 000 Mo dans
  les options avancées. Les fichiers les plus anciens sont supprimés plus tôt
  si ce plafond est atteint.
- Nettoyage automatique selon l'âge et la taille, y compris des archives
  existantes, avec prise en compte des réglages sans redémarrage.
- Migration automatique des paramètres et traductions en français, anglais,
  allemand, espagnol et italien.
- Validation : 17 tests des logs, test de migration et vérification du formulaire
  avec sauvegarde des réglages et rejet des valeurs invalides.

## 2026-09-07 - P0 Jellyfin : coupure et mot de passe

- Une erreur du message d'avertissement ne bloque plus la coupure groupee.
- Verification de la session et du titre avant Stop ; aucun arret d'un nouveau
  titre a partir d'une ancienne ligne du collecteur. Les reponses de sessions
  invalides et les redirections de commandes ne valent plus succes.
- Confirmation de l'arret jusqu'a cinq secondes, avec diagnostic des capacites
  du client si la lecture continue. Aucun changement des droits du compte.
- Correction de la regression du 06/09 : `ResetPassword=false` laisse Jellyfin
  appliquer `NewPw` ; `true` choisit une autre branche et ignore ce mot de passe.
- 33 tests cibles passent ; validation sur clients Jellyfin reels encore a faire.

## 2026-09-06 - Correction du mot de passe Jellyfin

- Remplacement de `NewPassword` par `NewPw`. Le parametre `ResetPassword`
  introduit dans ce lot a ete corrige le 07/09 (voir ci-dessus).
- Retrait de l'option « changement de mot de passe obligatoire », non supportée
  par le modèle de politique Jellyfin.

## 2026-08-31 - Liens externes de renouvellement du portail

- La piste d'integration directe aux API de paiement a ete abandonnee: VODUM ne
  stocke aucun credential marchand et ne cree ni transaction ni webhook.
- L'administrateur peut activer et organiser une liste compacte de liens HTTPS
  externes avec libelle, texte de bouton et instructions.
- La page Abonnement affiche les liens applicables avec un avertissement clair:
  le paiement est externe et le renouvellement reste valide manuellement.
- La devise affichee reste l'unique `subscription_currency` des reglages
  d'abonnement; aucun second reglage divergent n'est cree.

## 2026-08-31 - Audit securite backup et restauration

- Les archives refusent maintenant chemins malveillants POSIX/Windows, doublons,
  symlinks, fichiers speciaux et membres ZIP chiffres avant toute extraction.
- Le rollback post-restauration couvre desormais les pieces jointes avec la base
  et la cle de chiffrement.
- Une base restauree sans cle embarquee doit prouver que tous ses secrets sont
  compatibles avec la cle active avant le remplacement.
- Les telechargements sensibles sont `private, no-store` et l'API de liste ne
  divulgue plus les chemins locaux.

## 2026-08-31 - Audit des secrets et cles persistantes

- Une cle de chiffrement manquante n'est plus regeneree lorsqu'une base ou son
  WAL contient deja des credentials chiffres; le demarrage exige la restauration
  de la cle correspondante.
- La creation initiale de `vodum.encryption_key` est atomique et restrictive.
- La migration chiffre aussi les anciens secrets TOTP administrateur et
  Turnstile encore stockes en clair.
- Le filtre de logs neutralise maintenant explicitement mots de passe, secrets
  et cles API en plus des tokens et autorisations.

## 2026-08-31 - Audit LAN et reverse proxy

- La confiance des en-tetes forwarded, le filtre IP, HTTPS, les cookies Secure,
  HSTS et Host ont ete testes ensemble en acces direct et via proxy.
- Le controle de hostname du portail gere maintenant correctement les adresses
  IPv6 avec port.
- Les reseaux prives restent autorises par defaut; un proxy non approuve ne peut
  influencer ni l'adresse cliente, ni le schema HTTPS, ni Host.

## 2026-08-31 - Audit SSRF et origine des sorties HTTP

- La session HTTP des serveurs refuse maintenant toute requete initiale et toute
  redirection vers une origine non configuree.
- Les adresses LAN, loopback et IPv6 restent utilisables lorsqu'elles appartiennent
  explicitement aux URL du serveur configure.
- La recherche d'illustrations du tableau de bord et le ping des serveurs generiques
  utilisent desormais la session HTTP bornee commune.
- Un rapport d'inventaire et quatre tests de regression documentent la garantie.

## 2026-08-30 - En-tetes HTTP et CSP progressive

- Verification automatisee de HSTS sur HTTPS, `nosniff`, protection frame,
  Referrer-Policy et Permissions-Policy sur les reponses HTTP.
- Correction de la CSP stricte du portail : les deux comportements JavaScript
  inline encore presents ont ete externalises dans un asset `self`, ce qui evite
  leur blocage par le navigateur sans ajouter `unsafe-inline` aux scripts.
- Ajout de `object-src 'none'` et confirmation de la CSP d'enforcement et du
  `Cache-Control: no-store` sur les pages et API du portail.
- L'administration reste sans CSP d'enforcement jusqu'a externalisation de ses
  handlers inline; les autres en-tetes defensifs restent appliques globalement.

## 2026-08-30 - Audit XSS des rendus administrateur et portail

- Revue des contournements d'echappement Jinja, du HTML genere en Python et des
  sinks DOM dans le JavaScript applicatif, hors bibliotheques vendor minifiees.
- Confirmation que les valeurs utilisateur/provider, medias, serveurs, logs,
  communications, erreurs et imports sont echappees avant insertion HTML ou
  affectees avec `textContent`.
- Suppression du dernier `|safe` Jinja, inutile car il ne servait qu'a afficher
  des fleches de tri constantes.
- Ajout de regressions avec charges hostiles sur le seul filtre Python retournant
  `Markup`, qui echappe ses attributs et son texte visible.

## 2026-08-30 - Audit global CSRF et methodes HTTP

- Extraction du garde CSRF global dans un module de securite dedie, toujours
  enregistre directement par la fabrique Flask avant les modules de routes.
- Suppression d'exemptions techniques inutiles : toutes les requetes POST, PUT,
  PATCH et DELETE exigent maintenant sans exception un jeton de session valide.
- Ajout de regressions pour les formulaires et requetes JSON, les jetons absents,
  vides ou incorrects et chacune des quatre methodes mutantes.
- Extension de l'audit statique des GET a toute l'application; aucune mutation
  persistante non revue n'est detectee. Le proxy artwork authentifie et son cache
  local restent l'unique exception documentee.

## 2026-08-30 - Audit de non-enumeration du compte administrateur

- Confirmation que les emails administrateur connus et inconnus recoivent la
  meme erreur generique, la meme redirection et les memes controles anti-abus.
- Confirmation que les deux chemins executent exactement une verification de
  mot de passe couteuse; un hash factice est utilise pour un compte inconnu.
- Les motifs detailles restent reserves aux journaux et alertes d'exploitation
  et ne sont pas renvoyes dans la reponse d'authentification.

## 2026-08-30 - Audit anti-bruteforce des connexions

- Confirmation du verrouillage combine par IP et par email pour les connexions
  locales administrateur et portail, avec fenetre et duree de blocage bornees.
- Extension de cette protection a la connexion Jellyfin du portail : les echecs
  sont comptes par IP et par couple serveur/utilisateur avant tout nouvel appel
  au provider; les valeurs de compte restent uniquement stockees sous forme
  d'empreinte.
- Correction de la deconnexion portail en cas de panne DB : l'echec de revocation
  serveur est journalise mais n'empeche plus l'effacement du cookie navigateur.

## 2026-08-30 - Audit des cookies de session LAN et proxy HTTPS

- Verification des attributs reels `Secure`, `HttpOnly`, `SameSite` et
  `Expires` du cookie de session en HTTP LAN direct et derriere un reverse proxy
  HTTPS de confiance.
- Confirmation qu'un proxy non approuve ne peut pas imposer la semantique HTTPS
  avec un en-tete `X-Forwarded-Proto` forge.
- Le comportement existant est conserve : cookie utilisable en HTTP LAN avec
  `HttpOnly` et `SameSite=Lax`, et cookie `Secure` avec la politique SameSite
  configuree lorsque HTTPS est etabli directement ou par un proxy approuve.

## 2026-08-30 - Audit de la duree des sessions

- Confirmation d'une expiration glissante apres 12 heures d'inactivite par
  defaut, configurable avec `VODUM_SESSION_LIFETIME_HOURS`, pour les sessions
  administrateur et portail.
- Confirmation que seules les sessions authentifiees deviennent permanentes
  dans le navigateur; les etats temporaires de connexion restent lies a la
  session du navigateur.
- Ajout de regressions sur le caractere permanent et la rotation de l'etat
  pre-authentification, en complement des tests d'expiration serveur.

## 2026-08-29 - Invalidation serveur des sessions a la deconnexion

- Ajout de sessions administrateur opaques et revocables cote serveur; la
  deconnexion revoque uniquement la session courante avant d'effacer le cookie.
- Le garde global refuse les sessions revoquees, expirees, alterees et les anciens
  cookies sans reference serveur, qui doivent se reconnecter une fois apres migration.
- Confirmation de la revocation serveur deja appliquee aux sessions portail.

## 2026-08-29 - Verification anti-fixation des sessions admin

- Confirmation que les connexions locale et Plex utilisent la meme ouverture de
  session, qui supprime l'etat pre-authentification et ne preserve que la langue.
- Ajout de regressions prouvant la suppression des marqueurs controles, du CSRF
  pre-authentification et des preuves Plex temporaires apres authentification.

## 2026-08-29 - Audit de la confiance TOTP locale

- Restriction explicite de la confiance locale aux reseaux RFC1918, loopback,
  link-local et IPv6 ULA, sans dependre de la classification plus large et
  evolutive de `ipaddress.is_private`.
- Verification automatisee de la duree et des attributs HttpOnly, Secure et
  SameSite du cookie, ainsi que de son invalidation par email ou secret TOTP.

## 2026-08-29 - Audit de la verification et de l'enrolement TOTP

- Correction de l'enrolement TOTP Settings et wizard: le secret confirme est
  maintenant genere et lie a la session par le serveur, expire apres dix minutes
  et est consomme une seule fois; une valeur choisie dans le formulaire est ignoree.
- Retrait des champs caches qui renvoyaient le secret comme source d'autorite et
  ajout de tests d'expiration, isolation des usages et consommation unique.

## 2026-08-29 - Audit de la connexion administrateur Plex

- Audit du flux PIN Plex administrateur, de l'etat de session, du callback,
  de la correspondance d'identite, du TOTP VODUM optionnel et de l'ouverture
  de session; aucune vulnerabilite exploitable supplementaire n'a ete confirmee.
- Ajout de regressions sur l'usage unique, l'expiration, la separation des usages
  des flux Plex et la consommation de la preuve TOTP intermediaire expiree.

## 2026-08-29 - Audit de la connexion administrateur locale

- Audit du parcours complet email/mot de passe administrateur: CSRF, normalisation,
  anti-bruteforce IP/email, TOTP, redirection, rotation de session et journalisation.
- Suppression d'un canal d'enumeration temporelle: les emails inconnus effectuent
  maintenant une verification de hash factice aussi couteuse que les comptes connus.
- Ajout de tests de regression pour les chemins email connu et inconnu.

## 2026-08-28 - Runtime du conteneur et dependances

- Mise a jour des dependances Python directes, notamment Flask 3.1.3,
  Waitress 3.0.2, Requests 2.34.2 et Cryptography 50.0.1; `pip-audit` ne
  detecte aucune vulnerabilite connue dans le nouvel ensemble.
- Ajout d'une vraie route `/health` et remplacement du healthcheck trompeur sur
  `/` par une sonde Python directe, sans shell ni redirection de connexion.
- Retrait de `curl` de l'image, installation APT sans recommandations et
  configuration Python/pip adaptee a un conteneur de production.
- Correction du workflow de publication Docker mal forme et suppression de
  l'affichage inutile du nom de compte du registre.
- Documentation des controles restant a effectuer dans CI : scan de l'image
  Linux finale et validation des droits de volumes avant un passage non-root.

## 2026-08-28 - Durcissement de la classification des routes

- Audit des 178 routes Flask enregistrees et confirmation du repli ferme vers
  le perimetre administrateur pour toute route non explicitement classee.
- Correction des frontieres de prefixes publics et setup : des chemins voisins
  comme `/health-debug`, `/static-admin` ou `/setup-secret` ne peuvent plus
  heriter accidentellement d'un acces moins restrictif.
- Correction de la classification de `POST /portal/auth/jellyfin`, qui est de
  nouveau accessible avant connexion tout en conservant le controle du hostname,
  le rate limiting et les validations provider existantes.
- Ajout de tests couvrant les chemins ressemblants, l'acces anonyme, le refus
  d'un utilisateur portail sur l'administration et l'acces d'un administrateur.
# 2026-09-01

- Correction des actions des sauvegardes dont les séparateurs PowerShell
  littéraux étaient affichés dans les libellés Download, Restore et Delete.
- Placement de Payment & renewal derrière le mode debug : option expérimentale
  masquée en fonctionnement normal, avertissement « ne pas utiliser », panneau
  affiché seulement après activation dans les sections visibles et blocage
  serveur des liens lorsque le mode debug est désactivé.
- Finalisation des liens externes du User Portal : contrat i18n vérifié sur les
  cinq langues et régressions ajoutées pour l'absence de lien, les liens
  désactivés, les forfaits masqués déjà attribués, les abonnements à vie et les
  utilisateurs expirés.
# Corrections P0 — 2026-09-04

- Autorise les iframes locales dans la CSP d’administration et force le chargement
  du monitoring intégré au profil utilisateur.
- Le refresh des bibliothèques Plex/Jellyfin est désormais opérationnel depuis
  `Servers & Libraries` (route POST protégée par CSRF, avec ciblage de la section
  Plex et scan serveur Jellyfin).
