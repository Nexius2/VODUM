# Règles d'expiration — 23 septembre 2026

La date stockée est le dernier jour de validité. Une date au 23 septembre
reste valable le 23 ; le statut et les actions d'expiration s'appliquent à
partir du 24, lors du passage de leur tâche. Les tâches utilisent la date
locale du processus VODUM. Un délai de X jours est atteint quand la différence
entre aujourd'hui et la date d'expiration atteint X (minimum un jour).
Le préavis et la relance peuvent toujours être envoyés avant ou le dernier jour.

Le module `core/expiration_rules.py` centralise la lecture des dates et les
exemptions utilisées par le statut, les notifications automatiques, les
avertissements de lecture et les retraits d'accès. Les formats ISO et les
anciennes dates jour/mois/année sont reconnus. Une date invalide n'autorise
aucune action d'expiration.

Les abonnements à vie, overrides, propriétaires Plex et administrateurs
Jellyfin protègent la fiche entière, conformément à la portée de l'override
VODUM. Le statut manuel suspended/unfriended/disabled/removed est conservé.
Une fiche orpheline sans date garde son traitement historique de classement
expiré, sauf exemption ou statut manuel ; cela n'autorise pas sa suppression.

Une invitation Plex en attente protège son compte média. La prolongation
quotidienne de la date et le statut invited ne s'appliquent que si tous les
comptes concernés sont des invitations Plex en attente. Un compte actif sur
un autre serveur reste soumis à la date de la fiche. Les politiques système
stockent les identifiants des comptes éligibles (`expiration_media_user_ids`) ;
le moteur de lecture filtre les sessions sur cette liste et la fiche VODUM.
Les anciennes politiques sont actualisées au prochain passage du gestionnaire.
Les bibliothèques retirées appartiennent au serveur du compte ciblé.

Un renouvellement, une exemption ou une date retirée nettoie les blocages
système au passage du gestionnaire. Les politiques manuelles sont conservées.
Cette évolution ne restaure pas les accès déjà retirés ; la politique de
réactivation native reste un point distinct de la TODO.

La suppression définitive reste volontairement plus stricte : une invitation,
un compte protégé ou une identité native incertaine reporte la suppression
complète. Cela évite de supprimer une fiche contenant un compte encore
protégé. Voir [la suppression après expiration](suppression-expiration-2026-09-23.md).

Validation : 61 tests ciblés, dont 8 scénarios ajoutés pour les dates,
exemptions, installations mixtes, portée des politiques et bibliothèques,
nettoyage après renouvellement et idempotence. Les tests de suppression et
les formulaires sur schéma initialisé passent également. Les appels natifs
sont simulés ; les serveurs réels n'ont pas été modifiés.
