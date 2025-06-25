import discord
import os
import logger
import requests
import asyncio
import sqlite3
import xml.etree.ElementTree as ET
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import update_plex_users  # Importer la fonction de mise à jour
import json
from datetime import datetime, timedelta
from app import get_settings
#import logger
from logger import logger
from config import DATABASE_PATH

config = get_settings()
DISCORD_TOKEN = config.get("discord_token")
DISCORD_USER_ID = config.get("discord_user_id")
TAUTULLI_URL = config.get("tautulli_url")
TAUTULLI_API_KEY = config.get("tautulli_api_key")
PLEX_URL = config.get("plex_url")
PLEX_TOKEN = config.get("plex_token")


logger.debug("🧪 Test log depuis bot_plex.py")



if not DISCORD_TOKEN:
    logger.warning("❌ Aucun token Discord défini, le bot ne sera pas lancé.")
    exit(1)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

logger.info(f"🔧 Token Discord récupéré : {DISCORD_TOKEN[:6]}... (masqué)")



# Chargement des variables d'environnement
#DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


# Vérification des variables d'environnement
#required_vars = ["DISCORD_TOKEN", "PLEX_URL", "PLEX_TOKEN", "TAUTULLI_URL", "TAUTULLI_API_KEY"]



# Debugging pour voir si elles sont bien chargées
#logger.info(f"DEBUG: TAUTULLI_API_KEY={TAUTULLI_API_KEY}")
#logger.info(f"DEBUG: TAUTULLI_URL={TAUTULLI_URL}")


# Configuration des logs
#logger.basicConfig(
#    level=logger.DEBUG,
#    format="%(asctime)s [%(levelname)s] %(message)s",
#    handlers=[
#        logger.FileHandler('bot.log'),
#        logger.StreamHandler()
#    ]
#)

# Configuration du bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def close(self):
        self.conn.close()


@tasks.loop(minutes=10)
async def check_subscriptions():
    # Code de la tâche récurrente
    pass

@bot.event
async def on_ready():
    logger.info(f"✅ Bot connecté en tant que {bot.user}")

    if not check_subscriptions.is_running():
        check_subscriptions.start()

# Gestion des erreurs
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Commande inconnue. Tape `!help` pour voir la liste des commandes disponibles.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("⛔ Tu n'as pas les permissions pour cette commande.")
    else:
        await ctx.send(f"⚠ Une erreur est survenue : {str(error)}")
    logger.error(f"⚠ Erreur : {str(error)}")

# Vérification des permissions d'admin
def is_admin():
    async def predicate(ctx):
        admin_id = int(config.get("discord_user_id") or 0)
        if ctx.author.id == admin_id:
            return True
        await ctx.send("⛔ Tu n'es pas autorisé à utiliser cette commande.")
        return False
    return commands.check(predicate)


# Commande pour afficher l'état du bot
@bot.command()
async def status(ctx):
    """📌 Affiche l'état actuel du bot."""
    uptime = datetime.now() - bot.start_time
    await ctx.send(f"✅ Bot en ligne depuis {uptime.total_seconds():.0f} secondes")

# Commande pour lister les utilisateurs actifs sur Plex
@bot.command()
@is_admin()
async def plex_users(ctx):
    """📌 Affiche les utilisateurs actuellement connectés à Plex."""
    try:
        servers = update_plex_users.get_plex_servers()
        for srv in servers:
            try:
                headers = {"X-Plex-Token": srv["plex_token"]}
                response = requests.get(f"{srv['plex_url']}/status/sessions", headers=headers, timeout=10)

                if response.status_code != 200:
                    await ctx.send(f"❌ Erreur de connexion à Plex pour {srv['name']}")
                    continue

                root = ET.fromstring(response.text)
                users = []

                for video in root.findall(".//Video"):
                    user = video.find("User")
                    player = video.find("Player")

                    if user and player:
                        username = user.get("title", "Utilisateur anonyme")
                        device = player.get("title", "Appareil non identifié")
                        state = player.get("state", "inconnu")
                        users.append(f"[{srv['name']}] 👤 {username} sur {device} ({state})")

                if users:
                    await ctx.send(f"🖥️ **{srv['name']}**\n" + "\n".join(users))
                else:
                    await ctx.send(f"ℹ️ Aucun utilisateur en ligne sur **{srv['name']}**.")

            except Exception as e:
                logger.error(f"Erreur serveur {srv['name']} : {e}")
                await ctx.send(f"❌ Erreur lors de la vérification de {srv['name']}")
    except Exception as e:
        logger.error(f"Erreur dans plex_users : {e}")
        await ctx.send("❌ Une erreur générale est survenue lors de la vérification des utilisateurs")


