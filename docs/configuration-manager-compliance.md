# VODUM — Configuration Manager & Compliance
## Cahier des charges corrigé — À transmettre à Codex

### 1. Objectif

Développer un module centralisé permettant aux administrateurs VODUM de gérer les paramètres de configuration de leurs serveurs Plex et Jellyfin.

VODUM est une application hébergée dans un conteneur Docker. Elle doit fonctionner indépendamment du système d'exploitation de l'hôte et de celui des serveurs multimédias administrés.

Le module doit convenir à un administrateur possédant un seul Jellyfin comme à un administrateur gérant plusieurs dizaines de serveurs Plex.

Fonctionnement attendu :

**Configurer → Enregistrer un profil → Sélectionner les serveurs → Déployer → Vérifier la conformité → Corriger les écarts.**

### 2. Audit préalable

Avant toute modification, examiner les composants existants :

- Gestion des serveurs Plex et Jellyfin.
- Connexions et authentification aux API.
- Interface Servers / Libraries.
- Système de tâches planifiées.
- Tâche existante `check_servers`.
- Monitoring et alertes.
- Base de données et modèles.
- Traductions.
- Gestion des permissions administrateur.

**Réutiliser impérativement l'existant.**

Ne pas créer de nouveau mécanisme de vérification des serveurs si `check_servers` peut être étendu.

Ne pas perturber les fonctionnalités actuelles de VODUM.

### 3. Interface Server Configuration

Créer une interface **Server Configuration**, intégrée à l'administration existante.

Elle doit afficher dynamiquement les espaces de configuration disponibles.

**Règles de visibilité :**

- Au moins un serveur Plex configuré : afficher l'espace Plex.
- Au moins un serveur Jellyfin configuré : afficher l'espace Jellyfin.
- Les deux types présents : afficher les deux espaces.
- Aucun serveur configuré : afficher un état vide invitant à ajouter un serveur, sans onglets Plex/Jellyfin inutiles.

Les onglets doivent s'adapter automatiquement lorsqu'un serveur est ajouté ou supprimé.

Dans chaque espace, afficher les serveurs du type correspondant.

Prévoir une interface proche des paramètres natifs Plex et Jellyfin, avec des catégories adaptées :

- General
- Network
- Remote Access
- Transcoding
- Streaming
- Libraries
- Metadata
- Subtitles
- Scheduled Tasks
- Security
- Advanced

Les catégories doivent être affichées uniquement lorsqu'elles contiennent des paramètres disponibles.

L'objectif est de pouvoir consulter et modifier autant de paramètres que les API le permettent.

Chaque paramètre doit indiquer sa valeur actuelle, sa compatibilité et son caractère modifiable ou non.

### 4. Profils de configuration

Permettre de créer des profils réutilisables.

Un profil peut être :
- Créé manuellement.
- Généré depuis un serveur existant.
- Modifié.
- Dupliqué.
- Renommé.
- Supprimé.
- Affecté à un serveur ou à un groupe.

Les profils Plex et Jellyfin restent distincts.

Exemples :
- Plex Production
- Plex Test
- Jellyfin Production

Conserver une version courante du profil et les informations nécessaires aux déploiements.

**Ne pas développer un système complexe d'historisation des configurations.**

L'objectif est de gérer les configurations actuelles et leur conformité, pas de conserver des années d'évolution de paramètres.

### 5. Groupes de serveurs

Développer une véritable gestion des groupes.

Un administrateur doit pouvoir :
- Créer un groupe.
- Lui donner un nom et une description.
- Ajouter ou retirer des serveurs.
- Renommer ou supprimer le groupe.
- Affecter un profil à un groupe.
- Déployer une configuration sur tous les serveurs du groupe.

Un serveur peut appartenir à plusieurs groupes.

Exemples :
- Production
- Test
- Europe
- USA
- Serveurs Premium

Les groupes peuvent contenir plusieurs types de serveurs, mais un profil Plex ne doit cibler que les Plex compatibles et un profil Jellyfin uniquement les Jellyfin compatibles.

En cas de profils contradictoires, VODUM doit signaler le conflit et demander une résolution explicite.

Prévoir des groupes statiques dans un premier temps. Les groupes dynamiques pourront être ajoutés ultérieurement si nécessaire.

### 6. Déploiement des configurations

Créer une fonction **Deploy Configuration**.

Workflow :

1. Choisir un serveur source ou un profil.
2. Sélectionner un ou plusieurs serveurs destinataires.
3. Sélectionner les paramètres à appliquer.
4. Comparer les valeurs actuelles et attendues.
5. Afficher les paramètres incompatibles ou exclus.
6. Prévisualiser les modifications.
7. Confirmer.
8. Déployer.
9. Vérifier les résultats.

