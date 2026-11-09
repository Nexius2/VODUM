# Collections Franchise

Le catalogue contient six franchises de films :

- DC Universe : réunion des films de cinéma et des films animés issus de deux listes IMDb dédiées.
- Alien & Predator : liste IMDb ls543971628.
- Fast & Furious : liste IMDb ls4102351575, spin-off Hobbs & Shaw compris.
- Marvel Cinematic Universe : liste IMDb ls539646485.
- Star Trek : liste IMDb ls547463722.
- Star Wars : collection TMDb 10 (les neuf épisodes), complétée par The Clone Wars (film), Rogue One, Solo et The Mandalorian and Grogu, conformément au catalogue officiel https://www.starwars.com/films. Les suppléments autonomes sont ajoutés via IMDb ; les séries et épisodes ordinaires restent exclus.

Le catalogue est défini dans `app/data/franchise_universes.json`. Les listes sont désormais lues via GraphQL avec pagination complète, contrôle du nombre total et déduplication. Les types movie, tvMovie, video, short, tvShort et tvSpecial sont retenus. Les courts métrages, One-Shots, prologues et vidéos bonus référencés participent donc à la collection. Les séries et épisodes ordinaires restent exclus. Les identités sont résolues par identifiant IMDb dans TMDb, jamais par titre.

DC réunit deux listes IMDb complètes : ls020636102 pour les films sortis au cinéma, et ls058721118 pour les films animés. Les longs métrages animés distribués directement en vidéo sont inclus ; les courts métrages et spéciaux sont également inclus, les épisodes ordinaires restent exclus. Les doublons entre les deux listes sont regroupés par identifiant TMDb. Sa couverture dépend du classement des films dans TMDb ; ce n’est pas la seule continuité DCU récente.

Le catalogue principal Star Wars nécessite au maximum cinq requêtes TMDb pour ses métadonnées, mises en cache 24 heures. Ses suppléments IMDb suivent le cache commun des listes (24 heures) et des correspondances exactes (30 jours). Aucun parcours des métadonnées de tous les films locaux n'est effectué. Les films sont ensuite rapprochés de l'inventaire local par identifiant TMDb, dédupliqués et triés par date de sortie. Une réponse incomplète échoue avant mise en cache et conserve la collection existante.

Chaque franchise publie tous les films locaux correspondants, sans limite de sélection. Deux titres locaux distincts restent nécessaires. Le cache, la publication Plex/Jellyfin, la propriété des objets et les règles Arr existantes sont conservés. Aucune saga supplémentaire n’est découverte par parcours des collections TMDb de la bibliothèque.

Les identités IMDb/TMDb déjà vérifiées dans la bibliothèque sont réutilisées sans
nouvelle requête. Une erreur réseau TMDb sur un film n'annule pas les autres films
vérifiés. Après trois échecs réseau consécutifs, les résolutions non mises en cache
s'arrêtent pour cette passe. Si une liste IMDb est indisponible, l'instantané
de ses identités de films, vérifié le 29 octobre 2026, sert de secours explicite
et partiel (`app/data/franchise_list_snapshot.json`). Une telle passe conserve
les membres existants et n'autorise pas leur suppression.

La publication Plex crée au maximum 100 membres dans la requête initiale puis
ajoute les autres par lots. L'ordre chronologique des franchises utilise le tri
natif de Plex. Les grandes publications de continents et de plateformes ont un
budget de 30 secondes par collection : si elles avancent sans terminer, une
nouvelle passe reprend l'état réellement présent sur le serveur.

Une collection Plex en cours de création peut encore porter son nom technique
`VODUM <identifiant>`. Après confirmation de son marqueur de propriété (jusqu'à
trois lectures bornées si Plex tarde à refléter le marqueur), son nom définitif
et son poster sont maintenant appliqués avant les ajouts et le réordonnancement.
Une reprise réutilise l'identifiant Plex enregistré et finalise cet objet ; elle
ne crée pas de doublon et n'adopte aucune collection externe.

## Remplacement du catalogue précédent

Les objets possèdent une nouvelle clé `franchise:movie:universe_v2_<clé>`. Les sources sont résolues indépendamment : un échec conserve la franchise affectée et ne bloque pas les autres. Un titre IMDb sans correspondance TMDb est ignoré avec avertissement et ne part jamais vers Arr ; la publication conserve alors les membres existants. La suppression des anciennes sagas reste bloquée tant qu’une source ou une identité est incertaine. Lors d’un lancement complet et sans identité locale incertaine, les anciennes collections appartenant à cette configuration VODUM sont supprimées, puis les nouvelles sont créées avec leurs affiches. Les médias et les collections externes ne sont pas supprimés. Un aperçu ne modifie pas les serveurs.

Les anciennes configurations de séries peuvent encore être nettoyées ; le nouveau catalogue ne contient que des films.

## Affiches

Six fichiers PNG portrait sont embarqués dans `app/core/assets/collection_posters/universe-<clé>-v2.png`. Ils sont générés avec l’outil intégré imagegen et leurs prompts sont enregistrés dans `franchise-posters-v2-prompts.json` à côté des affiches. Les anciens catalogues et posters ont été retirés. Le changement s’applique aux serveurs après déploiement et relance de Franchise.

Les correspondances IMDb/TMDb vides ne sont plus conservées 30 jours. Une correction de métadonnées est retentée au lancement suivant ; seuls les identifiants résolus sont mis en cache. Les anciens caches de résolution sont invalidés par la nouvelle version de clé.

## Courts métrages et suppléments

Les six franchises autorisent les vidéos, courts métrages et spéciaux des listes sélectionnées. Le MCU comprend notamment les cinq One-Shots historiques, Team Thor, Team Thor: Part 2, Team Darryl, Peter’s To-Do List et le Holiday Special des Gardiens. Alien & Predator inclut les quatre Peter Weyland Files et les prologues Covenant ; la liste complémentaire ls042156304 apporte les six courts du 40e anniversaire. Fast & Furious inclut The Turbo-Charged Prelude, Los Bandoleros et Take Control.

DC complète ses listes avec ls045579204 pour les Showcase et autres vidéos/courts autonomes. Star Wars complète TMDb avec les suppléments de ls024519932 (Ewoks, Holiday Special, courts LEGO, Return of the Ewok, Zen) et les spéciaux LEGO identifiés explicitement dans le catalogue. Les longs métrages de ces listes complémentaires ne sont pas redécouverts ; leurs tvMovie restent autorisés.

Les listes IMDb sont communautaires. Leur pagination et leurs types ont été vérifiés le 29 octobre 2026. La provenance des identifiants et titres est conservée dans `app/data/franchise_supplements.json`, et les instantanés de secours comportent le type IMDb pour conserver le filtrage. Changer les types autorisés invalide le cache de liste précédent. Une source de suppléments indisponible conserve les films vérifiés et marque la passe comme partielle.

Seuls les médias présents comme éléments autonomes dans une bibliothèque peuvent être membres d’une collection Plex/Jellyfin. Un bonus rangé uniquement comme extra attaché à un film n’est pas un élément de collection autonome. Les titres sans correspondance TMDb certaine sont signalés et ne sont pas acquis via Arr. Les doublons entre films, listes et suppléments sont éliminés par identifiant TMDb ; plusieurs éditions locales restent prises en charge.
