# VODUM — Évolution du moteur Collections : gestionnaire de listes internes

## 1. Contexte et objectif

VODUM est une application Flask exécutée dans un conteneur Docker, destinée à administrer des infrastructures Plex et Jellyfin, qu'il s'agisse d'un seul serveur ou d'une flotte de plusieurs serveurs.

VODUM possède déjà un moteur de gestion des collections, avec différents types de collections, des paramètres de génération, des fréquences d'actualisation, des priorités et des bibliothèques cibles.

Certaines collections utilisent actuellement des listes de médias hébergées sur Internet, notamment pour identifier des franchises ou des ensembles de films et séries.

Ces listes externes ne sont pas administrables directement depuis VODUM.

**L'objectif est de remplacer cette dépendance aux listes statiques externes par un catalogue de listes internes à VODUM**, tout en permettant aux administrateurs de consulter, personnaliser et créer leurs propres listes.

Les collections dynamiques reposant sur des requêtes à des API externes doivent conserver leur fonctionnement actuel.

Le développement doit s'intégrer à l'architecture existante, sans créer de nouveau service ni réécrire inutilement le moteur Collections.

---

## 2. Nouvelle interface : Collections → Lists

Ajouter un onglet **Lists** dans la section Collections existante.

Cet onglet permet de :

- Consulter toutes les listes disponibles.
- Rechercher et filtrer les listes.
- Identifier les listes officielles et personnalisées.
- Voir les collections VODUM auxquelles chaque liste est rattachée.
- Voir le nombre de films et de séries de chaque liste.
- Consulter les médias d'une liste.
- Ajouter des médias.
- Retirer les médias ajoutés personnellement.
- Exclure des médias officiels.
- Annuler les exclusions.
- Créer, modifier, désactiver ou supprimer des listes personnalisées.
- Associer une liste à une ou plusieurs collections VODUM existantes.

L'interface doit respecter le design, les composants, les traductions et les conventions de navigation déjà présents dans VODUM.

Ne pas créer une interface d'administration indépendante.

## 3. Deux catégories de listes

### 3.1. Listes officielles VODUM

Les listes officielles sont fournies avec l'application.

Elles remplacent les listes statiques actuellement téléchargées depuis des sources externes.

Elles doivent :

- Être livrées avec les mises à jour de VODUM.
- Posséder un identifiant stable.
- Être versionnées.
- Pouvoir être enrichies ou corrigées lors des mises à jour.
- Être consultables par les administrateurs.
- Accepter les personnalisations locales.
- Ne jamais écraser ces personnalisations lors d'une mise à jour.

Les médias officiels ne doivent pas pouvoir être supprimés directement de la source officielle par l'administrateur.

L'administrateur peut cependant les exclure de sa liste effective.

### 3.2. Listes personnalisées

Les administrateurs peuvent créer leurs propres listes.

Une liste personnalisée possède au minimum :

- Un identifiant unique.
- Un nom.
- Une description facultative.
- Un état actif/inactif.
- Une liste de médias.
- Une ou plusieurs associations à des collections VODUM.

L'administrateur peut modifier librement ses listes personnalisées.

Les listes personnalisées doivent être conservées lors des mises à jour de VODUM.

---

## 4. Structure des médias

**Une liste peut contenir simultanément des films et des séries.**

Ne pas imposer de type Movie, TV ou Mixed au niveau de la liste.

C'est chaque média qui possède son propre type.

Informations minimales pour chaque média :

- Type : `movie` ou `tv`.
- Identifiant TMDB.
- Identifiant TVDB lorsqu'il est disponible et utile.
- Titre.
- Année.
- Origine : officielle ou personnalisée.
- État : actif ou exclu.

Utiliser les identifiants des fournisseurs pour identifier les médias, et non leurs titres.

Pour éviter les collisions, l'identité d'un média doit tenir compte du fournisseur, du type et de l'identifiant.

Exemple :

`tmdb:movie:12345`

`tmdb:tv:67890`

Les métadonnées descriptives peuvent être mises en cache selon les mécanismes déjà disponibles dans VODUM.

Ne pas dupliquer inutilement les informations accessibles via TMDB/TVDB.

---

## 5. Gestion des médias dans une liste

### 5.1. Ajout

L'administrateur doit pouvoir rechercher un média depuis l'interface.

La recherche doit accepter les films et les séries.

Chaque résultat doit afficher :

- Titre.
- Année.
- Affiche si disponible.
- Type Movie ou TV.
- Identifiant du fournisseur.

L'administrateur sélectionne le média à ajouter.

VODUM vérifie qu'il n'existe pas déjà dans la liste.

### 5.2. Suppression d'un ajout personnel

