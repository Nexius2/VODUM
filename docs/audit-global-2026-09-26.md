# Contrôle global — 26 septembre 2026

Contrôle réalisé sur la copie de travail locale, en conservant les modifications préexistantes. Les corrections ci-dessous sont locales ; aucun déploiement n'a été effectué.

## Anomalies confirmées et corrigées

| Anomalie | Conséquence | Correction |
| --- | --- | --- |
| Recommandation d'abonnement : absence de règle de plafond assimilée à zéro flux | Un abonnement personnalisé sans plafond de flux pouvait être écarté à tort | Distinguer absence de plafond et plafond explicitement égal à zéro, sans imposer de nom ni de règle fixe aux abonnements |
| Chemin SQLite en lecture seule non encodé en URI | Un chemin contenant notamment `#` ou `%` pouvait empêcher l'ouverture de la bonne base | Construire l'URI avec `Path.as_uri()` ; test de lecture et de refus d'écriture sur un chemin contenant ces caractères |
| Onglet de monitoring arbitraire utilisé pour choisir le template | Un onglet inconnu provoquait une erreur serveur | Valider les neuf onglets disponibles ; répondre 400 aux valeurs invalides, pour les pages complètes et HTMX |

Le diagnostic Jellyfin utilise désormais la connexion SQLite centralisée en lecture seule, avec fermeture explicite de la connexion.

## Vérifications

- **822 tests réussis, zéro échec**, répartis dans 198 fichiers. Chaque fichier a été exécuté dans un processus distinct pour isoler les remplacements de modules effectués par certains tests.
- Analyse syntaxique de 347 fichiers Python, 112 templates Jinja, 30 fichiers JavaScript et 15 fichiers JSON.
- Validation des traductions, des clés et paramètres de traduction, de la pagination partagée, des routes GET, du démarrage, des frontières des tâches médias, de la cohérence des données, de la file des tâches et de la rétention des sauvegardes.
- Validation du délai de transition entre lecteurs : le scénario testé conserve cinq minutes de grâce à partir du début de la transition.
- Démarrage réel de l'application sur une base temporaire ; contrôle de 39 requêtes couvrant les pages administrateur, les neuf onglets du monitoring, les fragments du tableau de bord et les pages du portail. Réponses attendues obtenues, y compris les redirections et les rejets d'onglets invalides.
- Tests de régression pour les trois anomalies corrigées. Vérification des différences Git sans erreur d'espacement.

Deux tests du portail dépendaient de sessions datées d'août devenues expirées : leurs horloges ou dates de préparation ont été corrigées. Le scénario du validateur de transition a également été remis en cohérence avec le début effectif de la transition. Il s'agissait de problèmes de tests, pas de trois nouvelles anomalies applicatives.

Résultats détaillés de la suite finale : `.tmp/global-audit-2026-09-26/summary.json` et journaux individuels du même dossier. Les contrôles de pages et les premiers validateurs sont dans `.tmp/global-audit-2026-09-25/` ; certains journaux initiaux conservent les échecs antérieurs aux corrections. Le validateur de transition a été relancé avec succès après correction.

## Limites

Ce contrôle couvre le code et les scénarios automatisés disponibles ; il ne garantit pas l'absence de tout bug. Aucune base de production ni session Plex/Jellyfin réelle n'a été utilisée. Il ne permet donc pas de confirmer directement les nouvelles tentatives de lecture après une coupure chez un utilisateur réel. Aucun test de charge, contrôle visuel dans le navigateur ou audit des vulnérabilités des dépendances n'a été réalisé.

Certains tests qui simulent une date très ancienne produisent des avertissements de journalisation sous Windows ; leurs assertions passent. Ce comportement de test n'a pas été assimilé à une panne en production.
