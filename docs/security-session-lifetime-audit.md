# Audit de la duree et de la permanence des sessions

Date: 2026-08-30

## Politique verifiee

- `PERMANENT_SESSION_LIFETIME` vaut 12 heures par defaut et peut etre configuree
  avec `VODUM_SESSION_LIFETIME_HOURS`; la configuration refuse implicitement
  toute duree inferieure a une heure.
- Les connexions administrateur locales et Plex appellent toutes deux
  `open_admin_session`. Les connexions du portail appellent
  `open_portal_session`. Ces deux fonctions vident l'etat precedent, ouvrent un
  principal neuf et marquent ensuite la session Flask comme permanente.
- Les formulaires et preuves temporaires avant authentification ne rendent pas
  la session permanente. Fermer le navigateur peut donc les abandonner sans
  conserver une session de connexion longue duree.
- `SESSION_REFRESH_EACH_REQUEST` renouvelle l'echeance du cookie permanent sur
  les requetes actives. Les lignes serveur `admin_sessions` et
  `portal_sessions` appliquent la meme duree comme delai d'inactivite glissant.
  Leur date est reecrite au plus toutes les cinq minutes pour limiter les
  ecritures SQLite.
- Une session serveur expiree, revoquee, alteree ou associee a un compte portail
  devenu inutilisable est refusee meme si le cookie navigateur existe encore.

## Conclusion

Aucune vulnerabilite exploitable n'a ete confirmee. Le comportement est une
expiration glissante par inactivite, et non une duree absolue depuis la
connexion. Ce choix preserve les sessions d'administration actives tout en
imposant une nouvelle authentification apres la periode d'inactivite configuree.

## Tests

- expiration et renouvellement avec la duree configuree pour les sessions
  administrateur et portail;
- rejet des durees invalides et des dates corrompues;
- session non permanente avant authentification;
- session permanente apres connexion admin ou portail;
- suppression de l'etat pre-authentification lors de l'ouverture de session.
