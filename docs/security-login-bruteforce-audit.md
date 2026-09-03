# Audit de la protection anti-bruteforce des connexions

Date: 2026-08-30

## Perimetre et protections existantes

La connexion administrateur locale compte les echecs dans deux portees
independantes, l'IP cliente et l'email normalise. Le seuil, la fenetre, la duree
de verrouillage et le delai entre alertes sont configurables. Les comptes
inconnus suivent aussi une verification de hash couteuse afin de limiter les
differences temporelles.

La connexion locale du portail applique egalement un verrouillage par IP et par
email apres cinq echecs dans une fenetre de quinze minutes. Les valeurs de portee
du portail ne sont pas stockees en clair : la table contient uniquement une
empreinte SHA-256 separee par usage. Une connexion reussie efface les compteurs
de l'IP et du compte concernes.

Les flux Plex ne manipulent pas de mot de passe VODUM ou provider. Leur creation
de PIN et leurs etapes sensibles conservent les limites de requetes existantes.

## Finding corrige

### MEDIUM - Limitation Jellyfin uniquement globale par IP

- Comportement initial : `/portal/auth/jellyfin` possedait une limite de trente
  requetes par IP et par quinze minutes, mais aucun compteur par compte.
- Prerequis : portail Jellyfin active et possibilite d'envoyer des requetes de
  connexion depuis plusieurs adresses.
- Scenario : une attaque distribuee pouvait multiplier les essais sur un meme
  compte Jellyfin sans atteindre la limite propre a chaque IP.
- Impact : augmentation du nombre de tentatives de mot de passe envoyees au
  serveur Jellyfin et charge reseau/provider supplementaire.
- Correction : controle avant l'appel provider puis comptage des echecs par IP
  et par couple `server_id:username`. La portee compte est normalisee et hachee
  par le mecanisme existant; aucun nom Jellyfin n'est ajoute en clair a la table.
- Risque de regression : apres cinq erreurs, le compte Jellyfin vise est bloque
  quinze minutes dans VODUM, y compris si les tentatives venaient d'une autre IP.
  Une connexion valide efface les deux compteurs.
- Statut : corrige.

## Robustesse de la deconnexion

L'audit des tests a aussi confirme qu'une exception de base de donnees pendant
la revocation pouvait empecher Flask d'enregistrer la suppression du cookie.
La deconnexion capture maintenant cette erreur, la journalise et efface toujours
la session navigateur. La session serveur non revoquee reste bornee par son
expiration d'inactivite et sera de nouveau invalidee lorsque la base redevient
accessible.

## Tests

- seuil, fenetre, expiration et remise a zero des compteurs portail;
- portees IP et compte/email independantes;
- normalisation et stockage hache du compte Jellyfin;
- refus avant appel Jellyfin lorsqu'une portee est verrouillee;
- comptage des echecs Jellyfin dans les deux portees;
- suppression du cookie de session meme si la revocation DB echoue.
