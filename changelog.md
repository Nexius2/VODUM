# Changelog

Changements depuis la derniere publication du 2026-10-09 (matin).

## Demarrage : detection des anciennes references de cles etrangeres

- Recherche des parents de tables legacy dans le schema SQLite au lieu d'un
  foreign_key_check global de toutes les donnees avant le bootstrap. Detection
  des suffixes _old, __rebuild et __rebuild_old, y compris tables vides et noms
  quotes ; aucun parcours des historiques necessaire pour cette detection.
- Verification complete conservee apres une reparation effective. Etapes de
  detection journalisees et sortie Python du bootstrap non tamponnee pour
  identifier un traitement lent avant le lancement de Waitress.
- Tests de detection et d'absence de lecture des donnees/ecriture valides ;
  demarrage Flask sur base temporaire valide avec 194 routes. Le blocage signale
  sur le conteneur reel n'a pas ete reproduit ; cause a confirmer avec les
  nouveaux logs ou la liste des processus du conteneur.

## Performances du suivi personnel du portail

- Statistiques personnelles chargees dans un snapshot SQLite commun aux
  periodes, historique, types de medias, serveurs, bibliotheques, courbe,
  lecteurs et IP. Lecture independante du verrou Python des ecritures.
- Requetes et regles conservees : isolation par utilisateur, deduplication,
  plafonnement des durees, pourcentages et masquage des IP. Autorisations
  de route inchangees ; aucune ecriture ajoutee.
- Comparaisons pendant transaction concurrente, utilisateur absent et
  regressions du suivi personnel validees.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 263,344 a 7,470 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --personal-monitoring`.
  Gain sur base representative toujours a mesurer.

## Performances des resumes Taches et Abonnements du dashboard

- Deux blocs de lecture isoles sur snapshots SQLite independants du verrou
  Python des ecritures. Execution des taches et gestion des abonnements inchangees.
- Ordre des prochaines taches, compteurs actifs/erreurs, exclusions des forfaits
  desactives, blocages sur sept jours et pourcentages/couleurs du graphique
  conserves. Resultats compares pendant transaction concurrente ; tables
  optionnelles absentes et absence d'ecriture testees.
- Benchmark synthetique des deux blocs, cinq repetitions avec ecriture de
  250 ms : mediane de 261,786 a 8,608 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --dashboard-summaries`.
  Gain sur base representative toujours a mesurer.

## Performances des suggestions de fusion

- Utilisateur et candidats lus dans un snapshot SQLite commun, independant du
  verrou Python des ecritures. Snapshot ferme avant le calcul des scores.
- Candidats, scores, classement et limites conserves ; action de fusion inchangee.
  Resultats compares pendant transaction concurrente, limites 0/1/sans limite
  et utilisateur absent testes, sans ecriture par le lecteur.
- Benchmark synthetique de la lecture (hors calcul des scores), cinq repetitions
  avec ecriture de 250 ms : mediane de 260,470 a 6,702 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --merge-candidates`.
  Gain sur base representative toujours a mesurer.

## Performances des politiques affichees sur la fiche utilisateur

- Identites et politiques actives de la fiche utilisateur lues dans un snapshot
  SQLite commun, independant du verrou Python des ecritures. Fonction reservee
  a l'affichage ; moteur d'application des restrictions inchange.
- Portee globale/utilisateur/serveur, filtrage du fournisseur, priorite,
  origine et valeurs affichees conserves. Comparaison pendant transaction
  concurrente et utilisateur absent testee, sans ecriture par le lecteur.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 262,339 a 6,733 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-policies`.
  Gain sur base representative toujours a mesurer.

## Performances du parrainage affiche sur la fiche utilisateur

- Contexte de parrainage et noms des comptes fusionnes charges sur snapshots
  SQLite independants du verrou Python des ecritures, pour l'affichage uniquement.
- Compteurs pending/qualified/rewarded, liste des filleuls, parrain de repli,
  tri et deduplication des noms conserves. Actions administratives inchangees.
- Comparaison pendant transaction concurrente et utilisateurs absents testees ;
  absence d'ecriture et contraintes referentielles verifiees.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 262,234 a 8,789 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-referrals`.
  Gain sur base representative toujours a mesurer.

## Message des demandes medias deja en recherche

- Message du portail reformule sans Sonarr/Radarr : le media est deja pris en
  charge par les outils de recherche et sera prochainement disponible en streaming.
  Texte harmonise dans les cinq langues et les fichiers de traduction legacy.

## Fiabilite de l'indicateur de mise a jour

- Version locale chargee par le meme mecanisme que l'application, avec prise
  en compte de VODUM_VERSION et des fichiers INFO hors conteneur.
- Comparaison numerique des formats de version reconnus ; statut invalide
  signale en erreur. Badge obsolete masque immediatement apres mise a niveau.
- Confirmation precedente conservee en cas de panne GitHub, pour la meme source,
  et recomparee avec la version installee. Erreurs visibles dans le moteur de
  taches, y compris echec de publication du statut.
- Publication atomique du JSON avec reprise bornee sous Windows et nettoyage
  des temporaires. Cache conserve, anciennete recalculee sans relecture JSON.
