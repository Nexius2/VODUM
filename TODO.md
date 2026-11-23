# VODUM - Feuille de route

Ce fichier suit uniquement les travaux restants. Les elements termines ont ete
retires apres publication ; les objectifs globaux restent ouverts tant que leurs
sous-parties ou mesures restent a faire. Le detail historique est archive dans
`changelog-archive-2026-11-19.md`.

Derniere mise a jour: 2026-11-19

## P0 - Performances et reactivite VODUM (priorite avant les evolutions P1/P2/P3)

Perimetre : application VODUM, independamment de la machine et de l'hebergement.
Ordre ci-dessous par impact attendu sur la reactivite globale, a confirmer par
mesure ; les gains sur installation representative restent a chiffrer. Conserver les optimisations deja
presentes (WAL, index, caches, agregats, lectures HTTP paralleles des demandes).

Prerequis obligatoires pour chaque optimisation : aucun changement visuel,
aucune perte de donnees, aucune suppression de fonctionnalite ni regression
des comportements existants. Conserver les acces, historiques, configurations,
filtres, tris, pagination et protections actuels. Valider chaque lot avant
extension ; une amelioration de performance ne justifie aucune perte fonctionnelle.

- [ ] Prealable de validation : mesurer les temps de routes p50/p95/p99, l'attente
  avant traitement web, l'attente du verrou DB, les durees SQL, les appels
  fournisseurs/cache et l'attente des jobs. Reutiliser `VODUM_ROUTE_TIMING` ;
  distinguer le temps Flask de la file Waitress. Comparer avant/apres avec une
  base representative, plusieurs utilisateurs et des fournisseurs lents,
  sans journaliser de secrets. Ces mesures peuvent ajuster l'ordre ci-dessous.

  Restent la mesure sur une base représentative et la couverture du SQL
  hors DBManager, des appels et caches hors de ce périmètre et des autres
  files et reprises de jobs.

- [ ] 1. Reduire la contention SQLite : remplacer progressivement la connexion
  partagee et son verrou global par des connexions de lecture independantes
  et une gestion explicite des ecritures. Auditer les usages directs de `db.conn`,
  les transactions et le dechiffrement sous verrou ; conserver l'atomicite,
  les contraintes et WAL. Ne pas simplement retirer le verrou actuel.

  Reste a mesurer sur une base representative et etendre aux autres parcours
  apres audit de leurs eventuelles ecritures.

  Mesurer le suivi Collections sur l'installation cible et qualifier le cout
  du repli historique pour les anciennes publications sans snapshot.

  Validation representative restante. Qualifier les connexions SQLite directes
  restantes dans `app/core/backup.py` avant de modifier ce parcours.

  Mesurer la fiche utilisateur complete sous charge representative ; les
  lectures initiales seules ont ete qualifiees avec une ecriture concurrente.
- [ ] 2. Liberer les threads web : executer les operations longues dans des jobs
  bornes, avec reponse rapide, suivi de progression et reprise idempotente.
  Prioriser demandes medias et recuperations lentes ; verifier qu'une operation
  fournisseur bloquee ne retarde pas la navigation des autres utilisateurs.
  Evaluer le dimensionnement Waitress apres reduction des blocages.

  Restent la recherche initiale et les autres opérations longues, ainsi
  que la mesure Waitress sous charge représentative.
- [ ] 3. Eviter les recalculs de tout l'historique dans le monitoring : materialiser
  les statistiques par utilisateur/bibliotheque et la derniere activite ; garder
  les filtres, tris et la pagination coherents. Retirer les identites repetees
  par lecture dans `GROUP_CONCAT`, charger les identites depuis leurs tables.
  Verifier les plans SQL et la deduplication ; ajouter uniquement les index utiles.

  Restent à matérialiser les totaux de lecture, optimiser les recherches avec
  espaces ou jokers SQL (`%`, `_`) et les tris Lectures/Durée sans recherche,
  et mesurer les gains sur l'installation réelle.
