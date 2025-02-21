# Utiliser une image de base Python
FROM python:3.9

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers nécessaires
COPY . /app

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port de l’API
EXPOSE 8000

# Lancer l’application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
