"""Bundled posters, resolved from an allowlist without public-server URLs."""
from pathlib import Path
from core.collections_platforms_catalog import PLATFORMS
from core.collections_awards_catalog import AWARDS
from core.collections_imdb_catalog import CHARTS as IMDB_CHARTS
from core.collections_tmdb_catalog import CHARTS as TMDB_CHARTS
from core.collections_seasonal_calendar import EVENT_IDS
from core.collections_universes_catalog import UNIVERSES

POSTERS={**{'platform_'+key:'platform-'+key+'-v1.png' for key in PLATFORMS},**{'continent_'+region:'continent-'+region+'-v1.png' for region in ('africa','americas','asia','europe','oceania')},**{'tmdb_'+chart:('tmdb-trending-v1.png' if chart.startswith('trending_') else 'tmdb-'+chart+'-v1.png') for chart in TMDB_CHARTS},**{'awards_'+award:'awards-'+award+'-v1.png' for award in AWARDS},**{'imdb_'+chart:'imdb-'+chart+'-v1.png' for chart in IMDB_CHARTS},**{'seasonal_'+event:'seasonal-'+event+'-v1.png' for event in EVENT_IDS},
         'hidden_gems':'hidden-gems-v1.png',
         'streaming_country':'top-streaming-country-v1.png',
         'kids':'kids-v1.png', 'family':'family-v1.png', 'recently_added':'recently-added-v1.png',
         'memoria':'memoria-v1.png', 'franchises':'franchises-v1.png',
         **{'universe_'+key:'universe-'+key+'-v2.png' for key in UNIVERSES},
         'top_country_popular':'top-country-most-popular-v1.png',
         'top_country_top':'top-country-top-rated-v1.png',
         'spotlight':'spotlight-v1.png', 'recent_releases':'latest-releases-country-v1.png',
         **{'streaming_'+region:'top-streaming-'+region+'-v1.png' for region in
            ('worldwide','africa','americas','asia','europe','oceania')}}


def streaming_poster_key(model, config):
    if model=='hidden_gems':return 'hidden_gems'
    if model=='top_country':
        return {'top':'top_country_top','popular':'top_country_popular'}.get(config.get('country_chart','top'))
    if model=='streaming_country':return 'streaming_country'
    if model=='streaming_worldwide':
        key='streaming_'+str(config.get('region','worldwide'))
        return key if key in POSTERS and key!='streaming_country' else None
    return None


def collection_poster(key):
    filename=POSTERS.get(key) if isinstance(key,str) else None
    if not filename:return None
    path=Path(__file__).parent/'assets'/'collection_posters'/filename
    if not path.is_file():raise ValueError('collections.poster_failed')
    return path


def object_poster_key(record,config):
    """Resolve existing child artwork without running its discovery engine."""
    explicit=config.get('collection_poster')
    if explicit in POSTERS:return explicit
    child=str(record.get('person_key') or '')
    tail=child.rsplit(':',1)[-1]
    if child.startswith('franchise:') and tail.startswith('universe_v2_'):
        key='universe_'+tail.removeprefix('universe_v2_')
    elif child.startswith('platform:'):key='platform_'+tail
    elif child.startswith('continent:'):key='continent_'+tail
    elif child.startswith('seasonal:'):key='seasonal_'+tail
    else:
        model=config.get('_collection_model') or child
        key=streaming_poster_key(model,config)
        if not key:
            key={'imdb':'imdb_'+config.get('imdb_chart','top'),
                 'tmdb':'tmdb_'+config.get('tmdb_chart','top_movies'),
                 'awards':'awards_'+config.get('award','oscars')}.get(model,model)
    return key if key in POSTERS else None


def plex_has_custom_poster(obj):
    for poster in obj.posters():
        if poster.selected is True:
            key=str(getattr(poster,'key','') or '').lower()
            provider=str(getattr(poster,'provider','') or '').lower()
            if 'composite' not in key and provider not in ('composite','generated'):
                return True
    return False