- [ ] 4. Rendre la consultation des logs proportionnelle a la page affichee :
  separer entretien/rotation et consultation, eviter le nettoyage force et la
  relecture de toutes les archives a chaque ouverture. Mettre les compteurs en
  cache, borner les lectures et etudier une file de journalisation dediee ;
  conserver recherche, traces multilignes, anonymisation et retention.

  Reste a borner les lectures lors d'un changement ou pour les gros historiques,
  et a optimiser la premiere recherche, les changements de filtre et les recherches
  lorsque les fichiers evoluent en continu ou depassent le budget de cache.
- [ ] 5. Reduire les parcours des demandes medias : qualifier les recherches
  ciblees par identifiant fournisseur Plex/Jellyfin/ARR et un index local
  actualise. Eviter les scans complets et appels de details repetes ; conserver
  les controles d'acces, la verification avant ajout, les reservations contre
  les doublons et l'absence de failover apres POST incertain. La parallelisation
  deja presente ne suffit pas a supprimer ces parcours.

  Restent l’index couvrant les autres bibliothèques et l’optimisation
  du contrôle d’absence.
- [ ] 6. Prioriser les appels Plex et les images interactives : revoir la limite
  partagee d'une requete/seconde, avec concurrence bornee et adaptation aux
  erreurs fournisseur. Servir immediatement un artwork ancien disponible,
  actualiser en arriere-plan, dedupliquer les recuperations simultanees et
  imposer un budget total aux essais de chemins/adresses. Reutiliser les
  connexions HTTP dans un meme travail sans partager une session mutable
  entre threads ; conserver les restrictions d'origine et la verification TLS.

  Restent la mesure sous charge et la qualification des autres appels Plex.
- [ ] 7. Regrouper les ecritures des collectes et synchronisations en petits lots :
  reduire les commits par session/evenement/droit et les reecritures de
  metadonnees inchangees. Garder les transactions courtes, sans appel reseau,
  et verifier coherence, reprise et comportement lors d'une erreur partielle.

  Mesurer sur l'instance cible la pression des ecritures restantes, notamment
  les premieres observations optionnelles et les collectes frequentes.

- [ ] 8. Separer les taches urgentes des travaux lourds : files/workers bornes
  pour monitoring et actions interactives, distincts des imports, campagnes,
  synchronisations et prechargements. Decouper les travaux longs, prevoir des
  budgets reels/cooperatifs et preserver les leases et protections contre les
  executions concurrentes incompatibles ; ne pas creer de threads abandonnes.

  Restent la mesure sous charge et le découpage des autres tâches longues.
- [ ] 9. Reduire les rafraichissements inutiles : cadence adaptative selon l'activite,
  suspension des onglets masques dans toutes les vues, absence de chevauchement
  et retour des seuls changements utiles. Conserver la protection du dashboard
  deja presente ; evaluer snapshots partages, reponses conditionnelles ou SSE
  selon le cout mesure et la compatibilite du serveur web/reverse proxy.

  Reste a etendre aux autres vues et evaluer cadence adaptative et snapshots.
- [ ] 10. Rendre les calculs de fond incrementaux : recalculer uniquement les jours
  modifies des agregats quotidiens ; charger une seule fois les abonnements
  pendant l'analyse des usages. Dissocier la consultation des rapports de
  l'enregistrement des recommandations et etendre les caches avec invalidation.

  Restent l’invalidation des caches et la validation sous charge
  représentative.

- [ ] 11. Reduire les petits couts repetes : mutualiser les lectures de settings
  dans une requete, mettre en cache le statut de mise a jour avec invalidation,
  et comparer un niveau gzip moins couteux. Preserver la revocation immediate
  des sessions et les controles de droits ; ne pas cacher les autorisations
  sans politique d'invalidation explicite.

  Poursuivre l'audit des autres calculs CPU redondants des ecrans
  d'administration, en conservant leurs scores et classements exacts.