Les cibles peuvent être sélectionnées individuellement, par groupe ou globalement.

Les déploiements doivent être indépendants par serveur.

Un échec sur un serveur ne doit pas annuler les modifications réussies sur les autres.

Prévoir la possibilité de relancer les serveurs en échec.

**Exclusions par défaut :**

- Tokens et clés API.
- Identifiants uniques.
- Mots de passe.
- Certificats privés.
- Chemins locaux.
- Interfaces réseau.
- Ports spécifiques.
- URL propres aux serveurs.
- Paramètres matériels incompatibles.

Ces valeurs ne doivent pas être répliquées aveuglément.

### 7. Configuration Compliance

Créer un onglet **Compliance** dans le Configuration Manager.

Il doit permettre de visualiser immédiatement quels serveurs respectent leur configuration de référence.

Indicateurs :
- Nombre de serveurs conformes.
- Nombre de serveurs non conformes.
- Nombre de serveurs non vérifiés.
- Nombre de serveurs inaccessibles.
- Nombre d'écarts détectés.
- Date du dernier contrôle.

Les serveurs sans profil doivent être signalés comme non gérés par la conformité, et non comme conformes.

#### Vue par serveur

Sélectionner un serveur et afficher tous les paramètres non conformes.

Pour chaque écart :
- Paramètre.
- Catégorie.
- Valeur attendue.
- Valeur actuelle.
- Profil de référence.
- Possibilité de correction.

#### Vue par paramètre

Sélectionner un paramètre et afficher tous les serveurs concernés.

#### Configuration Matrix

Créer une matrice permettant de comparer plusieurs serveurs.

Exemple :

| Paramètre | Plex 01 | Plex 02 | Plex 03 |
|---|---|---|---|
| Transcodage matériel | OK | OK | Écart |
| Scan automatique | OK | Écart | OK |
| Limite de débit | OK | OK | Écart |

Un clic sur une cellule doit afficher les valeurs et les actions possibles.

Prévoir les filtres nécessaires pour rester utilisable avec plusieurs dizaines de serveurs.

### 8. Correction des écarts

Permettre :

- La correction d'un paramètre sur un serveur.
- La correction de tous les écarts sélectionnés d'un serveur.
- La correction d'un paramètre sur plusieurs serveurs.
- La correction des écarts d'un groupe.
- La correction des écarts sélectionnés de toute la flotte.

Avant application, afficher les changements prévus.

Après application, relire les valeurs via l'API pour confirmer leur prise en compte.

En cas d'échec, conserver les résultats des autres serveurs.

Prévoir des exceptions pour les paramètres propres à certaines machines.

Ne pas forcer une configuration incompatible.

### 9. Contrôle automatique via `check_servers`

**Réutiliser et enrichir la tâche existante `check_servers`.**

Ne pas créer un second ordonnanceur ou une tâche parallèle effectuant les mêmes contrôles.

Étudier le fonctionnement actuel de `check_servers` et y intégrer le contrôle de conformité.

Fonctionnement proposé :

1. Vérifier la disponibilité des serveurs comme actuellement.
2. Identifier les serveurs possédant un profil de configuration.
3. Récupérer les paramètres concernés par la conformité.
4. Comparer les valeurs aux profils.
5. Enregistrer le dernier résultat de conformité.
6. Mettre à jour les indicateurs de l'interface.
7. Signaler les nouveaux écarts si les notifications sont activées.

Le contrôle doit être non bloquant.

Une API lente ou inaccessible ne doit pas bloquer les vérifications des autres serveurs.

La fréquence doit réutiliser la configuration existante de `check_servers`, avec éventuellement une fréquence de conformité distincte si cela s'avère nécessaire.

Éviter les appels API inutiles.

Ne pas transformer `check_servers` en tâche lourde.

### 10. Surveillance des écarts

Si un paramètre est modifié directement dans Plex ou Jellyfin, VODUM doit pouvoir constater la différence lors du prochain contrôle.

Afficher :
- Le paramètre concerné.
- Sa valeur attendue.
- Sa valeur actuelle.
- Le serveur.
- Le dernier contrôle.

Ne pas développer une historisation exhaustive des changements.

Conserver uniquement les informations nécessaires au fonctionnement, au diagnostic et à la traçabilité des actions administratives.

Éviter de notifier plusieurs fois le même écart inchangé.

### 11. Modes de fonctionnement

Prévoir trois modes :

**Monitoring Only**

Détection des écarts sans modification.

**Manual Remediation**

Détection et correction sur validation de l'administrateur.

**Auto Remediation**

Correction automatique des paramètres explicitement autorisés.

Le mode par défaut doit être Monitoring Only.

La correction automatique ne doit jamais être activée implicitement.

