# Audit des collections — 1 novembre 2026

## Périmètre

Revue des 16 modèles de collections, des configurations groupées, du tri,
de Memoria, des sources, des publications Plex/Jellyfin, des reprises,
de l’inventaire partagé, des contrôles de visibilité et de l’interface.
Les parcours d’accès et les frontières CSRF ont également été vérifiés.

## Anomalies corrigées

1. **Inventaire Plex périmé bloquant une publication.** Des identifiants absents
   étaient retentés à chaque reprise et maintenaient la publication en attente.
   Deux identifiants du journal ont été vérifiés dans l’interface Plex : les
   deux consultations renvoient une 404. Après un refus d’ajout, VODUM vérifie
   l’existence du média. Une 404 confirmée est mémorisée par bibliothèque et
   génération d’inventaire. Le média est exclu des reprises et des prochaines
   sélections utilisant cet inventaire. Une actualisation réussie réinitialise
   ces exclusions. Un autre refus ou une panne réseau ne vaut pas une 404.
   Une erreur dans le lot initial de création est également prise en charge.
2. **Annulation pendant le remplacement d’une collection temporaire.**
   L’annulation ne déclenche plus de suppression de compensation. L’ancien
   identifiant est conservé dans une file persistante de prédécesseurs à
   nettoyer. La reprise et la suppression de la configuration vérifient à
   nouveau la propriété des anciens objets avant leur retrait.
3. **Score Memoria perdu pendant une indisponibilité de source.** Le dernier
   score connu est conservé si une nouvelle lecture ne fournit pas de score.
   Un score réellement égal à zéro reste pris en compte.
4. **Tri par sortie des médias connus seulement par leur année.** L’année
   disponible sert de repli au 1er janvier ; les dates complètes restent
   prioritaires pour préciser l’ordre au sein d’une année.
5. **Corps JSON de requête non conforme.** Les actions de recherche/gestion
   des personnes et de lancement rejettent les valeurs JSON qui ne sont pas
   des objets, plutôt que de provoquer une exception interne.
6. **Rafraîchissement bloqué après réception des en-têtes.** Le délai maximal
   couvre désormais aussi la lecture du corps JSON de la réponse.
7. **Tests dépendant de scripts privés retirés.** La comparaison optionnelle
   est conditionnée à leur présence. Un test autonome vérifie le classement
   fixe et la fusion des plateformes sans ces scripts.

## Vérification

- 609 tests Python de collections exécutés : 607 réussis, 2 ignorés.
- Les deux tests ignorés comparent des références externes non présentes.
- 9 scripts de tests JavaScript des collections réussis.
- 6 tests supplémentaires d’accès aux routes et de frontières CSRF réussis.
- Contrôle des espaces et conflits de diff : réussi.
- Tests de régression : média supprimé dans le lot initial et dans les ajouts,
  reprise avec une nouvelle instance d’adaptateur, réinitialisation après
  actualisation, refus d’un média existant, annulation, reprise de nettoyage,
  score manquant, année sans date complète, JSON invalide et réponse interrompue.

## Limites et déploiement

Les corrections sont locales. Aucun déploiement, changement de configuration,
ajout ni suppression de collection n’a été effectué sur le serveur réel.
La vérification Plex réelle était une consultation des deux médias en erreur.
Les tests des mutations utilisent des adaptateurs simulés ; ils ne constituent
pas une validation de tous les serveurs et versions de Plex/Jellyfin.

Après déploiement, le bootstrap ajoute les tables locales nécessaires. Si
« Par continent » est encore en cours, l’arrêter puis le relancer avec le
nouveau code. Actualiser l’inventaire partagé permet en plus de repartir de
la liste actuelle des médias. Les anciens journaux ne sont pas effacés.