- [ ] 12. Borner la maintenance : purges par lots, sauvegardes/checkpoints et
  entretien des caches sans longues pauses du traitement interactif. Verifier
  la restauration, la coherence des sauvegardes et les effets sur les lecteurs.

Chaque lot doit demontrer un gain de latence sous charge et conserver les
regressions fonctionnelles et de securite. Aucun changement d'hebergement ni
migration de moteur de base n'est requis par cette liste.

## Validation apres deploiement

Les validations ci-dessous restent ouvertes : ni la presence du code ni les tests
locaux ne permettent de les cocher sans observation sur l'installation cible.

- [ ] Derniers correctifs P1 : verifier l'audience des campagnes et le report
  d'expiration lorsque Jellyfin est hors ligne, puis la reprise lorsqu'il revient.

- [ ] Indicateur de mise a jour : verifier la connexion GitHub depuis le conteneur,
  la detection via check_update et le badge apres rechargement de page. Definir
  si le signal doit suivre main/INFO ou une image effectivement publiee ;
  voir `app/core/update_badge.py` et `app/tasks/check_update.py`. Traduction des infobulles et
  indication de fraicheur du dernier controle a etudier.

- [ ] Communications : verifier les traductions de l'historique, des anciens
  envois (`expiration_date_change`) et des notifications en attente.
- [ ] Monitoring > Servers : verifier les spectateurs dedupliques sur les donnees
  reelles et la distinction avec les utilisateurs actifs du dashboard.
- [ ] Routage admin : valider sur une copie representative les associations et
  priorites par bibliotheque, types compatibles, option par defaut et suppression
  de bibliotheques/instances ; verifier la migration des deux nouvelles tables.
- [ ] Sonarr/Radarr : valider ajout/edition/suppression et connexion API avec
  plusieurs instances, sous-chemin reverse proxy, mauvaise cle et serveur hors
  ligne ; verifier le refus avant insertion, les cartes et liens du dashboard,
  les champs URL/token et les courbes ARR apres plusieurs collectes.
- [ ] Jellyfin : verifier la desactivation/reactivation manuelle par compte et
  serveur, la conservation des droits et la protection des administrateurs.
  Verifier aussi le libelle du scan global depuis le menu d'une bibliotheque.
- [ ] Dashboard et connexion : deployer le filtre GUID Plex pour The Office et
  le correctif du clignotement ; lancer `refresh_dashboard_quote_cache` et
  controler une serie et un film sur le dashboard, le fond desktop et l'affiche
  mobile du login. Verifier la reprise apres indisponibilite d'un serveur.
- [ ] Portail : verifier une connexion Plex/Jellyfin, une modification de profil,
  une invitation d'ami et un message au support dans les logs admin et le monitoring.
- [ ] Invitations d'amis : valider SMTP reel, activation Plex, connexion Jellyfin
  avec le mot de passe genere et comptes mixtes ; confirmer les acces, forfait,
  limites, echeance et parrainage copies. Verifier les modeles personnalises avec
  `{jellyfin_username}` / `{jellyfin_password}` et la reprise apres echec d'envoi.
- [ ] Expiration : valider les modes existants, les effets apres synchronisation
  et renouvellement sur plusieurs serveurs et dans une installation mixte.
  Distinguer compte sans acces, compte encore reference et compte supprime.

- [ ] Dashboard : confirmer que la carte Serveurs apparait au premier rendu,
  avant le calcul des pics 7 jours. Liste et statuts rendus directement depuis
  les donnees deja chargees ; pics en cache reutilises, liste conservee en cas
  de timeout du complement. Duree du calcul historique encore a mesurer.

## Principes de suivi

- Retirer les lignes et sous-lots termines apres publication. Ne conserver ici
  que le travail restant ; tracer effets et limites dans `changelog.md`.
- Conserver ouverts les objectifs partiels et les validations apres deploiement ;
  une verification locale ne vaut pas une validation en production.
