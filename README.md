
# 🎬 Vodum – ALPHA Version - Gestion avancée de serveurs Plex (et Jellyfin)

**Vodum** est un outil open source de gestion d'utilisateurs et de bibliothèques pour les serveurs multimédia Plex – avec une compatibilité Jellyfin en préparation. Il centralise les accès, automatise les notifications, et simplifie la vie des administrateurs via une interface moderne, une API robuste et des intégrations pratiques (Discord, mail...).

---

## ✨ Fonctionnalités clés

- 🔐 **Gestion des utilisateurs** avec rôles, permissions et expiration d’abonnement
- 🗃️ **Accès multi-serveurs** (Plex aujourd’hui, Jellyfin à venir)
- 📚 **Partage de bibliothèques** intelligent et personnalisable
- ⏳ **Abonnements** avec relances, notifications email et désactivation automatique
- 🤖 **Bot Discord intégré** pour interaction et administration
- 🌐 **Interface web multilingue** (🇫🇷 Français & 🇬🇧 Anglais) avec thème sombre
- 🧠 **Automatisation des tâches** via des scripts planifiables (cron)
- 🔎 **Logs centralisés**, tableau de bord et système de configuration
- 🐳 **Déploiement Docker ready**

---

## 🚀 Installation rapide

### Option 1 : via Docker (recommandé)

```bash
git clone https://github.com/<TON-UTILISATEUR>/vodum.git
cd vodum
docker build -t vodum .
docker run -d -p 5000:5000 --name vodum vodum
```

Accessible sur `http://localhost:5000`

### Option 2 : manuel

- Installe Python 3.9+
- Installe les dépendances :

```bash
pip install -r requirements.txt
```

- Lance le script principal :

```bash
python app/start.py
```

---

## ⚙️ Configuration

La configuration se fait via l’interface web ou directement en base (`settings`) :

- 🔑 Token Plex (admin)
- 🔐 Accès Discord bot
- 📬 Paramètres SMTP pour les mails
- 🕒 Jours avant expiration / relance / suppression
- 🌍 Langue par défaut

Les bibliothèques et serveurs peuvent être ajoutés depuis l’interface après la première connexion.

---

## 🌍 Multilingue

- Tous les textes sont traduits depuis les fichiers `lang/fr.json` et `lang/en.json`
- La langue est automatiquement détectée depuis le navigateur (modifiable dans l'interface)
- Possibilité d’ajouter d’autres langues facilement

---

## 🔒 Sécurité

- **Aucun mot de passe ou token n’est stocké dans le code.**
- Les tokens Plex, Discord, SMTP sont stockés **dans la base** et ne sont jamais loggés.
- ⚠️ Ne jamais exposer la base `.db` en ligne sans la filtrer.
- Le fichier `.gitignore` exclut les éléments sensibles (base, logs, fichiers secrets…)

---

## 📁 Structure du projet

```
vodum/
├── app/                # Backend Python
├── lang/               # Traductions
├── static/             # Style, favicon
├── Dockerfile          # Build container
├── create-container.sh # Script de déploiement
├── requirements.txt    # Dépendances Python
├── tables.sql          # Schéma de la base
├── INFO, TODO.md       # Métadonnées du projet
```

---

## 🛠️ Feuille de route (extraits)

- [ ] Support complet Jellyfin
- [ ] Gestion OAuth (Google, Discord)
- [ ] Interface web de supervision (stats, graphiques)
- [ ] Module d'import/export JSON
- [ ] CI/CD GitHub Actions
- [ ] Tests automatisés

📄 Voir `TODO.md` pour la liste complète

---

## 🤝 Contribuer

Les contributions sont les bienvenues ! Suggestions, bugs, traductions ou pull requests :
- Forkez le projet
- Travaillez sur une branche
- Soumettez votre PR

---

## 🪪 Licence

> Ce projet est publié sous licence MIT. Vous êtes libre de l'utiliser, modifier et redistribuer avec mention.

---

## 📸 Captures d'écran

*(À venir – ajouter des screenshots de l'interface, des partages, du bot Discord...)*

---
