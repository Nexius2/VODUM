# Changelog

Les changements non publiés sont regroupés en tête de ce fichier. Les dates
indiquent la mise à jour du journal, pas une confirmation de déploiement.

## Non publié — mise à jour du 2026-11-19

### Formules fournies sans montant et exemple à vie

- Le [catalogue commun](app/core/default_subscription_templates.py) fournit
  désormais base, Family, Plus et « Lifetime sub » sans valeur d'abonnement
  renseignée. Le [premier démarrage](app/core/db_bootstrap_subscriptions.py) et
  la restauration utilisent les mêmes définitions, supprimant leurs montants
  divergents. Lifetime utilise `is_lifetime=1`, sans échéance ni règles de flux
  préremplies ; comme les autres exemples, il reste désactivé, et est masqué du
  portail tant que l'administrateur n'en décide pas autrement.
- Le [formulaire](static/js/pages/subscriptions-template-editor.js),
  l'[enregistrement](app/routes/subscriptions_page.py) et la
  [duplication](app/core/subscription_template_admin.py) conservent un montant
  absent ; un zéro explicitement saisi reste un zéro.
- Aucune migration de données existantes : montants personnalisés, formules et
  attributions sont conservés. Sur une installation existante, « Restaurer les
  formules par défaut » ajoute Lifetime s'il manque, sans écraser les formules
  présentes ni effacer leurs anciens montants. Un exemple supprimé ne revient
  pas automatiquement au démarrage. [Détails](vodum-docs/docs/subscriptions.md).

### Migrations limitées aux configurations admissibles

- La [disponibilité locale](app/core/migrations/availability.py) exige une paire
  Plex/Jellyfin, deux Jellyfin distincts, ou deux Plex dont les propriétaires
  identifiés sont différents. Même compte Plex, compte inconnu, serveur unique
  ou connexions ARR seules ne rendent pas les migrations disponibles.
- Le [menu](templates/base.html) est masqué et les [routes](app/routes/migrations.py)
  répondent 404 sans paire admissible, y compris les imports et démarrages par
  URL directe. L'[analyse](app/core/migrations/analysis.py) et le
  [traitement des utilisateurs](app/core/migrations/execution.py) vérifient aussi
  la paire. Les propriétaires Plex inconnus doivent d'abord être synchronisés.
- Une panne temporaire ne masque pas une configuration admissible, mais les
  contrôles d'analyse et d'exécution continuent à exiger deux serveurs en ligne.
  Campagnes et rapports existants sont conservés en base, même lorsque l'espace
  devient inaccessible. [Conditions et limites](vodum-docs/docs/migrations.md).
- Aucun nouvel index ni migration de schéma. Déployer ensemble catalogue,
  bootstrap, routes, contrôles, templates, script et traductions, puis redémarrer.
  Tests locaux des configurations, accès directs, exécution bloquée, initialisation,
  restauration, montants vides et personnalisés ; aucune validation en production.

### Ajout des serveurs Plex sélectionnés avec « Continuer »

- À l'étape Serveurs de l'[installation](templates/setup/wizard.html), les cases
  et les adresses des [propositions Plex](templates/servers/_plex_suggestions.html)
  sont envoyées avec « Continuer ». Le bouton d'ajout séparé disparaît uniquement
  dans l'assistant ; l'ajout manuel reste indépendant dans son bloc dépliable.
- Le [traitement de la sélection](app/routes/plex_auth.py) valide chaque serveur
  avant de passer à la suite. Les messages de réussite nomment les serveurs prêts
  et restent visibles après la redirection. Tout échec maintient l'étape 4,
  même si d'autres serveurs sont déjà configurés : les réussites sont conservées,
  les échecs restent cochés avec l'adresse choisie pour réessayer. Les sélections
  expirées, inconnues, hors ligne ou liées à une autre identité sont refusées.
- La [découverte](app/core/plex_server_discovery.py) retourne dès le premier
  affichage les identifiants persistés nécessaires aux cases du formulaire,
  comme lors des lectures du cache. Messages traduits dans les cinq langues.
- Aucune migration ; déployer ensemble routes, découverte, templates et
  traductions. Tests locaux des succès, échecs partiels, reprises, doublons et
  protections de sélection ; aucune validation sur les serveurs de production.

### Ajout manuel de serveurs replié dans l'installation

- À l'étape [Serveurs multimédias](templates/setup/wizard.html), le fournisseur,
  l'URL, le jeton et le bouton de test sont regroupés sous « Ajouter d'autres
  serveurs », fermé par défaut. Un clic déplie l'ajout manuel ; les propositions
  Plex et les serveurs déjà configurés restent directement accessibles.
- Libellé traduit dans les cinq langues. Aucune migration ; déployer le template
  et les traductions ensemble. Vérification locale du rendu HTML ; aucun
  changement du traitement des ajouts ou de leur validation.

### Compte administrateur Jellyfin et choix initial sans limitation des serveurs

- L'[installation](templates/setup/wizard.html) propose désormais Plex, Jellyfin
  ou un compte local VODUM. Un texte commun précise que d'autres serveurs et
  comptes média peuvent être ajoutés après l'installation, pour Plex comme pour
  Jellyfin. L'ancien conseil imposant le compte local à Jellyfin est remplacé.
- Le [client Jellyfin](app/core/admin_jellyfin_auth.py) et les
  [routes administrateur](app/routes/jellyfin_admin_auth.py) utilisent Quick
  Connect après saisie de l'adresse du serveur : code valable cinq minutes,
  approbation dans Jellyfin puis confirmation dans VODUM. Seul un administrateur
  Jellyfin actif est accepté. Le premier serveur est validé et ajouté avec le
  parcours existant ; son jeton est chiffré, aucun mot de passe Jellyfin n'est
  demandé. La liaison identifie l'adresse, le serveur et l'utilisateur ; une
  autre identité, une liaison révoquée ou un code expiré ne crée pas de session.
- La [connexion](app/routes/auth.py) affiche le bouton Jellyfin lorsque lié et
  ne renvoie plus les installations sans mot de passe local vers l'installation
  si une identité Plex ou Jellyfin est active. Le formulaire local n'est affiché
  que si ses identifiants existent. CSRF, contrôle IP/hôte, limitation des essais
  et sessions administrateur révocables restent actifs ; les confirmations en
  attente ne consomment pas d'essais supplémentaires.
- [Documentation et limites](vodum-docs/docs/configuration.md) : Quick Connect
  doit être actif et le serveur lié joignable. La gestion des liaisons Jellyfin
  dans les paramètres n'est pas ajoutée par ce lot. L'authentification du portail
  reste distincte ; ajouter des comptes média ne crée pas d'autres administrateurs
  VODUM. Interface et messages disponibles dans les cinq langues.
