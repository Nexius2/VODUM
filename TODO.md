# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines sont
documentes dans `changelog.md`.

Derniere mise a jour: 2026-10-08

## P0 - Performances et reactivite VODUM (priorite avant les evolutions P1/P2/P3)

Perimetre : application VODUM, independamment de la machine et de l'hebergement.
Ordre ci-dessous par impact attendu sur la reactivite globale, a confirmer par
mesure ; les gains ne sont pas encore chiffres. Conserver les optimisations deja
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

- [ ] 1. Reduire la contention SQLite : remplacer progressivement la connexion
  partagee et son verrou global par des connexions de lecture independantes
  et une gestion explicite des ecritures. Auditer les usages directs de `db.conn`,
  les transactions et le dechiffrement sous verrou ; conserver l'atomicite,
  les contraintes et WAL. Ne pas simplement retirer le verrou actuel.
  Premier lot livre : lectures lourdes Utilisateurs et tableau Bibliotheques du
  monitoring isolees sur des snapshots SQLite en lecture seule. Les ecritures,
  migrations, imports et controles d'acces gardent leur connexion actuelle.
  Deuxieme lot livre : historique, agregats de la vue d'ensemble et classements
  par bibliotheque isoles egalement. La reparation des references artwork reste
  sur le parcours d'ecriture existant, apres fermeture du snapshot de lecture.
  Reste a mesurer sur une base representative et etendre aux autres parcours
  apres audit de leurs eventuelles ecritures.
  Troisieme lot livre : blocs Servers et Usage risk du dashboard isoles sur
  des snapshots de lecture ; requete des pics alignee sur l'index de dates.
  Quatrieme lot livre : contexte et neuf lectures de statistiques de l'onglet
  Servers du monitoring isoles egalement. Comparaison des six valeurs de plage,
  absence d'ecriture et test de lecture pendant verrou d'ecriture occupe.
  Benchmark concurrent synthetique dans `tools/benchmark_monitoring_server_reads.py`.
- [ ] 2. Liberer les threads web : executer les operations longues dans des jobs
  bornes, avec reponse rapide, suivi de progression et reprise idempotente.
  Prioriser demandes medias et recuperations lentes ; verifier qu'une operation
  fournisseur bloquee ne retarde pas la navigation des autres utilisateurs.
  Evaluer le dimensionnement Waitress apres reduction des blocages.
- [ ] 3. Eviter les recalculs de tout l'historique dans le monitoring : materialiser
  les statistiques par utilisateur/bibliotheque et la derniere activite ; garder
  les filtres, tris et la pagination coherents. Retirer les identites repetees
  par lecture dans `GROUP_CONCAT`, charger les identites depuis leurs tables.
  Verifier les plans SQL et la deduplication ; ajouter uniquement les index utiles.
  Premier lot livre : compteur Utilisateurs sans filtre par verification indexee
  de l'existence d'un historique ; suppression de la concatenation des identites
  inutilisee lorsque la liste n'est pas filtree. Recherche filtree conservee
  a l'identique, avec comparaisons aux anciennes requetes pour tris/pagination.
  Reste a materialiser les statistiques et optimiser les recherches filtrees.
- [ ] 4. Rendre la consultation des logs proportionnelle a la page affichee :
  separer entretien/rotation et consultation, eviter le nettoyage force et la
  relecture de toutes les archives a chaque ouverture. Mettre les compteurs en
  cache, borner les lectures et etudier une file de journalisation dediee ;
  conserver recherche, traces multilignes, anonymisation et retention.
  Premier lot livre : l'entretien ne relit plus les fichiers deja controles
  et inchanges tant qu'aucune ligne ne peut expirer. Invalidation sur changement
  de fichier/politique ; reutilisation bornee du decodage des dates repetees.
  Deuxieme lot livre : cache borne des evenements analyses, invalide sur
  changement/rotation/purge ; consultation repetee sans relecture ni analyse
  des fichiers inchanges. Recherche, compteurs, pagination et export conserves.
  Reste a borner les lectures lors d'un changement ou pour les gros historiques,
  et a optimiser les compteurs et la recherche au-dela du cache.
- [ ] 5. Reduire les parcours des demandes medias : qualifier les recherches
  ciblees par identifiant fournisseur Plex/Jellyfin/ARR et un index local
  actualise. Eviter les scans complets et appels de details repetes ; conserver
  les controles d'acces, la verification avant ajout, les reservations contre
  les doublons et l'absence de failover apres POST incertain. La parallelisation
  deja presente ne suffit pas a supprimer ces parcours.
