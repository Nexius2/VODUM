# Changelog

Changements depuis la derniere publication, effectuee avant le monitoring du portail utilisateur.

## Nettoyage du cache des affiches

- Snapshot des posters du portail conserve lors du nettoyage du cache.
- Fichiers temporaires et orphelins recents proteges pendant 60 secondes
  pour laisser les ecritures d'affiches se terminer.
- Courte pause toutes les 100 entrees pour repartir le travail de maintenance.

## Sauvegarde SQLite en ligne

- Base sauvegardee via un snapshot SQLite coherent sur une connexion dediee,
  puis compressee sans utiliser le verrou de connexion partage de l'application.
- Checkpoint WAL force retire ; donnees commitees dans le WAL incluses.
  Format de l'archive, pieces jointes et cle de chiffrement conserves.
- Snapshot temporaire nettoye en cas de succes ou d'erreur.
- Budget du snapshot SQLite de 300 secondes, configurable via
  `VODUM_BACKUP_SNAPSHOT_TIMEOUT_SECONDS`. Depassement signale comme echec
  sans publier d'archive incomplete ; compression hors de ce budget.

## Purge des historiques par lots

- Retention des six tables historiques traitee par lots de 500 lignes avec
  liberation du verrou entre les lots, au lieu d'une suppression massive.
- Meme traitement pour les sessions, jetons, audits, limites de requetes et
  tentatives de connexion du portail. Comptes conserves et reprise possible
  au passage suivant si une purge est interrompue.
- Dates reverifiees avant suppression ; nouvelles lignes laissees au prochain
  passage pour que les imports ne prolongent pas indefiniment la purge.

## Badge de mise a jour

- Statut JSON du badge reutilise entre requetes tant que le fichier ne change
  pas, au lieu de le rouvrir et de le decoder a chaque navigation ou polling.
- Modification, remplacement et suppression detectes ; les erreurs de lecture
  sont retentees a la requete suivante.

## Lectures de configuration pendant le rendu

- Langue, nom de marque et fuseau horaire reutilisent la configuration deja
  lue dans la meme requete GET, notamment lors du formatage de nombreuses dates.
- Configuration relue a la requete suivante et pour les requetes qui modifient
  les donnees. Controles d'acces et revocation des sessions inchanges.

## Affichage immediat des serveurs sur le dashboard

- Liste, statuts et dernier controle affiches avec la page, sans attendre le
  calcul des pics de lectures sur sept jours. Pics deja en cache reutilises.
- Calcul des pics charge ensuite ; une expiration de la requete conserve
  la liste visible au lieu de remplacer la carte par « No data ».

## Lien de connexion au portail dans les communications

- Variable `{portal_login_url}` conservee lors du premier rendu des envois
  planifies et construite depuis l'URL publique du portail.
- Lien disponible dans les mails de test et la reconstruction des anciens
  historiques ; messages deja enregistres conserves tels qu'envoyes.
- Construction du lien partagee avec la configuration du portail pour eviter
  de doubler le chemin `/portal`.

## Compression des reponses web

- Compression des reponses texte au niveau gzip 6 par defaut pour reduire
  le cout CPU, avec une legere hausse de taille selon le contenu.
  Niveau configurable de 1 a 9 via `VODUM_HTTP_GZIP_LEVEL`.
- Contenu decompresse identique ; exclusions des petites reponses, fichiers
  statiques, flux et reponses deja compressees conservees.

## Lisibilite du monitoring sur mobile

- Titres longs des tops films et series sur plusieurs lignes, avec compteurs
  maintenus a droite dans une colonne distincte. Titres limites a deux lignes
  sur mobile comme sur ordinateur.
- Navigation mobile presentee en boutons sur deux colonnes, avec bordures,
  zone tactile de 44 pixels et section active contrastee. Navigation desktop
  et visibilite conditionnelle du portail conservees.

## Rafraichissement du monitoring en arriere-plan