- Valider les changements de schema et les traitements automatiques sur une copie
  representative de la vraie base avant publication.
- Ajouter des tests de regression aux fonctions sensibles ou exposees sur Internet.
- Ne jamais journaliser de secret ou token ; conserver les secrets necessaires
  uniquement dans le stockage chiffre prevu a cet effet.
- Les evolutions ci-dessous sont a etudier puis a mettre en place si leur
  faisabilite et leur utilite sont confirmees. Elles ne changent pas les
  comportements existants par defaut.
- References techniques : [architecture](vodum-docs/docs/architecture.md) et
  [securite](vodum-docs/docs/security.md).

## P1 - Cycle de vie des utilisateurs et fins d'abonnement

- [ ] Ajouter la suppression manuelle du compte natif Jellyfin par compte/serveur
  en conservant la fiche VODUM. Reutiliser l'adaptateur de suppression existant ;
  preciser les cibles et les effets sur les donnees natives avant execution.
- [ ] Ajouter la desactivation native automatique Jellyfin (`IsDisabled`) en fin
  d'abonnement et sa politique de renouvellement/reprise : suivre l'origine du
  blocage, ne reactiver que les comptes desactives par cette politique, conserver
  les blocages manuels et les droits anterieurs, ne pas recreer un compte supprime.
  Reutiliser l'action manuelle et les modes d'expiration existants ; voir
  [suppression apres expiration](docs/suppression-expiration-2026-09-23.md).
- [ ] Etudier les operations Plex au-dela du retrait de partage serveur deja
  disponible dans la suppression apres expiration. Tenir compte des recherches
  deja infructueuses : distinguer retrait du partage serveur, relation d'amitie,
  invitation, Plex Home et traces historiques PMS. Qualifier les pistes
  `removeFriend`/`removeHomeUser` uniquement selon le perimetre choisi ; elles
  ne garantissent pas qu'un utilisateur cesse d'etre connu de Plex et peuvent
  depasser un seul serveur. Ne promettre aucune purge totale non demontree,
  ni modifier directement la base PMS pour masquer une identite.
- [ ] Etudier un masquage/exclusion d'import VODUM si les validations montrent
  des reimports indesirables ; ne pas le presenter comme une suppression Plex.

## P2 - Administration native a etudier

### Utilisateurs, appareils et invitations

- [ ] Ajouter l’edition des politiques natives Jellyfin au-dela de `IsDisabled` :
  visibilite, droits
  administrateur, acces distant, lecture/transcodage/debit, telechargement,
  suppression de contenus, controle parental, horaires, appareils et TV.
  Preserver les champs non geres et proteger le dernier administrateur.
- [ ] Ajouter l'inventaire des appareils et les actions de deconnexion/revocation
  lorsque le fournisseur les permet. Verifier le refus d'un ancien jeton apres
  revocation ; ne pas assimiler arret de lecture et deconnexion.
- [ ] Etudier une vue des invitations Plex : attente, anciennete, acceptation,
  annulation et erreurs. Masquer cette vue et ses entrees de navigation si aucun
  serveur Plex n'est configure ; ne pas l'afficher pour une installation
  uniquement Jellyfin. Filtrer les donnees selon les serveurs autorises.
- [ ] Etudier Plex Home, profils geres, PIN et restrictions de partage actuelles.
  Afficher les limites liees au compte, a la version et a Plex Pass ; ne pas
  promettre de gerer le mot de passe/MFA des comptes personnels invites.

### Serveurs et bibliotheques

- [ ] Ajouter progressivement les reglages natifs PMS/Jellyfin, avec lecture
  initiale, edition bornee, controle des droits et verification apres ecriture.
- [ ] Etudier un diagnostic de securite des serveurs : acces sans authentification,
  TLS, acces distant et permissions sensibles. Distinguer ces reglages de la
  securite de la connexion HTTP entre VODUM et les serveurs.
