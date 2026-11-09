from core.collection_schedule import automatic_schedule, next_collection_run, migrate_collection_schedules
from core.collections_awards_catalog import AWARDS, award_period, awards_collection_name
from core.collections_visibility import collection_visibility
from core.collections_tmdb_catalog import CHARTS as TMDB_CHARTS, tmdb_collection_name
"""Persistent collection settings. Remote calls never hold a SQLite transaction."""
import json
import os
import uuid
from datetime import datetime, timezone
from pytz import timezone as collection_timezone, UnknownTimeZoneError

from croniter import croniter
from core.collection_catalog import collection_catalog
from core.server_page_queries import LIBRARY_TYPE_SQL
from secret_store import encrypt_secret
from core.collections_imdb_catalog import CHARTS, imdb_collection_name
from core.collections_streaming_options import EXTRA_COUNTRIES, CONTENT_LANGUAGES

TRIBUTE_TITLES = {"fr":"En hommage à {name}","en":"In tribute to {name}","de":"In Erinnerung an {name}","es":"En homenaje a {name}","it":"In omaggio a {name}"}


class CollectionRunCancelled(Exception):
    pass


SPOTLIGHT_TITLES = {'fr':'Sélection du moment 🍿','en':'In the spotlight 🍿',
                    'de':'Im Rampenlicht 🍿','es':'En primer plano 🍿','it':'In primo piano 🍿'}


WORLDWIDE_TITLES = {'fr':'Top streaming mondial 🌍','en':'Top streaming worldwide 🌍','de':'Top streaming weltweit 🌍','es':'Top streaming mundial 🌍','it':'Top streaming mondiale 🌍'}

STREAMING_REGIONS = ('worldwide','africa','americas','asia','europe','oceania')
REGION_NAMES = {
    'fr': ('Monde','Afrique','Amériques','Asie','Europe','Océanie'),
    'en': ('Worldwide','Africa','Americas','Asia','Europe','Oceania'),
    'de': ('Weltweit','Afrika','Amerika','Asien','Europa','Ozeanien'),
    'es': ('Mundial','África','Américas','Asia','Europa','Oceanía'),
    'it': ('Mondiale','Africa','Americhe','Asia','Europa','Oceania'),
}

def worldwide_collection_name(region='worldwide', language='fr'):
    if region not in STREAMING_REGIONS:
        raise ValueError('collections.invalid_configuration')
    if region=='worldwide':
        return WORLDWIDE_TITLES.get(language,WORLDWIDE_TITLES['fr'])
    return 'Top streaming '+REGION_NAMES.get(language,REGION_NAMES['fr'])[STREAMING_REGIONS.index(region)]+' 🌍'


STREAMING_COUNTRY_NAMES = {'fr': {'FR': 'France', 'US': 'États-Unis', 'GB': 'Royaume-Uni', 'DE': 'Allemagne', 'ES': 'Espagne', 'IT': 'Italie', 'CA': 'Canada', 'BE': 'Belgique', 'CH': 'Suisse'}, 'en': {'FR': 'France', 'US': 'United States', 'GB': 'United Kingdom', 'DE': 'Germany', 'ES': 'Spain', 'IT': 'Italy', 'CA': 'Canada', 'BE': 'Belgium', 'CH': 'Switzerland'}, 'de': {'FR': 'Frankreich', 'US': 'Vereinigte Staaten', 'GB': 'Vereinigtes Königreich', 'DE': 'Deutschland', 'ES': 'Spanien', 'IT': 'Italien', 'CA': 'Kanada', 'BE': 'Belgien', 'CH': 'Schweiz'}, 'es': {'FR': 'Francia', 'US': 'Estados Unidos', 'GB': 'Reino Unido', 'DE': 'Alemania', 'ES': 'España', 'IT': 'Italia', 'CA': 'Canadá', 'BE': 'Bélgica', 'CH': 'Suiza'}, 'it': {'FR': 'Francia', 'US': 'Stati Uniti', 'GB': 'Regno Unito', 'DE': 'Germania', 'ES': 'Spagna', 'IT': 'Italia', 'CA': 'Canada', 'BE': 'Belgio', 'CH': 'Svizzera'}}

for _names in STREAMING_COUNTRY_NAMES.values():
    _names.update({code:row[3] for code,row in EXTRA_COUNTRIES.items()})
STREAMING_COUNTRY_NAMES['fr'].update(IN='Inde',JP='Japon',KR='Corée du Sud',BR='Brésil',MX='Mexique',ZA='Afrique du Sud')

def streaming_title(model, language, country='FR', region='worldwide', content_language='', kids_chart='top'):
    title = kids_collection_name(country,language,kids_chart) if model=='kids' else worldwide_collection_name(region,language) if model=='streaming_worldwide' else streaming_collection_name(country,language)
    return title+(' · '+CONTENT_LANGUAGES[content_language] if content_language else '')


def streaming_collection_name(country, language='fr'):
    country = str(country or 'FR').upper()
    countries = STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])
    if country not in countries: country = 'FR'
    flag = ''.join(chr(0x1F1E6+ord(letter)-ord('A')) for letter in country)
    return 'Top streaming '+countries[country]+' '+flag