- Suivi des sauvegardes et imports Tautulli : polling suspendu dans les onglets
  masques, reprise au retour, sans chevauchement et attente bornee cote navigateur.
  Les jobs continuent sur le serveur. Une erreur temporaire de lecture du statut
  ne marque pas la sauvegarde terminee ; resultat final et arret du suivi conserves.

- Page Tasks : polling suspendu dans les onglets masques, reprise au retour,
  requete unique en vol et delai maximal de 10 secondes cote navigateur.
  Le tableau n'est plus reconstruit lorsque son contenu est identique ; les
  changements de statut et les boutons d'action restent actualises.

- Les vues Vue d'ensemble et Lectures en cours suspendent leurs requetes
  periodiques lorsque l'onglet est masque et se rafraichissent au retour.
- Les requetes lentes ne se chevauchent pas et ne s'empilent pas. Cadences
  visibles, filtres, ordre des cartes et mises a jour de lecture conserves.
- Tests JavaScript sur 100 tentatives masquees, retour visible, onglets sans
  polling et reexecution du script ; regressions du monitoring conservees.

## Compteurs de blocages Usage risk

- Comptage des incidents sur 7/30/90 jours limite aux actions kill, sans
  parcours des avertissements. Index partiel de dates ajoute au schema initial
  et au bootstrap ; deduplication par serveur/session et scores conserves.
- Rapport sans evenement filtre : aucun comptage global des blocages.
- Comparaison des rapports complets sur actions mixtes, acteurs sans blocage,
  sessions repetees et identites externes. EXPLAIN QUERY PLAN confirme l'index.
- Benchmark local de 200 000 evenements dont 2 000 blocages, sept executions :
  mediane 124,414 ms contre 3,355 ms pour cette requete, compteurs identiques.
  Mesure synthetique en memoire, sans prediction de latence en production.
- Index construit au prochain bootstrap ; espace et cout d'entretien
  supplementaires pour les blocages. Aucun historique modifie ou supprime.

## Fond discret des demandes medias du portail

- Selection des affiches conservee sur disque pour survivre aux redemarrages
  et etre partagee entre processus web. Seuls les quatre films et quatre series
  affiches dans le monitoring sont utilises, avec leurs images resolues exactes.
  Les affiches identiques sont dedupliquees ; aucun remplacement par d'autres
  titres de l'historique ou du classement. Les acces restent verifies.

- Mosaique translucide des quatre premiers films et series du classement deja
  en cache, avec affiches presentes sur disque. Aucun recalcul de classement ni
  appel fournisseur supplementaire ; absence de decor si aucune image locale
  accessible n'est disponible.
- Images decoratives masquees aux lecteurs d'ecran, chargement differe et
  adaptation mobile. L'endpoint du portail reverifie session, fonctionnalite
  et acces a la bibliotheque ; reponse privee sans stockage navigateur.
- Aucun acces aux endpoints artwork admin depuis le portail ; les historiques
  sans bibliotheque identifiable ne sont pas utilises pour le decor.

## Premier chargement du dashboard et analyse Usage risk

- Contexte des serveurs et statistiques de Monitoring > Servers lus dans des
  snapshots independants de la connexion d'ecriture partagee. Aucun changement
  de requetes, filtres, plages, statistiques, dechiffrement ou rendu ; chaque
  operation voit un snapshot coherent ferme en fin de traitement.
- Comparaison des valeurs pour all/7d/1m/6m/12m et plage invalide, absence
  d'ecriture et lecture pendant occupation du verrou partagent les regressions
  SQLite. Benchmark WAL synthetique avec transaction de 250 ms : mediane de
  lecture 261,796 ms avant et 9,182 ms apres, statistiques identiques sur cinq
  executions. Details dans la documentation technique des lectures serveur.

