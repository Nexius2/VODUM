"""Allowlisted TMDb charts and presentation-language labels."""
CHARTS = {
    'top_movies': ('movie','top_rated'), 'top_series': ('tv','top_rated'),
    'popular_movies': ('movie','popular'), 'popular_series': ('tv','popular'),
    'trending_movies_day': ('movie','trending/day'), 'trending_series_day': ('tv','trending/day'),
    'trending_movies_week': ('movie','trending/week'), 'trending_series_week': ('tv','trending/week'),
}
LABELS = {
    'fr': ('Films les mieux notés','Séries les mieux notées','Films populaires','Séries populaires','Films tendance du jour','Séries tendance du jour','Films tendance de la semaine','Séries tendance de la semaine'),
    'en': ('Top rated movies','Top rated TV shows','Popular movies','Popular TV shows','Trending movies today','Trending TV shows today','Trending movies this week','Trending TV shows this week'),
    'de': ('Bestbewertete Filme','Bestbewertete Serien','Beliebte Filme','Beliebte Serien','Filmtrends des Tages','Serientrends des Tages','Filmtrends der Woche','Serientrends der Woche'),
    'es': ('Películas mejor valoradas','Series mejor valoradas','Películas populares','Series populares','Películas en tendencia hoy','Series en tendencia hoy','Películas en tendencia esta semana','Series en tendencia esta semana'),
    'it': ('Film più votati','Serie più votate','Film popolari','Serie popolari','Film di tendenza oggi','Serie di tendenza oggi','Film di tendenza della settimana','Serie di tendenza della settimana'),
}


def tmdb_collection_name(chart, language='fr'):
    if not isinstance(chart,str) or chart not in CHARTS:
        raise ValueError('collections.tmdb_invalid_chart')
    return 'TMDb · '+LABELS.get(language,LABELS['fr'])[list(CHARTS).index(chart)]


def tmdb_charts(language='fr'):
    return [{'id':key,'label':tmdb_collection_name(key,language).split(' · ',1)[1],
             'media_type':'movie' if value[0]=='movie' else 'shows'} for key,value in CHARTS.items()]
