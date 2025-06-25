# start.py
import threading
import subprocess
from logger import logger

def start_flask():
    logger.info("🚀 Lancement de l'interface Flask")
    subprocess.run(["python3", "app.py"])

def start_discord_bot():
    logger.info("🤖 Lancement du bot Discord")
    subprocess.run(["python3", "bot_plex.py"])

threading.Thread(target=start_flask).start()
threading.Thread(target=start_discord_bot).start()