- [ ] 6. Prioriser les appels Plex et les images interactives : revoir la limite
  partagee d'une requete/seconde, avec concurrence bornee et adaptation aux
  erreurs fournisseur. Servir immediatement un artwork ancien disponible,
  actualiser en arriere-plan, dedupliquer les recuperations simultanees et
  imposer un budget total aux essais de chemins/adresses. Reutiliser les
  connexions HTTP dans un meme travail sans partager une session mutable
  entre threads ; conserver les restrictions d'origine et la verification TLS.
- [ ] 7. Regrouper les ecritures des collectes et synchronisations en petits lots :
  reduire les commits par session/evenement/droit et les reecritures de
  metadonnees inchangees. Garder les transactions courtes, sans appel reseau,
  et verifier coherence, reprise et comportement lors d'une erreur partielle.
- [ ] 8. Separer les taches urgentes des travaux lourds : files/workers bornes
  pour monitoring et actions interactives, distincts des imports, campagnes,
  synchronisations et prechargements. Decouper les travaux longs, prevoir des
  budgets reels/cooperatifs et preserver les leases et protections contre les
  executions concurrentes incompatibles ; ne pas creer de threads abandonnes.
- [ ] 9. Reduire les rafraichissements inutiles : cadence adaptative selon l'activite,
  suspension des onglets masques dans toutes les vues, absence de chevauchement
  et retour des seuls changements utiles. Conserver la protection du dashboard
  deja presente ; evaluer snapshots partages, reponses conditionnelles ou SSE
  selon le cout mesure et la compatibilite du serveur web/reverse proxy.
  Premier lot livre : polling des vues Monitoring overview/now_playing suspendu
  en onglet masque, reprise immediate au retour, sans empilement de requetes
  lentes. Les cadences visibles et soumissions de filtres sont conservees.
  Deuxieme lot livre : polling de Tasks suspendu en onglet masque, reprise au
  retour, une seule requete en vol avec attente bornee a 10 secondes. Tableau
  conserve quand son contenu genere est identique ; statuts et actions actualises
  lors d'un changement. Tests sur reponse lente, erreur et reprise.
  Troisieme lot livre : suivi des sauvegardes et imports Tautulli suspendu en
  onglet masque, reprise au retour et requetes sans chevauchement, bornees a
  10 secondes cote navigateur. Une erreur de lecture du statut de sauvegarde
  ne vaut plus confirmation de fin ; rafraichissement final conserve.
  Reste a etendre aux autres vues et evaluer cadence adaptative et snapshots.
- [ ] 10. Rendre les calculs de fond incrementaux : recalculer uniquement les jours
  modifies des agregats quotidiens ; charger une seule fois les abonnements
  pendant l'analyse des usages. Dissocier la consultation des rapports de
  l'enregistrement des recommandations et etendre les caches avec invalidation.
  Premier lot livre : abonnements charges une seule fois par rapport Usage risk,
  uniquement si une recommandation est necessaire. Configuration relue au
  rapport suivant ; resultats compares et benchmark synthetique disponible dans
  `tools/benchmark_usage_risk.py`.
  Deuxieme lot livre : statistiques quotidiennes recalculees uniquement pour
  les jours absents ou modifies. Suivi SQLite des insertions/corrections/purges
  d'historique et des changements d'identite ; recalcul conservateur de toute
  la fenetre apres changement d'identite. Benchmark local et cout d'ecriture
  documentes dans `docs/performance-daily-refresh-2026-10-08.md`.
  Reste a separer consultation/enregistrement des recommandations, etendre
  l'invalidation des caches et valider sous charge representative.
  Troisieme lot livre : compteurs de blocages Usage risk limites aux actions
  kill avec index partiel de dates ; aucune lecture globale de ces compteurs
  quand aucun evenement ne correspond aux filtres. Rapports compares a la
  requete precedente ; benchmark dans `tools/benchmark_usage_risk_kill_windows.py`.
- [ ] 11. Reduire les petits couts repetes : mutualiser les lectures de settings
  dans une requete, mettre en cache le statut de mise a jour avec invalidation,
  et comparer un niveau gzip moins couteux. Preserver la revocation immediate
  des sessions et les controles de droits ; ne pas cacher les autorisations
  sans politique d'invalidation explicite.
  Premier lot livre : compression HTML/JSON au niveau gzip 6 par defaut,
  configurable de 1 a 9 via VODUM_HTTP_GZIP_LEVEL. Contenu et exclusions
  preserves ; benchmark synthetique reproductible (y compris quatre workers)
  dans `tools/benchmark_http_compression.py`. Mesure en production restante.
  Deuxieme lot livre : langue, nom de marque, fuseau horaire et contexte
  global des templates partagent une lecture des settings par requete GET/HEAD.
  Aucun cache entre requetes ; lectures fraiches pour les requetes mutantes.
  Controles d'autorisation et revocation inchanges. Gain sous charge a mesurer.
  Troisieme lot livre : statut du badge de mise a jour reutilise tant que le
  fichier ne change pas. Invalidation par metadonnees, remplacement/suppression
  detectes ; erreurs relues a la requete suivante. Mesure sous charge restante.
