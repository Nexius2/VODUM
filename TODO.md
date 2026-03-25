# TODO VODUM — audit bugs, anomalies et évolutions

> Audit réalisé sur le zip fourni (`vodum.zip`).
> J’ai vérifié la structure, la compilation Python, le bootstrap DB sur base vierge, les traductions, l’architecture d’import, et quelques points de cohérence applicative.

---

## 1. Critique — corriger en priorité

- [X] **Supprimer le double démarrage implicite de l’application et du scheduler**
  - **Fichier :** `app/app.py`
  - **Problème :** le module crée une instance globale avec `app = create_app()` puis démarre le scheduler au chargement du module.
  - **Impact :**
    - risque de **double initialisation** de l’app Flask ;
    - risque de **double scheduler** / tâches lancées plusieurs fois ;
    - comportements différents selon qu’on importe `app`, `app.app` ou `run.py`.
  - **Indice concret :** `run.py` recrée ensuite encore une app avec `app = create_app()`.
  - **Action attendue :** garder **une vraie app factory pure** dans `app/app.py`, et déplacer le démarrage runtime/scheduler uniquement dans `run.py`.

- [ ] **Corriger `tools/smoke_routes.py` qui cible probablement le mauvais objet**
  - **Fichier :** `tools/smoke_routes.py`
  - **Problème :** le script fait `import app as appmod` puis `flask_app = appmod.app`.
  - **Risque réel :** dans ce contexte, `appmod.app` peut référencer le **sous-module `app.app`** et non l’instance Flask.
  - **Impact :** le smoke test peut être trompeur, cassé, ou ne pas tester la bonne instance.
  - **Action attendue :** importer explicitement `from app import create_app` puis construire l’app dans le script de test.

- [ ] **Stabiliser l’architecture d’imports internes**
  - **Fichiers concernés :** une grande partie du projet (`app/app.py`, `app/routes/*`, `app/tasks/*`, `app/core/*`, etc.)
  - **Constat :** j’ai relevé **beaucoup d’imports absolus internes** (`from logging_utils import ...`, `from db_manager import ...`, `from core...`) qui ne tiennent que grâce à `app/module_aliases.py` et aux shims `app/core/*.py`.
  - **Impact :**
    - exécution fragile selon le point d’entrée ;
    - scripts/tests plus difficiles à lancer proprement ;
    - forte dette technique ;
    - risque de bugs subtils lors de futurs refactors.
  - **Action attendue :** migrer progressivement vers des imports canoniques et cohérents (`from app...` ou imports relatifs internes).

---

## 2. Important — bugs fonctionnels / incohérences visibles

- [ ] **Compléter les clés de traduction manquantes dans certaines langues**
  - **Fichiers :** `lang/de.json`, `lang/es.json`, `lang/it.json`
  - **Clés manquantes détectées :**
    - `comm_provider_all`
    - `comm_trigger_event`
    - `comm_trigger_user_creation`
  - **Impact :** affichage brut des clés dans l’UI Communications/Templates au lieu d’un vrai libellé.

- [ ] **Corriger les messages utilisateurs encore codés en dur**
  - **Fichiers repérés :**
    - `app/routes/auth.py`
    - `app/routes/servers.py`
    - `app/routes/users_detail.py`
    - `app/routes/settings.py`
    - `app/routes/monitoring_user.py`
    - `app/routes/backup.py`
  - **Problème :** plusieurs `flash(...)` utilisent directement du texte FR/EN au lieu d’une clé de traduction.
  - **Impact :**
    - interface partiellement non traduite ;
    - mélange FR/EN selon le flux ;
    - maintenance i18n plus compliquée.
  - **Action attendue :** remplacer tous les messages codés en dur par des clés `t(...)` / clés de flash dédiées.

- [ ] **Nettoyer la coexistence ancienne / nouvelle logique des campagnes d’expiration**
  - **Fichier :** `app/db_bootstrap.py`
  - **Constat :** la tâche legacy `send_expiration_emails` est encore créée, en parallèle des tâches plus récentes (`send_mail_campaigns`, `send_comm_campaigns`, `send_expiration_discord`, etc.).
  - **Impact :**
    - confusion dans l’UI Tasks ;
    - risque de logique legacy oubliée ;
    - dette de migration incomplète.
  - **Action attendue :** décider clairement si cette tâche est encore supportée ou si elle doit disparaître définitivement.

- [ ] **Rendre `db_bootstrap.py` autonome ou expliciter sa dépendance au schéma initial**
  - **Fichier :** `app/db_bootstrap.py`
  - **Constat :** lancé seul sur une DB vide, il échoue tant que `tables.sql` n’a pas été importé avant.
  - **Impact :** ce n’est pas bloquant en prod via `entrypoint.sh`, mais c’est piégeux pour le debug, les tests et les scripts manuels.
  - **Action attendue :** soit documenter clairement cette précondition, soit faire un garde-fou plus propre dans le script.

---

## 3. Moyen — anomalies, dette technique, comportements à fiabiliser

- [ ] **Éliminer les side effects au chargement des modules**
  - **Fichiers :** `app/app.py` principalement
  - **Problème :** importer le module ne devrait pas démarrer de scheduler ni construire d’instance globale automatiquement.
  - **Action attendue :** séparer strictement :
    - factory ;
    - bootstrap runtime ;
    - exécution CLI / serveur.

