# ⚠️ Projet en développement - Non fonctionnel pour le moment ⚠️

## 🎬 VODUM - Video On Demand User Manager

VODUM est une application de gestion des utilisateurs Plex et Jellyfin permettant de gérer les abonnements, les accès aux bibliothèques et les quotas de flux en toute simplicité. Ce projet est encore en phase de développement et n'est pas encore prêt à être utilisé en production.

---

## 🚀 Fonctionnalités prévues

- **Gestion des utilisateurs** : Création, modification et suppression des comptes Plex/Jellyfin.
- **Gestion des abonnements** : Attribution des durées d'abonnement avec alertes avant expiration.
- **Multi-serveurs** : Gestion de plusieurs serveurs Plex et Jellyfin avec des jetons d'authentification.
- **Statistiques et monitoring** : Intégration avec Tautulli pour suivre l'utilisation des flux en temps réel.
- **Notifications** : Envoi d'e-mails pour les rappels d'expiration et les annonces globales.
- **Système de paiement** : Gestion des paiements via PayPal et possibilité d'ajouter d'autres moyens.
- **Tableau de bord** : Interface web moderne pour administrer les utilisateurs et les serveurs.

---

## 🛠 Technologies utilisées

- **Backend** : Python (FastAPI)
- **Frontend** : React (prévu)
- **Base de données** : PostgreSQL
- **Auth & Sécurité** : JWT, 2FA optionnelle
- **Intégrations** : Plex, Jellyfin, Tautulli
- **Déploiement** : Docker & Unraid
- **CI/CD** : GitHub Actions, Docker Hub/GHCR

---

## 📝 Licence

VODUM est un projet open-source sous licence **MIT**.

---

## 📢 Contribuer au projet

Le projet étant en développement, toute aide est la bienvenue ! N'hésite pas à :
- Signaler des bugs et proposer des améliorations via les [Issues](https://github.com/Nexius2/VODUM/issues)
- Discuter des fonctionnalités sur Discord ou GitHub Discussions
- Soumettre des Pull Requests une fois le projet stabilisé

---

## 📌 Statut du projet

VODUM est actuellement en phase de développement **early-stage**. Les fonctionnalités ne sont pas encore entièrement implémentées. Restez à l'écoute pour les mises à jour ! 🚧

---

## 📩 Contact

Pour toute question ou suggestion, ouvre une issue sur GitHub ou contacte-moi directement.

---

🔥 **Suivez l'avancement sur GitHub !** 🔥

---

## 📦 Déploiement avec Docker

VODUM est conçu pour être déployé avec Docker. Voici les étapes pour construire et exécuter le projet localement :

```sh
git clone https://github.com/Nexius2/VODUM.git
cd VODUM
docker-compose up -d

