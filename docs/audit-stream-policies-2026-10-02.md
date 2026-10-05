# Contrôle des policies et du risque d'usage — 2 octobre 2026

## Conclusion

Les correctifs de l'audit du 24 septembre sont toujours présents dans le dépôt actuel : les appareils indépendants ne sont plus fusionnés définitivement et les délais de transition restent bornés. Les captures montrent un avertissement puis un arrêt le 24 septembre. Au 2 octobre, zéro action sur sept jours est compatible avec ce dernier événement, situé plus de sept jours auparavant.

La cause de l'absence de nouveaux événements en production n'est pas établie. Aucune base ou journal de production n'est disponible dans l'espace de travail. Le nombre de policies activées ne prouve ni leur application aux sessions ni le bon fonctionnement des tâches.

Cet audit a trouvé et corrigé quatre défauts supplémentaires dans le code de développement. Ils ne constituent pas une preuve qu'ils ont causé le silence observé sur l'instance. Le dépôt contenait de nombreuses modifications locales avant cet audit ; elles ont été conservées. Aucun déploiement, arrêt de lecture réel ou envoi de notification n'a été effectué.

## Défauts reproduits et corrigés

1. **Comptage fragmenté entre comptes médias.** Les limites par utilisateur regroupaient les sessions avec le couple `(vodum_user_id, external_user_id)`. Un utilisateur VODUM associé à deux comptes médias pouvait donc avoir deux lectures/deux IP, chacune comptée séparément sous une limite de un. Le regroupement utilise maintenant l'identité VODUM ; les comptes non rattachés restent isolés par serveur. L'identité externe réelle du lecteur ciblé reste conservée dans les événements.
2. **Dépassement perdu lors de la revérification.** Si la cible passait d'un compte média/serveur à un autre compte du même utilisateur VODUM, la comparaison exigeait le même identifiant externe. La revérification suit maintenant l'utilisateur VODUM. Un compte non rattaché ne peut pas être suivi sur un autre serveur sur la seule égalité d'identifiants externes.
3. **Règle malformée susceptible de interrompre l'ensemble du contrôle.** Un JSON qui n'est pas un objet, ou un plafond non numérique, pouvait provoquer une exception dans la résolution/évaluation. Le chargement écarte maintenant ces règles, journalise leur identifiant et laisse les règles valides fonctionner. Un plafond négatif est également écarté ; zéro reste valide. Une règle écartée n'est pas appliquée et doit être réparée par l'administrateur.
4. **Blocages sous-comptés dans Usage Risk entre serveurs.** Les compteurs de blocages distincts utilisaient seulement la clé de session. Deux serveurs utilisant la même clé étaient assimilés à un incident. La déduplication utilise maintenant serveur + clé de session pour les fenêtres 7/30/90 jours ; les tentatives répétées sur la même session du même serveur restent dédupliquées.

Les nouveaux tests ont reproduit les échecs avant correction, puis passent après correction. Un scénario exécute aussi le contrôleur avec ses effets externes simulés et vérifie la génération de `warn` puis `kill`, ainsi que la conservation du compte média ciblé.

## Chaîne contrôlée et conditions à vérifier en production