# Commande pour afficher les statistiques Tautulli
@bot.command()
@is_admin()
async def tautulli_stats(ctx):
    """📌 Affiche des statistiques Tautulli sur l'utilisation de Plex."""
    try:
        if not TAUTULLI_API_KEY or not TAUTULLI_URL:
            await ctx.send("❌ La configuration Tautulli est manquante. Vérifiez vos variables d'environnement.")
            return

        params = {
            "apikey": TAUTULLI_API_KEY,
            "cmd": "get_activity"
        }
        
        response = requests.get(f"{TAUTULLI_URL}/api/v2", params=params, timeout=10)
        data = response.json()
        
        if not data["response"]["data"]["sessions"]:
            await ctx.send("📊 Aucun flux en cours sur Plex.")
            return

        sessions = []
        for session in data["response"]["data"]["sessions"]:
            sessions.append(f"🎥 {session['friendly_name']} regarde **{session['full_title']}**")

        if sessions:
            await ctx.send("\n".join(sessions))
        else:
            await ctx.send("📊 Aucune activité détectée sur Plex.")

    except Exception as e:
        logger.error(f"Erreur dans tautulli_stats : {e}")
        await ctx.send("❌ Une erreur est survenue lors de la récupération des statistiques.")


# Commande pour ajouter un utilisateur Plex
@bot.command()
@is_admin()
async def ajouter_plex(ctx, email: str):
    """📌 Ajoute un utilisateur Discord à Plex avec les permissions par défaut."""
    try:
        headers = {
            "X-Plex-Token": PLEX_TOKEN,
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{PLEX_URL}/users",
            headers=headers,
            json={"email": email},
            timeout=10
        )
        
        if response.status_code == 201:
            await ctx.send(f"✅ Utilisateur {email} ajouté à Plex")
        else:
            await ctx.send(f"❌ Erreur lors de l'ajout de l'utilisateur : {response.text}")

    except Exception as e:
        logger.error(f"Erreur dans ajouter_plex : {e}")
        await ctx.send("❌ Une erreur est survenue lors de l'ajout de l'utilisateur")

# Ajout de la vérification automatique des abonnements
@tasks.loop(hours=24)
async def check_subscriptions():
    try:
        db = Database()
        today = datetime.now().date()

        users = db.cursor.execute(
            "SELECT discord_user_id, last_notification FROM users WHERE last_notification <= ?",
            (today + timedelta(days=3),)
        ).fetchall()

        for user in users:
            discord_id, expiration_date = user
            user_obj = bot.get_user(discord_id)
            if user_obj:
                await user_obj.send(f"🚨 Ton abonnement expire le {expiration_date}. Pense à le renouveler !")

        db.close()

    except Exception as e:
        logger.error(f"Erreur dans check_subscriptions : {e}")





# Commande pour désactiver un abonnement
@bot.command()
@is_admin()
async def desabonner(ctx, member: discord.Member):
    """📌 Désabonne un utilisateur Discord de Plex."""
    try:
        conn = await get_db_connection()
        
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM users WHERE discord_id = $1",
                member.id
            )
        
        await ctx.send(f"{member.mention} a été désabonné ✖️")
        await member.send("⚠ Ton accès à Plex a été retiré.")

    except Exception as e:
        logger.error(f"Erreur dans desabonner : {e}")
        await ctx.send("❌ Une erreur est survenue lors de la suppression de l'abonnement")

# Commande pour afficher les informations d'un utilisateur
@bot.command()
@is_admin()
async def info_user(ctx, member: discord.Member = None):
    """📌 Affiche les informations d'abonnement d'un utilisateur Discord."""
    if member is None:
        await ctx.send("⛔ Erreur : Tu dois mentionner un utilisateur ! Exemple : `!info_user @pseudo`")
        return

    db = Database()
    row = db.cursor.execute("SELECT expiration_date FROM users WHERE discord_id = ?", (member.id,)).fetchone()
    db.close()

    if row:
        await ctx.send(f"📅 {member.mention} est abonné jusqu'au {row[0]}")
    else:
        await ctx.send(f"👤 {member.mention} n'est pas abonné")