def kids_collection_name(country, language='fr', chart='top'):
    country=str(country or 'FR').upper()
    countries=STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])
    if country not in countries:
        raise ValueError('collections.invalid_country')
    flag=''.join(chr(0x1F1E6+ord(letter)-ord('A')) for letter in country)
    if chart not in ('top','latest'):
        raise ValueError('collections.invalid_configuration')
    label = {'fr':('Kids · Top','Kids · Top nouveautés'),'en':('Kids · Top','Kids · Top latest'),'de':('Kids · Top','Kids · Top Neuheiten'),'es':('Kids · Top','Kids · Top novedades'),'it':('Kids · Top','Kids · Top novità')}.get(language,('Kids · Top','Kids · Top latest'))[chart=='latest']
    return label+' · '+countries[country]+' '+flag


def top_country_name(country, language='fr', chart='top', content_language=''):
    countries=STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])
    if country not in countries:raise ValueError('collections.invalid_country')
    if chart not in ('top','popular'):raise ValueError('collections.invalid_configuration')
    labels={'fr':('Top œuvres','Œuvres populaires'),'en':('Top media','Popular media'),
            'de':('Beste Titel','Beliebte Titel'),'es':('Mejores títulos','Títulos populares'),
            'it':('Migliori titoli','Titoli popolari')}
    flag=''.join(chr(0x1F1E6+ord(letter)-ord('A')) for letter in country)
    title=labels.get(language,labels['en'])[chart=='popular']+' · '+countries[country]+' '+flag
    return title+(' · '+CONTENT_LANGUAGES[content_language] if content_language else '')


def recent_collection_name(country, language='fr'):
    country = str(country or 'FR').upper()
    countries = STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])
    if country not in countries: country = 'FR'
    prefixes = {'fr':'Dernières sorties','en':'Latest releases','de':'Neueste Veröffentlichungen','es':'Últimos estrenos','it':'Ultime uscite'}
    flag = ''.join(chr(0x1F1E6+ord(letter)-ord('A')) for letter in country)
    return prefixes.get(language,prefixes['fr'])+' '+countries[country]+' '+flag


def seasonal_collection_name(country, language='fr'):
    prefixes={'fr':'Saisons et fêtes','en':'Seasonal','de':'Saisonale Feste','es':'Fiestas y temporadas','it':'Feste e stagioni'}
    countries=STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])
    return prefixes.get(language,prefixes['fr'])+' · '+countries.get(country,countries['FR'])+' 🎉'


def recently_added_name(model, language='fr'):
    return {'fr':'Récemment ajoutés','en':'Recently added','de':'Kürzlich hinzugefügt','es':'Añadidos recientemente','it':'Aggiunti di recente'}.get(language,'Recently added')


def family_collection_name(language='fr'):
    return {'fr':'En famille','en':'Family','de':'Für die Familie','es':'En familia','it':'In famiglia'}.get(language,'Family')


def hidden_gems_name(language='fr'):
    return {'fr':'Les pépites oubliées','en':'Forgotten gems','de':'Vergessene Perlen',
            'es':'Joyas olvidadas','it':'Gemme dimenticate'}.get(language,'Forgotten gems')


def fixed_collection_name(model, language, fallback=''):
    if model=='platforms':return {'fr':'Par plateforme','en':'By platform','de':'Nach Plattform','es':'Por plataforma','it':'Per piattaforma'}.get(language,'By platform')
    if model=='continents':return {'fr':'Par continent','en':'By continent','de':'Nach Kontinent','es':'Por continente','it':'Per continente'}.get(language,'By continent')
    if model=='franchises':return {'fr':'Franchise','en':'Franchise','de':'Franchise','es':'Franquicia','it':'Franchise'}.get(language,'Franchise')
    if model=='hidden_gems':return hidden_gems_name(language)
    if model=='family':return family_collection_name(language)
    if model in ('recently_added',):
        return recently_added_name(model,language)
    if model=='memoria':
        return TRIBUTE_TITLES.get(language,TRIBUTE_TITLES['fr']).format(name='…')
    if model=='streaming_worldwide':
        return WORLDWIDE_TITLES.get(language,WORLDWIDE_TITLES['fr'])
    if model=='spotlight':
        return SPOTLIGHT_TITLES.get(language,SPOTLIGHT_TITLES['fr'])
    return fallback


def default_collection_schedule(model, frequency, slot=0):
    # Stagger libraries by fifteen minutes, with Spotlight ahead of evening viewing.
    minutes = (15*60 if model=='spotlight' else 5*60+15) + 15*slot
    hour, minute = divmod(minutes % (24*60),60)
    if frequency=='monthly':
        return f'{minute} {hour} 1 * *'
    return f'{minute} {hour} * * '+('1' if frequency=='weekly' else '*')


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or utcnow()).astimezone(timezone.utc).isoformat(timespec='seconds')


def next_occurrence(schedule, zone, now=None):
    if not schedule:
        return None
    return stamp(croniter(schedule, (now or utcnow()).astimezone(collection_timezone(zone))).get_next(datetime))


def global_timezone(db):
    settings = db.query_one('SELECT timezone FROM settings WHERE id=1')
    return str(settings['timezone'] if settings and settings['timezone'] else os.environ.get('TZ') or 'UTC')


def load_instance(db, instance_id):
    row = db.query_one('SELECT * FROM collection_instances WHERE id=?', (instance_id,))
    return dict(row) if row else None


