"""Chart definitions shared by the collection editor and worker."""

CHARTS = {
    'tv': ('shows',),
    'movie': ('movie',),
    'bypopularity': ('movie', 'shows'),
}

LABELS = {
    'fr': ('Top séries animées', 'Top films d’animation japonaise', 'Animes les plus populaires'),
    'en': ('Top TV Anime', 'Top Anime Films', 'Most Popular Anime'),
    'de': ('Beste Anime-Serien', 'Beste Anime-Filme', 'Beliebteste Anime'),
    'es': ('Mejores series de anime', 'Mejores películas de anime', 'Animes más populares'),
    'it': ('Migliori serie anime', 'Migliori film anime', 'Anime più popolari'),
}


POPULAR_FILMS = {
    'fr': 'Films d’animation japonaise les plus populaires',
    'en': 'Most Popular Anime Films',
    'de': 'Beliebteste Anime-Filme',
    'es': 'Películas de anime más populares',
    'it': 'Film anime più popolari',
}


def myanimelist_charts(language):
    return [
        {'id': chart, 'label': label, 'media_types': media_types,
         'movie_label': POPULAR_FILMS.get(language, POPULAR_FILMS['en']) if chart == 'bypopularity' else label}
        for (chart, media_types), label in zip(CHARTS.items(), LABELS.get(language, LABELS['en']))
    ]


def myanimelist_collection_name(chart, language, media_type=None):
    for option in myanimelist_charts(language):
        if option['id'] == chart:
            return 'MyAnimeList · ' + option['movie_label' if media_type == 'movie' else 'label']
    raise ValueError('collections.myanimelist_invalid_chart')