- Rafraichissement des statistiques quotidiennes limite aux jours manquants ou
  modifies. Les imports tardifs, corrections, deplacements entre jours et
  suppressions sont suivis par triggers SQLite ; les changements d'identite
  invalident conservativement la fenetre. Les agregats perimes ne sont plus
  utilises lors d'une lecture non cachee ; repli sur les requetes existantes.
- Migration additive au bootstrap : revisions par jour et identites, colonnes
  de revisions dans les agregats et neuf triggers. Les anciens agregats sont
  reconstruits au premier passage, sans modifier l'historique source.
- Benchmark local : 31 000 sessions, 31 jours, un jour modifie ; rafraichissement
  complet 281,001 ms, incremental 8,723 ms, resultats identiques. Surcout mesure
  de suivi : environ 8 ms pour 5 000 insertions. Details et limites dans
  la documentation technique des statistiques quotidiennes.

- Blocs Servers et Usage risk sur des snapshots SQLite en lecture seule,
  independants du verrou de la connexion partagee. Filtre des pics sur sept
  jours aligne sur l'index datetime existant, verifie par EXPLAIN QUERY PLAN.
- Abonnements charges une seule fois par analyse Usage risk, a la premiere
  recommandation necessaire ; aucun cache entre rapports. Les recommandations,
  filtres, scores et enregistrements gardent leur parcours existant.
- Mesures des routes lentes actives par defaut (desactivables avec
  VODUM_ROUTE_TIMING=false), incluant les hooks avant requete, et duree Flask
  exposee par Server-Timing. La file Waitress n'est pas incluse.
- Benchmark synthetique hors production : 500 utilisateurs, 100 abonnements,
  sept executions ; mediane 209,242 ms avant et 131,202 ms apres, 500 lectures
  des abonnements contre une seule, rapports identiques. Ce resultat ne mesure
  pas la latence de l'instance ni un scenario multi-utilisateur sous charge.
- 50 tests dashboard/Usage risk passent, y compris comparaison des rapports,
  configuration modifiee entre deux analyses et liste d'abonnements vide.

## Requetes Utilisateurs du monitoring

- Le compteur sans recherche verifie l'existence d'un historique par compte
  avec l'index existant, au lieu de regrouper toutes les lectures.
- La liste sans recherche evite la concatenation inutilisee des identites par
  lecture. Les recherches filtrees gardent leur comportement, y compris les
  caracteres SQL LIKE, les comptes regroupes, tris et pagination.
- Comparaison aux requetes precedentes sur 250 cas de compteurs/listes.
  Aucun changement de schema, de donnees ou de templates.

## Reduction des parcours de retention des logs

- Consultation : cache unique et borne des evenements analyses pour les fichiers
  inchanges, avec controle des metadonnees a chaque demande. Toute modification,
  rotation ou purge invalide le cache ; les lectures partielles/en erreur ne
  sont pas mises en cache. Les gros historiques restent consultables sans
  troncature. Recherche, compteurs, pagination, tracebacks et export brut
  anonymise conservent leur comportement, sans modification visuelle.

- Les fichiers inchanges deja controles ne sont plus relus par l'entretien
  tant qu'aucune ligne retenue ne peut expirer. Les modifications de contenu,
  rotations et changements de politique invalident ce controle.
- Decodage des dates repetees reutilise via un cache borne. Les regles de
  retention, tracebacks, consultation, recherche, compteurs et exports restent
  inchanges ; aucune modification des templates ou du schema.
- Regressions sur expiration apres mise en cache, fichiers modifies/remplaces,
  dates invalides, politique de retention et budget disque.

## Isolation des lectures lourdes du monitoring

- Extension a l'historique, aux agregats de la vue d'ensemble (cache froid ou
  chaud) et aux classements par bibliotheque. Les reparations des references
  d'affiches restent executees avec la connexion d'ecriture apres fermeture
  du snapshot ; filtres, pagination, classements, URL et caches sont conserves.

