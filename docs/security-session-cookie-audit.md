# Audit des cookies de session LAN et reverse proxy HTTPS

Date: 2026-08-30

## Comportement verifie

VODUM utilise `VodumSessionInterface` pour concilier deux modes d'acces qui ont
des exigences differentes : l'acces HTTP direct sur le LAN et la publication
HTTPS derriere un reverse proxy.

- `HttpOnly` reste actif dans les deux modes et interdit l'acces normal au cookie
  depuis JavaScript.
- En HTTP LAN direct, l'attribut `Secure` est retire afin que le navigateur puisse
  renvoyer le cookie. Une configuration `SameSite=None`, invalide sans `Secure`,
  est ramenee a `SameSite=Lax` pour cette reponse.
- En HTTPS direct, ou lorsque `ConditionalProxyFix` accepte les en-tetes d'un
  pair appartenant a `VODUM_TRUSTED_PROXY_NETS`, le cookie conserve `Secure` et
  la politique SameSite configuree.
- Un pair non approuve ne peut pas rendre la requete securisee en forgeant
  `X-Forwarded-Proto: https`; ses en-tetes forwarded sont ignores.
- Les sessions authentifiees sont permanentes et le cookie contient donc une
  echeance conforme a `PERMANENT_SESSION_LIFETIME`.

Le demarrage du flux Plex est la seule adaptation ciblee : `SameSite=Strict` est
temporairement emis en `Lax` afin que le cookie d'etat accompagne le retour GET
depuis Plex. Les autres routes conservent la valeur configuree.

## Conclusion

Aucune vulnerabilite exploitable n'a ete confirmee et aucune modification du
code de production n'est necessaire. L'acces LAN ne peut pas offrir la
confidentialite transport de HTTPS; le mode public doit donc rester publie en
HTTPS avec les cookies securises et uniquement derriere des proxies explicitement
approuves.

## Regressions ajoutees

- cookie HTTP LAN : `HttpOnly`, `SameSite=Lax`, expiration, sans `Secure`;
- cookie via proxy HTTPS approuve : `HttpOnly`, `SameSite=None`, expiration et
  `Secure`;
- tentative de spoofing HTTPS par un pair non approuve : absence de `Secure` et
  repli `SameSite=Lax`.