def public_instance(row):
    data = json.loads(row['config_json'])
    name = fixed_collection_name(row['model'],data.get('language','fr'),row['name'])
    if row['model']=='platforms':
        name+=' · '+STREAMING_COUNTRY_NAMES.get(data.get('language','fr'),STREAMING_COUNTRY_NAMES['en']).get(data.get('country','FR'),data.get('country','FR'))
    if row['model']=='awards':
        name=awards_collection_name(data.get('award','oscars'),data.get('award_period','latest'),data.get('language','fr'))
    if row['model']=='tmdb':
        name=tmdb_collection_name(data.get('tmdb_chart','top_movies'),data.get('language','fr'))
    if row['model']=='imdb':
        name = imdb_collection_name(data.get('imdb_chart','top'),data.get('language','fr'))
    if row['model']=='top_country':
        name=top_country_name(data.get('country','FR'),data.get('language','fr'),data.get('country_chart','top'),data.get('content_language',''))
    if row['model']=='streaming_worldwide':
        name = worldwide_collection_name(data.get('region','worldwide'),data.get('language','fr'))
    if row['model'] in ('streaming_country','recent_releases','seasonal','kids'):
        name = (seasonal_collection_name if row['model']=='seasonal' else recent_collection_name if row['model']=='recent_releases' else streaming_collection_name)(data.get('country','FR'),data.get('language','fr'))
    if row['model'] in ('streaming_country','streaming_worldwide','kids'):
        name = streaming_title(row['model'],data.get('language','fr'),data.get('country','FR'),data.get('region','worldwide'),data.get('content_language',''),data.get('kids_chart','top'))
    return {**data, 'visibility':collection_visibility(data), **{key: row[key] for key in ('id','model','name','library_id','enabled','schedule','timezone','next_run','last_run','state','last_error')},
            'name':name,
            'library': str(row['library_id']), 'has_tmdb_key': bool(row['secret_tmdb'] or os.environ.get('TMDB_API_KEY')),
            'requested': row['requested']}


def collection_settings(db):
    row = db.query_one('SELECT secret_tmdb,suppress_empty FROM collection_settings WHERE id=1')
    legacy = db.query_one("SELECT COUNT(DISTINCT secret_tmdb) AS count FROM collection_instances WHERE secret_tmdb IS NOT NULL AND secret_tmdb!=''")
    return {'suppress_empty':bool(row['suppress_empty']) if row else True,'has_tmdb_key':bool(row and row['secret_tmdb'] or os.environ.get('TMDB_API_KEY')),
            'legacy_key_conflict':bool(legacy and legacy['count']>1 and not (row and row['secret_tmdb']))}


def save_collection_settings(db, payload):
    if not isinstance(payload,dict):
        raise ValueError('collections.invalid_configuration')
    key = str(payload.get('tmdb_api_key') or '').strip()
    suppress = payload.get('suppress_empty',collection_settings(db)['suppress_empty'])
    if not isinstance(suppress,bool):
        raise ValueError('collections.invalid_configuration')
    if len(key)>1024:
        raise ValueError('collections.tmdb_key_required')
    encrypted = encrypt_secret(key) if key else None
    with db.transaction() as cur:
        cur.execute('UPDATE collection_settings SET suppress_empty=? WHERE id=1',(int(suppress),))
        if encrypted is not None:
            cur.execute('UPDATE collection_settings SET secret_tmdb=? WHERE id=1',(encrypted,))
            cur.execute('UPDATE collection_instances SET secret_tmdb=NULL')
    return collection_settings(db)


def group_members(db, instance_id):
    return [dict(row) for row in db.query('SELECT * FROM collection_instances WHERE group_id=? OR id=? ORDER BY retired,created_at,id',(instance_id,instance_id))]