- [ ] **Réduire la duplication “compatibility shims” entre `app/` et `app/core/`**
  - **Fichiers :** `app/core/db_manager.py`, `app/core/logging_utils.py`, etc.
  - **Constat :** plusieurs fichiers `app/core/*` ne sont que des wrappers vers les modules racine.
  - **Impact :**
    - bruit ;
    - confusion sur le vrai module source ;
    - maintenance plus risquée.
  - **Action attendue :** garder une seule source de vérité à terme.

- [ ] **Dédupliquer certains blocs du bootstrap DB**
  - **Fichier :** `app/db_bootstrap.py`
  - **Constat :** certains contrôles/logs reviennent plusieurs fois, par exemple la ligne `Monitoring history table verified` apparaît deux fois lors de l’exécution.
  - **Impact :** bruit dans les logs, difficulté à relire le bootstrap.

- [ ] **Nettoyer les imports de route manifestement inutiles / trop larges**
  - **Fichiers :** beaucoup de fichiers sous `app/routes/*`
  - **Constat :** de nombreuses routes importent systématiquement les mêmes helpers (`BackupConfig`, `ensure_backup_dir`, `create_backup_file`, etc.) alors qu’ils ne semblent pas tous utilisés localement.
  - **Impact :** startup plus lourd, lisibilité réduite, refactor plus dangereux.

- [ ] **Mettre à jour le `TODO.md` du repo**
  - **Fichier :** `TODO.md`
  - **Constat :** il est très en retard par rapport au code réel ; il ne reflète plus l’état du projet.

---

## 4. Base de données / migrations

- [ ] **Ajouter un vrai test d’idempotence du bootstrap**
  - **Fichiers :** `tables.sql`, `app/db_bootstrap.py`
  - **Constat :** le bootstrap passe bien après initialisation du schéma, mais il continue à relancer plusieurs étapes de migration/log à chaque démarrage.
  - **Action attendue :**
    - tester 1er démarrage / 2e démarrage / DB déjà migrée ;
    - vérifier qu’aucune duplication parasite n’est créée ;
    - réduire le bruit de log si la migration ne fait rien.

- [ ] **Ajouter un script de vérification de cohérence schéma ↔ code**
  - **But :** détecter automatiquement :
    - tables/colonnes manquantes ;
    - tâches déclarées sans implémentation ;
    - clés étrangères cassées ;
    - index attendus absents.

- [ ] **Documenter clairement la chaîne d’initialisation DB**
  - **Chaîne actuelle :** `tables.sql` → migration V1/V2 éventuelle → bootstrap idempotent.
  - **Pourquoi :** aujourd’hui la logique est correcte, mais pas assez évidente pour un futur debug manuel.

---

## 5. Qualité / tests / sécurité de régression

- [ ] **Mettre en place un vrai socle de tests automatiques**
  - **Minimum utile :**
    - test de création d’app (`create_app`) ;
    - test de bootstrap DB sur base vierge ;
    - test d’idempotence du bootstrap ;
    - test du scheduler (pas de double start) ;
    - test smoke des routes GET simples ;
    - test de traduction (aucune clé visible brute dans l’UI critique).

- [ ] **Ajouter une vérification automatique des clés i18n**
  - **But :** scanner `templates/`, `app/routes/`, `app/tasks/` et comparer avec `lang/*.json`.
  - **Gain :** éviter les régressions du type “clé affichée brute dans l’interface”.

- [ ] **Ajouter une CI minimale**
  - **Étapes recommandées :**
    - compilation Python (`compileall`) ;
    - test bootstrap SQLite temporaire ;
    - smoke routes ;
    - contrôle des traductions.

- [ ] **Ajouter un check de lint / style**
  - **Objectif :** homogénéiser imports, détecter variables inutilisées, code mort, doublons évidents.

---

## 6. Évolutions utiles (hors bugs purs)

- [ ] **Refactorer le démarrage applicatif en 3 couches claires**
  - `create_app()` pur
  - `start_scheduler(app)` explicite
  - `run.py` comme seul point d’entrée runtime

- [ ] **Créer un mode “maintenance / diagnostic” CLI officiel**
  - **But :** lancer facilement :
    - bootstrap DB ;
    - check schéma ;
    - smoke routes ;
    - contrôle traductions ;
    - contrôle tâches enregistrées.

- [ ] **Documenter l’architecture des tâches**
  - **But :** clarifier les tâches legacy vs nouvelles tâches unifiées (communications, expiration, import, monitoring).

- [ ] **Créer un vrai guide de contribution technique**
  - conventions d’import
  - conventions i18n
  - conventions migrations DB
  - conventions création de tâches

---

## 7. Résumé ultra-court

### À faire en premier
1. corriger `app/app.py` pour supprimer la double création d’app / double scheduler ;
2. corriger `tools/smoke_routes.py` ;
3. nettoyer les imports internes et réduire la dépendance aux alias ;
4. compléter les traductions manquantes + supprimer les `flash()` codés en dur ;
5. clarifier la suppression ou la survie de `send_expiration_emails`.

### Ensuite
6. ajouter tests + CI minimale ;
7. alléger `db_bootstrap.py` et le rendre plus lisible/idempotent ;
8. remettre `TODO.md` du repo à jour.

