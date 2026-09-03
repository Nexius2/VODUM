# Audit acces LAN, Internet et reverse proxy

Date: 2026-08-31

## Conclusion

La chaine de confiance separe correctement l'adresse du pair TCP et les
en-tetes transmis. `X-Forwarded-For`, `X-Forwarded-Proto` et
`X-Forwarded-Host` ne sont appliques que lorsque `VODUM_TRUST_PROXY` est actif
et que `REMOTE_ADDR` appartient a `VODUM_TRUSTED_PROXY_NETS`. L'application lit
ensuite uniquement `request.remote_addr`, deja normalise par le middleware, et
ne reparse pas directement les en-tetes fournis par le client.

Avec un seul proxy approuve, `x_for=1` retient l'adresse la plus a droite. Une
valeur locale ajoutee a gauche par un client ne remplace donc pas l'adresse
ajoutee par le reverse proxy. Les deploiements comportant plusieurs niveaux de
proxy doivent faire terminer la chaine par un proxy VODUM unique et renseigner
uniquement son reseau direct comme reseau approuve.

## Modes verifies

- Acces LAN direct: le filtre actif par defaut autorise loopback et les plages
  RFC1918; les en-tetes forwarded sont ignores.
- LAN via proxy approuve: l'adresse client transmise est soumise a
  `VODUM_ALLOWED_NETS`.
- Internet via proxy approuve: necessite de desactiver explicitement le filtre
  IP ou d'autoriser les plages voulues; l'authentification reste obligatoire.
- Source ou proxy non approuve: tous les en-tetes forwarded sont ignores.
- HTTPS termine au proxy: `X-Forwarded-Proto=https` produit cookies Secure et
  HSTS seulement lorsque le pair est approuve.
- Host du portail: doit correspondre au hostname de `portal_public_url`; le
  parseur gere maintenant correctement hostname, port et IPv6.

## Host header

Le portail possede une origine publique configuree et rejette un autre Host.
L'administration conserve volontairement les Host LAN/IP variables pour ne pas
casser l'acces direct. Les callbacks Plex sont lies a un etat de session a usage
unique; une modification de Host ne permet pas a un autre navigateur de
consommer le flux. Une allowlist globale d'Host n'est donc pas imposee sans
nouveau reglage d'URL administrative.

## Configuration sure

`VODUM_TRUSTED_PROXY_NETS` doit contenir seulement l'adresse ou le sous-reseau
du proxy qui se connecte directement a VODUM, jamais une plage cliente large.
Pour une exposition publique, HTTPS doit terminer sur ce proxy et
`VODUM_TRUST_PROXY=1` doit etre utilise avec ce reseau restreint.