def list_instances(db):
    rows = [dict(row) for row in db.query('SELECT * FROM collection_instances ORDER BY created_at,id')]
    controls={row['instance_id']:dict(row) for row in db.query('SELECT * FROM collection_controls')}
    settings = dict(db.query_one('SELECT * FROM settings WHERE id=1') or {})
    tasks = {row['name']:dict(row) for row in db.query("SELECT * FROM tasks WHERE name IN ('run_collections','refresh_collection_inventory')")}
    servers = {row['id']:dict(row) for row in db.query('SELECT * FROM servers')}
    libraries = {row['id']:dict(row) for row in db.query('SELECT * FROM libraries')}
    retries = {row['server_id']:row['retry_after'] for row in db.query('SELECT * FROM collection_server_retries')}
    from core.server_cooldown import should_skip_unreachable_server
    groups = {}
    for row in rows:
        groups.setdefault(row['group_id'] or row['id'],[]).append(row)
    result = []
    for group_id,members in groups.items():
        active = [row for row in members if not row['retired']]
        if not active:
            continue
        order = json.loads(active[0]['config_json']).get('libraries',[])
        if order:
            active.sort(key=lambda row:order.index(str(row['library_id'])))
        data = public_instance(active[0])
        data.update(id=group_id,libraries=[str(row['library_id']) for row in active],
                    arr_servers={str(row['library_id']):json.loads(row['config_json']).get('arr_server') for row in active},
                    member_ids=[row['id'] for row in members],count_member_ids=[row['id'] for row in active],has_tmdb_key=collection_settings(db)['has_tmdb_key'])
        # A live membership lease is authoritative even if a queued action
        # changed the stored state while the worker was executing.
        live_members = [row['id'] for row in members if row['lease_id'] and row['lease_until'] and row['lease_until']>stamp()]
        data['running_member_ids'] = live_members
        # Presentation commands have their own status; they are not media runs.
        states = ['running'] if live_members else [row['state'] for row in members if row['requested']!='visibility']
        fallback_state = next((row['state'] for row in active if row['requested']!='visibility'),'idle')
        data['state'] = next((state for state in ('running','queued','error','warning') if state in states),fallback_state)
        data['locked'] = any(row['lease_until'] and row['lease_until']>stamp() for row in members)
        if any(row['requested']=='cancel' for row in members):
            data['state'] = 'stopping'
        data['last_error'] = next((row['last_error'] for row in members if row['last_error']),None)
        data['can_run_manual'] = bool(data['enabled']) and not data['locked'] and all(
            row['requested'] in (None,'sync','visibility') for row in active)
        data['can_retry_queue'] = data['state']=='queued' and not data['locked'] and all(
            row['state']=='queued' or row['requested'] is None for row in members)
        data['queue_reasons'] = []
        if data['state']=='queued':
            task=tasks.get('run_collections',{})
            inventory=tasks.get('refresh_collection_inventory',{})
            for row in members:
                if row['state']!='queued':continue
                library=libraries.get(row['library_id'],{})
                server=servers.get(library.get('server_id'),{})
                if not settings.get('enable_cron_jobs',1):reason='queue_cron_disabled'
                elif not task.get('enabled'):reason='queue_task_disabled'
                elif should_skip_unreachable_server(server):reason='queue_server_unreachable'
                elif retries.get(server.get('id'),'')>stamp():reason='queue_server_retry'
                elif row['requested']=='visibility' and row['id'] in controls and controls[row['id']]['state']=='running':reason='queue_worker_running'
                elif row['requested']=='visibility' and row['id'] in controls:reason='queue_configuration_pending'
                elif inventory.get('status')=='running':reason='queue_inventory_running'
                elif task.get('status')=='running':reason='queue_worker_running'
                elif task.get('queued_count',0):reason='queue_worker_pending'
                else:reason='queue_not_dispatched'
                data['queue_reasons'].append({'library_name':library.get('name',''),
                    'reason':'collections.'+reason,'retry_after':retries.get(server.get('id')) if reason=='queue_server_retry' else None})

        reasons={row['reason'].removeprefix('collections.') for row in data['queue_reasons']}
        data['queue_state'] = ('blocked' if reasons & {'queue_cron_disabled','queue_task_disabled','queue_server_unreachable','queue_server_retry'}
            else 'start_required' if 'queue_not_dispatched' in reasons else 'waiting') if data['state']=='queued' else None
        pending=[controls[row['id']] for row in active if row['id'] in controls
            and controls[row['id']]['revision']>controls[row['id']]['applied_revision']]
        data['presentation_state']=next((state for state in ('error','running','pending')
            if any(row['state']==state for row in pending)),None)
        if not pending and any(row['id'] in controls for row in active):
            data['presentation_state']='success'
        result.append(data)
    return result


