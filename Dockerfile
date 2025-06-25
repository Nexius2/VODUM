# Utilisation de l'image Python Slim pour réduire la taille
FROM python:3.12-slim

# Mise à jour et installation de SQLite3
RUN apt-get update && apt-get install -y curl sqlite3 && rm -rf /var/lib/apt/lists/*


# Définition du répertoire de travail
WORKDIR /app
RUN ls -lh .



# Copier les fichiers nécessaires
COPY requirements.txt .
#COPY bot_plex.py .
#COPY tables.sql /app/tables.sql  # Assurez-vous que tables.sql est bien copié
#COPY ["tables.sql", "/app/tables.sql"]
#COPY update_plex_users.py /app/update_plex_users.py
#COPY start.py /app/start.py
#COPY translations.json /app/translations.json
#COPY app.py /app/app.py

COPY app/ /app/
# Assurez-vous que le dossier templates existe et copiez le fichier index.html
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY lang/ /app/lang/
COPY icon.png /usr/share/icons/hicolor/256x256/apps/icon.png
COPY INFO /app/INFO



# Assurer que les variables d’environnement sont bien chargées
ENV BOT_LANGUAGE=fr



# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Lancer le bot au démarrage
CMD ["python3", "start.py"]