- Horaire personnalise de verification preserve lors de la relance au demarrage.
- Audit complet et limites de distribution documentes dans
  `docs/audit-update-badge-2026-10-20.md` ; tests de detection, erreurs, cache,
  concurrence, scheduler et rendu Jinja ajoutes.

## Performances des pages de communication

- Pages Campagnes et Modeles chargees chacune dans un snapshot SQLite en
  lecture seule, independant du verrou Python des ecritures.
- Listes, editeurs, traductions et metadonnees des pieces jointes conserves.
  Enregistrements, restauration des modeles et envois inchanges.
- Comparaisons pendant transaction concurrente, langues avec/sans traduction,
  selection absente/inexistante, modeles desactives, pagination et cas vides
  testes ; absence d'ecriture et contraintes referentielles verifiees.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 260,767 a 8,537 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --communication-pages`.
  Gain sur base representative toujours a mesurer.

## Performances du detail et de la configuration Communications

- Detail de l'historique et configuration charges sur des snapshots SQLite
  independants du verrou Python des ecritures. Lectures utilisees uniquement
  pour la consultation ; enregistrement et envois inchangees.
- Conservation du message archive et du rendu des anciens messages, des
  substitutions historiques, du masquage des trois secrets et des compteurs
  pending/error. Comparaisons pendant transaction concurrente et cas vides
  verifies, sans ecriture depuis les lecteurs.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 261,966 a 9,386 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --communication-details`.
  Gain sur base representative toujours a mesurer.

## Performances du tableau d'acces utilisateur

- Serveurs et bibliotheques de la fiche utilisateur charges dans un meme
  snapshot SQLite, independant du verrou Python des ecritures. Aucun snapshot
  ouvert quand les deux listes sont inutiles pour l'onglet consulte.
- Selection du compte le plus renseigne par serveur et droits bibliotheques
  issus de tous les comptes lies conserves. Lectures de profil/parametres et
  autres lectures partagees avec l'enregistrement inchangees.
- Comparaison pendant transaction concurrente pour trois utilisateurs et
  trois combinaisons de chargement ; identite absente, droits et absence
  d'ecriture verifies.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 262,973 a 7,247 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-access`.
  Gain sur base representative toujours a mesurer.

## Performances de l'historique des notifications utilisateur

- Compteurs et pages email/Discord de la fiche utilisateur lus dans un snapshot
  SQLite commun, independant du verrou Python des ecritures. Aucun snapshot
  ouvert lorsque l'historique est desactive pour l'onglet consulte.
- Isolation par utilisateur/canal, pagination independante, libelles de
  modeles/campagnes et metadonnees archivees conserves. Requetes et tri inchanges.
- Comparaison pendant transaction concurrente, pages hors limites/invalides,
  utilisateur absent, envois echoues et absence d'ecriture testes.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 260,329 a 7,423 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-notifications`.
  Gain sur base representative toujours a mesurer.

## Performances du dashboard : lectures en cours

- Sessions, compteurs et verification de la file de taches charges dans un meme
  snapshot SQLite en lecture seule, sans attendre le verrou Python des ecritures.
- Conservation de la limite de six sessions, des identites et du repli de
  trente minutes lorsque la file de taches est occupee.
- Tests : comparaison avec le parcours precedent, sessions absentes/anciennes,
  sessions manquantes et lecture des donnees commitees pendant une transaction.
