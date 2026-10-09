# Rafraichissement incremental des statistiques quotidiennes

La tache materialize_monitoring_daily_stats reconstruisait 31 jours a chaque
execution. Elle reconstruit maintenant les jours manquants ou dont les sources
ont change. Aucun historique source n'est supprime ou transforme par ce lot.

## Invalidation et reprise

Le bootstrap ajoute deux compteurs persistants (revision par jour et revision
globale des identites), deux colonnes de revision dans monitoring_daily_stats
et neuf triggers. Les anciennes lignes ont une revision -1 et sont donc
reconstruites au premier passage. Installation verifiee sur schema neuf et
installation repetee ; la creation des triggers ne parcourt pas l'historique.

Les insertions, corrections et suppressions d'historique invalident leur jour.
Un deplacement invalide l'ancien et le nouveau jour. Les triggers couvrent les
ecritures du collecteur, imports et purges, y compris les actions de cles
etrangeres. Les modifications de champs non utilises par les agregats ne
declenchent pas de recalcul. Les renommages, associations, creations et
suppression d'identites invalident conservativement toute la fenetre.

La revision est lue avant l'historique et enregistree avec le resultat. Une
mutation intervenant pendant le calcul laisse une divergence de revision :
le jour sera repris, sans perdre le signal de changement. Une exception laisse
les jours restants a recalculer. Les triggers participent a la transaction
source, et un rollback annule aussi l'invalidation. Aucune longue transaction
supplementaire ne verrouille l'historique pendant les calculs Python.

Une lecture des agregats verifie couverture et revisions ; un resultat perime
declenche le repli deja existant sur l'historique. Les caches de la vue d'ensemble
gardent leur TTL actuel (jusqu'a 120 secondes) : ce lot n'ajoute pas une
invalidation immediate des valeurs deja en cache.

## Mesures reproductibles

Commande depuis la racine : `.venv/Scripts/python.exe tools/benchmark_daily_stats.py`.
Base SQLite synthetique en memoire, 31 000 sessions, 31 jours, cinq executions.
Comparaison du recalcul complet avec le rafraichissement incremental, un jour
modifie avant chaque execution. La comparaison porte sur toutes les donnees
des agregats (hors computed_at), pas seulement sur les compteurs.

| Parcours | Mediane | Jours recalcules |
| --- | ---: | ---: |
| Recalcul complet | 281,001 ms | 31 |
| Incremental, un jour modifie | 8,723 ms | 1 |
| Aucun changement, un passage | 0,072 ms | 0 |

Mesure distincte de 5 000 insertions en lot : 4,758 ms sans suivi, 12,781 ms
avec suivi, soit environ 8 ms supplementaires. Ces mesures incluent les
commits SQLite en memoire ; elles ne representent pas le cout disque reel.

Ce benchmark ne mesure ni les p95/p99 des routes, ni la file Waitress, ni une
base de production ou la concurrence de plusieurs utilisateurs. Le premier
remplissage et les changements d'identite necessitent encore un recalcul de
la fenetre. Les compteurs par jour persistent pour eviter de perdre une
invalidation tardive ; leur nombre depend du nombre de jours d'historique,
pas du nombre de sessions.

## Verification

Tests fonctionnels : deduplication, plafonnement du temps regarde, union des
spectateurs, jours inchanges sans lecture d'historique, import tardif,
correction, deplacement, suppression, changement d'identite, configuration de
schema repetee, anciennes revisions, mutation pendant calcul et rollback.
Les regressions de monitoring, dashboard, bootstrap et lectures SQLite
isolees sont executees separement. Validation sous charge representative reste
ouverte dans le TODO.