- Les statistiques Utilisateurs et le tableau Bibliotheques utilisent une
  connexion SQLite en lecture seule par operation, fermee en fin de traitement.
  Ces lectures ne monopolisent plus le verrou de la connexion partagee avec
  les pages et les taches de fond ; les requetes et le rendu restent identiques.
- Aucun changement de schema, migration ou suppression de donnees. Les ecritures,
  transactions, imports et controles d'acces conservent leur parcours existant.
- Regressions : lectures/ecritures concurrentes, snapshots coherents, refus des
  ecritures sur le lecteur, fermeture apres erreur, commit/rollback et resultats
  identiques avec filtres, pagination et lectures dedupliquees.

## Serveurs de creation utilisateur

- Choix des serveurs limite a Plex et Jellyfin lors de la creation utilisateur.
  Rejet des ARR cote serveur avant creation du compte ou attribution d'acces.

## Visibilite et suivi des demandes du portail

- Demandes de medias en deuxieme position apres l'accueil. Activation independante
  de l'acces aux medias dans les sections visibles, avec controle admin d'au moins
  un ARR ayant profil et destination enregistres.
- Monitoring : compteurs demandes, ajouts envoyes, deja disponibles, recherche
  en cours et echecs ; tableau dedie avec date, utilisateur, titre, type et resultat.
  Les ajouts correspondent a l'envoi a l'ARR, pas a un telechargement termine.
- Resultats detailles des nouvelles demandes enregistres dans l'audit existant,
  sans doublon d'evenements. Traductions dans les cinq langues.

## Explication des demandes pour les utilisateurs

- Texte du portail reformule dans les cinq langues : rechercher un titre,
  le selectionner pour demander son ajout et expliquer sa recherche puis son
  ajout automatique aux serveurs lorsqu'il devient disponible, sans jargon.

## Recherche unifiee du portail

- Recherche des films et series sans selecteur de type, avec indication du type
  sur chaque resultat. Les identifiants signes et destinations restent propres
  a chaque media. Les resultats disponibles sont conserves si un type echoue.

## Actions de la fiche serveur

- Bouton Delete deplace a cote de Save dans l'en-tete, avec le style et la
  confirmation de suppression existants.

## Exclusion des ARR non configures

- Notice rouge dans la liste et la fiche de chaque ARR sans profil qualite et
  destination de demandes enregistres. Ces instances sont exclues des recherches,
  verifications de doublons et ajouts du portail, quelle que soit leur priorite.
- Sauvegarde explicite des identifiants des choix uniques proposes par l'ARR.

## Departage des bibliotheques pour les demandes

- A preference et priorite identiques, selection de la bibliotheque dont le
  premier ARR correspondant dispose de valeurs de demande enregistrees, avant
  le departage par ID. Evite qu'une bibliotheque specialisee sans configuration
  bloque une destination generale configuree. L'ordre ARR et les criteres restent
  respectes ; aucune verification de profil sur les ARR secondaires.

## Associations ARR avant destinations de secours

- Le routage automatique traite les associations configurees avant les
  bibliotheques sans association, meme si une destination de secours possede une
  preference ou une priorite superieure. Les acces utilisateur et criteres medias
  restent verifies.
- Journal des bibliotheques candidates, origine explicite ou secours et nom de
  l'ARR retenu pour expliquer les erreurs de configuration. Aucun secret ajoute.

## Diagnostic de l'instance ARR retenue

- Journal de resolution avec bibliotheque, instance et priorite effectivement
  retenues. Si les valeurs par defaut echouent, comparaison des identifiants
  sauvegardes et disponibles, sans cle API ni chemin.
- Tests de regression Sonarr et Radarr : le second ARR sans valeurs par defaut
  reste interroge pour les doublons, mais seule l'instance prioritaire est
  verifiee pour le profil/destination puis recoit l'ajout.

## Ordre des ARR par bibliotheque

