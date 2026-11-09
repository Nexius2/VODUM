# Limites de lecture strictes — 22 octobre 2026

La capture montre un deuxième stream démarré à 23:43:47, encore vu à
23:51:55, avec une action enregistrée à 23:52:09 : 8 min 08 s de présence
observée et 8 min 22 s jusqu'à l'action. Ces dates ne prouvent pas une lecture
ininterrompue et ne donnent pas la date du premier constat de dépassement.
Sans les journaux de cette installation, la répartition exacte du délai reste inconnue.

## Causes trouvées dans le code

- Les appareils mobiles pouvaient bénéficier d'une tolérance de cinq minutes,
  même avec des contenus différents et des IP différentes.
- Le regroupement temporaire de sessions sur un appareil pouvait masquer
  plusieurs lectures pendant cinq minutes.
- Les nouveaux streams étaient exclus pendant quinze secondes. Un événement
  Plex de démarrage pouvait donc provoquer un contrôle qui ignorait ce stream.
- Une attente de 45 secondes précédait la coupure ; Jellyfin pouvait ajouter
  une minute de messages avant l'arrêt.
- Les limites de streams coupaient une seule lecture par passage, même si
  plusieurs lectures dépassaient le plafond.
- Le scheduler attendait trente secondes entre ses passages, malgré des
  intervalles de tâches plus courts.

## Comportement corrigé

Les limites `max_streams_per_user`, `max_streams_per_ip` et `max_ips_per_user`
comptent les sessions distinctes dès leur première observation. Seuls les
doublons exacts de clé de session sur le même serveur sont regroupés.
Les ressemblances entre appareils, médias ou réseaux ne donnent plus de délai.

Le contrôle confirme le dépassement depuis l'état collecté courant sans attente,
puis demande l'arrêt de tous les streams excédentaires selon le sélecteur
configuré. Aucun message préalable ni délai de nouvelle tentative n'est accordé.
Les échecs d'arrêt sont enregistrés et les autres cibles restent traitées.
Chaque arrêt conserve l'identité du compte et le serveur réellement ciblés.

Le contrôle périodique et le passage du scheduler passent à cinq secondes.
La coupure prend la priorité sur les autres tâches en attente. Une migration
met à jour les installations existantes et efface leur ancienne échéance.
Lorsqu'une limite de concurrence est active, une préférence de rafraîchissement
serveur lente est plafonnée à quinze secondes. Les notifications Plex continuent
de déclencher une collecte et un contrôle sans attendre ce polling.

## Limites opérationnelles

VODUM demande un arrêt après détection ; il n'intercepte pas l'autorisation
initiale de lecture du serveur. Les notifications, le polling, les appels réseau,
la disponibilité du serveur et une tâche déjà en cours influencent donc le délai.
Les cinq secondes sont une fréquence de contrôle, pas une garantie de coupure.
Le contenu déjà mis en tampon peut encore être lu côté client.
Empêcher tout partage de mot de passe, y compris des usages successifs respectant
les plafonds, nécessiterait un contrôle d'accès supplémentaire côté serveur.

Les règles activées, leurs scopes, sélecteurs et dérogations administratives
restent applicables. Aucun changement n'a été déployé sur le serveur de production.
