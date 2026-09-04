# Changelog

## 2026-08-31 - Liens externes de renouvellement du portail

- La piste d'integration directe aux API de paiement a ete abandonnee: VODUM ne
  stocke aucun credential marchand et ne cree ni transaction ni webhook.
- L'administrateur peut activer et organiser une liste compacte de liens HTTPS
  externes avec libelle, texte de bouton et instructions.
- La page Abonnement affiche les liens applicables avec un avertissement clair:
  le paiement est externe et le renouvellement reste valide manuellement.
- La devise affichee reste l'unique `subscription_currency` des reglages
  d'abonnement; aucun second reglage divergent n'est cree.

## 2026-08-31 - Audit securite backup et restauration

- Les archives refusent maintenant chemins malveillants POSIX/Windows, doublons,
  symlinks, fichiers speciaux et membres ZIP chiffres avant toute extraction.
- Le rollback post-restauration couvre desormais les pieces jointes avec la base
  et la cle de chiffrement.
- Une base restauree sans cle embarquee doit prouver que tous ses secrets sont
  compatibles avec la cle active avant le remplacement.
- Les telechargements sensibles sont `private, no-store` et l'API de liste ne
  divulgue plus les chemins locaux.

## 2026-08-31 - Audit des secrets et cles persistantes

- Une cle de chiffrement manquante n'est plus regeneree lorsqu'une base ou son
  WAL contient deja des credentials chiffres; le demarrage exige la restauration
  de la cle correspondante.
- La creation initiale de `vodum.encryption_key` est atomique et restrictive.
- La migration chiffre aussi les anciens secrets TOTP administrateur et
  Turnstile encore stockes en clair.
- Le filtre de logs neutralise maintenant explicitement mots de passe, secrets
  et cles API en plus des tokens et autorisations.

## 2026-08-31 - Audit LAN et reverse proxy

- La confiance des en-tetes forwarded, le filtre IP, HTTPS, les cookies Secure,
  HSTS et Host ont ete testes ensemble en acces direct et via proxy.
- Le controle de hostname du portail gere maintenant correctement les adresses
  IPv6 avec port.
- Les reseaux prives restent autorises par defaut; un proxy non approuve ne peut
  influencer ni l'adresse cliente, ni le schema HTTPS, ni Host.

## 2026-08-31 - Audit SSRF et origine des sorties HTTP

- La session HTTP des serveurs refuse maintenant toute requete initiale et toute
  redirection vers une origine non configuree.
- Les adresses LAN, loopback et IPv6 restent utilisables lorsqu'elles appartiennent
  explicitement aux URL du serveur configure.
- La recherche d'illustrations du tableau de bord et le ping des serveurs generiques
  utilisent desormais la session HTTP bornee commune.
- Un rapport d'inventaire et quatre tests de regression documentent la garantie.

## 2026-08-30 - En-tetes HTTP et CSP progressive

- Verification automatisee de HSTS sur HTTPS, `nosniff`, protection frame,
  Referrer-Policy et Permissions-Policy sur les reponses HTTP.
- Correction de la CSP stricte du portail : les deux comportements JavaScript
  inline encore presents ont ete externalises dans un asset `self`, ce qui evite
  leur blocage par le navigateur sans ajouter `unsafe-inline` aux scripts.
- Ajout de `object-src 'none'` et confirmation de la CSP d'enforcement et du
  `Cache-Control: no-store` sur les pages et API du portail.
- L'administration reste sans CSP d'enforcement jusqu'a externalisation de ses
  handlers inline; les autres en-tetes defensifs restent appliques globalement.

## 2026-08-30 - Audit XSS des rendus administrateur et portail

- Revue des contournements d'echappement Jinja, du HTML genere en Python et des
  sinks DOM dans le JavaScript applicatif, hors bibliotheques vendor minifiees.
- Confirmation que les valeurs utilisateur/provider, medias, serveurs, logs,
  communications, erreurs et imports sont echappees avant insertion HTML ou
  affectees avec `textContent`.
- Suppression du dernier `|safe` Jinja, inutile car il ne servait qu'a afficher
  des fleches de tri constantes.
- Ajout de regressions avec charges hostiles sur le seul filtre Python retournant
  `Markup`, qui echappe ses attributs et son texte visible.

