# Audit de sécurité VODUM

Date de l'audit : 1er septembre 2026  
Périmètre autorisé : `streamportal.duckdns.org` et `vodempire.duckdns.org`  
Nature des tests : contrôles externes anonymes non destructifs, complétés par une revue ciblée du code local.

> État de remédiation dans le code au 1er septembre 2026 : VODUM-01, VODUM-02,
> VODUM-03, VODUM-04 et VODUM-07 ont été corrigés et couverts par les tests.
> Les constats externes resteront observables sur les domaines jusqu'au déploiement
> de cette version. VODUM-05 relève du choix fonctionnel d'illustrations publiques.
> L'isolation stricte de VODUM-02 s'active avec `VODUM_ADMIN_PUBLIC_URL` lorsque
> l'Admin et le Portal ont des domaines différents. Une installation mono-domaine
> conserve volontairement `/login` et `/portal/login` sur le même hôte.

## Résumé exécutif

Aucune vulnérabilité **CRITICAL** ou **HIGH** n'a été confirmée pendant cette phase anonyme. Les API et pages métier testées sont protégées avant authentification, les requêtes de modification sans jeton CSRF sont refusées, aucun CORS permissif n'a été observé et aucun secret Plex/Jellyfin n'a été trouvé dans les réponses publiques ou les fichiers JavaScript examinés.

Deux problèmes **MEDIUM** sont toutefois confirmés :

1. le cookie `vodum_session` émis en HTTPS ne possède pas l'attribut `Secure` sur les deux domaines ;
2. les routes d'authentification Admin, notamment `/login`, sont aussi publiées par le domaine Portal, ce qui augmente inutilement la surface d'attaque et affaiblit l'isolation attendue entre les deux hôtes.

Priorité immédiate : activer les cookies sécurisés en production, puis refuser toutes les routes Admin sur le virtual host Portal.

## Méthode et limites

- Aucune donnée, configuration, session ou utilisateur n'a été modifié.
- Aucun identifiant Admin n'a été utilisé.
- Aucun bruteforce réel ni déclenchement volontaire du verrouillage n'a été effectué.
- Les routes courantes et plusieurs noms de fichiers sensibles ont été vérifiés avec un faible nombre de requêtes.
- Les contrôles Portal authentifiés et les tests d'IDOR en production n'ont pas été exécutés faute de compte de test dédié. Ils ont été complétés par une revue du code et des tests existants.
- Une partie des tests locaux Flask ne peut actuellement pas démarrer à cause d'une incompatibilité de l'environnement `.venv` : Flask attend `werkzeug.test`, absent du module Werkzeug chargé. Les tests indépendants de cette interface passent, notamment ceux sur l'anti-énumération, le verrouillage et les contrats de propriété. Cette panne de banc de test est à corriger, mais ne constitue pas à elle seule une vulnérabilité déployée.

## Tableau des découvertes

| ID | Niveau | État | Découverte |
|---|---|---|---|
| VODUM-01 | MEDIUM | CONFIRMÉ | Cookie de session sans attribut `Secure` sur les deux domaines |
| VODUM-02 | MEDIUM | CONFIRMÉ | Interface d'authentification Admin accessible depuis le domaine Portal |
| VODUM-03 | LOW | CONFIRMÉ | Chemin local Unraid divulgué sur la page de connexion Admin |
| VODUM-04 | LOW | CONFIRMÉ | Absence de CSP sur la page de connexion Admin |
| VODUM-05 | LOW | CONFIRMÉ | Illustrations issues des médias accessibles anonymement sur les pages de connexion |
| VODUM-06 | INFO | CONFIRMÉ | Divulgation de la pile proxy, du domaine servi et de la version d'assets |
| VODUM-07 | LOW | CONFIRMÉ | Une partie importante des tests de sécurité locaux ne s'exécute plus dans `.venv` |

---

## A. PORTAIL UTILISATEUR — streamportal.duckdns.org

### Contrôles positifs confirmés