- [ ] Etudier les logs natifs, taches de maintenance, etat/version et commandes
  de redemarrage/arret lorsque disponibles ; distinguer les taches natives
  des taches VODUM et les contraintes propres a l'hebergement.
- [ ] Etudier la gestion native des bibliotheques : creation, parametres et
  emplacements. Distinguer suppression d'une bibliotheque et suppression des
  fichiers medias. Plugins/depots Jellyfin : faisabilite a qualifier ensuite.
- [ ] Etudier un scan Jellyfin cible par bibliotheque seulement si une API
  equivalente est validee ; `/Items/{id}/Refresh` traite les metadonnees et ne constitue
  pas la preuve d'un scan cible.

## P3 - Capacites, securite d'administration et fiabilite

- [ ] Generaliser un registre de capacites par fournisseur, version et identite :
  supporte, interdit, indisponible ou non teste. L'utiliser pour les nouvelles
  actions et leur affichage, des les premiers lots.
- [ ] Etudier plusieurs administrateurs nominatifs, roles et droits par serveur,
  appliques cote serveur aux lectures comme aux mutations.
- [ ] Unifier l'audit des operations natives avec auteur, cible, motif,
  avant/apres expurge, resultat et identifiant d'operation ; reutiliser les
  historiques et protections existants.
- [ ] Etendre les jobs existants aux nouvelles actions : etat souhaite/envoye/
  confirme, relecture native, reprises idempotentes et echecs partiels visibles.
  Tester aussi le provisionnement Jellyfin interrompu entre creation, mot de
  passe et restriction des droits ; prevoir une compensation sure.
- [ ] Etudier la detection des changements faits dans Plex/Jellyfin et la
  reconciliation avec VODUM, sans ecraser un changement administratif externe
  ni relancer involontairement un ancien acces.
- [ ] Etudier les modeles de politiques natives et une reponse a incident
  multi-serveurs, avec actions distinctes de suspension, coupure et revocation.
- [ ] Etudier l'inventaire et la rotation des cles/tokens selon les API : tester
  la nouvelle cle avant revocation de l'ancienne, masquer les secrets et
  respecter la portee reelle des droits accordes par le fournisseur.

## Sauvegardes - protection locale et restauration portable

Le ZIP local contient volontairement la base et sa cle pour permettre une
restauration sur une nouvelle instance. Le chiffrement obligatoire du ZIP
n'est pas retenu comme correction prioritaire. La protection repose sur les
droits du serveur et l'acces aux sauvegardes ; le ZIP reste un fichier sensible.

- [ ] Verifier les permissions du repertoire/fichiers, l'absence d'exposition
  publique et les acces au volume de sauvegarde, en conservant les protections
  admin et anti-cache des routes deja auditees. Le stockage local seul ne
  protege pas contre le vol du ZIP ou la compromission du serveur.
- [ ] En option seulement, etudier la protection des exports/copies hors serveur
  (stockage chiffre ou chiffrement avec secret de recuperation separe), avec
  procedure de restauration testee. Conserver la restauration locale simple.

## Portail utilisateur

- [ ] Completer les demandes medias avec un historique durable consultable et
  des quotas fonctionnels ; failover avec reconciliation apres une reponse ARR
  incertaine. Le traitement existant ne rejoue pas automatiquement un POST incertain.

- [ ] Ajouter un historique contractuel des abonnements avec un modele de donnees
  dedie ; l'historique des cadeaux disponible dans Subscriptions ne le remplace pas.

## Securite - controles restant a terminer

Les exigences encore ouvertes restent ci-dessous ; les anciens rapports
d’audit termines ont ete retires du depot. Consulter la documentation de securite
et le changelog archive pour le contexte historique.

### Uploads et imports volumineux

- [ ] Determiner les besoins reels par type d'upload: import Tautulli, restauration
  VODUM et autres fichiers; ne pas reduire aveuglement la limite globale de 4096 Mo.