- Remplacement du champ priorite ARR par un tableau des instances liees avec
  boutons monter/descendre. Rang recalcule automatiquement, sauvegarde globale.
- Reordonnancement transactionnel sans collision, en conservant les criteres et
  activations des autres ARR. Une liste perimee ou invalide est rejetee.

## Sauvegarde globale dans le titre des fiches serveur

- Bouton Save unique en haut a droite du titre, avec le meme style que Settings.
- Retrait du bouton dans Media Request Routing et dans la carte de connexion :
  l'action enregistre toujours toute la fiche, y compris les profils et destinations ARR.

## Perimetre de verification des demandes medias

- Selection de la destination avant les controles obligatoires. Un serveur media
  ou un ARR sans rapport avec cette bibliotheque ne bloque plus l'ajout.
- A preference/priorite egales, les liens admin explicites passent avant les
  bibliotheques non configurees utilisant le fallback automatique.
- La bibliotheque retenue et tous ses ARR actifs restent verifies avant l'envoi.
- Correction de l'ajout Sonarr lorsque les metadonnees de saisons sont nulles.
- Messages distincts pour verification media, verification ARR, ajout refuse et
  reponse d'ajout incertaine. Diagnostic admin sans URL, cle ou payload dans les logs.

## Retour colore sur les demandes medias

- Resultat affiche dans un petit popup au-dessus des recherches : vert pour
  disponible/ajoute, violet pour recherche deja en cours, rouge en cas d'erreur.
- Envoi sans rechargement : recherche et resultats restent visibles. Fermeture
  manuelle ou avec Echap ; les confirmations disparaissent apres dix secondes.
- Formulaire classique conserve sans JavaScript, avec retour a la recherche.

## Demandes simplifiees et affiches medias

- Suppression des choix de bibliotheque et de resolution dans le portail.
  Destination automatique selon les acces, preferences, priorites et criteres medias.
- Qualite confiee au profil existant de Sonarr/Radarr choisi dans la fiche admin ;
  suppression des cases de resolution fixes du routage. Les anciennes contraintes
  de resolution ne bloquent plus les demandes automatiques.
- Affiches a cote des resultats, avec remplacement visuel si aucune affiche
  n'est disponible. URLs publiques TMDB/TVDB uniquement, jamais les URLs ARR.
- Conservation du theme, de la sauvegarde unique et des controles de doublons.

## Demandes medias dans le portail utilisateur

- Recherche films/series via Sonarr/Radarr et selection du media, de la bibliotheque
  accessible et de la resolution. Resultats dedupliques par TMDB/TVDB ID.
- Verification de Plex/Jellyfin puis de tous les ARR lies : deja disponible,
  recherche deja en cours, ou ajout avec recherche dans l'ARR prioritaire qui
  satisfait les criteres medias. Une verification en echec bloque l'ajout.
- Profil qualite et destination par defaut dans la fiche ARR, sauvegardes avec
  son bouton unique. Valeurs existantes de l'instance, sans mapping de chemins.
- Revalidation des acces, selection signee, CSRF, limites par utilisateur/IP,
  reservation SQLite contre les soumissions simultanees et audit du portail.
  Connexions et cles API restent cote serveur. Traductions dans les cinq langues.
- Validation : tests du portail, du routage admin, du schema et des serveurs ;
  verification des doublons, acces, pannes et soumissions signees/CSRF.
- TODO ajuste : historique, quotas fonctionnels et failover avec reconciliation
  restent a traiter. Aucun ajout reel effectue pendant les tests.

## Activation unique par association ARR

- Une seule case « Link this ARR » lie et active l'ARR pour la bibliotheque,
  et affiche ses options. Decochee, elle retire cette association et replie la carte.
- Suppression des deux cases d'activation supplementaires. Retirer un ARR
  ne desactive pas les demandes ou les associations des autres instances.

## Cartes de routage ARR compactes