- Migration additive au démarrage dans le
  [bootstrap d'authentification](app/core/db_bootstrap_admin_auth.py) : table
  `admin_auth_flows` et index d'expiration, pour consommer les approbations une
  seule fois côté serveur, même en cas de rejeu d'un ancien cookie. Aucune donnée
  existante réécrite. Déployer ensemble bootstrap, modules Python, templates et
  traductions, puis redémarrer avant d'utiliser le nouveau choix.
  Vérifications locales sur bases temporaires et réponses
  Jellyfin simulées, sans connexion à un compte réel ni validation en production.

### P0 — pagination du monitoring utilisateurs avant calcul de l'historique

- Le [monitoring utilisateurs](app/core/monitoring/overview_users.py) calcule les
  totaux dédupliqués uniquement pour les utilisateurs de la page lors des tris
  nom, dernière lecture, IP et lecteur sans recherche. Les comptes liés, durées,
  données de dernière lecture et pages conservent leur logique. Les recherches
  et tris Lectures/Durée gardent le parcours global.
- [Mesures locales et limites](docs/performance-monitoring-users-2026-11-19.md) :
  sur 100 082 lectures et 1 005 comptes synthétiques, médiane de 269 à 27 ms pour
  la dernière lecture et de 257 à 24 ms pour le nom. Comparaison de résultats,
  index utilisé et lectures pendant écriture concurrente vérifiés ; 46 tests
  ciblés réussis. Ces mesures SQL ne sont pas des temps HTTP en production.
- Le sous-lot est coché dans le [TODO](TODO.md), le chantier P0 reste ouvert.
  Aucune migration ni nouvel index ; déployer le module Python et redémarrer.
  Mesure sur installation représentative et optimisation des autres parcours
  toujours nécessaires.

### Budget des scans de croissance des bibliothèques

- La [tâche de croissance](app/tasks/refresh_library_growth.py) dispose désormais
  de 30 minutes par bibliothèque au lieu de 5, pour laisser aboutir les grandes
  bibliothèques de séries dont les épisodes sont parcourus individuellement.
  Les logs de réussite et d'échec indiquent la durée écoulée et le budget.
- La [documentation](vodum-docs/docs/library-growth.md) précise le comptage des
  épisodes et la relance manuelle. Aucune migration ; déployer la tâche avant
  de la relancer. Le budget est vérifié entre les requêtes et les éléments ;
  une requête en cours conserve son timeout réseau. Les scans restent séquentiels
  et peuvent donc allonger la durée totale de la tâche. Validation locale
  uniquement, sans garantie de durée sur les serveurs de production.

### Libellés des tâches de monitoring

- Ajout des noms lisibles pour les tâches de croissance des bibliothèques et de
  recommandations de risque d'utilisation dans les traductions
  [françaises](translations/ui/fr.json), [anglaises](translations/ui/en.json),
  [allemandes](translations/ui/de.json), [espagnoles](translations/ui/es.json) et
  [italiennes](translations/ui/it.json). La page Tâches n'affiche plus leurs clés
  techniques `task.refresh_library_growth` et `task.refresh_usage_risk_recommendations`.
- Aucune migration ni changement de planification ; déployer les traductions.
  Les cinq fichiers JSON ont été validés localement, sans validation en production.

### Suggestions Plex limitées aux serveurs en ligne

- Les [suggestions automatiques](app/core/plex_server_discovery.py) excluent les
  serveurs signalés hors ligne par Plex, y compris dans les résultats en cache.
  Le panneau d'ajout disparaît si aucun serveur ne reste à proposer.
- Le [résultat de découverte manuelle](app/routes/plex_auth.py) applique le même
  filtre. Aucune migration ; déployer les deux modules ensemble. Le statut reste
  celui fourni par Plex lors de la découverte (cache de dix minutes maximum),
  sans nouvelle vérification réseau. Vérification locale uniquement.

### Diagnostic des premiers scans de bibliothèques

- Le [tableau des bibliothèques](templates/monitoring/tabs/libraries.html) affiche
  l'erreur et la date de tentative même si aucun relevé n'a réussi.
- Les avertissements de [refresh_library_growth](app/tasks/refresh_library_growth.py)
  incluent le nom de la tâche pour être retrouvés dans les logs. Un serveur
  indisponible produit un avertissement avec les identifiants concernés.
- Aucune migration ; déployer la tâche et le template ensemble. Fréquence et budget
  inchangés. Vérifications locales uniquement ; la cause des échecs en production
  reste à confirmer.

### Easter egg réservé au dashboard

- Le [monitoring](templates/monitoring/partials/cards/_live_sessions.html) n'affiche
  plus la citation et l'affiche de film en l'absence de lecture. Le message habituel
  d'absence de session est rétabli ; l'easter egg reste présent sur le dashboard.
- La [route monitoring](app/routes/monitoring_overview.py) ne prépare plus cette
  carte, y compris lors des actualisations partielles.
- Aucune migration. Déployer la route et le template ensemble. Vérification locale
  du rendu des cartes ; aucune validation en production.

## Non publié — mise à jour du 2026-11-18

### P0 — chargement initial des collections sans attente du verrou partagé

- Le [chargement de la page Collections](app/core/collections_page_data.py) utilise
  un snapshot SQLite indépendant pour les bibliothèques, ARR, configurations et
  réglages. Les lectures peuvent aboutir pendant une transaction d'écriture sans
  exposer ses données non validées ; le snapshot est fermé avant le rendu HTML.
- Les routes ARR compatibles et activées sont chargées en une seule requête au
  lieu d'une requête par bibliothèque. Types normalisés, ordre, priorités,
  groupes de collections, réglages et bibliothèques sans route sont conservés.
- [Mesure locale et limites](docs/performance-collections-reads-2026-11-18.md) :
  103 bibliothèques, verrou synthétique tenu 250 ms et cinq mesures par parcours ;
  médiane de 253 à 3,65 ms, 103 lectures de routes ARR ramenées à une seule.
  Ces chiffres ne constituent pas une mesure de latence en production.
- Vérifications : 17 tests ciblés réussis, lecture pendant écriture concurrente,
  intégrité SQLite et route authentifiée sur base temporaire. Le HTML complet est
  identique à celui du parcours précédent après normalisation du nonce CSP.
  Aucun appel fournisseur, message envoyé ou compte réel modifié.
- Aucune migration. Déployer ensemble la [route](app/routes/collections.py) et le
  nouveau module. L'API de suivi conserve son parcours de récupération des
  exécutions bloquées ; son isolation et la mesure sur base représentative restent
  ouvertes. Le sous-lot P0 est coché dans le [TODO](TODO.md), sans clôturer P0.


### Remise à jour du suivi TODO

- La [feuille de route](TODO.md) conserve désormais les travaux terminés avec
  des cases cochées, au lieu de les retirer. Les 67 sous-lots P0 déjà décrits
  comme livrés sont cochés séparément ; les objectifs globaux restent ouverts
  pour leurs extensions et mesures sur installation représentative.
- Les trois derniers points P1 (audience des campagnes, indisponibilité des
  serveurs lors des suppressions, README Unraid) sont rétablis comme terminés.
  L'exclusion Docker des données/sauvegardes est cochée après lecture de
  [.dockerignore](.dockerignore). Les travaux livrés sur les interfaces mobiles,
  les logs, les collections Jellyfin et la documentation sont rendus visibles.
- Le suivi persistant des demandes médias est distingué de l'historique complet
  et des quotas encore manquants : la [vue actuelle](app/core/portal_media_request_jobs.py)
  présente dix jobs au maximum et les résultats des dernières 24 heures. Les
  demandes de réconciliation après un POST incertain restent ouvertes.
- Le premier rendu des serveurs du dashboard est identifié comme implémenté dans
  la [route](app/routes/dashboard.py), tandis que son contrôle après déploiement
  rejoint la section dédiée. Les validations réelles des dernières évolutions P1
  y sont également explicites. Les autres validations, évolutions natives,
  audits de sécurité et modernisations Docker restent ouverts.
- Bilan documentaire après revue : 79 cases cochées et 71 ouvertes, y compris
  les objectifs parents. Vérification des liens Markdown locaux et des statuts ;
  aucune modification fonctionnelle, migration ou nouvelle validation en production.


### Suppressions reportées quand un serveur est indisponible

- La [vérification native préalable](app/core/expired_user_deletion.py) classe les
  échecs de connexion, timeouts et réponses HTTP 502/503/504 comme une indisponibilité
  temporaire. Aucun compte local n'est supprimé sans confirmation native. Un serveur
  inaccessible n'est plus sollicité pour les autres utilisateurs du même lot ; ce
  cache est limité à l'exécution, pour permettre une nouvelle vérification ensuite.
- La [tâche](app/tasks/delete_expired_users.py) affiche un message INFO explicite :
  serveur injoignable ou temporairement indisponible, suppression reportée, fiches
  conservées et nouvelle vérification à la prochaine exécution planifiée. Le résumé
  compte les reports séparément ; une indisponibilité seule ne déclenche plus une
  erreur de tâche ni ses reprises rapprochées.
- Une interruption pendant la suppression conserve également la fiche pour reprise
  et précise l'étape ; les suppressions distantes déjà confirmées ne sont pas
  annulées. Les erreurs de certificat TLS, d'authentification, de protection ou de
  confirmation restent des erreurs. Aucun ping ni statut historique ne remplace
  la vérification effective de l'API ; « injoignable » n'affirme pas une panne
  physique du serveur.
- Aucune migration. Déployer ensemble [l'adaptateur](app/core/native_user_deletion.py),
  le contrôle d'expiration et la tâche. Vérifications locales : 24 tests réussis,
  couvrant indisponibilité, absence de suppression, reprise après retour du serveur,
  interruption partielle, certificat et maintien des erreurs réelles. Aucun compte
  réel modifié ni déploiement en production validé.


### Messages des logs directement visibles

- La [page Logs](templates/logs/logs.html) affiche directement le message complet
  de chaque événement, y compris les tracebacks, sans panneau « Technical details »
  ni phrases génériques répétitives. Les sauts de ligne sont conservés et les
  longues lignes reviennent à la ligne, sans hauteur tronquant le message.
  Le contenu reste échappé par le template.
- La [route des logs](app/routes/logs.py) ne calcule plus les explications
  génériques de chaque entrée. Filtres, pagination, compteurs et export sont
  conservés ; les fichiers historiques ne sont pas réécrits.
- La [documentation](vodum-docs/docs/logs.md) décrit cet affichage direct.
  Aucune migration ; déployer ensemble la route et le template. Vérification
  locale du rendu multiligne et de l'échappement HTML, sans validation en production.
- Les captures reçues identifient deux échecs de connexion Jellyfin au serveur 6
  pendant inspect, avant suppression. Elles ne précisent pas la cause réseau
  (DNS, refus de connexion ou autre) ; aucune résolution de ce problème distant
  n'est annoncée par cette modification d'affichage.


### Campagnes, diagnostic des suppressions et installation Unraid

- Les [campagnes](templates/communications/communications_campaigns.html) proposent
  « Tous les utilisateurs actifs » par défaut : statuts active, pre_expired
  (expiration proche) et reminder. « Tous les utilisateurs » reste disponible.
  Les critères serveur, fournisseur et abonnement se cumulent avec ce choix.
- Le [calcul des destinataires](app/communications_engine.py) recharge également
  les filtres fournisseur et abonnement lors de la mise en file ; les clauses de
  filtrage des abonnements sont corrigées. Les destinataires déjà en file restent
  inchangés. Les campagnes existantes conservent leur audience antérieure.
- Migration additive et idempotente : [bootstrap communications](app/core/db_bootstrap_communications.py)
  ajoute comm_campaigns.user_scope avec la valeur historique all. Exécuter le
  bootstrap au démarrage avant de servir les nouvelles routes ; déployer ensemble
  Python, schéma, template et traductions. Aucun changement de version INFO.
- La [tâche de suppression après expiration](app/tasks/delete_expired_users.py)
  inclut désormais dans son erreur finale les identifiants utilisateur/serveur/compte,
  le fournisseur, l'étape et le motif contrôlé de l'échec natif (dix premiers échecs).
  Les protections et la conservation locale jusqu'à confirmation native restent
  appliquées. Le traceback reçu ne permet pas encore d'identifier la cause des
  deux suppressions non confirmées ; cette évolution améliore le diagnostic,
  sans annoncer leur résolution. Aucune migration pour cette partie.
- Le [README](README.md) présente l'installation depuis le store Unraid Community
  Applications et conserve les alternatives template et Docker.
- Vérifications locales : 49 tests ciblés réussis, migration d'une base temporaire
  exécutée deux fois, création/modification et rendu des campagnes vérifiés avec
  le vrai bootstrap, intégrité SQLite contrôlée. Aucun message envoyé, aucun
  compte réel supprimé et aucune validation en production.


### Tableaux de l’administration sur mobile

- Les [tableaux admin](static/js/admin-mobile.js) à en-tête simple deviennent des
  fiches sur téléphone : libellés près des valeurs, nom en tête, informations
  longues et actions sur toute la largeur. Les liens de tri restent accessibles
  en haut ; les liens, formulaires, filtres et paginations existants sont conservés.
- Les bibliothèques de **Serveurs et bibliothèques** et du **Monitoring** mettent
  le nom de la bibliothèque en tête. Les utilisateurs du monitoring et **Mes
  collections** bénéficient aussi des [styles de fiches](static/css/admin-mobile.css).
  Les actions des collections ont des libellés visibles ; les menus des bibliothèques
  se déplient dans leur fiche plutôt que hors écran.
- Les rafraîchissements HTMX et les lignes remplacées par le suivi des collections
  réappliquent les libellés aux seuls tableaux concernés. Les lignes masquées et
  les états vides sont préservés. Les matrices à en-têtes groupés ou cellules sur
  plusieurs lignes conservent leur défilement horizontal ; le rendu desktop reste
  tabulaire. La liste Utilisateurs admin conserve ses fiches existantes.
- Aucune migration. Déployer ensemble le template de base, les templates de
  bibliothèques/collections et les scripts/styles ; les ressources mobiles portent
  une révision de cache pour être rechargées après mise à jour.
- Vérifications locales à 320, 390, 767 et 1280 pixels sur les quatre écrans
  prioritaires : absence de débordement global, fiches sur téléphone et tableau
  sur desktop, menus, remplacement HTMX et rafraîchissement des collections.


### Résultats des collections et limites Jellyfin

- Le [classement des avertissements](app/core/collection_sync_status.py) distingue
  les informations attendues (nombre de titres inférieur à la limite, acquisitions
  en attente, tri et accueil non pris en charge par Jellyfin) des avertissements
  nécessitant une vérification. Une exécution sans erreur avec ces seules
  informations se termine en succès ; les détails et compteurs sont conservés.
- Le [contrôle de présentation](app/core/collections_control.py) ne transforme plus
  les limites Jellyfin en « Configuration · Error » et ne les remet plus en file
  comme un échec. Les erreurs, avertissements effectifs et échecs de visibilité
  continuent à être signalés.
- Les [explications des logs](app/core/log_presentation.py) ne décrivent plus une
  ancienne exécution informative comme « Collection processing failed ». Le niveau
  historique et le message technique original sont conservés, sans réécriture.
- Aucune migration. Déployer Python et traductions ensemble, puis relancer la
  synchronisation pour actualiser les états d’exécution et de présentation déjà
  enregistrés. Les relevés du tableau de bord reclassent les limites connues à la
  lecture ; aucun succès en production n’est déduit des seuls tests locaux.
- Validation : 163 tests ciblés passent. La suite streaming élargie conserve
  3 échecs et 10 erreurs, reproduits avec l’ancien classement des avertissements
  sur les mêmes cas ; ces attentes de sources/API ne sont pas corrigées ici.


### Construction Docker et suggestions Plex

- Le [contrôle des templates Docker](Dockerfile) suit désormais la chaîne de
  chargement différé des suggestions : page Serveurs, chargeur HTMX, route et
  fragment de résultat. Il ne cherche plus l’inclusion directe supprimée de la
  page Serveurs lors de l’amélioration de navigation.
- Les contrôles de connexion Plex et de l’assistant restent actifs. Aucune
  migration ; reconstruire l’image avec ce Dockerfile et les sources associées.
  Les assertions sont vérifiées localement ; la construction complète de l’image
  n’a pas été exécutée dans cet environnement dépourvu de Docker.


### Tri des collections avec Jellyfin

- Le [formulaire Collections](templates/collections/collections.html) masque et
  désactive le réglage d’ordre des médias dès qu’une bibliothèque Jellyfin est
  sélectionnée, principale ou secondaire, y compris dans un groupe mixte Plex/Jellyfin.
  Une explication remplace le choix et figure aussi dans le récapitulatif.
- La [mise à jour du formulaire](static/js/pages/collections.js) s’applique à la
  création, à l’édition et aux changements de bibliothèque ou de mode. Le choix
  réapparaît pour une sélection uniquement Plex. L’ordre enregistré reste conservé
  pour la sélection des titres et la publication Plex ; aucune collection existante
  n’est modifiée automatiquement. Aucune migration ; déployer ensemble le template,
  le script et les traductions. Ce changement ne fournit pas de tri personnalisé Jellyfin.
- Le [guide des collections](vodum-docs/docs/collections.md) précise cette limite.


### Documentation et thème VODUM — 18 novembre 2026

- La [documentation](vodum-docs/docs/index.md) adopte les fonds bleu nuit, les
  panneaux slate, les accents indigo et l’icône de VODUM. Accueil par guides,
  navigation réorganisée, recherche, mode clair optionnel et présentation mobile
  sont configurés dans le [thème](vodum-docs/docs/assets/stylesheets/extra.css).
- Les guides couvrent désormais les collections et leurs sources, les demandes
  médias en arrière-plan, la carte des utilisateurs, la croissance des
  bibliothèques, les invitations et les performances. Les guides existants sont
  actualisés, notamment le portail, les tâches par files dédiées, la sécurité,
  les communications, les cadeaux et la restauration. La langue anglaise existante
  est conservée et les fonctions expérimentales restent signalées.
- Les liens du site ciblent le dépôt `Nexius2/vodum-docs`. Les dépendances de
  construction sont fixées et le [workflow Pages](vodum-docs/.github/workflows/docs.yml)
  compile en mode strict. Le [README](vodum-docs/README.md) précise la prévisualisation
  et le transfert vers ce dépôt distinct avant publication.
- Aucune migration applicative. La mise en ligne exige de publier le contenu du
  dossier dans le dépôt documentaire ; les contrôles locaux n’annoncent pas un
  déploiement sur GitHub Pages.
- Validation locale : compilation MkDocs stricte, liens des 37 pages HTML générées,
  recherche, bascule clair/sombre et navigation sur ordinateur et téléphone.


### Temps d’accès et navigation dans l’administration

- La [liste utilisateurs](app/core/user_list_queries.py) sélectionne la page avant
  de calculer ses accès pour les tris simples. Le total ne joint plus les
  bibliothèques ; les tris par compteurs et abonnement conservent leur portée
  globale. Les [compteurs serveurs](app/core/server_page_queries.py) ne multiplient
  plus les comptes par les bibliothèques avant de les compter.
- Les fichiers publics CSS/JS et `/health` évitent les lectures de réglages
  d’authentification, après le contrôle IP. Les lectures de réglages et de sessions
  admin utilisent des connexions isolées, avec vérification fraîche des sessions.
  Les copies du cache d’agrégats ne retiennent plus son verrou global.
- Les [suggestions Plex](app/routes/servers.py) se chargent après la page Serveurs,
  avec relance en cas d’échec. Le [monitoring](templates/monitoring/monitoring.html)
  affiche d’abord sa navigation, les serveurs et le live ; ses statistiques
  historiques arrivent ensuite, avec indicateur de chargement et relance.
- L’[audit local](docs/navigation-performance-2026-11-17.md) détaille les mesures :
  sur 3 000 utilisateurs et 300 000 accès, la liste répétée passe d’environ 369 à
  18 ms et les serveurs de 82 à 12 ms. Avec 100 000 lectures, le premier affichage
  navigateur du monitoring prend 94 ms ; les classements terminent ensuite vers
  3 secondes. Ces chiffres ne valident pas les performances en production.
- Aucune migration. Déployer ensemble Python et templates, puis redémarrer le
  processus. Les calculs historiques et les attentes réseau restent à mesurer
  sur l’instance réelle. Les tests ciblés couvrent les résultats, les contrôles
  d’accès et les lectures concurrentes ; deux fixtures obsolètes ont été actualisées.


### Administration sur mobile

- Le [socle admin](templates/base.html) propose une navigation basse vers le
  tableau de bord, les utilisateurs, le monitoring et les serveurs, ainsi qu’un
  menu complet avec gestion du focus, fermeture par Échap et retour au contenu.
- La [liste utilisateurs](templates/users/users.html) affiche des fiches sur
  téléphone avec les coordonnées, le statut, l’abonnement et les accès. Le tri,
  la recherche, les filtres et la création restent disponibles.
- Les [styles mobiles](static/css/admin-mobile.css) agrandissent les contrôles,
  réorganisent les filtres et rendent les onglets défilants. Les autres tableaux
  conservent un défilement horizontal local accessible au clavier, y compris
  après chargement HTMX. La présentation desktop est conservée.
- Aucune migration. Déployer ensemble les templates, les styles et les scripts
  associés ; ces vérifications locales ne constituent pas une validation en production.


### Collections sur le tableau de bord

- Une [carte cliquable](templates/dashboard/partials/_collections.html)
  indique le nombre de configurations, réparties entre « Réussies »
  et « À vérifier ». Une configuration compte une seule fois et passe
  en « Réussies » quand chaque bibliothèque a un dernier résultat de
  synchronisation réussi. Les avertissements, les échecs et l’absence
  de résultat sont comptés dans « À vérifier ». La carte apparaît dès
  la première configuration et ouvre la page Collections.
- Dans « Mes collections », un point reprend les couleurs du tableau de
  bord à gauche de l’état. Les deux écrans utilisent le [même calcul](app/core/collection_sync_status.py).
- Une collection synchronisée peut rester verte si des titres manquent
  ou si des demandes ARR sont en attente. Les autres avertissements et
  les échecs restent à vérifier, avec le motif affiché par bibliothèque.
  La migration au démarrage ajoute un relevé du dernier résultat de
  synchronisation, conservé lors de la réduction de l’historique. Si un
  résultat a déjà été purgé, la prochaine synchronisation le remplacera.

### Latence du monitoring

- Avec le tri par dernière lecture, [Bibliothèques](app/core/monitoring/overview_libraries.py)
  sélectionne d’abord la page via l’index SQLite existant et calcule les
  totaux de lecture pour les lignes affichées. Aucune migration nécessaire.
- Le [rapport de temps](app/route_timing_report.py) peut distinguer les
  onglets du monitoring et le chargement différé du classement des
  bibliothèques. Lorsque la mesure Waitress est activée, l’attente d’un
  thread est aussi disponible dans l’en-tête `Server-Timing`.

### Vérification des demandes médias

- La [détection des doublons](app/core/portal_media_requests.py) consulte
  l’inventaire local des collections pour retrouver un candidat Plex ou
  Jellyfin. Une lecture ciblée confirme son identifiant fournisseur avant
  de signaler un média déjà présent. Sans candidat confirmé, la
  vérification paginée reste nécessaire. Aucune migration requise.

### Consultation des logs

- Quand le fichier actif change, la [page des logs](app/logging_utils.py)
  réutilise l’analyse des archives inchangées tant qu’elles tiennent dans
  le cache. La rotation et la purge invalident ce cache. Les traces
  multilignes sont conservées et le téléchargement reste en texte brut.

### Dernière lecture dans le monitoring

- Dans [Monitoring → Utilisateurs](app/core/monitoring/overview_users.py),
  la dernière lecture, son IP et son lecteur sont retrouvés via l’index
  des comptes média. Le classement des dernières lectures ne porte plus
  sur tout l’historique. Les statistiques dédupliquées et le périmètre de
  recherche sont conservés. Aucune migration nécessaire.

### Recommandations Usage Risk

- Ouvrir le rapport ou une fiche utilisateur ne déclenche plus d’écriture
  de recommandations. Une [tâche planifiée](app/tasks/refresh_usage_risk_recommendations.py)
  actualise l’historique toutes les 30 minutes selon la période configurée.
  Les suggestions affichées dans le rapport sont toujours calculées avec
  les filtres courants. La tâche d’envoi vérifie encore les recommandations
  avant de notifier. La nouvelle tâche est ajoutée au démarrage sans
  changement de schéma.

### Historique des cadeaux d’abonnement

- L’[historique](templates/subscriptions/_gift_history.html) se rafraîchit
  toutes les 30 secondes au premier plan et reprend dès le retour sur
  l’onglet ou après l’envoi d’un cadeau. Une lecture lente est interrompue
  côté navigateur après 10 secondes. Une réponse identique ou une erreur
  temporaire laisse la dernière liste affichée en place.

### Navigation du monitoring

- Dans [Bibliothèques](templates/monitoring/tabs/libraries.html), le tableau
  s’affiche sans attendre le classement des titres les plus regardés. Le
  classement se charge quand sa section devient visible et ses agrégats
  sont réutilisés pendant une minute pour les mêmes filtres. La pagination
  vérifie l’existence de lectures via l’index par bibliothèque.
- Les onglets qui n’affichent pas l’état des serveurs évitent les requêtes
  associées lors de la navigation.

### Croissance des bibliothèques

- Dans **Monitoring → Bibliothèques**, un [tableau](templates/monitoring/tabs/libraries.html)
  affiche par bibliothèque le nombre de films ou d’épisodes ajoutés et la
  taille de leurs fichiers sur 7 jours, 30 jours ou 1 an. Les tailles
  incomplètes sont signalées. Les chiffres portent sur les médias encore
  présents dans Plex ou Jellyfin et sur les tailles déclarées par ces serveurs.
- Les chiffres de croissance et de lecture figurent dans le même tableau.
  Les bibliothèques suivies pour la croissance apparaissent même sans
  historique de lecture.
- Au démarrage, la migration crée le stockage des relevés et ajoute la
  [tâche quotidienne](app/tasks/refresh_library_growth.py). Déployer ensemble
  le code et les templates, puis laisser la tâche effectuer le premier
  relevé. Un échec conserve la dernière mesure disponible et sa date.

### Paramètres de sécurité

- Une [carte dédiée](templates/settings/partials/_settings_security.html)
  regroupe l’accès administrateur, la connexion Plex et la sécurité web.
  Les réglages d’authentification à deux facteurs et de Turnstile sont
  accessibles via le bouton de gestion de l’accès administrateur.
- Le [contrôle de construction Docker](Dockerfile) vérifie la présence de
  la connexion Plex dans la nouvelle carte de sécurité et l’inclusion de
  cette carte dans la page Paramètres.

### Emails de campagne

- Les [campagnes manuelles](app/tasks/send_comm_campaigns.py), y compris les
  envois de test, affichent uniquement le nom de l’application en pied de page.
  Les notifications par modèle conservent la mention d’envoi automatique.

## Version 26.11.17 b0846

### Nettoyage du dépôt

- Les consignes d’assistants, le TODO interne, les audits, les scripts de
  diagnostic et les instructions de génération des affiches sont exclus du
  dépôt par les [règles Git](.gitignore). Les guides utilisateur et les affiches
  utilisées par VODUM restent versionnés.

### File dédiée au monitoring

- La collecte en direct et l’application des limites de lecture partagent
  un [worker série dédié](app/tasks_engine.py). Les imports, campagnes
  et synchronisations n’occupent plus ce worker. L’ordonnanceur retrouve
  aussi les jobs de monitoring restés en file après un redémarrage.
- Une [restauration](app/core/tasks/database_restore_gate.py) attend la fin
  des travaux déjà lancés par les files parallèles et suspend les nouveaux
  départs jusqu’au redémarrage. Les [demandes médias en attente dans une
  sauvegarde restaurée](app/core/tasks/configuration.py) sont clôturées
  pour éviter de renvoyer un ajout passé. Déployer ensemble l’ordonnanceur,
  le worker du portail et la tâche de restauration. Aucune migration
  supplémentaire n’est nécessaire.

### Traitement des demandes de médias en arrière-plan

- La [soumission du portail](app/routes/portal.py) répond dès la mise en
  file. Les [demandes récentes](templates/portal/requests.html) indiquent
  l’attente, la vérification et le résultat, y compris après rechargement.
  Le [worker dédié](app/core/portal_media_request_jobs.py) traite un job à
  la fois. Les vérifications interrompues peuvent reprendre. Une interruption
  après le début de l’ajout ARR est signalée comme incertaine et le POST
  n’est pas rejoué automatiquement.
- Le [bootstrap](app/core/db_bootstrap_portal.py) crée la file sur une base
  existante. Exécuter le bootstrap avant de démarrer la nouvelle application
  et déployer ensemble les routes, les gabarits et le script du portail.
  La file accepte 32 jobs actifs au total, dont 3 par compte. Les résultats
  restent visibles pendant 24 heures et sont conservés 7 jours. La recherche
  initiale reste synchrone.

### Résultat des jobs de suivi en direct

- Le [worker du monitoring](app/tasks/media_jobs_worker.py) comptabilise
  les refus d’authentification et les collectes en échec comme des erreurs,
  même si les sessions précédentes restent [visibles](app/core/monitoring/collector.py).
  Les jobs suivent la reprise existante et les tentatives échouées
  comptent dans la limite de 20 jobs par passage. Une collecte réussie
  sans lecture reste un succès. Aucune migration n’est nécessaire.

### Suivi du propriétaire Plex

- Le [monitoring](app/core/monitoring/mappers.py) reconnaît l’identifiant local
  `1` de Plex si le nom transmis correspond à l’unique propriétaire
  synchronisé du serveur et qu’aucun compte synchronisé ne porte déjà cet
  identifiant. Les anciennes lectures sans rattachement peuvent être
  récupérées lors de la prochaine collecte lorsque leurs métadonnées
  confirment cette correspondance. Aucune migration n’est nécessaire.

### Purge des jobs de rafraîchissement du monitoring

- Le [worker](app/tasks/media_jobs_worker.py) purge au plus 500 jobs par
  statut et par passage, du plus ancien au plus récent. Les succès restent
  éligibles après 2 jours, les erreurs et annulations après 7 jours. Les
  autres jobs sont hors de cette purge.
- Le [schéma initial](tables.sql) contient l’index partiel de purge. Sur une
  base existante, le [bootstrap](app/core/db_bootstrap_media_jobs.py) ajoute
  automatiquement l’index et vérifie la colonne `processed_at` avant le
  démarrage du worker. Le reliquat est traité aux passages suivants.

### Portail utilisateur sur mobile

- Le [portail mobile](static/css/portal-mobile.css) dispose d’une barre basse
  pour les demandes de médias, l’abonnement et le profil, avec un menu pour
  les autres pages. La page active est signalée et la déconnexion est
  séparée des liens. Le profil et l’assistance proposent des raccourcis, les
  recherches et formulaires ont des actions tactiles, et les tableaux de
  suivi et d’état se lisent sous forme de fiches. L’abonnement met en avant
  le forfait et ouvre le renouvellement en bas de l’écran. Déployer ensemble
  les [gabarits](templates/portal/base.html), styles et scripts. Sur
  ordinateur, la navigation reste dans l’en-tête. Aucune migration n’est
  nécessaire.

### Affiches des demandes de médias sur mobile

- Le [fond de la page](static/css/portal-requests.css) affiche des couleurs
  plus visibles et deux rangées d’affiches de hauteur fixe sur téléphone.
  Le dégradé protège la lisibilité du titre et le formulaire conserve son
  fond opaque. Aucune migration n’est nécessaire.

### Canaux d’envoi des communications

- Dans les campagnes et les modèles, le [sélecteur de canaux](templates/communications/_delivery_channels.html)
  propose uniquement les choix compatibles avec la configuration. Désactiver
  Discord retire « Discord » et « Email et Discord » de la liste. Un choix
  déjà enregistré mais devenu indisponible reste conservé jusqu’à son
  remplacement explicite. Aucune migration n’est nécessaire.
- Dans les [campagnes](templates/communications/communications_campaigns.html)
  et les [modèles](templates/communications/communications_templates.html),
  l’option des paramètres globaux indique uniquement les canaux configurés.
  Le compteur de messages Discord apparaît quand la sélection comprend Discord,
  y compris par héritage si Discord est configuré. Aucune migration n’est
  nécessaire.

### Chargement des images du monitoring

- Le [proxy d’affiches](app/core/monitoring/artwork_proxy.py) sert
  immédiatement une copie expirée et tente de la rafraîchir en arrière-plan.
  Deux rafraîchissements au maximum s’exécutent par processus. Les demandes
  simultanées d’une même image partagent la récupération, même si le cache
  est vide. Après un échec en arrière-plan, une nouvelle tentative attend
  au moins 30 secondes pour cette image tant que son délai reste mémorisé.
  Les [fichiers temporaires](app/core/monitoring/artwork_cache.py) sont
  distincts quand plusieurs tâches alimentent le cache. Aucune migration
  n’est nécessaire.
- Le [proxy d’images](app/core/monitoring/artwork_proxy.py) utilise un budget
  commun de 10 secondes pour ses essais de chemins et d’adresses, y compris
  l’attente d’un [créneau Plex](app/core/plex_rate_limit.py). Une fois
  le budget écoulé, aucun nouvel essai n’est lancé et une copie ancienne
  reste utilisable si elle est en cache. Les délais de socket s’appliquent
  aux requêtes déjà engagées. Aucune migration n’est nécessaire.

### Purge des instantanés du monitoring

- Après chaque [instantané du monitoring](app/core/monitoring/collector.py),
  VODUM supprime au plus 500 instantanés de plus de 30 jours, du plus ancien
  au plus récent. Un éventuel reliquat est traité par les collectes
  suivantes afin de limiter la durée de chaque écriture SQLite. Aucune
  migration n’est nécessaire.

### Synchronisation des métadonnées de bibliothèque

- Si une bibliothèque Plex disparaît du fournisseur, la
  [synchronisation](app/core/plex_library_sync.py) retire la bibliothèque et
  ses droits locaux dans la même [transaction](app/core/library_access_repository.py),
  comme pour Jellyfin. Si une configuration locale empêche la suppression,
  les droits sont conservés et la synchronisation continue. Aucune migration
  n’est nécessaire.
- Les synchronisations [Plex](app/core/plex_library_sync.py) et
  [Jellyfin](app/tasks/sync_jellyfin.py) évitent de réécrire les noms, les
  types et les compteurs de médias déjà identiques. Un compteur inconnu
  peut toujours être remplacé par zéro. Les données sont préservées si
  le fournisseur ne renvoie pas de compteur. Aucune migration n’est nécessaire.

### Synchronisation des droits de bibliothèque

- Plex et Jellyfin appliquent les [changements de droits](app/core/library_access_repository.py)
  en une transaction SQLite par compte média et serveur. Un échec annule
  tous les changements du compte sur ce serveur. Les droits identiques ne
  sont pas réécrits, et les droits des autres serveurs sont préservés.
  Aucune migration n’est nécessaire.

### Écritures de la collecte du monitoring

- La [clôture d’une session](app/core/monitoring/collector.py) valide
  ensemble l’événement d’arrêt, l’historique et le retrait de la session en
  direct. Si une écriture échoue, la collecte peut reprendre la clôture
  sans dupliquer l’événement. Le délai de grâce et les clés de déduplication
  sont conservés. Aucune migration n’est nécessaire.
- Pour chaque [session active](app/core/monitoring/collector.py), la collecte
  enregistre la session et son changement d’état dans une même transaction
  SQLite. Si l’insertion de l’événement échoue, la collecte suivante peut
  retrouver la transition. Les sessions déjà actives évitent aussi une
  réécriture du compteur d’absence. L’activation d’un abonnement à la lecture
  intervient après la transaction. Aucune migration n’est nécessaire.

### Pagination des journaux

- Pour une consultation sans recherche, la [page des journaux](app/routes/logs.py)
  exploite l’[index par niveau](app/logging_utils.py) et copie seulement les
  événements de la page. Les compteurs continuent de couvrir tout l’historique
  retenu. La recherche, les traces multilignes et l’export anonymisé conservent
  leur comportement. Un historique modifié doit encore être relu. Aucune
  migration n’est nécessaire.

### Vérification des doublons pour les demandes médias

- Le [contrôle des bibliothèques](app/core/portal_media_requests.py)
  reconnaît les anciens GUID Plex de TMDb, TVDb et IMDb, même lorsque le
  serveur les renvoie dans le champ principal. Une correspondance dans
  ce champ évite l’appel au détail. Côté Jellyfin, la casse des noms de
  fournisseurs n’empêche plus de reconnaître un identifiant. Aucune migration
  n’est nécessaire.
- Le [contrôle ARR](app/core/portal_media_requests.py) demande à Radarr ou
  Sonarr les entrées correspondant à l’identifiant TMDb ou TVDb, sur toutes
  les instances compatibles. Si une instance rejette ce paramètre, VODUM
  retente la lecture avec la liste complète. Une lecture en échec peut
  toujours bloquer l’ajout pour éviter un doublon. Aucune migration n’est
  nécessaire.
- Avant une [demande média](app/core/portal_media_requests.py), VODUM charge
  une seule fois la configuration de chaque serveur dont les bibliothèques
  doivent être vérifiées. Les critères de routage et de vérification restent
  les mêmes. Aucune migration n’est nécessaire.

### Réactivité des collections

- Le [suivi des collections](static/js/pages/collections.js) espace les
  consultations sans activité à 10 secondes et conserve les 2 secondes
  lorsqu’un job est en attente, en cours ou en cours d’arrêt. Les actions
  explicites et le retour au premier plan rafraîchissent immédiatement la page
  si aucune requête n’est déjà en cours. Aucune migration n’est nécessaire.

### Mesure des appels fournisseurs et du cache d’agrégats

- Avec `VODUM_PROVIDER_CACHE_TIMING=1`, le
  [rapport de performance](app/route_timing_report.py) restitue la durée des
  [appels HTTP sécurisés](app/core/http_security.py) et des consultations du
  [cache d’agrégats](app/core/aggregate_cache.py) dans le contexte Flask.
  Les traces contiennent des durées et compteurs, sans URL ni clé de cache.
  L’option couvre le chemin instrumenté dans le contexte de la requête,
  y compris les lectures parallèles du portail qui héritent de ce contexte.
  Déployer le code avant la collecte. Aucune migration n’est nécessaire.

### Mesure de l’attente des jobs médias

- Avec `VODUM_MEDIA_JOB_QUEUE_TIMING=1`, les workers de
  [rafraîchissement du monitoring](app/tasks/media_jobs_worker.py) et
  [d’accès Plex](app/tasks/apply_plex_access_updates.py) enregistrent le délai
  entre l’éligibilité du job et sa première prise en charge. Le
  [rapport CSV](app/route_timing_report.py) donne les p50/p95/p99 par type de
  job. Les reprises et les autres files restent hors mesure. Aucune migration
  n’est nécessaire.

### Mesure des temps de réponse Flask

- La mesure SQLite couvre aussi les [curseurs de transaction](app/db_manager.py),
  la lecture des résultats et le temps de BEGIN, COMMIT ou ROLLBACK. Le
  compteur d’appels compte les exécutions demandées par le code utilisateur
  du curseur. Aucune migration n’est nécessaire.
- Avec `VODUM_WAITRESS_QUEUE_TIMING=1`, le
  [serveur web](app/serve.py) mesure l’attente d’un thread Waitress
  séparément du traitement Flask. Le [rapport CSV](app/route_timing_report.py)
  fournit les percentiles et le nombre de requêtes mesurées. La lecture
  du corps de la requête et le transfert de la réponse sont hors de ce délai.
- Sur activation de `VODUM_SQLITE_TIMING`, les traces distinguent le temps
  d’attente du verrou [DBManager](app/db_manager.py) du temps cumulé des
  opérations SQL instrumentées, y compris les lectures sur snapshot.
  Le [rapport CSV](app/route_timing_report.py) calcule leurs percentiles et
  indique combien de requêtes ont été instrumentées. Les accès directs à
  SQLite hors DBManager restent hors mesure.
- Les [traces de performance](app/app.py) identifient les routes par leur nom
  Flask et omettent les URL concrètes, qui peuvent contenir des identifiants
  ou des jetons. Le [rapport CSV](app/route_timing_report.py) calcule les
  p50/p95/p99 à partir de captures produites après ce changement.
- Déployer le code avant la collecte, puis suivre le
  protocole de mesure interne. Les durées couvrent le
  traitement Flask jusqu’au hook de mesure. Aucune migration n’est nécessaire.

### Configuration des clés API des collections

- Sous les champs TMDb et MyAnimeList, la
  [configuration des collections](templates/collections/collections.html)
  ouvre les pages officielles de création des identifiants dans un nouvel
  onglet. Aucune migration n’est nécessaire.

### Affichage des clés API des collections

- Dans Collections → Configuration, un bouton à droite des champs TMDb et
  MyAnimeList affiche ou remasque la clé saisie ou enregistrée. Les clés
  enregistrées sont chargées à la demande via une
  [route administrateur](app/routes/collections.py), puis effacées du champ
  au remasquage, en quittant l’onglet ou lors de l’enregistrement.
- Déployer ensemble la [page](templates/collections/collections.html), ses
  ressources et la route. Aucune migration n’est nécessaire.

### Collections AniList

- « More ways to discover » propose le top des séries anime, le top des films
  anime et le classement de popularité AniList. Les affiches intégrées couvrent
  les [séries](app/core/assets/collection_posters/anilist-tv-v1.png), les
  [films](app/core/assets/collection_posters/anilist-movie-v1.png) et la
  [popularité](app/core/assets/collection_posters/anilist-bypopularity-v1.png).
- Le [moteur AniList](app/core/collections_anilist.py) lit jusqu’à 500 entrées
  via l’API publique sans identifiant. Il rapproche les titres et années de la
  bibliothèque Plex ou Jellyfin. Les rapprochements ambigus sont ignorés.
  L’acquisition Arr n’est pas proposée et Jellyfin conserve les limites de tri
  de son API.
- Déployer conjointement le code et les affiches. Aucune migration de base de
  données ni configuration d’API n’est requise. Les affiches sont envoyées
  lors de la synchronisation.

### Collections MyAnimeList

- La section « More ways to discover » propose les meilleures séries anime,
  les meilleurs films anime et le classement de popularité. Chacun reçoit
  une affiche dédiée ([séries](app/core/assets/collection_posters/myanimelist-tv-v1.png),
  [films](app/core/assets/collection_posters/myanimelist-movie-v1.png),
  [popularité](app/core/assets/collection_posters/myanimelist-bypopularity-v1.png)).
  L’aperçu et la synchronisation récupèrent jusqu’à 500 entrées par classement
  et rapprochent les titres principaux, originaux et alternatifs par année
  avec la bibliothèque Plex ou Jellyfin sélectionnée.
- Le [moteur MyAnimeList](app/core/collections_myanimelist.py) ignore les
  correspondances ambiguës. L’acquisition Arr n’est pas proposée.
  Jellyfin publie la sélection selon les possibilités de tri de son API.
- Déployer conjointement le code et les affiches. Au démarrage, la
  [migration automatique](app/core/db_bootstrap_collections.py) ajoute
  le champ chiffré. Saisir ensuite le Client ID MyAnimeList dans
  Collections → Configuration avant d’activer le modèle. Les affiches
  sont envoyées lors de la synchronisation.

## Entrées précédentes — mise à jour du 2026-11-14

### Carte des utilisateurs dans Monitoring

- La molette permet de zoomer et dézoomer lorsque le pointeur est sur la carte.

- Un clic sur un groupe numéroté ouvre les fiches de ses utilisateurs dans un
  [panneau](templates/monitoring/tabs/location.html) à droite de la carte.
  Sur mobile, le panneau s’affiche sous la carte.

- En mode historique, [la localisation](app/core/monitoring/overview_locations.py)
  privilégie l’IP du dernier événement de session enregistré avant l’instant
  sélectionné. Les sessions terminées peuvent utiliser l’IP de leur fiche
  d’historique en secours. Une session encore ouverte sans IP observée à cet
  instant reste comptée sans point sur la carte. Aucune migration requise.

- Le pincement à deux doigts permet de zoomer sur la carte. Pendant un
  déplacement, [le rendu](static/js/pages/monitoring-location.js) est limité à
  une mise à jour par image. La lecture de l’historique affiche immédiatement
  l’instant sélectionné et se met en pause si son chargement échoue.

- Les infobulles administrateur affichent l’IP de la session et le dernier
  niveau Usage Risk enregistré dans une recommandation active, si disponible.
  L’historique distingue lecture et pause à partir des événements conservés.
  Les sessions sans événement exploitable restent affichées avec un état
  générique. Aucune migration requise.
- Les avatars compatibles sont chargés à l’ouverture d’une infobulle depuis
  [le relais administrateur](app/routes/monitoring_api.py), avec les initiales
  en secours. Les tracés des pays sont préparés une seule fois par chargement
  pour réduire le travail de dessin pendant le déplacement et le zoom.

- La carte [Localisation](templates/monitoring/tabs/location.html) distingue
  les utilisateurs inactifs, les sessions récentes et les lectures en cours.
  Elle regroupe les points proches, affiche quatre compteurs et conserve le
  cadrage manuel lors des actualisations. Les infobulles donnent accès au profil
  et aux informations de lecture disponibles.
- La carte thermique compte chaque utilisateur une fois. Les filtres combinent
  le serveur, le pays et les lectures actives. La barre temporelle couvre
  24 heures, 7 jours ou 30 jours à partir des sessions conservées.
- L’historique utilise l’IP enregistrée avec chaque session et son estimation
  géographique actuelle. Il dépend de la rétention des sessions et de la
  disponibilité de la géolocalisation. Aucune migration requise.

- L’onglet [Localisation](templates/monitoring/tabs/location.html) cadre la carte
  sur la dernière lecture de chaque utilisateur Plex ou Jellyfin. Le survol,
  le focus clavier ou le toucher d’un point affiche le nom, le titre et la date.
  Le filtre « Utilisateurs en direct uniquement » suit la fenêtre de Now Playing.
- Un [interrupteur](templates/monitoring/monitoring.html) bascule entre la
  dernière localisation et les utilisateurs en direct. Le navigateur mémorise
  le dernier mode choisi pendant un an.
- Les points sont approximatifs. Les lectures sans IP publique géolocalisable
  sont omises. Le fond de carte Natural Earth est livré avec VODUM.
- Déployer le code applicatif, les gabarits, les traductions et les fichiers
  statiques ensemble. Aucune migration requise.

### Suggestions de serveurs Plex

- Le [panneau de suggestions Plex](templates/servers/_plex_suggestions.html)
  indique seulement que les serveurs proposés proviennent du compte Plex lié,
  dans les cinq langues de l’interface. Aucune migration ni ordre de déploiement
  particulier requis.