- [ ] Evaluer des limites distinctes par fonction et verifier pour les imports
  multi-Go: espace disque, fichiers temporaires, nettoyage apres echec, timeout,
  validation DB, memoire, streaming et concurrence.

### SQL, fichiers et commandes

- [ ] Auditer les SQL dynamiques (`f-string`, `.format`, concatenation) et confirmer
  que les valeurs externes sont parametrees et les identifiants dynamiques issus
  de listes internes strictes.
- [ ] Auditer les chemins variables, lectures/ecritures/suppressions, symlinks et
  fichiers temporaires hors du perimetre backup deja traite.
- [ ] Auditer `subprocess`, `shell=True` et `os.system`; aucune valeur utilisateur ou
  provider ne doit devenir une commande ou de la syntaxe shell.

### API, erreurs et resistance aux abus

- [ ] Auditer les API JSON contre IDOR et exposition excessive en testant la
  substitution des IDs utilisateur, compte media, serveur, policy, communication,
  backup, task et monitoring.
- [ ] Auditer les erreurs 4xx/5xx et les logs restants contre les traces, chemins,
  SQL, internals DB, secrets et reponses provider sensibles.
- [ ] Auditer les operations couteuses: connexions, checks Plex/Jellyfin, monitoring,
  artwork, backup/restore, imports, synchronisations, tasks, recherches et grosses
  reponses; verifier timeout, pagination, concurrence et limites raisonnables.

### Cloture avant publication

- [ ] Completer les regressions des constats encore ouverts sans casser l'acces LAN,
  Plex/Jellyfin, les imports Tautulli, SQLite, le scheduler ou les reverse proxies.
- [ ] Produire le rapport final classe `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`,
  avec chemin reel, protections existantes, exploitabilite, impact, correction,
  risque de regression, tests et statut.

## Modernisation Docker et dependances (audit du 2026-10-09)

Traiter progressivement, avec analyse et validation de chaque lot avant le suivant.
Les versions ci-dessous sont des candidates relevees lors de l'audit ; reverifier
les versions disponibles au moment de chaque intervention.

- [ ] Valider les mises a jour de `requirements.txt` dans une image de test :
  installation, `pip check`, demarrage Waitress, routes, scheduler, connexions
  Plex/Jellyfin, WebSocket Plex et chiffrement/dechiffrement des secrets.
- [ ] Evaluer Python `3.14.8-slim-trixie` ; comparer avec une mise a jour
  conservatrice vers `3.12.15-slim-trixie`. Choisir explicitement la variante
  Debian et definir la politique de versions/digests et de reconstruction.
  Tester SQLite Python et CLI, initialisation, migrations V1/V2, bootstrap,
  sauvegarde/restauration et taches sur des donnees temporaires representatives.
- [ ] Verrouiller les dependances Python indirectes pour des constructions
  reproductibles ; examiner les imports directs de Werkzeug, MarkupSafe et
  urllib3 et leur declaration explicite. Verifier les vulnerabilites connues.
- [ ] Confirmer l'absence d'usage de `pytz` avant une eventuelle suppression ;
  conserver `python-dateutil` dans la resolution de croniter. Verifier `zoneinfo`
  et la disponibilite des donnees de fuseaux horaires dans l'image choisie.
- [ ] Ajouter une etape de construction Node/pnpm avec verrou fige pour preparer
  les assets, puis copier seulement les resultats dans l'image Python finale.
  Automatiser la synchronisation des fichiers `static/vendor` avec les versions
  declarees ; identifier et documenter l'origine/version de QRCode.
- [ ] Evaluer Tailwind CSS et CLI `4.3.3`, reconstruire le CSS et verifier le rendu.
  Chart.js `4.5.1` et Flatpickr `4.6.13` etaient deja a jour lors de l'audit.
- [ ] Etudier separement HTMX `1.9.12` -> `2.0.11` : changements de comportement,
  formulaires, CSRF, navigation, modales et rafraichissements/polling ; valider
  les parcours dans le navigateur avant adoption.