Un média ajouté personnellement peut être retiré de la liste.

Cela supprime uniquement son association avec la liste.

Aucun fichier média ne doit être supprimé.

### 5.3. Exclusion d'un média officiel

Un média provenant du catalogue officiel ne peut pas être supprimé directement.

L'administrateur peut l'exclure.

Le média reste visible dans l'interface, avec un statut Excluded.

Il n'est plus utilisé lors de la génération des collections.

### 5.4. Réintégration

Un média exclu peut être réintégré à tout moment.

Il redevient actif lors de la prochaine synchronisation.

### 5.5. Séparation des données

Les médias officiels et les modifications locales doivent être conservés séparément.

Pour une liste officielle, le contenu effectif correspond à :

**Médias officiels + ajouts personnels − exclusions locales**

Cette séparation est obligatoire pour garantir la persistance des personnalisations.

Si un média disparaît du catalogue officiel lors d'une mise à jour, il ne doit pas rester artificiellement dans la liste effective, sauf s'il existe aussi comme ajout personnel explicite.

---

## 6. Association des listes aux collections

Une liste peut être rattachée à une ou plusieurs collections VODUM.

Une collection VODUM peut utiliser plusieurs listes.

Exemple :

Collection VODUM : **Franchises**

Listes associées :

- Fast & Furious
- Harry Potter
- Jurassic Park
- Mission Impossible
- James Bond
- Toute autre liste créée par l'administrateur

Chaque liste doit pouvoir générer une collection distincte sur Plex ou Jellyfin, conformément au fonctionnement de la collection VODUM à laquelle elle est associée.

### Exemple : Harry Potter

L'administrateur crée une liste Harry Potter.

Il ajoute les huit films, puis éventuellement des spin-offs ou des séries.

Il rattache cette liste à la collection VODUM Franchises.

Lors de la prochaine synchronisation :

1. VODUM récupère les médias actifs de la liste Harry Potter.
2. Il identifie les films et les séries.
3. Il utilise les bibliothèques configurées pour la collection Franchises.
4. Il recherche chaque média dans les bibliothèques compatibles.
5. Il crée ou met à jour les collections Harry Potter correspondantes sur Plex/Jellyfin.

Une nouvelle liste personnalisée doit donc pouvoir produire une nouvelle collection Plex/Jellyfin sans modification du code source de VODUM.

Ne pas coder en dur les noms des franchises.

---

## 7. Gestion des bibliothèques Films et Séries

Une liste étant potentiellement mixte, VODUM doit déterminer la destination de chaque média selon son type.

Règles :

- Les médias `movie` sont recherchés uniquement dans les bibliothèques de films compatibles.
- Les médias `tv` sont recherchés uniquement dans les bibliothèques de séries compatibles.
- Les bibliothèques cibles sont celles définies par les paramètres existants de la collection VODUM.
- Une liste peut générer une collection dans plusieurs bibliothèques et sur plusieurs serveurs.
- Une même liste peut produire des collections de même nom dans des bibliothèques Films et Séries différentes.
- Seuls les médias effectivement présents dans une bibliothèque sont ajoutés à sa collection.
- Une bibliothèque sans média correspondant ne doit pas recevoir de collection vide.

Utiliser les mécanismes existants de résolution des médias et de communication avec Plex/Jellyfin.

Tenir compte des différences éventuelles entre les API et les comportements de Plex et Jellyfin.

---

## 8. Évolution des sources du moteur Collections

Toutes les collections actuelles ne doivent pas devenir des collections basées sur des listes.

Distinguer conceptuellement trois mécanismes de génération.

### A. Lists

Collections utilisant des listes de médias prédéfinies.

Exemples :

- Franchises.
- Univers cinématographiques.
- Collections thématiques fondées sur des listes statiques.

Ces collections doivent désormais utiliser les listes internes VODUM.

### B. Dynamic

Collections alimentées par des requêtes vers des services externes.

Exemples :

- In the Spotlight.
- Awards.
- Platforms.
- Autres collections reposant sur des données dynamiques externes.

**Ces collections doivent conserver leurs requêtes et leur comportement actuel.**

Ne pas les convertir artificiellement en listes statiques.

### C. Rules

Collections utilisant des règles ou des critères de sélection.

Exemples :

- Genres.
- Dates.
- Langues.
- Pays.
- Critères éditoriaux.
- Autres filtres existants.

Ces collections doivent également conserver leur fonctionnement actuel.

Cette classification sert à organiser l'architecture interne. Elle ne nécessite pas forcément l'ajout de nouveaux types visibles dans l'interface.

Une collection combinant plusieurs mécanismes doit pouvoir conserver ce fonctionnement.

---

## 9. Migration des listes externes existantes

