# Règles de développement VODUM

## Changelog obligatoire

- Mettre à jour `changelog.md` dans le même travail que toute modification
  fonctionnelle, correction, migration, évolution d'interface ou modification
  documentaire significative. Cette étape doit être terminée avant la réponse
  finale, même si aucun commit ni déploiement n'est demandé.
- Ajouter les entrées en tête, dans la section « Non publié », avec la date de
  mise à jour. Regrouper par fonctionnalité et expliquer les effets concrets.
- Mentionner les migrations, l'ordre de déploiement et les limites importantes.
  Ne pas annoncer une correction validée en production sur la seule base de tests.
- Ne pas inventer de version ou de date de publication. Ne pas modifier `INFO`
  pour une simple mise à jour du journal et préserver les entrées historiques.
- Avant de terminer, vérifier que le changelog couvre les changements du travail
  en cours et que ses liens vers les fichiers locaux existent.

## Fichiers de travail des agents

- Conserver les fichiers servant uniquement au travail de l'agent dans
  `tools/codex/` : logs dans `logs/`, audits dans `audits/`, rapports dans
  `reports/`, fichiers temporaires et captures de validation dans `tmp/`.
- Ne pas créer ces fichiers à la racine du dépôt ni ajouter une nouvelle règle
  `.gitignore` pour chaque artefact. `tools/` est déjà ignoré par Git et exclu
  de l'image Docker. Configurer aussi les sorties des commandes dans ce dossier.
- Garder les tests dans `tests/` et les outils réutilisables existants dans `tools/`.
  Ne pas déplacer les sources, documents du projet ou captures publiées utilisées
  par VODUM pour les confondre avec des artefacts de validation locaux.
