# Audit de la confiance TOTP locale

Date: 2026-08-29

## Perimetre

Emission, signature, duree, attributs HTTP, validation et restriction reseau du
cookie `vodum_local_2fa_trust` qui permet de ne pas redemander le TOTP pendant
trente jours sur un acces local explicitement autorise.

## Finding corrige

### LOW - Classification locale trop large et dependante de Python

- Fichier: `app/core/auth_local_trust.py`.
- Comportement initial: la decision utilisait `ipaddress.is_private`, dont la
  semantique inclut aussi diverses plages reservees et peut evoluer entre versions.
- Exploitabilite: theorique; il faudrait qu'une requete issue d'une plage reservee
  soit routable jusqu'a VODUM ou qu'un proxy de confiance relaie cette adresse,
  ainsi que posseder un cookie signe valide.
- Impact: suppression indue du second facteur pour un detenteur du cookie.
- Correction: allowlist explicite RFC1918 et IPv6 ULA, completee uniquement par
  les proprietes loopback et link-local.
- Risque de regression: faible; les acces LAN documentes restent acceptes.
- Statut: corrige.

## Protections confirmees

- Jeton signe et horodate avec la cle de session Flask et un sel dedie.
- Duree maximale de trente jours verifiee cryptographiquement et cote cookie.
- Liaison a l'email administrateur normalise et a l'empreinte du secret TOTP
  chiffre stocke; un changement d'email, une rotation ou une suppression du
  secret invalide donc immediatement le jeton existant.
- Cookie `HttpOnly`, `SameSite=Lax` et `Secure` lorsque la requete est HTTPS.
- Derriere un reverse proxy, HTTPS n'est reconnu qu'apres validation du proxy
  source par la couche de confiance conditionnelle existante.
- En HTTP LAN direct, le cookie ne peut pas etre `Secure` car le navigateur ne le
  renverrait plus; ce compromis est explicite et la fonctionnalite reste limitee
  aux adresses locales.
- Un cookie invalide, expire, externe ou mal signe retombe simplement sur la
  demande TOTP normale.

La configuration generale des cookies et la detection HTTPS restent suivies dans
leurs lignes d'audit dediees.