- [ ] Harmoniser les volumes et variables des scripts `create-container.sh` et
  `get-container.sh` avec Compose : `/appdata/logs`, `/appdata/backups`,
  `VODUM_LOG_DIR` et `VODUM_BACKUP_DIR`. Conserver les donnees et la cle
  `vodum.encryption_key` lors du remplacement du conteneur.
- [ ] Aligner le healthcheck et les ports publies sur `VODUM_PORT` ; evaluer un
  healthcheck dans l'image pour les lancements hors Compose et le delai de
  demarrage pendant les migrations longues.
- [ ] Examiner le workflow actif `.github/workflows/docker-image.yml` : actions
  checkout v7, setup-buildx v4, login v4, metadata v6 et build-push v7 candidates,
  compatibilite des runners, renouvellement de l'image de base, tags de version
  et validation avant publication. Clarifier le role de `docker-publish.yml`
  a la racine, qui n'est pas execute comme workflow GitHub Actions.
- [ ] Evaluer un utilisateur non-root et les permissions des volumes, en
  conservant SQLite CLI et Bash tant que l'entrypoint les utilise.
- [ ] Fiabiliser les metadonnees `INFO` : versions Python/SQLite de l'image
  construite, au lieu de celles de la machine hote dans `create-container.sh`.



## Configuration Manager & Compliance — chantier planifié après les priorités P0

Cahier des charges complet : [Configuration Manager & Compliance](docs/configuration-manager-compliance.md).
Parcours cible : configurer, enregistrer un profil, sélectionner les serveurs,
prévisualiser et déployer, vérifier la conformité, puis corriger les écarts.
Le périmètre ci-dessous est à développer ; aucune capacité API n'est considérée
comme acquise avant l'audit. Conserver l'indépendance Docker/OS et une expérience
adaptée à un serveur unique comme à plusieurs dizaines de serveurs.

### Phase 1 — Audit et consultation des paramètres

- [ ] Auditer serveurs, connexions et authentification API, interface Servers /
  Libraries, tâches et `check_servers`, monitoring/alertes, modèles, traductions
  et permissions. Présenter l'existant, les capacités API réelles par plateforme
  et version, leurs limites et les fichiers à modifier avant l'implémentation.
- [ ] Réutiliser les composants Flask/services existants et définir les adapters
  Plex/Jellyfin, profils, groupes, moteurs de diff, conformité et déploiement,
  sans multiplier inutilement les modules, tables ou tâches.
- [ ] Créer Server Configuration : espaces Plex/Jellyfin selon les serveurs
  configurés, état vide sans serveur et actualisation après ajout/suppression.
  Afficher uniquement les catégories disposant de paramètres : General, Network,
  Remote Access, Transcoding, Streaming, Libraries, Metadata, Subtitles,
  Scheduled Tasks, Security et Advanced.
- [ ] Présenter valeur actuelle, compatibilité et droits de lecture/écriture
  pour chaque paramètre ; conserver en lecture seule les informations utiles
  non modifiables. Ajouter recherche, filtres et états de chargement.

### Phase 2 — Profils et groupes statiques

- [ ] Créer, importer depuis un serveur, modifier, dupliquer, renommer et supprimer
  des profils distincts Plex/Jellyfin. Conserver la version courante et les seules
  informations nécessaires au déploiement, sans historisation exhaustive.
- [ ] Gérer nom, description et membres des groupes, ajout/retrait de serveurs,
  renommage/suppression et appartenance multiple. Autoriser les groupes mixtes
  tout en filtrant les cibles compatibles avec chaque profil.
- [ ] Affecter un profil à un serveur ou groupe ; détecter les profils
  contradictoires et demander une résolution explicite. Garder les groupes
  dynamiques pour une évolution éventuelle.

### Phase 3 — Comparaison, conformité et contrôle périodique

