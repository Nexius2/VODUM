# Changelog

Changements depuis la derniere publication du 2026-10-09 (matin).

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
