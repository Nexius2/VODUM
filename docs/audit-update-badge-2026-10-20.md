# Controle du mecanisme de notification de mise a jour

Audit du code local du 20 octobre 2026, avec corrections et tests automatises.
Aucune modification de base reelle, execution du scheduler de production,
publication Docker ou installation de mise a jour.

## Chaine examinee

1. `utils/version.py` charge `VODUM_VERSION`, puis les chemins INFO connus,
   notamment `/app/INFO` et le fichier du projet. `app/app.py` conserve cette
   version au demarrage dans `APP_VERSION`, affichee dans la barre laterale.
2. `core/db_bootstrap_task_catalog.py` cree `check_update`, active par defaut,
   cron quotidien `0 4 * * *`. Le scheduler utilise l'heure de son processus.
   `core/tasks/runtime.py` demande aussi une execution au demarrage lorsque les
   crons et la tache sont actifs, sans doubler une execution deja en attente.
   Il s'agit d'une mise en file : un travail long peut retarder la verification.
3. `tasks/check_update.py` interroge le INFO de `Nexius2/VODUM`, branche `main`,
   via HTTPS, avec verification TLS par defaut et timeout Requests de 15 s.
   Ce timeout est un timeout reseau, pas un budget global strict du travail.
4. Comparaison numerique annee/mois/jour/build, apres normalisation du prefixe
   v et des separateurs/builds acceptes par le chargeur de version.
5. Publication de `update_status.json` a cote de la base definie par
   `DATABASE_PATH`. Aucun acces fournisseur depuis le rendu de page.
6. Le hook `inject_version` lit ce statut via `core/update_badge.py`, puis
   `templates/base.html` affiche UPDATE dans le pied de barre laterale.
   Couleur indigo avant 7 jours, rouge des 7 jours, pulsation des 30 jours.
7. Le cache est local au processus et invalide selon chemin et metadonnees du
   fichier. Le rendu est recalcule lors des requetes ; aucun polling dedie
   ne remplace le badge d'une page deja ouverte. Un rechargement complet suffit.

## Defauts confirmes et corriges

| Priorite | Constat initial | Correction et verification |
| --- | --- | --- |
| MEDIUM | La tache lit uniquement `/app/INFO`, contrairement a l'application et a `VODUM_VERSION`. | Chargeur commun ; test de variable et resolution INFO. |
| MEDIUM | Comparaison textuelle de repli pouvant annoncer a tort une version differente/invalide comme plus recente. | Comparaison numerique commune ; versions inconnues signalees en erreur, jamais presumees plus recentes. |
| MEDIUM | Une panne HTTP efface une mise a jour deja confirmee. | Derniere version connue de la meme source conservee et recomparee avec l'installation courante. Sans confirmation anterieure, aucun badge invente. |
| MEDIUM | Apres mise a niveau, un ancien statut peut continuer a afficher UPDATE jusqu'au prochain job. | Nouvelle comparaison dans le lecteur du badge avec `APP_VERSION`, y compris lorsque le fichier est en cache. |
| MEDIUM | Ecriture directe du JSON, visible partiellement par les lecteurs. | Fichier temporaire voisin et remplacement atomique, nettoyage sur erreur ; reprise courte et bornee des refus de remplacement Windows. Ancien fichier conserve en cas d'echec. |
| MEDIUM | Erreurs HTTP/JSON/ecriture absorbees, moteur de taches indiquant un succes. | Statut persiste avec erreur puis exception vers le moteur, qui utilise son traitement d'echec existant. Erreur de publication propagee. |
| LOW | Relance au demarrage recalculant toujours le prochain passage a 04 h. | Conservation du cron ou de l'intervalle configure. |
| LOW | Anciennete figee dans le cache et types JSON permissifs. | Age recalcule depuis la premiere detection sans reparsing ; booleen strict, duree negative/invalide bornee. |

La date de premiere detection est conservee tant qu'une mise a jour reste
necessaire, y compris si une autre version plus recente apparait. Elle est
reinitialisee lorsque l'installation est a jour ou que la source change.

## Limites et observations restantes

- MEDIUM : le signal suit `main/INFO`, pas une release ni la disponibilite de
  l'image Docker. `.github/workflows/docker-image.yml` construit et publie apres
  push sur main : le badge peut apparaitre avant la fin du build ou alors que
  celui-ci echoue. Aucun controle de registre n'a ete ajoute sans definir le
  canal de distribution cible.
- LOW : si le code change sans modification du VERSION dans INFO, aucune mise
  a jour n'est detectable. `create-container.sh` genere sa propre version locale
  par date/heure ; une construction locale plus recente peut donc masquer des
  changements distants. Une variable VODUM_VERSION incorrecte a le meme effet.
- LOW : les textes UPDATE et les infobulles sont en anglais et le badge n'est
  pas un lien d'installation. Les couleurs basees sur l'anciennete n'indiquent
  aucune severite de vulnerabilite ; le texte "critical delay" ne provient pas
  d'une analyse de securite. Rendu existant conserve pour cet audit technique.
- INFO : une erreur conserve un badge deja confirme et l'age continue a avancer,
  mais le badge ne montre pas l'etat de fraicheur de la verification. Consulter
  l'erreur de la tache, les logs ou le JSON pour distinguer confirmation recente
  et derniere version connue. Aucun bandeau supplementaire ajoute.
- INFO : cron desactive, tache desactivee ou file occupee peuvent retarder les
  controles ; aucun appel HTTP n'est ajoute sur les requetes utilisateur.
- INFO : apres remplacement d'une installation, redemarrer l'application pour
  charger la nouvelle APP_VERSION. Les anciens fichiers JSON sans version
  distante valide sont masques jusqu'a une verification concluante.

## Validation

- `tests/test_check_update.py` : comparaison, environnement/INFO, chaine tache
  vers badge/cache, version egale/ancienne, anciennete, panne reseau/HTTP,
  source differente, statut invalide, version locale inconnue, publication
  atomique concurrente et en erreur, source absente et rendu reel du bloc Jinja.
- `tests/test_update_badge.py` : cache, remplacement/suppression/recreation,
  JSON invalide, chemins independants, types et progression d'anciennete.
- `tests/test_update_check_runtime.py` : cron/intervalle personnalises, tache
  absente/desactivee/en cours/deja en file et refus de mise en file.
- `tests/test_task_execution.py` : non-regression du moteur de taches.

Requetes HTTP simulees pour des resultats deterministes. Le template du pied
de page est rendu dans les tests aux seuils 0/7/30 jours et sans mise a jour.
Le rendu visuel dans un navigateur de production, l'acces GitHub depuis le
conteneur et la publication reelle Docker restent a verifier apres deploiement.