- Les bibliotheques dont les demandes sont desactivees sont repliees ; leur nom et les cases
  d'activation restent visibles. Les priorites et criteres apparaissent des que
  la case Enable requests est cochee, meme sans association explicite a l'ARR.
- Repli immediat sans effacer les valeurs saisies, avec conservation du theme
  et du bouton de sauvegarde unique.

## Sauvegarde unique de la configuration ARR

- Un seul bouton Save pour la fiche ARR : connexion et configuration de toutes
  les bibliotheques sont enregistrees ensemble. Suppression des boutons par carte,
  avec conservation de leur disposition et du theme.
- Sauvegarde transactionnelle : une regle invalide annule toutes les modifications
  de la page, y compris celles du serveur. Formulaire admin avec jeton CSRF.

## Routage configure depuis les fiches ARR et criteres medias

- Section de configuration deplacee vers les fiches Sonarr/Radarr ; les fiches
  Plex/Jellyfin gardent leurs sections habituelles. Chaque ARR propose uniquement
  les bibliotheques VODUM compatibles, avec le nom de leur serveur media.
- Edition de l'association courante sans effacer les autres ARR de la bibliotheque.
  Conservation des priorites, activation et preferences existantes.
- Criteres par association : genres, resolution demandee (720p/1080p/2160p),
  collections. Dimensions combinees avec AND, valeurs d'une dimension avec OR,
  comparaison sans casse ; criteres vides universels, metadonnees manquantes
  exclues si necessaires. Aucune correspondance de chemin ajoutee.
- Table `library_arr_conditions` liee aux associations existantes, suppression
  en cascade. Configuration persistee et fonction de correspondance testee ;
  raccordement au resolver et envoi portail encore au TODO.
- Validation : 9 tests du routage admin, dont criteres, preservation des autres
  instances, compatibilite, conflits et rendu. Aucun serveur reel modifie.

## Configuration admin du routage des demandes medias

- Section de routage dans les fiches Plex/Jellyfin, fondee sur toutes les
  bibliotheques deja synchronisees, independamment de leur pagination.
  Films : Radarr uniquement ; series : Sonarr uniquement ; autres types exclus.
- Plusieurs associations ARR par bibliotheque avec priorite numerique et activation,
  activation des demandes, bibliotheque preferee et priorite de bibliotheque.
  Sans association, affichage du premier ARR compatible par ID croissant.
- Tables `library_arr_routes` et `library_request_settings` au bootstrap et dans
  le schema initial, cles etrangeres avec suppression en cascade, sauvegarde
  transactionnelle et verification du serveur, de la bibliotheque, des types et
  des priorites uniques. Route admin POST avec formulaire CSRF ; aucun secret expose.
- Theme existant conserve, traductions dans les cinq langues. Aucun chemin ou
  root folder ajoute. La resolution utilisateur et l'envoi/failover des demandes
  restent a implementer ; ce lot configure leurs destinations.
- Validation : 59 tests reussis du routage admin et des serveurs, dont stockage,
  relecture, types incompatibles, IDs invalides, priorites, rendu et cascades.
  Aucun changement sur une base ou des serveurs reels.

## Detection automatique du type de serveur

- Suppression du choix du type dans les formulaires d'ajout : URL et token/cle
  API suffisent. Detection Plex, Jellyfin, Sonarr et Radarr par leurs reponses
  API authentifiees, sans deduction a partir du port.
- Verification du format et de l'identite de l'application, conservation des
  sous-chemins, timeout et refus des redirections ; serveur inconnu ou connexion
  invalide refuse avant insertion. Stockage chiffre et synchronisations conserves.
- Presentation et oeil du token conserves ; aide traduite dans les cinq langues.

## Disposition de la page Servers

- Ajout de serveur conserve en haut a gauche ; serveurs Plex disponibles deplaces
  a droite. Toutes les cartes de serveurs sont placees dans une grille uniforme
  en dessous, avec le contenu, le theme et les interactions existants.

