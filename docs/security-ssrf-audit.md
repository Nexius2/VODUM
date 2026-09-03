# Audit SSRF des sorties HTTP

Date: 2026-08-31

## Conclusion

L'application doit pouvoir joindre des serveurs Plex, Jellyfin et generiques sur
le LAN. Ces destinations privees ne sont donc pas bloquees globalement. Elles
sont autorisees parce que leurs origines ont ete explicitement configurees par
un administrateur; les chemins et identifiants ajoutes par les utilisateurs ne
peuvent pas changer l'origine HTTP.

La session commune `ConfiguredHostSession` verifie maintenant l'origine de la
requete initiale ainsi que chaque redirection. Une requete vers une origine non
configuree, une URL relative ou un schema autre que HTTP(S) echoue avant tout
acces reseau. Les variantes `url`, `local_url` et `public_url` d'un meme serveur
restent autorisees, y compris les adresses LAN, loopback et IPv6 configurees.

## Inventaire et classification

- Plex/Jellyfin, artwork, synchronisation, presence, validation, portail et
  migrations: session bornee aux origines du serveur en base; `plex.tv` et
  `app.plex.tv` ne sont ajoutes que pour les flux Plex qui en ont besoin.
- Recherche d'illustrations du tableau de bord et ping de serveur generique:
  anciens appels directs raccordes a la session bornee pendant cet audit.
- Authentification et decouverte Plex: origines Plex constantes et allowlistees.
- Discord, verification de mise a jour, telemetrie et citation externe: URL de
  service constantes dans le code; aucun hostname issu d'une requete web.
- Geolocalisation IP: hostname constant `ip-api.com`; l'IP est d'abord analysee
  par `ipaddress`, et les adresses privees, loopback, link-local, reservees,
  multicast ou non specifiees ne sont jamais envoyees au service.
- Turnstile: endpoint Cloudflare constant.
- SMTP: hote configure par l'administrateur; ce n'est pas un proxy pilotable par
  un utilisateur et il est necessaire de conserver les relais locaux.
- `plex_get` et `plex_request`: helpers internes sans appelant actif; ils ne sont
  exposes par aucune route.

## Correction confirmee

Avant cet audit, `ConfiguredHostSession` bornait les redirections mais ne
refusait pas explicitement une URL initiale hors allowlist. Les appelants actifs
construisaient normalement cette URL depuis le serveur configure, ce qui rendait
l'exploitation directe non confirmee, mais la garantie de la couche partagee
etait incomplete. Le controle initial a ete ajoute au point central.

## Tests

`tests/test_http_security.py` couvre les ports implicites, IPv4 LAN, loopback,
IPv6, schemas invalides, origine initiale arbitraire, redirection same-origin et
redirection vers une origine interdite. La suite complete preserve les parcours
Plex/Jellyfin existants.
