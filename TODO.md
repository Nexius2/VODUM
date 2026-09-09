# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines sont
documentes dans `changelog.md`.

Derniere mise a jour: 2026-09-07

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

## P0 - Corrections Jellyfin a traiter en priorite

- [ ] Valider sur une instance representative la creation, la modification et
  la migration des mots de passe Jellyfin : connexion avec le nouveau secret et
  refus de l'ancien. Correction du 07/09 : `NewPw` avec `ResetPassword=false` ;
  `true` selectionnait une reinitialisation ignorant le mot de passe fourni.
  Si la version intermediaire a ete utilisee, verifier les comptes concernes.
- [ ] Valider la coupure de lecture sur plusieurs clients Jellyfin (web, TV,
  mobile) en DirectPlay, DirectStream et transcodage. Les regressions corrigees
  le 07/09 couvrent l'echec du message avant coupure groupee, les reponses
  invalides, les redirections HTTP, le ciblage devenu obsolete et la confirmation
  tardive. La cause exacte du signalement sur l'installation reste a confirmer.
  Relever version/client, capacites de controle et resultat reel ; un client
  ignorant Stop doit rester en echec, sans desactivation ou revocation implicite.

## P1 - Cycle de vie des utilisateurs et fins d'abonnement

- [ ] Cartographier et clarifier les choix existants avant toute extension :
  suppression locale manuelle, `expiry_mode` (`none`, `warn_only`,
  `warn_then_disable`, `disable`), delai `warn_then_disable_days`, reglage
  `delete_after_expiry_days`, exceptions et renouvellement. Verifier le traitement
  effectivement branche a chaque reglage, pas seulement son libelle.
- [ ] Pour Jellyfin, proposer trois actions natives distinctes : retirer les
  acces aux bibliotheques, desactiver/reactiver le compte, supprimer le compte
  du serveur. Garder separee la suppression de la fiche VODUM. Preciser le
  compte et les serveurs cibles ainsi que les effets sur les donnees natives.
- [ ] Etudier le choix de l'action Jellyfin en fin d'abonnement, avec son delai,
  sans transformer le retrait d'acces actuel en desactivation ou suppression.
  Conserver les choix existants et proteger proprietaires/administrateurs.
- [ ] Prevoir le renouvellement et les reprises : ne reactiver que les comptes
  desactives par la politique concernee, conserver un blocage manuel et les
  droits anterieurs ; ne pas recreer silencieusement un compte supprime.
- [ ] Etudier la suppression cote Plex en tenant compte des recherches deja
  infructueuses : distinguer retrait du partage serveur, relation d'amitie,
  invitation, Plex Home et traces historiques PMS. Qualifier les pistes
  `removeFriend`/`removeHomeUser` uniquement selon le perimetre choisi ; elles
  ne garantissent pas qu'un utilisateur cesse d'etre connu de Plex et peuvent
  depasser un seul serveur. Ne promettre aucune purge totale non demontree,
  ni modifier directement la base PMS pour masquer une identite.
- [ ] Verifier les effets apres synchronisation et renouvellement, sur plusieurs
  serveurs du meme proprietaire et dans un environnement mixte. Distinguer
  compte sans acces, compte encore reference et compte supprime ; etudier un
  masquage/exclusion d'import VODUM si necessaire, sans le presenter comme
  une suppression native Plex.

## P2 - Administration native a etudier

### Utilisateurs, appareils et invitations

- [ ] Etendre la fiche Jellyfin aux politiques natives : visibilite, droits
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
- [ ] Clarifier la portee du refresh Jellyfin : l'action actuelle lance un scan
  de tout le serveur (`/Library/Refresh`), meme depuis une bibliotheque precise.
  Verifier le libelle et le retour utilisateur. Etudier un ciblage seulement
  s'il est valide ; `/Items/{id}/Refresh` concerne les metadonnees et ne prouve
  pas l'existence d'un scan equivalent par bibliotheque. Ne pas rouvrir le bug
  du bouton refresh deja corrige.

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
- [ ] Clarifier la documentation : secrets chiffres dans la base, mais archive
  complete non chiffree et autonome. Tester la restauration sur une instance
  neuve, sans dependance obligatoire a un secret reste sur l'ancien serveur.
- [ ] En option seulement, etudier la protection des exports/copies hors serveur
  (stockage chiffre ou chiffrement avec secret de recuperation separe), avec
  procedure de restauration testee. Conserver la restauration locale simple.

## Portail utilisateur et validation avant publication

- [ ] Ajouter l'historique des abonnements lorsqu'un modele de donnees dedie sera
  disponible.
- [ ] Executer la checklist manuelle de publication sur une instance representative
  derriere le reverse proxy HTTPS reel avant toute activation sur Internet.

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
