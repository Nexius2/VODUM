CONTAINER_NAME="vodum"
IMAGE_NAME="nexius2/vodum:latest"

echo "📥 Récupération de l'image depuis Docker Hub..."
docker pull "$IMAGE_NAME"

echo "🛑 Suppression de l'ancien conteneur..."
docker rm -f "$CONTAINER_NAME" 2>/dev/null

echo "🚀 Création du nouveau conteneur..."
docker run -d \
  --name=vodum \
  --hostname vodum \
  -p 5000:5000 \
  --restart unless-stopped \
  -v /mnt/user/appdata/vodum:/appdata \
  -v /mnt/user/appdata/vodum/logs:/logs \
  -v /mnt/user/appdata/vodum/backups:/backups \
  -e DATABASE_PATH="/appdata/database.db" \
  --label "net.unraid.docker.webui=http://[IP]:[PORT:5000]" \
  --label "net.unraid.docker.icon=http://[IP]:[PORT:5000]/static/icon.png" \
  "$IMAGE_NAME"
