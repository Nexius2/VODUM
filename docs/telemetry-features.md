# Compteurs de fonctionnalités (schéma 5)

Le schéma 5 ajoute 143 compteurs pour savoir quelles fonctions de VODUM sont
utilisées et à quelle échelle. La liste de référence est
`FEATURE_TELEMETRY_FIELDS` dans `app/core/feature_telemetry.py` ; le worker
valide exactement la même liste (`FEATURE_FIELDS`) et un test vérifie que les
deux restent identiques.

## Règles de confidentialité

- Chaque valeur est un entier plat et borné (0 à 10 000 000) : un nombre, un
  indicateur 0/1, une valeur de réglage ou un indice de tranche.
- Aucun nom, e-mail, adresse IP, URL, titre, texte libre, identifiant de
  serveur, de bibliothèque ou d'utilisateur n'est lu pour l'export. Les noms de
  champs ne contiennent aucun mot identifiant (`ip`, `name`, `token`…).
- Les types de règles de diffusion et les tâches planifiées passent par une
  liste blanche : une valeur inconnue est comptée dans `policy_rule_other` ou
  ignorée.
- La taille des bibliothèques est envoyée en tranche (`library_items_bucket` :
  0 aucune, 1 < 1 000, 2 < 10 000, 3 < 50 000, 4 < 200 000, 5 au-delà).
- Le worker stocke les compteurs dans `features_json`, généré à partir de la
  liste blanche ; le tableau de bord n'affiche que des agrégats.

## Contenu

- Capacité : serveurs Radarr, Sonarr et Seerr, bibliothèques par type, comptes
  sur les serveurs média, pics de lectures et de transcodages, spectateurs
  distincts, heures de lecture et lectures par type sur 30 jours.
- Demandes de médias : moteur (ARR ou Seerr), visibilité dans le portail,
  quota, bibliothèques ouvertes, routes et conditions ARR, demandes sur 30 jours.
- Abonnements : parrainage, récompenses, cadeaux, liens de paiement.
- Portail : rôles personnalisés, pages Monitoring et Support, conversations et
  messages de support, activations, Turnstile côté administration.
- Configuration des serveurs : profils, groupes, cibles, exceptions,
  déploiements, changements détectés, état de conformité par serveur, réglages
  en écart. Migrations, imports Tautulli et clés d'API.
- Communications : modèles, langues traduites, pièces jointes, modèles de
  bienvenue, bots Discord, campagnes et envois programmés sur 30 jours, rappels
  et mode d'envoi des notifications.
- Règles de diffusion par type et recommandations Usage Risk.
- Collections : listes officielles et personnalisées, listes de franchises,
  clés TMDB/MyAnimeList configurées, choix manuels de personnes, Spotlight.
- Sécurité et installation : double authentification, connexion admin Plex ou
  Jellyfin, reverse proxy, cookies sécurisés, assistant terminé, mode d'import
  Plex, monitoring ARR, durées de conservation, et l'état de chaque tâche
  planifiée.

## Robustesse côté client

Chaque compteur vérifie d'abord la présence de sa table et de ses colonnes ; une
base plus ancienne ou une erreur SQLite donne 0 sans bloquer le relevé. Si le
worker refuse le schéma 5 (champs inconnus ou corps trop gros pour l'ancienne
limite de 8 Ko), le client renvoie le même relevé en schéma 4, puis en schéma 3.

## Déploiement

1. `migration_20261128.sql` sur D1.
2. Déploiement du worker (limite de corps portée à 16 Ko).
3. Mise à jour de VODUM. Les installations en schéma 4 ou plus ancien restent
   comptées ; les cartes du schéma 5 n'utilisent que les installations qui
   l'envoient.