## Theme et navigation de la carte Servers

- Restauration du survol violet, de l'ombre, de la transition et du focus clavier
  existants sur la carte Servers du dashboard.
- Destination unique Servers & libraries pour toute la carte, y compris les
  lignes des serveurs ; les fiches restent accessibles depuis la page Servers.

## Formulaire serveurs, dashboard et monitoring ARR

- URL de creation au format URL, exemple adapte au type de serveur et champs
  de secret en `new-password` pour limiter l'autoremplissage de connexion.
  Oeil de visibilite du token restaure dans les deux variantes du formulaire.
- Verification de connexion avant insertion : un serveur inaccessible est refuse.
  Un serveur confirme est enregistre immediatement online, avec sa version.
- Dashboard : presentation commune pour tous les types, carte Servers cliquable
  et liens individuels vers les fiches, y compris avec un seul serveur.
- Monitoring ARR distinct des lectures : collecte periodique de disponibilite,
  temps de reponse API, taille de file et alertes de sante ; courbes par instance
  de disponibilite et de file sur la periode choisie. Affichage conditionnel par
  type ; valeurs inconnues conservees, historique retenu 366 jours et nettoye
  lors de la suppression de la connexion.
- Validation : 131 tests reussis des serveurs, connexions et monitoring ARR,
  monitoring media, dashboard et schema monitoring ; verification du rendu
  des liens et courbes conditionnelles. Aucun serveur reel modifie.
- Nouvelle table et index `arr_monitoring_samples`, ajoutes au bootstrap existant
  et au schema initial. L'historique commence au deploiement de cette version.

## Connexions Sonarr et Radarr

- Ajout des types Sonarr/Radarr dans Servers & libraries : plusieurs instances,
  URL de base et cle API dans le stockage chiffre existant ; edition et suppression
  locales reutilisees. La cle vide conserve le secret existant lors de l'edition.
- Controle authentifie via `/api/v3/system/status` avec `X-Api-Key`, timeout,
  refus des redirections, verification du type d'application et version.
  Le controle periodique reutilise `check_servers`, sans synchronisation de
  comptes ou de bibliotheques Plex/Jellyfin pour ces types.
- Dashboard > Servers et Monitoring > Servers : cartes Sonarr/Radarr dediees,
  conditionnees a la presence d'instances, avec statut, URL, version et date du
  dernier controle ; aucune cle transmise aux cartes et aucun compteur de lecture.
- Validation : 137 tests reussis (connexions API et cartes conditionnelles,
  serveurs, monitoring, dashboard, stockage chiffre, auto-enable et routes).
  Six templates verifies syntaxiquement. Aucun serveur reel modifie.
- Traductions dans les cinq langues. Le futur parcours de demandes du portail
  est documente au TODO ; les connexions sont disponibles pour sa mise en place.

## Nettoyage de la feuille de route

- Regroupement des validations apres deploiement (communications, monitoring,
  Jellyfin, dashboard, portail et expiration), sans les considerer comme terminees.
- Fusion des exigences de desactivation automatique Jellyfin et de renouvellement ;
  clarification de la suppression manuelle native encore a ajouter et de l'edition
  des politiques au-dela du champ `IsDisabled` deja gere manuellement.
- Conservation des etudes et audits ouverts, avec references aux fonctions
  existantes pour eviter les doublons. Aucun changement fonctionnel.

## Desactivation manuelle des comptes Jellyfin

- Fiche utilisateur Jellyfin : desactivation/reactivation explicite d'un compte
  sur un serveur precis, avec nom du compte et du serveur, aide et traductions
  dans les cinq langues. La fiche VODUM et les bibliotheques sont conservees.
- Lecture native avant ecriture, conservation des autres champs de politique,
  relecture de confirmation et mise a jour du snapshot local apres confirmation.
  Protection des administrateurs locaux et natifs, ciblage par compte lie a la
  fiche, route POST admin et jeton CSRF. Repetition sans ecriture si deja applique.