- Benchmark synthetique local (cinq repetitions, verrou d'ecriture de 250 ms) :
  mediane de 262,767 ms a 7,179 ms, resultats identiques. Script reproductible :
  `tools/benchmark_dashboard_live_reads.py`. Gain reel a mesurer sur une base
  representative ; le prealable global de mesure du TODO reste ouvert.

## Performances du monitoring en direct

- Sessions, statistiques et serveurs des onglets Overview/Now playing lus dans
  un snapshot SQLite commun, independant du verrou Python des ecritures.
- Enrichissement et corrections des references artwork executes apres fermeture
  du lecteur, sur la connexion d'ecriture existante. Les autres onglets
  n'ouvrent pas de snapshot ; regles de repli et progression conservees.
- Comparaison des resultats, lecture pendant transaction non commitee et
  preservation des ecritures artwork testees. Benchmark synthetique local sur
  cinq repetitions avec ecriture de 250 ms : mediane de 261,163 a 6,837 ms
  pour la phase de lecture (hors artwork). Commande reproductible :
  `python tools/benchmark_dashboard_live_reads.py --monitoring`.
  Validation sur base representative toujours restante.

## Performances des evenements et filtres du monitoring

- Evenements recents Overview/Activity et utilisateurs du filtre Bibliotheques
  lus sur snapshots independants du verrou Python des ecritures.
- Requetes, ordre, limites, details JSON des series et libelles inchanges.
  Les onglets sans evenements n'ouvrent aucune connexion supplementaire.
- Comparaisons pendant transaction non commitee et regressions fonctionnelles
  validees. Benchmark synthetique local, cinq repetitions avec ecriture de
  250 ms : evenements de 262,586 a 6,379 ms ; filtre utilisateurs de 263,174
  a 6,743 ms. Resultats identiques ; mesure representative encore necessaire.
- Commandes : `python tools/benchmark_dashboard_live_reads.py --activity`
  et `python tools/benchmark_dashboard_live_reads.py --library-users`.

## Performances du rapport d'usage du portail

- Compteurs, chronologie, utilisateurs, evenements pagines et demandes medias
  charges dans un snapshot SQLite commun, independant du verrou des ecritures.
  Periodes, limites et calculs existants conserves.
- Resultats compares aux anciennes lectures pour 7/30/90 jours, valeurs de
  repli et pages hors limites ; cas vide, transactions concurrentes, compteurs
  de demandes et integrite SQLite testes. Les controles d'acces restent dans
  le parcours de route existant.
- Benchmark synthetique local avec 100 evenements, cinq repetitions et ecriture
  de 250 ms : mediane de 262,185 a 7,825 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --portal-usage`.
  Mesure sur base representative toujours necessaire.

## Performances du monitoring des politiques

- Neuf fonctions de lecture de l'onglet Politiques sur snapshots SQLite
  independants du verrou Python des ecritures. Catalogue, statistiques,
  regroupements, chronologie et pagination conservent leurs requetes et regles.
  Les actions et controles d'acces existants restent sur leur parcours actuel.
- Resultats compares aux anciennes lectures sur donnees presentes/absentes,
  identites natives, regles systeme/verrouillees et transaction concurrente ;
  absence d'ecriture par les lecteurs et integrite SQLite verifiees.
- Benchmark synthetique des neuf lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 260,858 a 23,856 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --policies`.
  Validation sur base representative toujours restante.

## Performances du monitoring Sonarr/Radarr

- Consultation des statistiques ARR sur un snapshot SQLite commun, sans attendre
  le verrou Python des ecritures. Collecte HTTP, insertion et purge conservees.
  Aucun snapshot ouvert lorsqu'aucun serveur ARR n'est fourni.
- Comparaison des six plages avec les lectures precedentes pendant transaction
  concurrente. Dernier releve (y compris egalite de date), valeurs nulles,
  serveur sans releve et exclusion Plex/Jellyfin des agregats verifies.
- Benchmark synthetique local, cinq repetitions avec ecriture de 250 ms :
  mediane de 261,492 a 7,249 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --arr`.
  Gain sur base representative toujours a mesurer.

## Performances des listes Serveurs et Bibliotheques

- Liste des serveurs, compteur et page de bibliotheques isoles sur des snapshots
  SQLite de lecture, sans attendre le verrou Python des ecritures.
- Conservation des requetes et compteurs distincts, des types normalises,
  des tris et de la pagination. Lectures de detail et actions inchangees.
- Comparaison des tris et directions (y compris valeurs de repli), pages vides,
  compteurs et resultats pendant transaction concurrente ; absence d'ecriture
  et contraintes referentielles verifiees.
- Benchmark synthetique des trois lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 262,269 a 11,078 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --server-pages`.
  Mesure representative toujours restante.

## Performances des fiches serveur

- Cinq fonctions de lecture (detail, bibliotheques, utilisateurs et compteurs)
  isolees sur snapshots SQLite independants du verrou Python des ecritures.
  Appels limites a l'affichage de la fiche ; mutations inchangees.
- Comparaison pendant transaction concurrente, isolation entre serveurs,
  deduplication des utilisateurs, pagination et serveur inexistant testees.
- Benchmark synthetique des cinq lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 261,696 a 13,753 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --server-detail`.
  Validation representative toujours restante.
- Controle supplementaire `test_sqlite_connection_policy.py` : un echec sur les
  connexions directes deja presentes dans `app/diagnose_stream_policies.py` et
  `app/core/backup.py`, hors fichiers modifies dans ce lot ; analyse distincte
  necessaire, notamment pour respecter la sauvegarde sur connexion dediee.

## Simplification du portail utilisateur

- Accueil, Mon profil et Acces aux medias regroupes dans un seul onglet
  Mon profil, affiche a l'entree du portail.
- Informations personnelles et reglages de connexion toujours visibles en tete
  de page, sans bandeau depliable ; statut en vignette compacte coloree pres du
  titre : vert actif, jaune preavis/invitation, orange rappel, rouge acces termine
  ou suspendu, gris pour les etats inconnus.
  Acces aux bibliotheques affiches ensuite.
- Cartes Abonnement, Serveurs & bibliotheques et Activite personnelle retirees
  de Mon profil pour eviter les informations en double.
- Anciennes adresses conservees et apercu administrateur aligne sur la page
  regroupee. Options de visibilite des fonctionnalites conservees.

## Mise a jour des dependances Python

- PlexAPI : 4.18.2 -> 4.18.3.
- pytz : 2026.3.post1 -> 2026.5.
- websocket-client : 1.9.0 -> 1.9.2.
- cryptography : 50.0.1 -> 50.0.2.
- Autres dependances deja sur les dernieres versions disponibles lors de la
  verification PyPI du 2026-10-09. Validation du conteneur a effectuer.
