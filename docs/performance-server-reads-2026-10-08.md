# Lectures independantes de Monitoring > Servers

Audit de load_monitoring_server_context et load_monitoring_servers_tab : toutes
les operations SQL sont des SELECT. Le chargement des ressources lit les
collectes en base ; il ne contacte pas les fournisseurs. L'application des
ressources ne modifie que les dictionnaires du resultat. Aucun parcours
d'ecriture, controle d'acces ou reparation d'artwork n'est deplace.

Les deux fonctions utilisent maintenant isolated_read_operation : connexion
SQLite mode=ro et query_only, transaction de lecture et fermeture garantie.
La liste des serveurs conserve son dechiffrement. Les neuf requetes de
statistiques de l'onglet partagent un snapshot coherent et ne tiennent plus
le verrou Python de la connexion d'ecriture. Aucune requete ni aucun template
n'est modifie ; le cout SQL sans contention reste sensiblement le meme.

## Verification et mesure

90 tests passes : 79 tests monitoring et 11 tests de lectures SQLite isolees.
Comparaison avant/apres pour all, 7d, 1m, 6m, 12m et plage invalide ; contextes
servers, overview et history ; absence d'ecriture, integrite SQLite et
dechiffrement. Le test de verrou occupe verifie aussi all et 7d.

Commande locale : `.venv/Scripts/python.exe tools/benchmark_monitoring_server_reads.py`.
Base temporaire sur disque en WAL, transaction d'ecriture concurrente borne a
250 ms, cinq executions. La transaction modifie un marqueur hors statistiques ;
les resultats complets sont compares. Mediane 261,796 ms avec la connexion
partagee contre 9,182 ms avec le snapshot independant.

Ce scenario isole l'attente du verrou. Il ne predit pas la latence d'une base de
production, le debit des jobs ou les p95/p99 de routes sous charge. Les
lectures peuvent toujours attendre une contention SQLite externe ou le disque.
Les identifiants et mesures des serveurs restent des donnees lues au debut de
chaque operation ; aucune autorisation n'est mise en cache.

Le schema reste identique pour ce lot. Les ecritures et leurs transactions
conservent la connexion et le verrou existants. Les autres parcours, notamment
Usage risk hors dashboard, doivent encore etre audites car ils peuvent
enregistrer des recommandations pendant une consultation.