- Journalisation des identifiants et du resultat, sans reponse provider ni secret.
- Validation : 14 tests de l'action, du rendu multilingue, des scopes de routes
  et de la protection CSRF. Aucun compte reel modifie.
- La politique automatique de fin d'abonnement et la provenance des blocages
  restent au TODO ; cette action est strictement manuelle.

## Reprise du TODO et portee du scan Jellyfin

- Controle des briques existantes pour le premier lot : acces, suppression native
  apres expiration, suppression locale, reprises et lecture du statut Jellyfin.
  TODO precise pour reutiliser ces fonctions et distinguer les actions manuelles
  encore absentes ; retrait des lignes terminees deja tracees ici.
- Menu des bibliotheques : Jellyfin indique avant execution que le scan concerne
  toutes les bibliotheques du serveur, dans les cinq langues. Le message de
  succes existant et le scan Plex cible sont conserves.
- Validation : 12 tests du refresh et des requetes de la page serveurs reussis.
  Aucune operation native executee sur les comptes ou serveurs reels.

## Traductions et comptage des spectateurs

- Ajout du libelle historique `expiration_date_change` dans les cinq langues.
- Monitoring > Servers : deduplication des spectateurs par utilisateur VODUM
  entre serveurs, resolution des sessions sans identifiant interne et separation
  des identifiants externes par serveur pour eviter les collisions.
- Libelle explicite « Spectateurs sur la periode » : personnes ayant regarde du
  contenu sur la periode choisie, distinctes des utilisateurs actuellement actifs
  affiches sur le dashboard. Les anciens spectateurs restent dans l'historique.
- Validation : 7 tests reussis (monitoring des serveurs et historique des
  communications), dont un cas SQLite avec plusieurs serveurs et sessions live.

## Traductions de l'historique des communications

- Traduction des filtres, du titre et de l'aide, des notifications en attente,
  des tentatives et de leur prochaine date dans les cinq langues disponibles.
- Libelles lisibles pour les modeles standards et historiques : lecture bloquee,
  changement de date d'expiration, suggestion d'abonnement, abonnement expire,
  rappels, parrainage et creation d'utilisateur. Meme traduction dans la fenetre
  de detail ; conservation des noms personnalises non reconnus.
- Validation : 22 tests des communications, avec rendu de l'historique et de
  sa file d'attente dans les cinq langues et conservation d'un nom personnalise.

## Monitoring et journalisation du portail utilisateur

- Nouvel onglet Monitoring > User portal, reserve aux administrateurs et
  disponible uniquement lorsque le portail est active. Periodes de 7, 30 et
  90 jours, connexions quotidiennes, utilisateurs actifs/en ligne, invitations
  d'amis et modifications de compte, graphiques et historique pagine.
- Tableau des utilisateurs avec nombre de connexions, derniere activite,
  invitations et modifications. Correction du lien vers les fiches utilisateurs
  (`user_detail`) qui provoquait une erreur de rendu avec des comptes presents.
- Evenements du portail visibles dans les logs admin sous `vodum.portal_audit` :
  connexions et deconnexions, consultations, modifications de profil/mot de passe,
  methodes de connexion, invitations et messages au support. Resultats succes,
  echec ou blocage ; aucun contenu de formulaire ni mot de passe journalise.
- Comptage des connexions a partir des sessions pour couvrir les fournisseurs
  sans doubler les evenements d'authentification. Ajout d'index pour les requetes
  par periode, et correction des types d'audit Jellyfin/Plex manquants.
- Validation : 129 tests portail, dont rendu complet avec utilisateurs,
  controle admin/portail desactive, agregats, pagination et erreurs de formulaire.
  Graphiques controles dans le navigateur avec donnees locales de test.
  L'historique depend des donnees conservees ; les nouvelles actions sont
  enregistrees a partir du deploiement.