Cette étape est essentielle.

Avant toute modification, effectuer un audit complet du moteur Collections actuel.

Identifier :

- Tous les types de collections.
- Les collections utilisant des listes statiques externes.
- Les URL et fournisseurs de ces listes.
- Les formats des données.
- Les mécanismes de récupération.
- Les traitements effectués sur les médias.
- Les éventuelles listes générées ou transformées dynamiquement.
- Les dépendances entre listes et collections.
- Les mécanismes de création et de mise à jour Plex/Jellyfin.

À partir de cet inventaire, migrer les listes statiques pertinentes dans le catalogue officiel VODUM.

Ne pas convertir aveuglément toutes les sources externes.

Conserver les identifiants, les associations et les comportements existants lorsque cela est possible.

La migration doit être compatible avec les installations déjà déployées.

Elle ne doit pas nécessiter que les administrateurs recréent leurs collections.

Prévoir un mécanisme de migration idempotent, afin qu'un redémarrage ou une nouvelle mise à jour ne duplique pas les listes.

---

## 10. Synchronisation avec Plex et Jellyfin

Le moteur de synchronisation doit utiliser le contenu effectif des listes.

Il doit prendre en compte :

- Les médias officiels actifs.
- Les ajouts personnels.
- Les exclusions.
- Les listes personnalisées.
- Les associations entre listes et collections.
- Les bibliothèques et serveurs cibles.
- Les paramètres existants de la collection.

Lorsqu'une liste est modifiée, la synchronisation suivante doit refléter les changements.

Conserver les mécanismes existants de fréquence, priorité, ordre, affichage Home et autres paramètres des collections.

Éviter les reconstructions complètes lorsque des mises à jour incrémentales sont possibles.

### Suppression et désactivation

Lorsqu'une liste personnalisée est désactivée ou supprimée, définir un comportement sûr pour les collections Plex/Jellyfin précédemment générées.

Ne pas supprimer automatiquement une collection distante sans vérifier qu'elle est bien gérée par VODUM et qu'aucune autre association active ne l'utilise.

Une suppression explicite doit être confirmée par l'administrateur.

**Aucune opération sur les fichiers physiques des médias n'est autorisée.**

---

## 11. Mise à jour des listes officielles

Dans cette première version, les listes officielles sont livrées avec les mises à jour de VODUM.

Ne pas développer de système de publication externe, de serveur central ou de synchronisation GitHub.

Le catalogue officiel doit cependant être organisé proprement, par exemple sous forme de fichiers JSON versionnés, pour faciliter son enrichissement ultérieur.

Lors d'une mise à jour :

1. VODUM détecte la nouvelle version du catalogue.
2. Il met à jour les définitions officielles.
3. Il conserve les ajouts et exclusions locaux.
4. Il conserve les listes personnalisées.
5. Il conserve les associations configurées par les administrateurs.
6. Il prépare les synchronisations nécessaires.

Une mise à jour du catalogue ne doit pas écraser les paramètres locaux.

---

## 12. Interface détaillée

### Vue principale Lists

Afficher un tableau ou une liste avec :

- Nom.
- Origine : Official / Custom.
- Nombre de films.
- Nombre de séries.
- Collection(s) VODUM associée(s).
- Nombre d'ajouts personnels.
- Nombre d'exclusions.
- État actif/inactif.
- Actions disponibles.

Prévoir des filtres et une recherche.

### Fiche d'une liste

Afficher :

- Nom et description.
- Origine.
- Associations aux collections VODUM.
- Nombre de médias actifs.
- Nombre de médias exclus.
- Contenu détaillé.
- Recherche pour ajouter un média.
- Actions de suppression ou d'exclusion selon son origine.

Chaque média doit afficher clairement son type, son origine et son état.

### Création d'une liste

Champs nécessaires :

- Nom.
- Description facultative.
- Collection(s) VODUM associée(s).
- Activation.

Ne pas demander si la liste est destinée aux films ou aux séries.

### Indication de présence dans les bibliothèques

Si les informations nécessaires sont déjà disponibles dans VODUM, afficher éventuellement le nombre de médias présents dans les bibliothèques concernées.

Exemple :

Harry Potter — 8 films

- Plex Movies : 8/8
- Jellyfin Movies : 6/8

Cette fonctionnalité est secondaire et ne doit pas bloquer le développement principal.

---

## 13. Contraintes techniques

Respecter impérativement les points suivants :