## 2026-08-30 - Audit global CSRF et methodes HTTP

- Extraction du garde CSRF global dans un module de securite dedie, toujours
  enregistre directement par la fabrique Flask avant les modules de routes.
- Suppression d'exemptions techniques inutiles : toutes les requetes POST, PUT,
  PATCH et DELETE exigent maintenant sans exception un jeton de session valide.
- Ajout de regressions pour les formulaires et requetes JSON, les jetons absents,
  vides ou incorrects et chacune des quatre methodes mutantes.
- Extension de l'audit statique des GET a toute l'application; aucune mutation
  persistante non revue n'est detectee. Le proxy artwork authentifie et son cache
  local restent l'unique exception documentee.

## 2026-08-30 - Audit de non-enumeration du compte administrateur

- Confirmation que les emails administrateur connus et inconnus recoivent la
  meme erreur generique, la meme redirection et les memes controles anti-abus.
- Confirmation que les deux chemins executent exactement une verification de
  mot de passe couteuse; un hash factice est utilise pour un compte inconnu.
- Les motifs detailles restent reserves aux journaux et alertes d'exploitation
  et ne sont pas renvoyes dans la reponse d'authentification.

## 2026-08-30 - Audit anti-bruteforce des connexions

- Confirmation du verrouillage combine par IP et par email pour les connexions
  locales administrateur et portail, avec fenetre et duree de blocage bornees.
- Extension de cette protection a la connexion Jellyfin du portail : les echecs
  sont comptes par IP et par couple serveur/utilisateur avant tout nouvel appel
  au provider; les valeurs de compte restent uniquement stockees sous forme
  d'empreinte.
- Correction de la deconnexion portail en cas de panne DB : l'echec de revocation
  serveur est journalise mais n'empeche plus l'effacement du cookie navigateur.

## 2026-08-30 - Audit des cookies de session LAN et proxy HTTPS

- Verification des attributs reels `Secure`, `HttpOnly`, `SameSite` et
  `Expires` du cookie de session en HTTP LAN direct et derriere un reverse proxy
  HTTPS de confiance.
- Confirmation qu'un proxy non approuve ne peut pas imposer la semantique HTTPS
  avec un en-tete `X-Forwarded-Proto` forge.
- Le comportement existant est conserve : cookie utilisable en HTTP LAN avec
  `HttpOnly` et `SameSite=Lax`, et cookie `Secure` avec la politique SameSite
  configuree lorsque HTTPS est etabli directement ou par un proxy approuve.

## 2026-08-30 - Audit de la duree des sessions

- Confirmation d'une expiration glissante apres 12 heures d'inactivite par
  defaut, configurable avec `VODUM_SESSION_LIFETIME_HOURS`, pour les sessions
  administrateur et portail.
- Confirmation que seules les sessions authentifiees deviennent permanentes
  dans le navigateur; les etats temporaires de connexion restent lies a la
  session du navigateur.
- Ajout de regressions sur le caractere permanent et la rotation de l'etat
  pre-authentification, en complement des tests d'expiration serveur.

## 2026-08-29 - Invalidation serveur des sessions a la deconnexion

- Ajout de sessions administrateur opaques et revocables cote serveur; la
  deconnexion revoque uniquement la session courante avant d'effacer le cookie.
- Le garde global refuse les sessions revoquees, expirees, alterees et les anciens
  cookies sans reference serveur, qui doivent se reconnecter une fois apres migration.
- Confirmation de la revocation serveur deja appliquee aux sessions portail.

## 2026-08-29 - Verification anti-fixation des sessions admin

- Confirmation que les connexions locale et Plex utilisent la meme ouverture de
  session, qui supprime l'etat pre-authentification et ne preserve que la langue.
- Ajout de regressions prouvant la suppression des marqueurs controles, du CSRF
  pre-authentification et des preuves Plex temporaires apres authentification.

## 2026-08-29 - Audit de la confiance TOTP locale

- Restriction explicite de la confiance locale aux reseaux RFC1918, loopback,
  link-local et IPv6 ULA, sans dependre de la classification plus large et
  evolutive de `ipaddress.is_private`.