- `/portal`, `/portal/profile`, `/portal/subscription`, `/portal/media-access`, `/portal/monitoring`, `/portal/support` et `/api/portal/v1/me` redirigent un visiteur anonyme vers `/portal/login`.
- Les routes Portal appelées sur le domaine Admin retournent `404`, conformément au contrôle de nom d'hôte du code.
- La CSP Portal bloque par défaut les origines tierces, interdit les objets et limite les formulaires à la même origine.
- Les réponses Portal portent `Cache-Control: no-store`.
- Les POST anonymes testés sans jeton CSRF, notamment `/portal/login/submit`, `/portal/profile` et `/portal/support/messages`, retournent `403`.
- Aucun en-tête `Access-Control-Allow-Origin` n'a été renvoyé pour les origines Portal, Admin ou arbitraires testées.
- L'API `/api/portal/v1/me` utilise le `vodum_user_id` du principal authentifié. Le test existant vérifie qu'un `?user_id=999` est ignoré et que les champs tels que tokens, mots de passe, identifiants externes et URL serveur sont exclus.
- La mise à jour du profil utilise également l'identité de session et ignore un identifiant utilisateur soumis par le navigateur.

### VODUM-01 — Cookie de session sans `Secure`

**Niveau : MEDIUM — CONFIRMÉ**

La réponse HTTPS émet :

```text
Set-Cookie: vodum_session=...; HttpOnly; Path=/; SameSite=Lax
```

L'attribut `Secure` manque. Le HTTP est bien redirigé vers HTTPS et HSTS est présent, mais un navigateur qui ne connaît pas encore la politique HSTS peut envoyer le cookie lors d'une première requête HTTP avant la redirection. Le code confirme que ce comportement dépend du réglage `web_secure_cookies`, dont la valeur par défaut en base est `0`.

Reproduction non destructive :

```bash
curl -sS -D - -o /dev/null https://streamportal.duckdns.org/portal/login
```

Correction : activer `web_secure_cookies` sur l'instance publique ou imposer `SESSION_COOKIE_SECURE=True` lorsque l'URL publique est HTTPS. Conserver `HttpOnly` et `SameSite=Lax`. Le besoin d'accès LAN en HTTP ne doit pas diminuer la sécurité des virtual hosts publics.

### VODUM-05 — Illustrations de connexion publiques

**Niveau : LOW — CONFIRMÉ**

Les ressources `/login/artwork/backdrop`, `/login/artwork/poster` et `/branding/logo` sont publiques et mises en cache. Selon l'illustration sélectionnée, un visiteur anonyme peut déduire un élément de la médiathèque. Ce n'est pas une fuite de compte ou de token, mais c'est une fuite de contenu potentielle.

Reproduction :

```bash
curl -sS -D - -o /dev/null https://streamportal.duckdns.org/login/artwork/backdrop
```

Correction : utiliser des illustrations génériques ou explicitement choisies pour être publiques, et ne jamais sélectionner automatiquement un média privé pour l'écran anonyme.

---

## B. ADMINISTRATION — vodempire.duckdns.org

### Contrôles positifs confirmés

- Un inconnu atteint `/login`, mais les routes `/`, `/settings`, `/users`, `/servers`, `/backup`, `/api/tasks/list`, `/api/backup/list`, `/api/monitoring/activity` et `/logs/download` redirigent vers le login.
- Les chemins sensibles testés (`/.env`, `/.git/config`, `/database.db`, `/backup.zip`, `/docker-compose.yml`) ne sont pas servis anonymement et redirigent eux aussi vers le login.
- Les POST sans CSRF vers `/login/submit`, `/settings/save` et `/api/mailing/toggle` retournent `403`.
- Aucune stack trace, adresse IP privée, donnée Plex/Jellyfin, base SQLite, sauvegarde ou secret n'a été obtenu.
- Le code applique une politique « fail closed » : toute route non reconnue devient une route Admin et nécessite un principal Admin valide.

### VODUM-01 — Cookie de session sans `Secure`

**Niveau : MEDIUM — CONFIRMÉ**

Le même défaut que sur le Portal affecte le cookie Admin :

```bash
curl -sS -D - -o /dev/null https://vodempire.duckdns.org/login
```

Le risque est plus important ici, car le cookie protège l'administration. Appliquer la correction décrite dans la section Portal.

### VODUM-03 — Divulgation d'un chemin local

**Niveau : LOW — CONFIRMÉ**

La page de connexion Admin contient le chemin d'exemple :

```text
/mnt/user/appdata/VODUM/password.reset
```

Cela révèle l'organisation du stockage local et l'usage probable d'Unraid. Cette information n'offre pas directement un accès, mais facilite le profilage de l'infrastructure.

Reproduction :

```bash
curl -sS https://vodempire.duckdns.org/login | grep -F '/mnt/user/appdata/VODUM/password.reset'
```