def normalize_config(db, payload):
    if not isinstance(payload, dict):
        raise ValueError('collections.invalid_configuration')
    model = next((item for item in collection_catalog() if item['id'] == payload.get('model')), None)
    if not model:
        raise ValueError('collections.invalid_configuration')
    library_id = int(payload.get('library') or payload.get('library_id') or 0)
    library = db.query_one(f"""SELECT l.id, {LIBRARY_TYPE_SQL} AS type, LOWER(s.type) AS provider
        FROM libraries l JOIN servers s ON s.id=l.server_id WHERE l.id=?""", (library_id,))
    if not library or library['provider'] not in ('plex','jellyfin') or library['type'] not in model['media_types']:
        raise ValueError('collections.invalid_library')
    name = str(payload.get('name') or '').strip()
    name = fixed_collection_name(model['id'],payload.get('language','fr'),name)
    if model['id'] in ('streaming_country','recent_releases','seasonal','kids','top_country'):
        from core.collections_streaming_source import COUNTRIES
        country = str(payload.get('country') or 'FR').upper()
        if country not in COUNTRIES or model['id'] not in ('streaming_country','kids','top_country') and country not in ('FR','US','GB','DE','ES','IT','CA','BE','CH'): raise ValueError('collections.invalid_country')
        name = (seasonal_collection_name if model['id']=='seasonal' else recent_collection_name if model['id']=='recent_releases' else streaming_collection_name)(country,payload.get('language','fr'))
    if model['id']=='platforms':
        from core.collections_streaming_source import COUNTRIES
        country=str(payload.get('country') or 'FR').upper()
        if country not in COUNTRIES:raise ValueError('collections.invalid_country')
        name=fixed_collection_name('platforms',payload.get('language','fr'))+' · '+STREAMING_COUNTRY_NAMES.get(payload.get('language','fr'),STREAMING_COUNTRY_NAMES['en']).get(country,country)
    if model['id']=='awards':
        award=payload.get('award','oscars')
        period=award_period(payload.get('award_period','latest'))
        name=awards_collection_name(award,period,payload.get('language','fr'))
        if library['type'] not in AWARDS[award]['media_types']:raise ValueError('collections.awards_library')
    if model['id']=='tmdb':
        tmdb_chart=payload.get('tmdb_chart','top_movies')
        name=tmdb_collection_name(tmdb_chart,payload.get('language','fr'))
        if TMDB_CHARTS[tmdb_chart][0]!=('tv' if library['type']=='shows' else 'movie'):
            raise ValueError('collections.tmdb_chart_library')
    if model['id']=='imdb':
        chart = payload.get('imdb_chart','top')
        name = imdb_collection_name(chart,payload.get('language','fr'))
        if CHARTS[chart][0] != ('tv' if library['type']=='shows' else 'movie'):
            raise ValueError('collections.imdb_chart_library')
    if not name or len(name) > 120:
        raise ValueError('collections.name_required')
    mode = payload.get('mode', 'published')
    language = payload.get('language', 'fr')
    if mode not in ('published','private','arr') or language not in ('fr','en','de','es','it'):
        raise ValueError('collections.invalid_configuration')
    # Configurations for other models remain inactive until their own engine exists.
    enabled = payload.get('enabled') is True and model['id'] in ('memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems')
    frequency = payload.get('frequency', 'daily')
    slot = db.query_one('SELECT COUNT(*) AS n FROM libraries WHERE id<?',(library_id,))['n']
    schedules = {frequency:default_collection_schedule(model['id'],frequency,slot) for frequency in ('daily','weekly','monthly')}
    schedules['manual'] = None
    schedule = str(payload.get('schedule') or '').strip() if frequency == 'custom' else schedules.get(frequency)
    zone = global_timezone(db)
    try:
        collection_timezone(zone)
        if frequency not in (*schedules, 'custom') or frequency == 'custom' and not schedule:
            raise ValueError()
        if schedule and (len(schedule.split()) != 5 or not croniter.is_valid(schedule)):
            raise ValueError()
    except (ValueError, UnknownTimeZoneError):
        raise ValueError('collections.invalid_schedule') from None
    def bounded(key, default, minimum, maximum):
        value = int(payload.get(key, default))
        if not minimum <= value <= maximum:
            raise ValueError('collections.invalid_configuration')
        return value
    credits = payload.get('credits') or 'actors_directors'
    if credits not in ('actors_directors','actors','directors'):
        raise ValueError('collections.invalid_configuration')
    config = {'mode':mode, 'language':language, 'frequency':frequency, 'credits':credits,
              'retention':bounded('retention',30 if model['id']=='spotlight' else 7,1,365),
              'min_popularity':bounded('min_popularity',25,0,10000), 'max_people':bounded('max_people',4,1,100), 'detection_days':7, 'limit':bounded('limit',model['default_limit'],0,100000),
              'priority':bounded('priority',10,1,999), 'sort':payload.get('sort') or ('daily_random' if model['id']=='seasonal' else 'release'),
              'arr_enabled':payload.get('arr_enabled') is True or mode == 'arr',
              'arr_server':int(payload.get('arr_server') or 0) or None}
    config['visibility']=collection_visibility({'mode':mode,'visibility':payload.get('visibility',{})})
    if model['id'] in ('recent_releases','recently_added','family','continents'):
        if config['arr_enabled']: raise ValueError('collections.releases_no_arr')
        config['arr_server']=None
    else:
        selections = payload.get('arr_servers', {})
        if not isinstance(selections, dict):
            raise ValueError('collections.invalid_configuration')
        selected = selections.get(str(library_id), config['arr_server'])
        expected = 'radarr' if library['type']=='movie' else 'sonarr'
        routes = db.query('''SELECT r.arr_server_id FROM library_arr_routes r JOIN servers s ON s.id=r.arr_server_id
            WHERE r.library_id=? AND r.enabled=1 AND LOWER(TRIM(s.type))=? ORDER BY r.priority,r.arr_server_id''',
            (library_id,expected))
        selected = int(selected or 0) or (routes[0]['arr_server_id'] if routes else None)
        if selected is not None and selected not in {row['arr_server_id'] for row in routes}:
            raise ValueError('collections.arr_route_required')
        config['arr_server'] = selected
    if config['sort'] not in ('release','popularity','random','daily_random','added','rank','availability'):
        raise ValueError('collections.invalid_configuration')
    if model['id'] in ('recently_added','family'):
        config.update(sort='added',arr_server=None)
    if model['id']=='platforms':
        from core.collections_platforms_catalog import PLATFORMS
        platforms=payload.get('platforms',list(PLATFORMS))
        if not isinstance(platforms,list) or not platforms or any(not isinstance(key,str) or key not in PLATFORMS for key in platforms):
            raise ValueError('collections.platforms_required')
        config.update(platforms=list(dict.fromkeys(platforms)),country=country)
    if model['id']=='awards':
        config.update(award=award,award_period=period,sort=payload.get('sort') or 'rank')
        if config['sort'] not in ('rank','release','popularity','added','random'):raise ValueError('collections.invalid_configuration')
        audio=payload.get('content_language') or ''
        if not isinstance(audio,str) or audio and audio not in CONTENT_LANGUAGES:raise ValueError('collections.invalid_configuration')
        config['content_language']=audio
    if model['id']=='tmdb':
        config.update(tmdb_chart=tmdb_chart,sort='rank')
    if model['id']=='imdb':
        config.update(imdb_chart=chart,sort='rank')
    if model['id']=='franchises':
        if config['limit']==1:raise ValueError('collections.invalid_configuration')
        config.update(sort='release',limit=0)
    if model['id']=='spotlight':
        if mode=='arr' or config['arr_enabled']:
            raise ValueError('collections.spotlight_no_arr')
        config['sort']='availability'
        config.update(min_score=bounded('min_score',65,0,100),
                      release_window_days=bounded('release_window_days',30,1,180),
                      audio_language=payload.get('audio_language') or 'fr')
        if config['audio_language'] not in ('fr','en','de','es','it'):
            raise ValueError('collections.invalid_configuration')
    if model['id']=='recent_releases':
        if mode=='arr' or config['arr_enabled']: raise ValueError('collections.releases_no_arr')
        config.update(country=country,sort='release',arr_server=None)
    if model['id'] in ('family','kids','top_country'):
        audio=payload.get('required_audio_language') or ''
        if not isinstance(audio,str) or audio and audio not in CONTENT_LANGUAGES:raise ValueError('collections.invalid_configuration')
        config['required_audio_language']=audio
    if model['id']=='hidden_gems':
        import math
        def decimal_setting(key, default, maximum):
            raw=payload.get(key,default)
            if isinstance(raw,bool):raise ValueError('collections.invalid_configuration')
            try:value=float(raw)
            except (TypeError,ValueError):raise ValueError('collections.invalid_configuration') from None
            if not math.isfinite(value) or not 0<=value<=maximum:
                raise ValueError('collections.invalid_configuration')
            return value
        raw_votes=payload.get('minimum_votes',200)
        if isinstance(raw_votes,bool) or not str(raw_votes).isdigit():
            raise ValueError('collections.invalid_configuration')
        config.update(minimum_rating=decimal_setting('minimum_rating',7.5,10),
                      minimum_votes=bounded('minimum_votes',200,1,1000000),
                      maximum_popularity=decimal_setting('maximum_popularity',10,100000),
                      sort=payload.get('sort') or 'rank')
        if config['sort'] not in ('rank','added','random'):raise ValueError('collections.invalid_configuration')
    if model['id']=='top_country':
        chart=payload.get('country_chart','top')
        content_language=payload.get('content_language') or ''
        if not isinstance(content_language,str) or content_language and content_language not in CONTENT_LANGUAGES:
            raise ValueError('collections.invalid_configuration')
        name=top_country_name(country,language,chart,content_language)
        config.update(country=country,country_chart=chart,content_language=content_language,
                      minimum_votes=bounded('minimum_votes',100,0,1000000),sort=payload.get('sort') or 'rank')
        if config['sort'] not in ('rank','added','random'):raise ValueError('collections.invalid_configuration')
    if model['id']=='family':
        chart=payload.get('family_chart','top')
        if chart not in ('top','latest'):raise ValueError('collections.invalid_configuration')
        config.update(family_chart=chart,sort='rank' if chart=='top' else 'release',arr_enabled=False,arr_server=None)
    if model['id']=='kids':
        chart=payload.get('kids_chart','top')
        if chart not in ('top','latest'):raise ValueError('collections.invalid_configuration')
        config['kids_chart']=chart
    if model['id'] in ('streaming_country','kids'):
        config.update(country=country,sort='rank')
    if model['id']=='streaming_worldwide':
        region = payload.get('region','worldwide')
        name = worldwide_collection_name(region,language)
        config.update(country='worldwide',region=region,sort='rank')
    if model['id'] in ('streaming_country','streaming_worldwide','kids'):
        content_language = payload.get('content_language') or ''
        if not isinstance(content_language,str) or content_language and content_language not in CONTENT_LANGUAGES:
            raise ValueError('collections.invalid_configuration')
        config['content_language'] = content_language
        name = streaming_title(model['id'],language,config['country'],config.get('region','worldwide'),content_language,config.get('kids_chart','top'))
    if model['id']=='seasonal':
        from core.collections_seasonal_calendar import EVENT_IDS, celebration
        events=payload.get('events',['halloween'])
        source=payload.get('seasonal_source','both')
        if not isinstance(events,list) or not events or any(not isinstance(event,str) or event not in EVENT_IDS for event in events):
            raise ValueError('collections.seasonal_events_required')
        if source not in ('web','local','both'):raise ValueError('collections.invalid_configuration')
        if any(celebration(event,country,utcnow().year) is None for event in events):
            raise ValueError('collections.seasonal_event_unavailable')
        if source=='local' and config['arr_enabled']:raise ValueError('collections.seasonal_local_no_arr')
        if config['sort'] not in ('daily_random','release','popularity','rank','added','random'):raise ValueError('collections.invalid_configuration')
        config.update(country=country,events=list(dict.fromkeys(events)),seasonal_source=source)
        if source=='local':config['arr_server']=None
    if payload.get('sort') in ('rank','added','random'):
        config['sort']=payload['sort']
    # Reserved presentation options for models with no engine yet.
    for key in ('country','events','period'):
        if key in payload and not (key=='country' and model['id'] in ('streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems')) and not (key=='events' and model['id']=='seasonal'):
            config[key] = payload[key]
    return model['id'], library_id, name, config, int(enabled), schedule, zone


