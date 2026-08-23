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
COPY translations/ /app/translations/
COPY migrations/ /app/migrations/

# Fail the image build if the dedicated Plex sign-in UI is missing from the
# Docker context. This prevents an apparently successful rebuild from shipping
# stale settings templates.
RUN grep -Fq 'data-testid="plex-auth-settings-card"' /app/templates/settings/partials/_settings_system.html \
    && grep -Fq 'form="plex-auth-link-form"' /app/templates/settings/partials/_settings_system.html \
    && grep -Fq "url_for('plex_auth_link_start')" /app/templates/settings/settings.html \
    && grep -Fq 'name="admin_auth_method"' /app/templates/setup/wizard.html \
    && grep -Fq 'wizard_admin_use_plex_help' /app/templates/setup/wizard.html \
    && grep -Fq 'include "servers/_plex_suggestions.html"' /app/templates/servers/servers.html \
    && grep -Fq 'include "servers/_plex_suggestions.html"' /app/templates/setup/wizard.html \
    && grep -Fq "preferred_url_" /app/templates/servers/plex_discovery.html

# SQL seeds
COPY tables.sql /app/tables.sql
#COPY default_data.sql /app/default_data.sql

# Entrypoint + INFO
COPY entrypoint.sh /app/entrypoint.sh
COPY run.py /app/run.py
COPY INFO /app/INFO
RUN chmod 644 /app/INFO
RUN grep -Eiq '^VERSION=v?[0-9]+\.[0-9]+\.[0-9]+([[:space:]._-]+(b|build)[0-9]+)?$' /app/INFO


# Ensure entrypoint executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 5000

CMD ["/app/entrypoint.sh"]