- Verification automatisee de la duree et des attributs HttpOnly, Secure et
  SameSite du cookie, ainsi que de son invalidation par email ou secret TOTP.

## 2026-08-29 - Audit de la verification et de l'enrolement TOTP

- Correction de l'enrolement TOTP Settings et wizard: le secret confirme est
  maintenant genere et lie a la session par le serveur, expire apres dix minutes
  et est consomme une seule fois; une valeur choisie dans le formulaire est ignoree.
- Retrait des champs caches qui renvoyaient le secret comme source d'autorite et
  ajout de tests d'expiration, isolation des usages et consommation unique.

## 2026-08-29 - Audit de la connexion administrateur Plex

- Audit du flux PIN Plex administrateur, de l'etat de session, du callback,
  de la correspondance d'identite, du TOTP VODUM optionnel et de l'ouverture
  de session; aucune vulnerabilite exploitable supplementaire n'a ete confirmee.
- Ajout de regressions sur l'usage unique, l'expiration, la separation des usages
  des flux Plex et la consommation de la preuve TOTP intermediaire expiree.

## 2026-08-29 - Audit de la connexion administrateur locale

- Audit du parcours complet email/mot de passe administrateur: CSRF, normalisation,
  anti-bruteforce IP/email, TOTP, redirection, rotation de session et journalisation.
- Suppression d'un canal d'enumeration temporelle: les emails inconnus effectuent
  maintenant une verification de hash factice aussi couteuse que les comptes connus.
- Ajout de tests de regression pour les chemins email connu et inconnu.

## 2026-08-28 - Runtime du conteneur et dependances

- Mise a jour des dependances Python directes, notamment Flask 3.1.3,
  Waitress 3.0.2, Requests 2.34.2 et Cryptography 50.0.1; `pip-audit` ne
  detecte aucune vulnerabilite connue dans le nouvel ensemble.
- Ajout d'une vraie route `/health` et remplacement du healthcheck trompeur sur
  `/` par une sonde Python directe, sans shell ni redirection de connexion.
- Retrait de `curl` de l'image, installation APT sans recommandations et
  configuration Python/pip adaptee a un conteneur de production.
- Correction du workflow de publication Docker mal forme et suppression de
  l'affichage inutile du nom de compte du registre.
- Documentation des controles restant a effectuer dans CI : scan de l'image
  Linux finale et validation des droits de volumes avant un passage non-root.

## 2026-08-28 - Durcissement de la classification des routes

- Audit des 178 routes Flask enregistrees et confirmation du repli ferme vers
  le perimetre administrateur pour toute route non explicitement classee.
- Correction des frontieres de prefixes publics et setup : des chemins voisins
  comme `/health-debug`, `/static-admin` ou `/setup-secret` ne peuvent plus
  heriter accidentellement d'un acces moins restrictif.
- Correction de la classification de `POST /portal/auth/jellyfin`, qui est de
  nouveau accessible avant connexion tout en conservant le controle du hostname,
  le rate limiting et les validations provider existantes.
- Ajout de tests couvrant les chemins ressemblants, l'acces anonyme, le refus
  d'un utilisateur portail sur l'administration et l'acces d'un administrateur.
# 2026-09-01

- Correction des actions des sauvegardes dont les séparateurs PowerShell
  littéraux étaient affichés dans les libellés Download, Restore et Delete.
- Placement de Payment & renewal derrière le mode debug : option expérimentale
  masquée en fonctionnement normal, avertissement « ne pas utiliser », panneau
  affiché seulement après activation dans les sections visibles et blocage
  serveur des liens lorsque le mode debug est désactivé.
- Finalisation des liens externes du User Portal : contrat i18n vérifié sur les
  cinq langues et régressions ajoutées pour l'absence de lien, les liens
  désactivés, les forfaits masqués déjà attribués, les abonnements à vie et les
  utilisateurs expirés.
# Corrections P0 — 2026-09-04

- Autorise les iframes locales dans la CSP d’administration et force le chargement
  du monitoring intégré au profil utilisateur.
- Le refresh des bibliothèques Plex/Jellyfin est désormais opérationnel depuis
  `Servers & Libraries` (route POST protégée par CSRF, avec ciblage de la section
  Plex et scan serveur Jellyfin).
