# Relevés de langues (schéma 4)

La configuration de l'installation est distincte des langues observées :

- `default_language` : langue configurée ou `auto` lorsque le réglage est vide.
- `language_observations_json` : combinaisons distinctes zone (administration ou
  portail), configuration, préférence navigateur, langue effectivement affichée.

Le navigateur transmet sa préférence via Accept-Language. Seul le code de la
préférence de meilleure priorité positive est retenu, même s'il n'existe pas de
traduction correspondante. L'en-tête complet, les identifiants de visiteurs et
les informations de session ne sont pas collectés. La langue affichée inclut
le choix manuel de session et la résolution existante des langues ; observer
une différence ne prouve donc pas à elle seule l'absence de traduction.

La collecte a lieu lors du rendu des pages et uniquement lorsque la télémétrie
anonyme est activée. Les fragments HTMX sont exclus : ils ne constituent pas
de nouvelles préférences de navigation. Une connexion distincte sans attente
de verrou est utilisée ; si une écriture concurrente occupe SQLite,
l'observation facultative est ignorée et pourra être reprise à la prochaine
page complète. La collecte ne doit pas ralentir le rendu de l'interface.
Chaque combinaison est enregistrée au plus une fois par
jour. Conservation glissante de 30 jours, au plus 32 combinaisons par jour et
32 combinaisons distinctes envoyées par relevé. Il ne s'agit ni d'un nombre
de personnes, ni d'un nombre de visites. Les codes sont normalisés et bornés.

Le tableau central affiche les trois distributions puis les parcours croisés
`configuration → navigateur → interface`, avec les nombres d'installations
distinctes. Une installation peut figurer dans plusieurs lignes ; les totaux
des langues observées ne s'additionnent pas pour obtenir un nombre de personnes.
Les anciennes valeurs `unknown` restent « Unknown / legacy » ; il est impossible
de les reclasser rétrospectivement comme automatiques.

Ordre de déploiement :

1. Appliquer une fois `worker_telemetry/migration_20261102.sql` à D1.
2. Déployer le worker mis à jour, qui accepte aussi les anciens clients.
3. Déployer VODUM. La table locale est créée automatiquement au démarrage.

Le nouveau champ n'est pas accepté par les anciens workers : mettre le
récepteur à jour avant les clients. Aucun déploiement n'est effectué par cette
modification du dépôt.
