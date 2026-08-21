# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines
sont documentes dans `changelog.md`.

Derniere mise a jour: 2026-08-21

## Principes de suivi

- Garder ici seulement les sujets encore utiles a traiter.
- Retirer une ligne quand elle est terminee et la tracer dans `changelog.md`.
- Prioriser les gains qui servent a la fois l'administration actuelle et la
  partie utilisateur exposee sur internet.
- Eviter les gros changements non valides sur la vraie base sans test terrain.

## P0 - Stabilisation et validation terrain

- [~] Valider sur une instance reelle le cycle Plex complet: invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.
- [~] Valider et renforcer la protection contre les pertes de donnees Plex sur
  instance reelle. Les garde-fous existent, il reste la validation terrain.
- [~] Valider les campagnes Migrations sur de grandes instances reelles Plex et
  Jellyfin, y compris les suppressions et restaurations d'acces, avant
  d'activer davantage d'automatisations destructives.

## P8 - Partie utilisateur et ouverture externe

- [ ] Valider manuellement l'authentification admin Plex sur une installation
  neuve et une installation existante : indisponibilite Plex, changement de
  compte, deliaison, connexion locale de secours et option de double 2FA.
- [ ] Valider manuellement la suggestion de serveurs depuis le wizard et la
  page Serveurs avec plusieurs serveurs possedes/partages, des connexions
  locales, publiques et relay, Plex indisponible et un serveur deja configure.
- [ ] Creer un acces web utilisateur configurable depuis un nouveau menu admin.
  - Login possible via compte admin, Plex, Jellyfin ou email standard.
  - Donner a l'utilisateur acces a son profil, son abonnement, les informations
    liees a son compte et son propre monitoring.
  - Gerer les roles et autorisations: admin, utilisateur et roles futurs.
  - Configurer le domaine ou lien d'acces.
  - Definir les regles d'acces, mots de passe, validations et zone support.
- [ ] Ajouter les possibilites Plex et Jellyfin encore manquantes, notamment
  l'edition du profil.
- [ ] Ajouter un mecanisme ou un lien de paiement aux profils utilisateurs.
- [ ] Ajouter une API publique apres cadrage: donnees exposees, objectifs,
  securite, quotas et authentification.
- [ ] Ameliorer la creation d'utilisateur et les emails d'invitation depuis
  l'espace web VODUM:
  - creation automatique, assistee ou controlee des comptes Plex/Jellyfin;
  - liens de telechargement des lecteurs media;
  - aide a la configuration du lecteur.

### Securite des acces publics

- [ ] Integrer Cloudflare Turnstile comme protection anti-automatisation
  optionnelle des formulaires publics.
  - Ajouter la configuration dans la modale de securite Settings, sous la 2FA,
    tout en gardant Turnstile independant de la 2FA.
  - Prevoir les modes compact et invisible, avec choix des formulaires
    proteges: connexion admin, reinitialisation du mot de passe et futurs acces
    utilisateurs.
  - Demander une Site Key et une Secret Key; masquer et chiffrer la Secret Key
    avec le mecanisme de secrets existant.
  - N'autoriser l'activation que lorsque la configuration est complete et
    proposer un test affichant clairement son etat de validite.
  - Valider chaque jeton cote serveur via l'endpoint Cloudflare `siteverify`,
    avec timeout court, controle du hostname et journalisation sans secret.
  - Definir explicitement le comportement en cas d'indisponibilite Cloudflare
    afin de ne pas verrouiller accidentellement toute l'administration.
  - Conserver les protections anti-bruteforce et 2FA existantes: Turnstile les
    complete et ne les remplace pas.
  - Prevoir un moyen de recuperation locale/admin en cas de cle ou de widget
    mal configure, ainsi que les traductions et ajustements CSP necessaires.

## Notes de prudence

- `GET /api/monitoring/poster/<server_id>` est une exception GET autorisee :
  proxy authentifie de posters et backgrounds avec cache local, declaree dans
  `tools/audit_get_routes.py`.
- Ne pas supprimer le cache artwork existant: il est utile et deja raccorde
  aux headers HTTP.
- Ne pas remplacer `sync` par `revoke` partout cote provider: Plex a
  volontairement un garde-fou contre sync vide.
- Les optimisations SQL doivent etre validees avec la vraie base et
  `EXPLAIN QUERY PLAN`; ajouter trop d'index peut ralentir les ecritures et le
  bootstrap.
- Les modifications de fichiers contenant du texte corrige doivent rester
  ciblees pour eviter de recreer du mojibake.
