"""Allowlisted public IMDb title charts; movie and TV scopes stay separate."""
CHARTS = {
    'top': ('movie','chart/top/',250),
    'toptv': ('tv','chart/toptv/',250),
    'moviemeter': ('movie','chart/moviemeter/',100),
    'tvmeter': ('tv','chart/tvmeter/',100),
    'top_english': ('movie','chart/top-english-movies/',250),
    'boxoffice': ('movie','chart/boxoffice/',10),
    'bottom': ('movie','chart/bottom/',100),
    'india': ('movie','india/top-rated-indian-movies/',250),
    'tamil': ('movie','india/top-rated-tamil-movies/',50),
    'telugu': ('movie','india/top-rated-telugu-movies/',50),
    'malayalam': ('movie','india/top-rated-malayalam-movies/',50),
}
CHART_LABELS = {
    'fr': ('Top 250 films','Top 250 séries','Films les plus populaires','Séries les plus populaires',
           'Top 250 films anglophones','Top box-office (États-Unis)','Bottom 100 films',
           'Top 250 films indiens','Top 50 films tamouls','Top 50 films télougous','Top 50 films malayalam'),
    'en': ('Top 250 movies','Top 250 TV shows','Most popular movies','Most popular TV shows',
           'Top 250 English-language movies','Top box office (US)','Bottom 100 movies',
           'Top 250 Indian movies','Top 50 Tamil movies','Top 50 Telugu movies','Top 50 Malayalam movies'),
    'de': ('Top 250 Filme','Top 250 Serien','Beliebteste Filme','Beliebteste Serien',
           'Top 250 englischsprachige Filme','Top-Kinocharts (USA)','Bottom 100 Filme',
           'Top 250 indische Filme','Top 50 tamilische Filme','Top 50 Telugu-Filme','Top 50 Malayalam-Filme'),
    'es': ('Top 250 películas','Top 250 series','Películas más populares','Series más populares',
           'Top 250 películas en inglés','Top taquilla (EE. UU.)','100 películas peor valoradas',
           'Top 250 películas indias','Top 50 películas tamiles','Top 50 películas telugu','Top 50 películas malayalam'),
    'it': ('Top 250 film','Top 250 serie','Film più popolari','Serie più popolari',
           'Top 250 film in inglese','Top incassi (USA)','100 film con i voti più bassi',
           'Top 250 film indiani','Top 50 film tamil','Top 50 film telugu','Top 50 film malayalam'),
}
CHART_LABELS = {language:dict(zip(CHARTS,labels)) for language,labels in CHART_LABELS.items()}


def imdb_collection_name(chart, language='fr'):
    if not isinstance(chart,str) or chart not in CHARTS:
        raise ValueError('collections.imdb_invalid_chart')
    return 'IMDb · '+CHART_LABELS.get(language,CHART_LABELS['fr'])[chart]


def imdb_charts(language='fr'):
    labels=CHART_LABELS.get(language,CHART_LABELS['fr'])
    return [{'id':key,'label':labels[key],'media_type':'shows' if row[0]=='tv' else 'movie',
             'url':'https://www.imdb.com/'+row[1],'count':row[2]} for key,row in CHARTS.items()]