- VODUM reste une application Flask conteneurisée et indépendante du système hôte.
- Aucune dépendance à un OS particulier.
- Aucun nouveau conteneur obligatoire.
- Aucun service externe supplémentaire.
- Aucune intelligence artificielle.
- Aucune clé API supplémentaire si les intégrations existantes suffisent.
- Réutiliser les modèles, services, tâches et composants déjà présents lorsque c'est pertinent.
- Respecter le système de traductions existant : EN, FR, DE, ES et IT.
- Respecter les mécanismes d'authentification et d'autorisation existants.
- Préserver les paramètres des collections actuelles.
- Préserver les données lors des mises à jour.
- Ne jamais manipuler les fichiers physiques des bibliothèques.
- Éviter les requêtes externes inutiles et les synchronisations coûteuses.

Ne pas imposer une nouvelle architecture complexe si une extension propre de l'architecture existante suffit.

---

## 14. Tests et validation

Prévoir au minimum les scénarios suivants.

### Listes

- Consultation d'une liste officielle.
- Création d'une liste personnalisée.
- Ajout d'un film.
- Ajout d'une série dans la même liste.
- Suppression d'un ajout personnel.
- Exclusion d'un média officiel.
- Réintégration d'un média exclu.
- Prévention des doublons.
- Conservation des personnalisations après mise à jour.

### Collections

- Association d'une nouvelle liste à Franchises.
- Création de la collection correspondante sur Plex.
- Création de la collection correspondante sur Jellyfin.
- Répartition correcte des films et séries.
- Gestion des médias absents des bibliothèques.
- Mise à jour d'une collection après modification de liste.
- Désactivation et suppression sécurisées.
- Conservation des collections dynamiques existantes.

### Migration

- Migration d'une installation existante.
- Conservation des paramètres.
- Absence de doublons.
- Absence de suppressions intempestives.
- Compatibilité après redémarrage.
- Nouvelle exécution de la migration sans effet indésirable.

---

## 15. Méthode de travail demandée à Codex

Ne pas commencer par réécrire le moteur Collections.

Procéder par étapes.

### Phase 1 — Audit

Analyser le code existant et produire un inventaire précis des collections, des sources externes, des formats de listes et des mécanismes de synchronisation.

Identifier les éléments réutilisables et les risques de migration.

### Phase 2 — Conception

Proposer les modifications minimales nécessaires :

- Modèles de données.
- Catalogue officiel.
- Personnalisations locales.
- Associations listes/collections.
- Services de résolution.
- Adaptations du moteur Collections.
- Interface Lists.

Présenter les impacts sur les fonctionnalités existantes.

### Phase 3 — Développement

Implémenter progressivement les modifications validées.

Privilégier des changements ciblés, maintenables et compatibles avec les installations existantes.

### Phase 4 — Migration et tests

Migrer les listes statiques externes, tester les collections concernées et vérifier que les collections dynamiques et les collections basées sur des règles continuent de fonctionner normalement.

Ne pas considérer le développement terminé tant que les scénarios de non-régression ne sont pas validés.

---

## 16. Hors périmètre

Ne pas développer pour cette évolution :

- VODUM Center.
- Intelligence artificielle.
- API OpenAI, Grok, Gemini ou autres fournisseurs IA.
- Hébergement local de modèles IA.
- Gestion multi-fournisseurs IA.
- Télémétrie centralisée.
- Catalogue communautaire.
- Publication automatique de listes sur GitHub.
- Service de mise à jour distant des listes.
- Nouvelle infrastructure de synchronisation.

Ces idées pourront éventuellement être étudiées ultérieurement.

---

## 17. Résultat attendu

À l'issue du développement :

1. VODUM possède un onglet Lists intégré à Collections.
2. Les listes statiques utilisées par les collections sont gérées en interne.
3. Les administrateurs peuvent consulter et personnaliser les listes officielles.
4. Ils peuvent créer librement de nouvelles listes.
5. Chaque liste peut contenir simultanément des films et des séries.
6. Chaque liste peut être associée à une ou plusieurs collections VODUM.
7. Une nouvelle liste associée à Franchises peut générer automatiquement sa propre collection Plex/Jellyfin.
8. Les modifications sont prises en compte lors des synchronisations.
9. Les listes officielles peuvent évoluer avec les mises à jour VODUM sans écraser les personnalisations.
10. Les collections dynamiques et les collections basées sur des règles conservent leur fonctionnement.
11. Les installations existantes sont migrées sans perte de configuration.
12. Aucun fichier média physique n'est modifié ou supprimé.

**Objectif final : faire de VODUM un gestionnaire autonome, extensible et administrable de listes de médias, entièrement intégré à son moteur Collections existant, sans complexité technique inutile.**

**Instruction finale à Codex : commencer par l'audit du code actuel, identifier les collections réellement concernées et proposer un plan de migration avant toute modification importante. Ne pas supposer que toutes les collections utilisent des listes externes.**