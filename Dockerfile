FROM python:3.12-slim

# Utils
RUN apt-get update && apt-get install -y sqlite3 curl && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ /app/
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY lang/ /app/lang/
COPY migrations/ /app/migrations/
COPY tools/ /app/tools/

# SQL seeds
COPY tables.sql /app/tables.sql
#COPY default_data.sql /app/default_data.sql

# Entrypoint + INFO
COPY entrypoint.sh /app/entrypoint.sh
COPY run.py /app/run.py
COPY INFO /app/INFO
RUN chmod 644 /app/INFO


# Ensure entrypoint executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 5000

CMD ["/app/entrypoint.sh"]