def save_instance(db, payload, instance_id=None):
    if not isinstance(payload,dict):
        raise ValueError('collections.invalid_configuration')
    libraries = payload.get('libraries') or [payload.get('library') or payload.get('library_id')]
    if not isinstance(libraries,list) or not 1<=len(libraries)<=2:
        raise ValueError('collections.invalid_library')
    libraries = [int(value) for value in libraries]
    if len(set(libraries)) != len(libraries):
        raise ValueError('collections.invalid_library')
    normalized = [normalize_config(db,{**payload,'library':value}) for value in libraries]
    if len(libraries)==2 and normalized[0][0]=='tmdb':
        raise ValueError('collections.tmdb_chart_library')
    if len(libraries)==2 and normalized[0][0]=='imdb':
        raise ValueError('collections.imdb_chart_library')
    if len(libraries)==2:
        types = {db.query_one(f'SELECT {LIBRARY_TYPE_SQL} AS type FROM libraries l WHERE l.id=?',(value,))['type'] for value in libraries}
        if types != {'movie','shows'}:
            raise ValueError('collections.library_pair_required')
    now = stamp()
    group_id = instance_id or str(uuid.uuid4())
    next_runs = [next_occurrence(row[5],row[6]) if row[4] else None for row in normalized]
    if normalized[0][4] and normalized[0][0] not in ('recently_added','family','continents') and not (normalized[0][0]=='seasonal' and normalized[0][3]['seasonal_source']=='local') and not collection_settings(db)['has_tmdb_key']:
        raise ValueError('collections.tmdb_key_required')
    with db.transaction() as cur:
        previous = [dict(row) for row in cur.execute('SELECT * FROM collection_instances WHERE group_id=? OR id=?',(group_id,group_id)).fetchall()]
        if instance_id and not previous:
            raise ValueError('collections.not_found')
        if any(row['requested']=='delete' for row in previous):
            raise ValueError('collections.busy')
        if any(row['lease_until'] and row['lease_until']>now for row in previous):
            # Presentation and stopping future ARR additions do not alter the
            # in-flight selection. Preserve its lease, schedule and request.
            if set(libraries)!={row['library_id'] for row in previous if not row['retired']}:
                raise ValueError('collections.busy')
            from core.collections_control import queue_control
            for model,library_id,name,config,enabled,schedule,zone in normalized:
                old=next(row for row in previous if row['library_id']==library_id)
                before=json.loads(old['config_json']);config['libraries']=[str(value) for value in libraries]
                if 'schedule_anchor' in before:config['schedule_anchor']=before['schedule_anchor']
                mutable={'visibility','priority','mode','arr_enabled'}
                if (model!=old['model'] or enabled!=old['enabled'] or name!=old['name'] or zone!=old['timezone']
                    or config['frequency']=='custom' and schedule!=old['schedule']
                    or config['mode']=='arr' or before.get('mode')=='arr'
                    or config['arr_enabled'] and not before.get('arr_enabled')
                    or {k:v for k,v in config.items() if k not in mutable}!={k:v for k,v in before.items() if k not in mutable}):
                    raise ValueError('collections.busy')
                changed=collection_visibility(before)!=config['visibility'] or before.get('priority',10)!=config['priority']
                cur.execute('UPDATE collection_instances SET config_json=?,updated_at=? WHERE id=?',
                    (json.dumps(config),now,old['id']))
                if changed:queue_control(cur,old['id'],priority=True)
            return next(row for row in list_instances(db) if row['id']==group_id)
        if any(row['model']!=normalized[0][0] for row in previous):
            raise ValueError('collections.invalid_configuration')
        for index,(model,library_id,name,config,enabled,schedule,zone) in enumerate(normalized):
            config['libraries'] = [str(value) for value in libraries]
            old = next((row for row in previous if row['library_id']==library_id),None)
            row_id = old['id'] if old else group_id if not previous and index==0 else str(uuid.uuid4())
            if config['frequency'] in ('daily','weekly','monthly'):
                schedule = automatic_schedule(cur, config, zone, utcnow(), old)
            next_runs[index] = next_collection_run({'enabled': enabled, 'schedule': schedule,
                'timezone': zone, 'config_json': json.dumps(config)})
            # Explicitly disabled configurations remove every owned object.
            cleanup = not enabled and bool(old)
            if old:
                old_config=json.loads(old['config_json'])
                visibility_changed=(collection_visibility(old_config)!=config['visibility']
                                    or int(old_config.get('priority',10))!=config['priority'])
                requested = 'cleanup' if cleanup else old['requested'] if old['requested'] in ('sync','preview','visibility') else 'visibility' if visibility_changed and config['mode']!='arr' else None
                if visibility_changed and enabled and config['mode']!='arr':
                    from core.collections_control import queue_control
                    queue_control(cur,row_id,priority=True)
                    cur.execute('UPDATE collection_instances SET priority_pending=1 WHERE id=?',(row_id,))
                cur.execute("""UPDATE collection_instances SET name=?,config_json=?,enabled=?,schedule=?,timezone=?,
                    next_run=?,last_error=NULL,state=?,requested=?,retired=0,updated_at=? WHERE id=?""",
                    (name,json.dumps(config),enabled,schedule,zone,next_runs[index],'queued' if requested else 'idle',
                     requested,now,row_id))
            else:
                cur.execute("""INSERT INTO collection_instances(id,group_id,model,library_id,name,config_json,enabled,schedule,timezone,next_run)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",(row_id,group_id,model,library_id,name,json.dumps(config),enabled,schedule,zone,next_runs[index]))
                if enabled:
                    cur.execute("UPDATE collection_instances SET requested='sync',state='queued' WHERE id=?", (row_id,))
        for old in previous:
            if old['library_id'] not in libraries:
                cur.execute("UPDATE collection_instances SET enabled=0,retired=1,next_run=NULL,requested='cleanup',state='queued',updated_at=? WHERE id=?",(now,old['id']))
    return next(row for row in list_instances(db) if row['id']==group_id)


def request_run(db, instance_id, kind):
    if kind not in ('sync','preview','cleanup','delete','resume'):
        raise ValueError('collections.invalid_configuration')
    now = stamp()
    with db.transaction() as cur:
        rows = cur.execute('SELECT * FROM collection_instances WHERE group_id=? OR id=?',(instance_id,instance_id)).fetchall()
        if not rows:
            raise ValueError('collections.not_found')
        if kind=='resume':
            if any(row['lease_until'] and row['lease_until']>now for row in rows):
                raise ValueError('collections.busy')
            if not any(row['state']=='queued' for row in rows):
                raise ValueError('collections.invalid_configuration')
            for row in rows:
                if row['state']=='queued':
                    cur.execute("UPDATE collection_instances SET requested=COALESCE(requested,?),updated_at=? WHERE id=?",
                        ('sync' if row['enabled'] and not row['retired'] else 'cleanup',now,row['id']))
            return
        for row in rows:
            if row['model'] not in ('memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems') and kind!='delete':
                raise ValueError('collections.engine_unavailable')
            if (row['requested'] and not (row['requested']=='sync' and row['state']=='queued') and not (kind=='sync' and row['requested']=='visibility')) or row['lease_until'] and row['lease_until']>now:
                raise ValueError('collections.busy')
            if kind=='sync' and not row['enabled'] and not row['retired']:
                raise ValueError('collections.collection_disabled')
        for row in rows:
            if not row['retired'] or kind=='delete':
                cur.execute("UPDATE collection_instances SET requested=?,state='queued',updated_at=? WHERE id=?",(kind,now,row['id']))


def due_sql():
    return """SELECT i.* FROM collection_instances i WHERE
        (i.requested IS NOT 'visibility' OR NOT EXISTS(SELECT 1 FROM collection_controls c WHERE c.instance_id=i.id)) AND
        (i.state!='error' OR i.requested IS NOT NULL
         OR julianday(i.next_run)<=julianday('now')
         OR julianday(i.updated_at)<=julianday('now','-1 day')) AND
        (i.lease_until IS NULL OR i.lease_until<=?) AND
        (i.requested IS NOT NULL OR (i.enabled=1 AND i.next_run IS NOT NULL AND i.next_run<=?)
         OR EXISTS(SELECT 1 FROM collection_people p LEFT JOIN collection_objects o
            ON o.instance_id=p.instance_id AND o.person_key=p.person_key
            WHERE p.instance_id=i.id AND (p.expires_at<=? OR (i.enabled=0 AND o.state!='deleted' AND o.remote_id IS NOT NULL)))
         OR EXISTS(SELECT 1 FROM collection_seasonal_windows w WHERE w.instance_id=i.id AND julianday(w.expires_at)<=julianday('now'))
         OR EXISTS(SELECT 1 FROM collection_spotlight_entries e WHERE e.instance_id=i.id AND e.active=1 AND julianday(e.expires)<=julianday('now'))
         OR EXISTS(SELECT 1 FROM collection_person_choices c WHERE c.group_id=COALESCE(i.group_id,i.id)
            AND c.data_json!='{}' AND julianday(c.expires_at)<=julianday('now')))
        ORDER BY i.created_at,i.id"""


def recover_stale_collection_runs(db):
    now = stamp()
    with db.transaction() as cur:
        cur.execute("""UPDATE collection_instances SET requested=NULL,state='idle'
            WHERE requested='visibility' AND (lease_until IS NULL OR lease_until<=?)
            AND EXISTS(SELECT 1 FROM collection_controls c WHERE c.instance_id=collection_instances.id
                AND c.state='applied' AND c.revision=c.applied_revision)""",(now,))
        stale = cur.execute("SELECT id FROM collection_instances WHERE state='running' AND (lease_until IS NULL OR lease_until<=?)",(now,)).fetchall()
        for row in stale:
            cur.execute("UPDATE collection_runs SET state='interrupted',finished_at=? WHERE instance_id=? AND state='running'",(now,row['id']))
            cur.execute("UPDATE collection_instances SET state='interrupted',lease_id=NULL,lease_until=NULL,requested=CASE WHEN requested='cancel' THEN NULL ELSE requested END WHERE id=?",(row['id'],))
    return len(stale)


def stop_collection(db, group_id):
    now = stamp()
    zone = global_timezone(db)
    with db.transaction() as cur:
        rows = cur.execute('SELECT * FROM collection_instances WHERE group_id=? OR id=?',(group_id,group_id)).fetchall()
        if not rows:
            raise ValueError('collections.not_found')
        for row in rows:
            if row['lease_until'] and row['lease_until']>now:
                cur.execute("UPDATE collection_instances SET requested='cancel' WHERE id=?",(row['id'],))
            else:
                next_run = next_collection_run(dict(row))
                cur.execute("UPDATE collection_instances SET requested=NULL,state='idle',lease_id=NULL,lease_until=NULL,next_run=? WHERE id=?",(next_run,row['id']))
                cur.execute("UPDATE collection_runs SET state='interrupted',finished_at=? WHERE instance_id=? AND state='running'",(now,row['id']))


def wake_due_collections(db, enqueue):
    """The existing scheduler wakes the same daily task for individual deadlines."""
    recover_stale_collection_runs(db)
    migrate_collection_schedules(db)
    now = stamp()
    task = db.query_one("SELECT id,enabled,status,queued_count FROM tasks WHERE name='run_collections'")
    if not task or not task['enabled'] or task['status']=='running' or task['queued_count']:
        return False
    zone = global_timezone(db)
    for row in db.query('SELECT * FROM collection_instances WHERE timezone!=? AND (lease_until IS NULL OR lease_until<=?)',(zone,now)):
        db.execute('UPDATE collection_instances SET timezone=?,next_run=? WHERE id=?',
            (zone,next_collection_run({**dict(row), 'timezone': zone}),row['id']))
    if db.query_one(due_sql() + ' LIMIT 1', (now,now,now)):
        return bool(enqueue(int(task['id'])))
    return False