Correction : remplacer ce chemin par une formulation générique dans l'interface publique et réserver le chemin exact à la documentation locale authentifiée.

### VODUM-04 — Pas de Content Security Policy sur le login Admin

**Niveau : LOW — CONFIRMÉ**

Le Portal reçoit une CSP, mais aucune CSP n'est appliquée à `/login` Admin. Le code limite volontairement la CSP aux chemins `/portal` et `/api/portal/`. Il s'agit d'une protection en profondeur manquante, particulièrement utile sur une interface sensible.

Reproduction :

```bash
curl -sS -D - -o /dev/null https://vodempire.duckdns.org/login
```

Correction : définir une CSP pour toutes les pages Admin, puis retirer progressivement les scripts/styles inline éventuels ou les autoriser par nonce/hash.

### Protection du login et énumération

**État : CONFIRMÉ PAR LE CODE ET LES TESTS, APPLICATION LIVE DU VERROUILLAGE À VÉRIFIER**

Les valeurs par défaut sont de 5 échecs sur 15 minutes, suivis d'un verrouillage de 15 minutes. Le suivi est fait par IP et par identité. Un compte inconnu passe par une vérification de hash factice et reçoit le même message générique qu'un compte connu. Les tests unitaires correspondants passent.

Ce dispositif est raisonnable contre les tentatives simples. Il ne remplace pas une protection au reverse proxy contre les attaques distribuées. L'activation effective de Turnstile et le comportement du verrouillage sur l'instance publique restent à valider avec un compte de test expressément dédié, sans verrouiller le vrai compte Admin.

---

## C. ISOLATION PORTAL ↔ ADMIN

### Contrôles positifs confirmés

- Les deux hôtes utilisent le même nom de cookie, `vodum_session`, mais aucun attribut `Domain` n'est émis : les cookies sont donc limités à leur hôte respectif.
- Les routes `/portal/*` et `/api/portal/*` sont refusées par `404` sur le domaine Admin lorsque `portal_public_url` est configuré.
- Aucun CORS permissif n'a été observé entre les deux domaines.
- Les sessions sont typées par rôle (`admin` ou `user`) et adossées à une session serveur révocable.
- Le garde global exige le rôle Admin pour les routes Admin. Une session Portal présentée à une route Admin reçoit `403` dans les tests du code.
- Les contrôles de propriété utilisent l'identité de session et échouent de manière fermée lorsqu'elle est absente ou différente.

### VODUM-02 — Routes Admin publiées sur le domaine Portal

**Niveau : MEDIUM — CONFIRMÉ**

`https://streamportal.duckdns.org/login` affiche la page de connexion Admin. Les routes Admin protégées sont également routées sur ce domaine et redirigent vers ce login. Le garde global vérifie le nom d'hôte pour le Portal, mais pas pour l'Admin.

Cela n'a pas permis de contourner l'authentification. Cependant, le domaine public Portal devient un second point d'attaque du login Admin et rend l'isolation réseau moins claire. Une mauvaise configuration future du proxy ou du garde aurait alors un impact accru.

Reproduction :

```bash
curl -sS -D - -o /dev/null https://streamportal.duckdns.org/login
curl -sS -D - -o /dev/null https://streamportal.duckdns.org/users
```

Correction : sur le virtual host Portal, n'acheminer que `/portal/*`, `/api/portal/*` et les ressources publiques strictement nécessaires. Ajouter en complément un contrôle applicatif du nom d'hôte attendu pour les scopes `admin` et `admin_auth`, avec retour `404` sur tout autre hôte.

### Conclusion sur l'élévation Portal → Admin

Aucune élévation n'a été confirmée. Les garanties du code sont solides, mais le résultat reste **À VÉRIFIER en production avec une session Portal de test**, notamment en appelant directement une sélection de routes Admin et en testant les identifiants de ressources d'un second compte de test. Cette étape nécessite deux comptes Portal dédiés et ne doit pas utiliser de vrais utilisateurs.

---

## D. EXPOSITION INFRASTRUCTURE

### VODUM-06 — Informations techniques publiques

**Niveau : INFO — CONFIRMÉ**

Les réponses révèlent `Server: openresty`, `X-Served-By` et une version de build dans les URL d'assets. `/health` est public mais ne renvoie qu'une réponse minimale. Aucun token, chemin de base de données, IP privée ou configuration Docker exploitable n'a été obtenu par ces endpoints.

