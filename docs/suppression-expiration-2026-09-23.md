# Suppression après expiration

Le mode `expiry_mode=delete` ajoute une option exclusive aux modes existants.
Il est désactivé par défaut. Le délai `delete_after_expiry_days` est désormais
utilisé par ce mode, entre 1 et 3 650 jours. La tâche `delete_expired_users`
s'exécute chaque heure à la minute 33 lorsque le mode et le planificateur sont
activés. Les modes d'expiration existants gardent leurs traitements.

## Comportement

1. Vérifier la date contractuelle, le délai et les exclusions locales.
2. Vérifier tous les comptes et serveurs associés avant toute suppression.
3. Jellyfin : supprimer le compte par identifiant natif, puis vérifier son
   absence dans la liste des utilisateurs authentifiée.
4. Plex : retirer uniquement les partages correspondant à cet identifiant sur
   les serveurs concernés, puis vérifier leur absence. Le compte Plex personnel,
   la relation d'amitié globale et Plex Home ne sont pas supprimés.
5. Supprimer la fiche VODUM et ses relations locales uniquement après la
   confirmation de toutes les cibles.

Le délai part de la date d'expiration. Ce mode n'ajoute pas de blocage de lecture
pendant le délai et ne restaure pas des accès déjà retirés par un ancien mode.
Le nettoyage des anciennes règles système lors d'un changement de mode préserve
les règles manuelles.

Les propriétaires, administrateurs, comptes Plex Home, invitations en attente,
abonnements à vie et exemptions d'expiration sont exclus. Les statuts manuels
comme `suspended` ne sont pas traités. Les administrateurs Jellyfin et le
propriétaire Plex sont également vérifiés sur la réponse native, sans se fier
uniquement au rôle enregistré dans VODUM.

## Réimport Plex

L'aide « ? » à côté de l'option explique que l'import global peut réimporter une
identité Plex après sa suppression locale. Utiliser « Importer uniquement les
utilisateurs partagés » évite sa réimportation par cette synchronisation lorsque
le compte n'a plus de partage sur les serveurs configurés. Le mode d'import
n'est pas modifié silencieusement lorsque la suppression est activée.

## Échecs, concurrence et reprises

- Une erreur HTTP, un timeout, une redirection, une réponse mal formée ou une
  confirmation manquante conserve la fiche locale et apparaît dans les logs de
  tâche. Aucune réponse fournisseur ni secret n'est copié dans ces messages.
- Une suppression distante déjà effectuée n'est pas annulée si un autre serveur
  échoue. La reprise vérifie l'état natif ; une absence confirmée est idempotente.
- Les jobs d'accès en cours reportent la suppression. Les jobs encore en file
  sont annulés après les vérifications, y compris si la suppression échoue ensuite,
  pour éviter qu'un ancien grant/sync ne rétablisse les accès.
- Une transaction par utilisateur sérialise la vérification d'éligibilité,
  les opérations et la suppression locale avec les écritures concurrentes.
  Les appels HTTP ont un timeout de 20 secondes et refusent les redirections.
  Les autres accès à la connexion DB partagée peuvent attendre pendant cette
  opération ; la transaction n'englobe pas tout le lot d'utilisateurs.
- Un renouvellement enregistré avant la transaction annule l'éligibilité.
  Il ne recrée jamais un compte déjà supprimé sur un serveur lors d'un échec partiel.

## Vérification

35 tests ciblés passent : adaptateurs natifs simulés, délai, exclusions,
renouvellement, échecs partiels, reprise, tâches et formulaires sur base temporaire
avec le vrai bootstrap. Aucun compte réel n'a été modifié.

Références : [API utilisateurs Jellyfin](https://typescript-sdk.jellyfin.org/classes/generated-client.UserApi.html)
et implémentation existante du retrait de partage dans
`app/tasks/apply_plex_access_updates.py`.