Pour une première version, privilégier les corrections manuelles. Le mode automatique peut être préparé dans l'architecture et implémenté ultérieurement.

### 12. Sécurité

- Réutiliser les connexions API déjà configurées.
- Ne jamais exposer les secrets au navigateur.
- Vérifier les droits administrateur côté backend.
- Protéger les opérations groupées.
- Empêcher les déploiements contradictoires.
- Gérer les paramètres incompatibles.
- Prévoir des délais d'attente.
- Ne pas exécuter de commandes système arbitraires.
- Ne pas imposer SSH ou un agent sur les serveurs.
- Vérifier les valeurs après modification.

Conserver une journalisation raisonnable des opérations administratives, sans créer un système d'archivage complexe.

### 13. Architecture technique

Prévoir des composants logiques réutilisables :

- Plex Configuration Adapter.
- Jellyfin Configuration Adapter.
- Configuration Profiles.
- Server Groups.
- Configuration Diff Engine.
- Compliance Engine.
- Deployment Engine.

Réutiliser l'architecture Flask, les modèles de données et les services existants.

Ne pas multiplier inutilement les modules, tables ou tâches.

Les capacités de lecture et d'écriture doivent être vérifiées pour chaque paramètre, selon la plateforme et la version.

Les paramètres non modifiables doivent rester visibles en lecture seule lorsque cela apporte une information utile.

### 14. Interface et traductions

Respecter l'interface VODUM existante.

L'expérience doit rester simple pour un administrateur avec un seul serveur et efficace pour une flotte importante.

Prévoir :
- Recherche de paramètres.
- Filtres par catégorie.
- Sélection multiple.
- Indicateurs de conformité.
- Fenêtres de comparaison.
- Prévisualisation des déploiements.
- Messages d'erreur explicites.
- États de chargement.
- Affichage des opérations réussies et échouées.

Intégrer toutes les nouvelles chaînes au système de traduction existant : EN, FR, DE, ES et IT.

### 15. Ordre de développement

**Phase 1 — Audit et lecture des paramètres**
- Examiner le code existant.
- Étudier `check_servers`.
- Identifier les paramètres accessibles.
- Développer les interfaces Plex/Jellyfin avec affichage conditionnel.

**Phase 2 — Profils et groupes**
- Créer les profils.
- Importer une configuration depuis un serveur.
- Créer les groupes.
- Affecter les profils aux serveurs ou groupes.

**Phase 3 — Comparaison et conformité**
- Développer le moteur de comparaison.
- Créer la vue Compliance.
- Créer la Configuration Matrix.
- Intégrer les contrôles à `check_servers`.

**Phase 4 — Déploiement**
- Modifier les paramètres compatibles.
- Prévisualiser les changements.
- Déployer vers plusieurs serveurs.
- Vérifier les résultats.
- Gérer les échecs.

**Phase 5 — Corrections**
- Correction individuelle.
- Correction groupée.
- Exceptions locales.
- Notifications de non-conformité.
- Préparation des automatisations futures.

### 16. Tests obligatoires

Tester notamment :

- Installation avec un seul Jellyfin.
- Installation avec un seul Plex.
- Installation avec les deux plateformes.
- Installation sans serveur.
- Plusieurs dizaines de serveurs.
- Groupes mixtes.
- Profils incompatibles.
- Paramètres indisponibles.
- Serveur inaccessible.
- Déploiement partiellement réussi.
- Correction des écarts.
- Exceptions locales.
- Intégration à `check_servers`.
- Absence de régression des contrôles existants.
- Permissions administrateur.
- Traductions.

### 17. Résultat attendu

Un administrateur VODUM doit pouvoir :

1. Ouvrir les paramètres de son Plex ou Jellyfin.
2. Configurer les options accessibles.
3. Enregistrer la configuration comme profil.
4. Créer des groupes de serveurs.
5. Déployer le profil vers les serveurs souhaités.
6. Consulter une fenêtre indiquant précisément les serveurs non conformes.
7. Identifier les paramètres différents.
8. Corriger les écarts individuellement ou en groupe.
9. Laisser `check_servers` surveiller régulièrement la conformité.

### Instruction finale à Codex

Commencer par examiner le dépôt VODUM et les composants existants, notamment `check_servers`.

Ne pas développer de mécanismes parallèles inutiles.

Ne pas construire un système d'historisation complexe.

Respecter l'architecture Docker de VODUM et son indépendance vis-à-vis des systèmes d'exploitation.

Privilégier une solution simple, modulaire, maintenable et compatible avec les installations allant d'un seul serveur à une flotte importante.

**Après l'audit, présenter les éléments existants, les possibilités réelles des API Plex/Jellyfin, les limitations identifiées et les fichiers à modifier. Puis commencer l'implémentation progressive, avec tests à chaque phase.**