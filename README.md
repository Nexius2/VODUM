
# 🎬 Vodum – ALPHA Version - Gestion utilisateurs de Plex

**Vodum** est un outil open source de gestion d'utilisateurs et de bibliothèques pour les serveurs multimédia Plex. Il centralise les accès, automatise les notifications d'abonnements, et simplifie la vie des administrateurs via une interface et des intégrations pratiques (Discord, mail...).

---

## ✨ Fonctionnalités clés

- 🔐 **Gestion des utilisateurs** avec rôles, permissions et expiration d’abonnement
- 🗃️ **Accès multi-serveurs** 
- 📚 **Partage de bibliothèques** intelligent et personnalisable
- ⏳ **Abonnements** avec relances, notifications email et désactivation automatique
- 🤖 **Bot Discord intégré** pour interaction et administration
- 🌐 **Interface web multilingue** (🇫🇷 Français & 🇬🇧 Anglais a venir) 
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

## 🌍 Multilingue (en cours)

- Tous les textes sont traduits depuis les fichiers `lang/fr.json` et `lang/en.json`
- La langue est automatiquement détectée depuis le navigateur 
- Possibilité d’ajouter d’autres langues facilement

---

## 🔒 Sécurité

- **Aucun mot de passe ou token n’est stocké dans le code.**
- Les tokens Plex, Discord, SMTP sont stockés **dans la base** et ne sont jamais loggés.
- ⚠️ Ne jamais exposer la base `.db` en ligne sans la filtrer.


## 🪪 Licence

> Ce projet est publié sous licence MIT. Vous êtes libre de l'utiliser, modifier et redistribuer avec mention.




