#!/bin/sh
python3 app.py &
exec supercronic /app/vodum-cron
