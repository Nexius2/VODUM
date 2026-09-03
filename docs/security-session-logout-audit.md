# Audit de l'invalidation des sessions a la deconnexion

Date: 2026-08-29

## Finding corrige

### HIGH - Rejeu d'une copie du cookie admin apres deconnexion

- Comportement initial: `/logout` effacait le cookie dans le navigateur, mais les
  sessions Flask admin etaient entierement autonomes et signees cote client.
- Prerequis: avoir copie le cookie admin avant sa deconnexion, par exemple apres
  compromission du navigateur ou d'un transport HTTP LAN.
- Exploit confirme par analyse: une copie correctement signee ne dependait
  d'aucun etat serveur et restait donc acceptee jusqu'a son expiration.
- Impact: maintien d'un acces administrateur apres une deconnexion volontaire.
- Correction: chaque nouvelle connexion cree une ligne `admin_sessions` avec un
  jeton aleatoire dont seule l'empreinte est stockee. Le principal contient la
  reference et le jeton; le garde global les valide sur chaque requete admin.
  Logout revoque la ligne courante avant d'effacer la session navigateur.
- Les anciens cookies sans reference serveur sont refuses afin de ne pas conserver
  une fenetre de rejeu; les administrateurs connectes devront se reconnecter une
  fois lors du deploiement de cette migration.
- Risque de regression: une lecture DB supplementaire par requete admin et une
  reconnexion unique apres mise a jour. Les autres navigateurs ne sont pas revoques.
- Statut: corrige.

## Portail utilisateur

Le portail possedait deja une session opaque cote serveur. La deconnexion marque
sa ligne `portal_sessions` comme revoquee puis efface le cookie. Les tests
confirment maintenant explicitement les deux effets.

## Tests

- validite d'une nouvelle session admin puis rejet apres revocation;
- rejet d'un mauvais jeton et d'une session expiree;
- bootstrap idempotent de `admin_sessions`;
- rejet et effacement d'un principal admin sans session serveur;
- revocation et effacement de la session portail.