# Commande pour afficher toutes les informations du bot
@bot.command()
@is_admin()
async def stats(ctx):
    """📌 Affiche des statistiques sur les abonnés Plex."""
    try:
        db = Database()
        subscribed_users = db.cursor.execute("SELECT discord_id FROM users").fetchall()
        db.close()

        embed = discord.Embed(title="Statistiques du Bot", color=discord.Color.blue())
        embed.add_field(
            name="Utilisateurs abonnés",
            value=len(subscribed_users)
        )
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Erreur dans stats : {e}")
        await ctx.send("❌ Une erreur est survenue lors de la génération des statistiques")


# Fonction pour récupérer tous les utilisateurs abonnés
def get_subscribed_users():
    db = Database()
    rows = db.cursor.execute("SELECT discord_id FROM users").fetchall()
    db.close()
    return [row[0] for row in rows]



# Commande pour voir les abonnés
@bot.command()
@is_admin()
async def abonnés(ctx):
    db = Database()
    users = db.cursor.execute("SELECT discord_user_id, last_notification FROM users").fetchall()
    db.close()

    if not users:
        await ctx.send("📜 Aucun utilisateur abonné.")
        return

    msg = "📜 Liste des abonnés :\n"
    for user in users:
        msg += f"👤 <@{user[0]}> - Abonné jusqu'au {user[1]}\n"

    await ctx.send(msg)




# ... (le reste du code)

def get_db_connection():
    """Retourne une connexion SQLite"""
    return sqlite3.connect(DATABASE_PATH)

# Commande pour ajouter un utilisateur
@bot.command()
@is_admin()
async def abonner(ctx, member: discord.Member, jours: int, start_date: str = None):
    """📌 Abonne un utilisateur pour une durée définie."""
    try:
        # Déterminer la date de début
        if start_date:
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                await ctx.send("❌ Format de date invalide. Utilisez AAAA-MM-JJ.")
                return
        else:
            start_date = datetime.now()

        # Calculer la date de fin
        end_date = start_date + timedelta(days=jours)

        # Mise à jour dans la base de données
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET start_date = ?, end_date = ? 
            WHERE discord_user_id = ?;
        """, (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), str(member.id)))
        conn.commit()
        conn.close()

        await ctx.send(f"✅ {member.mention} a été abonné jusqu'au {end_date.strftime('%Y-%m-%d')}.")

    except Exception as e:
        logger.error(f"Erreur dans abonner : {e}")
        await ctx.send("❌ Une erreur est survenue lors de l'abonnement.")


@bot.command()
@is_admin()
async def sync_plex(ctx):
    """📌 Synchronise manuellement les utilisateurs Plex avec la base de données."""
    await ctx.send(get_translation("sync_start"))
    result = update_plex_users.sync_plex_users()
    await ctx.send(get_translation("sync_done") if "succès" in result else get_translation("sync_error"))


@bot.command()
@is_admin()
async def list_plex_users(ctx):
    """📌 Affiche la liste des utilisateurs Plex enregistrés."""
    db = Database()
    users = db.cursor.execute("SELECT username, email, role FROM users").fetchall()
    db.close()

    logger.info(f"🔍 Utilisateurs récupérés depuis SQLite : {users}")

    if not users:
        await ctx.send("📭 Aucun utilisateur Plex enregistré.")
        return

    message = "**📋 Liste des utilisateurs Plex :**\n"
    for user in users:
        username, email, role = user
        message += f"👤 **{username}** | 📧 {email or 'N/A'} | 🎭 Rôle: `{role}`\n"

    logger.info(f"📜 Longueur du message Discord : {len(message)}")

    # Vérifier si le message dépasse la limite Discord
    if len(message) > 2000:
        messages = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for part in messages:
            await ctx.send(f"```{part}```")
    else:
        await ctx.send(f"```{message}```")



# Chargement des traductions
# Charger la langue depuis les variables d’environnement du conteneur
LANGUAGE = os.getenv("BOT_LANGUAGE", "fr")  # Par défaut, français

# Charger les traductions
with open("translations.json", "r", encoding="utf-8") as f:
    TRANSLATIONS = json.load(f)

def get_translation(key):
    """📌 Récupère la traduction pour une clé donnée."""
    return TRANSLATIONS.get(LANGUAGE, {}).get(key, key)  # Retourne la clé si non trouvée

# Log pour vérifier la langue chargée
logger.info(f"🌍 Langue du bot chargée : {LANGUAGE}")





if __name__ == "__main__":
    try:
        bot.start_time = datetime.now()
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.critical(f"Erreur fatale : {e}")


