FROM python:3.10

# Définition du répertoire de travail
WORKDIR /app/backend

# Installation des dépendances système pour PostgreSQL
RUN apt-get update && apt-get install -y \
    postgresql postgresql-contrib

# Copie uniquement le backend
COPY . /app

# Installation des dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Définition des variables d'environnement pour PostgreSQL
ENV POSTGRES_USER=vodum
ENV POSTGRES_PASSWORD=vodum
ENV POSTGRES_DB=vodum
ENV DATABASE_URL=postgresql://vodum:vodum@localhost:5432/vodum

ENV PYTHONPATH="/app"


#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]


# Commande pour démarrer PostgreSQL et l'API FastAPI
CMD service postgresql start && \
	sleep 5 && \
    su - postgres -c "psql -c \"CREATE ROLE vodum WITH LOGIN PASSWORD 'vodum';\"" && \
    su - postgres -c "psql -c \"ALTER ROLE vodum CREATEDB;\"" && \
    su - postgres -c "psql -c \"CREATE DATABASE vodum OWNER vodum;\"" && \
    #su - postgres -c "psql -c \"ALTER USER vodum WITH PASSWORD 'vodum';\"" && \
	sleep 5 && \
    uvicorn main:app --host 0.0.0.0 --port 8080