| Étape | Comportement vérifié dans le code | Cause possible de silence à contrôler |
|---|---|---|
| Planification | Collecte et contrôleur utilisent des tâches périodiques, normalement à intervalle de 15 secondes ; le worker peut également demander un contrôle après collecte. | Interrupteur global des tâches, tâche désactivée, file bloquée, tâche en erreur. |
| Collecte Plex/Jellyfin | Les sessions sont normalisées puis stockées ; le compte est recherché sur le serveur par identifiant externe, puis par nom. | Échec réseau/authentification, cooldown, absence d'IP, comptes non rattachés. |
| Sessions admissibles | Dernière observation dans les 90 secondes, `missing_count=0`, serveur disponible et hors cooldown ; stabilité de 15 secondes, sauf expiration stricte. | Sessions obsolètes ou intermittentes, données de collecte manquantes. |
| Règles d'abonnement | Portée et héritage passent par le même résolveur pour le contrôle et le plafond IP d'Usage Risk. | Règle absente de l'instantané, portée serveur/fournisseur différente, limites volontairement illimitées. |
| Dérogations | Un `max_streams_override` positif remplace la limite de flux et exempte actuellement les limites IP et flux par IP. | Dérogations devenues positives sur les utilisateurs concernés. Ce comportement préexistant n'a pas été changé. |
| Transitions | Tolérances en mémoire de cinq minutes ; épisodes et clés renouvelés ne prolongent pas indéfiniment un chevauchement régulièrement observé. | Redémarrages récurrents, chevauchements courts, absence d'observations continues. |
| Actions | Avertissement enregistré, puis revérification après 45 secondes ; expiration stricte sans délai. Plex vérifie la disparition du lecteur après terminaison. | Dépassement réellement terminé avant revérification, échec d'arrêt, absence de nouveau contrôle. |
| Monitoring | Courbe : actions `warn` et `kill`. Tableau : comprend aussi les échecs. | Les totaux de règles incluent les échecs et peuvent dépasser les valeurs visibles sur les deux courbes. |
| Usage Risk | Analyse des événements de contrôle, plafonds effectifs, appareils/IP et blocages répétés. | Sans événement de contrôle, il n'y a pas d'analyse indépendante exhaustive des lectures historiques. |
| Recommandations | Réglages, seuils, abonnement suggérable, modèle de communication et délai entre envois. | Une absence de recommandation peut être normale même avec des hits. |

## Limites restantes

- Le worker de tâches est séquentiel. Les attentes du contrôleur (45 secondes, puis éventuellement 60 secondes de messages Jellyfin) peuvent retarder les collectes. La revérification relit la base sans effectuer une nouvelle collecte elle-même. Avec plusieurs dépassements dans la même exécution, les observations peuvent dépasser la fenêtre de fraîcheur ; une revérification peut aussi utiliser une observation qui précède le délai. Cette limite architecturale reste présente et n'explique pas à elle seule une absence d'avertissements pendant huit jours.
- Usage Risk lit au maximum 5 000 événements pour ses preuves. Un compte peut être exclu de cette fenêtre sur une instance très active. Les compteurs 7/30/90 jours et les preuves filtrées restent de périmètres différents.
- Les clés de session réutilisées au fil du temps sur un même serveur peuvent toujours sous-compter les incidents ; la correction serveur + session ne reconstitue pas des épisodes de lecture historiques distincts.
- Le score historique n'est pas une preuve de simultanéité ou de fraude. Déplacements, usages mobiles et limites réellement autorisées doivent être considérés.

## Validation

147 tests ciblés passent : contrôleur, fournisseurs et stockage des actions, héritage des règles, abonnements, délais de transition, risque d'usage, monitoring, migrations de tâches et diagnostic. Les tests simulent les fournisseurs ; aucun appel aux serveurs réels. La suite complète du dépôt n'a pas été exécutée.

Le diagnostic a également été exécuté contre une base temporaire créée depuis `tables.sql` : ses dix rubriques sont compatibles avec le schéma, sans erreur. Les tests vérifient qu'il conserve les octets d'une base existante et ne crée pas une base manquante.

Les anciens tests d'horloge artificielle peuvent provoquer des messages de journalisation Windows avec des dates proches de 1970. Pour la validation groupée, les gestionnaires de journalisation de fichiers ont été retirés du processus de test, en conservant la capture de logs utilisée par les assertions.

## Diagnostic de l'instance

Le fichier `app/diagnose_stream_policies.py` utilise uniquement SQLite en lecture seule (`mode=ro`, `query_only`), sans initialisation de l'application. Il ne contacte pas Plex/Jellyfin et n'envoie pas de message. Son JSON contient des compteurs et identifiants internes, sans noms de comptes, adresses IP, tokens ou mots de passe.

Dans un conteneur contenant ce fichier :

```sh
python /app/diagnose_stream_policies.py /appdata/database.db
```

Ou sur une copie locale existante :

```sh
python app/diagnose_stream_policies.py /chemin/vers/database.db
```

Le résultat indique l'état des tâches, les réglages de risque, les collectes, la fraîcheur et le rattachement des sessions, les dérogations, les règles invalides et les actions quotidiennes. Un échec de rubrique est explicitement signalé, jamais converti en zéro. Il faut compléter ces données par la version réellement déployée et les erreurs du journal du contrôleur/collecteur pour attribuer la cause du silence en production.