- [ ] 12. Borner la maintenance : purges par lots, sauvegardes/checkpoints et
  entretien des caches sans longues pauses du traitement interactif. Verifier
  la restauration, la coherence des sauvegardes et les effets sur les lecteurs.
  Premier lot livre : six tables historiques de cleanup_data_retention purgees
  par lots de 500 lignes avec commit et pause entre lots. Borne initiale des
  identifiants, dates reverifiees avant suppression ; retention inchangee.
  Deuxieme lot livre : cinq tables de retention du portail traitees avec le
  meme mecanisme ; comptes et regles d'expiration conserves. Reprise apres
  interruption testee. Checkpoints/sauvegardes et mesure sous charge restants.
  Troisieme lot livre : sauvegarde SQLite en ligne par connexion dediee,
  snapshot temporaire puis compression ; checkpoint TRUNCATE force retire.
  Restauration du contenu WAL validee, donnees non commitees exclues et
  nettoyage apres erreur teste. Mesure concurrente representative restante.
  Quatrieme lot livre : budget cooperatif du snapshot SQLite (300 s par defaut,
  VODUM_BACKUP_SNAPSHOT_TIMEOUT_SECONDS). Abandon propre sans archive publiee
  en cas de depassement ; coherence testee pendant des commits concurrents.
  Compression et parcours des pieces jointes hors de ce budget.
  Cinquieme lot livre : nettoyage artwork avec pause toutes les 100 entrees,
  grace de 60 s pour fichiers temporaires/orphelins et exclusion du snapshot
  portal-backdrop.json. Retention et suppression des anciens binomes testees.

Chaque lot doit demontrer un gain de latence sous charge et conserver les
regressions fonctionnelles et de securite. Aucun changement d'hebergement ni
migration de moteur de base n'est requis par cette liste.

## Validation apres deploiement

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

## Principes de suivi

- Retirer une ligne lorsqu'elle est terminee et la tracer dans `changelog.md`.
- Valider les changements de schema et les traitements automatiques sur une copie
  representative de la vraie base avant publication.
- Ajouter des tests de regression aux fonctions sensibles ou exposees sur Internet.
- Ne jamais journaliser de secret ou token ; conserver les secrets necessaires
  uniquement dans le stockage chiffre prevu a cet effet.
- Les evolutions ci-dessous sont a etudier puis a mettre en place si leur
  faisabilite et leur utilite sont confirmees. Elles ne changent pas les
  comportements existants par defaut.
- Reference technique : [audit Plex/Jellyfin du 6 septembre 2026](docs/audit-couverture-plex-jellyfin-2026-09-06.md).

Etat des briques deja presentes : [controle du premier lot](docs/todo-existant-2026-10-06.md).

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

- [x] Demandes medias du portail : recherche films/series via ARR, resolution automatique parmi
  les bibliotheques accessibles, verification Plex/Jellyfin et tous les ARR lies,
  ajout dans l'ARR prioritaire correspondant aux criteres. Deduplication par ID,
  CSRF, limites de requetes et reservation contre les soumissions simultanees.
  Profil qualite et destination par defaut choisis dans la fiche ARR.
- [ ] Completer les demandes medias avec historique persistant, suivi et quotas
  fonctionnels ; failover avec reconciliation apres une reponse ARR incertaine.

- [ ] Ajouter un historique contractuel des abonnements avec un modele de donnees
  dedie ; l'historique des cadeaux disponible dans Subscriptions ne le remplace pas.

## Securite - controles restant a terminer

Les audits deja termines sont dans `docs/security-*-audit.md`,
`docs/container-runtime-audit.md` et `changelog.md`. Ne pas les recreer ici.

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

## Notes de prudence

- `GET /api/monitoring/poster/<server_id>` est l'unique exception GET mutante
  autorisee: proxy authentifie d'artwork avec cache local, documente dans
  `tools/audit_get_routes.py`.
- Ne pas supprimer le cache artwork existant ni remplacer globalement `sync` par
  `revoke`; Plex conserve volontairement un garde-fou contre un sync vide.
- Valider les optimisations SQL avec la vraie base et `EXPLAIN QUERY PLAN`; trop
  d'index peut ralentir les ecritures et le bootstrap.
- Garder les modifications de texte ciblees afin de ne pas recreer de mojibake.
- [ ] Dashboard : confirmer que la carte Serveurs apparait au premier rendu,
  avant le calcul des pics 7 jours. Liste et statuts rendus directement depuis
  les donnees deja chargees ; pics en cache reutilises, liste conservee en cas
  de timeout du complement. Duree du calcul historique encore a mesurer.