- [ ] Développer le diff et Compliance : conformes, non conformes, non vérifiés,
  inaccessibles, nombre d'écarts et date du dernier contrôle. Les serveurs sans
  profil sont non gérés, jamais implicitement conformes.
- [ ] Ajouter les vues par serveur et paramètre, avec catégorie, valeurs attendue
  et actuelle, profil et correction possible. Créer une Configuration Matrix
  filtrable dont les cellules détaillent les valeurs et actions.
- [ ] Enrichir `check_servers` après audit : contrôle des paramètres référencés,
  comparaison, dernier résultat et indicateurs. Réutiliser son ordonnanceur et
  sa cadence ; étudier une cadence de conformité distincte seulement si utile.
  Éviter les appels inutiles, borner les délais et isoler les serveurs lents,
  sans alourdir ou bloquer les contrôles existants.
- [ ] Détecter les modifications effectuées directement dans Plex/Jellyfin,
  conserver la traçabilité administrative nécessaire et dédupliquer les alertes
  d'écarts inchangés, sans historique exhaustif de configuration.

### Phase 4 — Déploiements prévisualisés et vérifiés

- [ ] Choisir serveur source ou profil, cibles individuelles/par groupe/globales
  et paramètres à appliquer. Comparer, afficher incompatibilités et exclusions,
  prévisualiser les modifications puis demander confirmation avant application.
- [ ] Exclure par défaut tokens/clés API, identifiants uniques, mots de passe,
  certificats privés, chemins locaux, interfaces réseau, ports spécifiques,
  URL propres aux serveurs et paramètres matériels incompatibles.
- [ ] Déployer indépendamment par serveur, relire les valeurs via API pour
  confirmer leur prise en compte, afficher réussites/échecs et permettre de
  relancer les seuls échecs sans annuler les autres réussites.

### Phase 5 — Corrections et modes de fonctionnement

- [ ] Prévoir Monitoring Only par défaut et Manual Remediation sur validation
  explicite. Corriger un paramètre, des écarts sélectionnés, un serveur, un
  groupe ou la flotte avec prévisualisation et vérification après écriture.
- [ ] Gérer les exceptions locales sans forcer de paramètres incompatibles ;
  intégrer les notifications de nouveaux écarts lorsqu'elles sont activées.
- [ ] Préparer Auto Remediation sans l'activer implicitement ; son implémentation
  peut être différée et doit rester limitée aux paramètres explicitement autorisés.

### Conditions transversales et validation de chaque phase

- [ ] Réutiliser les connexions configurées, protéger les actions groupées et
  vérifier les droits administrateur côté backend ; ne jamais exposer les secrets,
  exécuter de commandes système arbitraires ni imposer SSH ou un agent distant.
- [ ] Respecter l'interface existante, traduire en EN/FR/DE/ES/IT et fournir
  sélection multiple, comparaison, erreurs explicites et résultats partiels.
- [ ] Tester sans serveur, un seul Plex, un seul Jellyfin, les deux plateformes,
  plusieurs dizaines de serveurs, groupes mixtes, profils et paramètres
  incompatibles/indisponibles, serveur inaccessible, déploiement partiel,
  corrections, exceptions, permissions et traductions.
- [ ] Vérifier l'intégration à `check_servers` et l'absence de régression des
  contrôles et fonctionnalités actuels, avec tests à chaque phase.

## Notes de prudence

- `GET /api/monitoring/poster/<server_id>` est l'unique exception GET mutante
  autorisee: proxy authentifie d'artwork avec cache local, documente dans
  `tools/audit_get_routes.py`.
- Ne pas supprimer le cache artwork existant ni remplacer globalement `sync` par
  `revoke`; Plex conserve volontairement un garde-fou contre un sync vide.
- Valider les optimisations SQL avec la vraie base et `EXPLAIN QUERY PLAN`; trop
  d'index peut ralentir les ecritures et le bootstrap.
- Garder les modifications de texte ciblees afin de ne pas recreer de mojibake.
