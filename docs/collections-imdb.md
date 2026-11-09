# Collections IMDb

Les classements autorisés comprennent les Top 250 films et séries, les films et séries populaires, le Bottom 100, le box-office, ainsi que les classements anglophones, indiens, tamouls, télougous et malayalam.

La lecture utilise directement GraphQL IMDb. Les pages HTML et le secours Chromium ne font plus partie de ce parcours. Les réponses partielles ou contenant des erreurs sont rejetées ; le classement complet est validé avant publication et mis en cache six heures. Les identités sont résolues par identifiant IMDb dans le catalogue TMDb correspondant au type de média.

## Limite locale et acquisition

Une limite de 20 désigne 20 films ou séries disponibles dans la bibliothèque sélectionnée. Le moteur parcourt le classement dans l'ordre jusqu'à obtenir 20 éléments locaux, ou jusqu'à épuisement du classement vérifié. Les manquants des 20 premières places peuvent être envoyés au serveur Arr lié si l'acquisition est activée. Les rangs inférieurs servent uniquement à compléter la collection locale : ils n'élargissent pas la demande de téléchargement. Le mode Arr seul conserve la portée des 20 premières places. Zéro signifie l'intégralité du classement disponible.

L'identification privilégie les identifiants TMDb et accepte les correspondances IMDb/TVDb exactes des médias locaux sans identifiant TMDb. Une identité contradictoire ou incertaine ne doit pas déclencher une acquisition. Le nombre demandé n'est atteint que si le classement contient suffisamment de titres locaux identifiables.

L'aperçu ne modifie pas les médias ni les collections. Une source indisponible conserve la collection précédente. Les objets externes ne sont pas adoptés. La sélection, les manquants, les acquisitions réelles et les sources sont rapportés séparément.
