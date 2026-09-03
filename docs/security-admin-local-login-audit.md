# Audit de la connexion administrateur locale

Date: 2026-08-29

## Perimetre

Flux examine: `GET /login`, `POST /login/submit`, creation du principal
administrateur, redirection apres connexion et protections transversales appliquees
par l'application.

## Protections confirmees

- Le formulaire de connexion utilise POST et le controle CSRF global.
- L'email est normalise avant comparaison et les erreurs visibles restent generiques.
- Le mot de passe est verifie avec le hash Werkzeug configure.
- Les echecs sont limites independamment par adresse IP et par email.
- Lorsque la 2FA est active, le TOTP est verifie seulement apres le mot de passe.
- La confiance TOTP locale est signee, liee a l'administrateur et au secret TOTP,
  limitee aux clients locaux, et expiree.
- Une connexion reussie vide l'ancienne session avant de creer un principal explicite;
  seule la langue choisie est preservee.
- La destination `next` passe par la validation des redirections locales.

## Finding corrige

### LOW - Enumeration temporelle de l'email administrateur

- Fichier/fonction: `app/routes/auth.py`, `login_submit`.
- Comportement initial: un email incorrect etait rejete avant tout calcul de hash,
  tandis que l'email correct declenchait une verification de mot de passe couteuse.
- Prerequis: repetitions distantes et mesures statistiques de latence suffisamment
  precises; aucune exploitation n'a ete confirmee sur une instance publique.
- Impact: confirmation theorique de l'adresse administrateur, sans contournement
  d'authentification.
- Correction: verification d'un hash factice pour les emails inconnus, avec un seul
  chemin de decision visible et conservation des compteurs existants.
- Risque de regression: faible; cout CPU volontairement identique a une tentative
  portant sur le bon email et toujours borne par l'anti-bruteforce.
- Tests: verification que les chemins connu et inconnu executent exactement une
  verification de hash et utilisent respectivement le hash stocke et le hash factice.
- Statut: corrige.

## Points suivis separement

Les audits Plex, TOTP/enrolement, cookie de confiance, duree de session, attributs
de cookie et invalidation de deconnexion restent des elements distincts du TODO et
ne sont pas declares termines par ce rapport.