Correction : retirer les en-têtes et versions non nécessaires lorsque cela est simple, sans considérer cette action comme prioritaire.

### TLS, redirection et en-têtes

- HTTP redirige vers HTTPS sur les deux domaines.
- HSTS est actif sur les réponses HTTPS.
- `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` et `Permissions-Policy` sont présents.
- La directive HSTS observée au proxy (`max-age=63072000; preload`) diffère de celle du code applicatif (`max-age=31536000; includeSubDomains`), ce qui montre que le reverse proxy remplace ou complète les en-têtes. Il est préférable de définir une politique unique et documentée.

### VODUM-07 — Banc de tests de sécurité partiellement cassé

**Niveau : LOW — CONFIRMÉ**

Dans `.venv`, les tests utilisant `Flask.test_client()` échouent avant leur exécution avec :

```text
AttributeError: module 'werkzeug' has no attribute 'test'
```

Les tests ne détecteront donc pas certaines régressions tant que les versions/imports Flask-Werkzeug ne seront pas remis en cohérence. Les tests indépendants couvrant l'anti-énumération, le verrouillage, la rotation de session et la propriété horizontale ont pu passer.

Correction : figer des versions Flask/Werkzeug compatibles, recréer `.venv`, puis exécuter la suite complète dans la CI.

---

## Réponses aux 10 questions

1. **Un inconnu peut-il atteindre autre chose que le login Admin ?**  
   Il peut atteindre les ressources publiques (`/health`, branding, artwork, assets) et, sur le domaine Portal, le login Admin. Les pages et API métier testées exigent une authentification.

2. **Un utilisateur Portal peut-il atteindre une fonction Admin ?**  
   Aucune fonction Admin n'est accessible selon le code et les tests de rôle ; une session Portal doit recevoir `403`. À confirmer une dernière fois en production avec un compte Portal de test.

3. **Des données VODUM sont-elles accessibles sans authentification ?**  
   Aucune donnée utilisateur ou donnée métier n'a été trouvée. Seuls des éléments publics de connexion, dont des illustrations potentiellement issues de médias, sont accessibles.

4. **Des tokens Plex/Jellyfin ou autres secrets sont-ils exposés ?**  
   Aucun secret n'a été trouvé dans les réponses, les routes testées ou les JavaScript publics examinés.

5. **Peut-on identifier les utilisateurs VODUM depuis Internet ?**  
   Aucun mécanisme d'énumération n'a été confirmé. Le code utilise un message générique et une vérification de hash factice pour les identités inconnues.

6. **Les protections contre le bruteforce sont-elles suffisantes ?**  
   Elles sont raisonnables dans le code (5 essais/15 min, verrouillage 15 min, scopes IP et identité, alerte), mais la protection live et Turnstile doivent être validés avec un compte de test. Une limitation supplémentaire au reverse proxy est recommandée contre les sources distribuées.

7. **Les sessions Portal et Admin sont-elles correctement isolées ?**  
   Les cookies sont host-only et les rôles sont distincts. L'isolation logique est bonne, mais l'exposition du login Admin sur le domaine Portal doit être supprimée et l'attribut `Secure` doit être activé.

8. **Des informations sur le réseau interne sont-elles divulguées ?**  
   Aucune IP interne n'a été trouvée. Un chemin local Unraid `/mnt/user/appdata/VODUM/password.reset` est toutefois divulgué.

9. **Existe-t-il une vulnérabilité exploitable HIGH ou CRITICAL ?**  
   Aucune n'a été confirmée pendant cette phase.

10. **Quelle est la première chose à corriger ?**  
    Activer immédiatement l'attribut `Secure` des cookies sur les deux domaines publics. Ensuite, empêcher le domaine Portal de servir toute route Admin.

## Ordre de correction recommandé

1. Activer les cookies `Secure` en production et vérifier le résultat avec `curl` et un navigateur.
2. Isoler les virtual hosts : routes Admin uniquement sur `vodempire.duckdns.org`.
3. Ajouter une CSP à l'Admin.
4. Retirer le chemin Unraid de la page publique et rendre les illustrations anonymes génériques.
5. Réparer l'environnement de tests et exécuter toute la suite en CI.
6. Créer deux comptes Portal de sécurité dédiés pour terminer les tests live IDOR et Portal → Admin sans toucher aux données réelles.
