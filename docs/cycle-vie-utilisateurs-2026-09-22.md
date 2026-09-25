# Cycle de vie des utilisateurs — état du code au 22 septembre 2026

Cette cartographie couvre les traitements locaux existants. Elle ne réexécute
pas les validations sur les serveurs réels, confirmées par l'utilisateur.

## Actions et réglages actuels

| Réglage ou action | Traitement effectivement branché | Limites |
| --- | --- | --- |
| Suppression manuelle de la fiche | `routes/users_actions.py`, `_delete_vodum_user_everywhere` : suppression transactionnelle des données locales et relations associées | Aucun appel de suppression native. Les propriétaires Plex et administrateurs Jellyfin sont protégés par le contrôle de suppression. Une synchronisation peut réimporter un compte toujours présent sur le serveur. |
| `expiry_mode=none` | Désactivation des deux tâches d'expiration ; suppression des règles système de blocage d'expiration | Les calculs de statut et notifications ont leur propre fonctionnement. Les accès déjà retirés ne sont pas restaurés. Les jobs déjà envoyés ne sont pas annulés par ce changement de mode. |
| `expiry_mode=warn_only` | `expired_subscription_manager` crée une règle utilisateur `max_streams_per_user=0`, identifiée par `system_tag=expired_subscription` | Le `stream_enforcer` coupe la lecture ; ce n'est pas un simple avertissement. Les accès aux bibliothèques restent présents. |
| `expiry_mode=warn_then_disable` | Même blocage, puis retrait des bibliothèques lorsque `(aujourd'hui - expiration).days >= warn_then_disable_days` | Le délai part de la date contractuelle, pas du premier avertissement. Aucun compte natif n'est supprimé. |
| `expiry_mode=disable` | `disable_expired_users` retire les relations locales aux bibliothèques et crée les jobs d'application | Plex : `revoke`. Jellyfin : `sync` avec liste des bibliothèques vide. Ce n'est pas la désactivation native du compte Jellyfin. |
| `delete_after_expiry_days` | Valeur historique conservée en base et dans les chemins de sauvegarde compatibles | Aucun traitement ne lit cette valeur pour supprimer un utilisateur ou retirer ses accès. Le champ trompeur a été retiré des deux formulaires. |
| `enable_cron_jobs=0` | Les choix d'activation des tâches d'expiration sont conservés dans `enabled_prev`, sans relancer le gestionnaire | Ne constitue pas une annulation d'une opération déjà en cours. |

Pour Jellyfin, `core/providers/jellyfin_users.py` relit la politique, puis modifie
`EnableAllFolders` et `EnabledFolders`. Le retrait d'accès ne modifie pas
`IsDisabled` et ne supprime pas le compte.

## Renouvellement

`api/subscriptions.py:update_user_expiration` met à jour la date et recalcule
le statut contractuel. Une date supérieure ou égale à aujourd'hui supprime
immédiatement les règles système d'expiration, même si la tâche n'est plus active.
Les règles manuelles ne sont pas supprimées par ce nettoyage.

Lors d'une réactivation depuis le statut `expired`, le code annule les anciens
jobs Plex et demande une synchronisation par serveur Plex. Aucun mécanisme
équivalent Jellyfin n'est déclenché par cette fonction. Surtout, les tâches de
retrait effacent les relations aux bibliothèques sans sauvegarder les droits
antérieurs : demander une synchronisation ne garantit donc pas leur restitution.
Le mode `warn_only` conserve ces relations et évite ce problème de restauration.

La prolongation ne doit pas être assimilée à la réactivation d'un compte natif
désactivé ou supprimé. Le suivi de l'origine d'une désactivation et la protection
des blocages manuels restent à concevoir avant cette extension.

## Exceptions et écarts restant à traiter

- **Date frontière** : `update_user_status.compute_status` considère la date du
  jour comme expirée (`<=`), mais les tâches de retrait/blocage attendent une
  date strictement antérieure (`<`). Définir une convention commune, puis
  l'appliquer au statut, aux notifications et aux actions.
- **Exceptions** : `update_user_status` prolonge les dates des comptes avec
  `expiration_date_override` et des abonnements à vie. Les tâches de retrait et
  de blocage ne filtrent pas directement ces exceptions ; leur protection dépend
  donc de l'ordre des traitements. Les propriétaires/administrateurs bénéficient
  de protections dans la fiche et la synchronisation, pas d'un garde-fou commun
  dans les deux tâches d'expiration.
- **Invitations Plex** : `disable_expired_users` exclut un utilisateur ayant une
  invitation en attente sans compte Plex accepté. Cette exclusion porte sur
  l'utilisateur VODUM entier, y compris ses éventuels comptes Jellyfin, et n'est
  pas partagée par `expired_subscription_manager`.
- **Multi-serveurs** : les requêtes de sélection relient les bibliothèques selon
  le type de fournisseur, puis la suppression cible le serveur du compte média.
  Vérifier explicitement la correspondance de serveur et la granularité des
  invitations avant d'ajouter de nouvelles actions natives.
- **Confirmation et reprise** : le retrait local précède l'application distante
  par les jobs. Prévoir une sauvegarde des droits et distinguer demande, envoi,
  confirmation et échec avant d'étendre le renouvellement automatique.

## Corrections livrées avec cette cartographie

- Retrait du champ sans effet `delete_after_expiry_days` des formulaires, avec
  une explication indiquant qu'il n'existe pas de suppression automatique.
- Nettoyage centralisé des seules règles système d'expiration lors du passage
  à `none` ou `disable`, quel que soit le formulaire utilisé.
- Respect de l'arrêt du planificateur dans la page Abonnements et le service
  d'activation automatique des tâches d'expiration.
- Nettoyage d'une règle d'expiration résiduelle lorsque la date devient `NULL`.

La prochaine étape consiste à unifier les critères d'expiration et les
exceptions ci-dessus avant les actions natives Jellyfin distinctes.
