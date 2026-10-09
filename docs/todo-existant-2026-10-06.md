# Reprise du TODO : fonctions existantes, 6 octobre 2026

Controle du premier lot dans le code local, sans modification de comptes reels.

| Point | Existant | Travail restant |
| --- | --- | --- |
| Acces Jellyfin | `core/user_library_access.py`, `tasks/apply_jellyfin_access_updates.py` : selection des bibliotheques et jobs de synchronisation | Desactivation native reversible distincte du retrait des bibliotheques |
| Suppression native | `core/native_user_deletion.py` : suppression Jellyfin par ID, retrait du partage Plex par serveur, verification native | Exposer une action manuelle par compte/serveur sans supprimer la fiche VODUM |
| Suppression apres expiration | `core/expired_user_deletion.py`, `tasks/delete_expired_users.py` : delai, exclusions, preflight, confirmation et suppression locale finale | Validation representative apres deploiement ; ne pas dupliquer le mode existant |
| Renouvellement | Controle transactionnel de l'eligibilite avant suppression ; les comptes supprimes ne sont pas recrees | Provenance et restauration des droits pour la future desactivation native Jellyfin |
| Suppression locale | `core/user_deletion.py`, route `user_delete` : suppression de la fiche VODUM | Conserver cette operation distincte des futures actions natives manuelles |
| Jellyfin IsDisabled | `tasks/sync_jellyfin.py` lit le statut natif ; la fiche l'affiche | Action manuelle ajoutee dans `core/jellyfin_account_state.py` ; cycle automatique et provenance des blocages encore au TODO |
| Refresh | `core/library_refresh.py`, fournisseurs et route POST deja presents ; message de succes Jellyfin deja explicite | Libelle avant execution corrige ; scan cible a etudier separement |
| Capacites | `core/providers/base.py`, registre des fournisseurs | Registre supporte/interdit/indisponible/non teste par version et identite encore distinct |
| Historique abonnements | Historique des cadeaux dans Subscriptions | Historique contractuel du portail encore distinct ; ne pas assimiler les deux |

Ce controle ne cloture pas les audits de securite ni les validations sur la vraie
installation. Les reprises existantes sont celles des jobs d'acces et de suppression,
pas une garantie pour les futures actions natives.
