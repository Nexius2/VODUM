"""Memoria's Wikidata detection / TMDb credits flow, using stable person IDs.

Adapted from the neighbouring Memoria project's detection_service and
tmdb_service. A name match alone is never sufficient to identify a person.
"""
import re
import json
from datetime import timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from core.collections_repository import stamp, utcnow


class MemoriaSource:
    def __init__(self, api_key, language):
        if not api_key:
            raise ValueError('collections.tmdb_key_required')
        self.heartbeat = lambda: None
        self.key = api_key
        self.language = language
        self.external_ids_cache = {}
        self.db = None
        self.http = requests.Session()
        self.http.headers['User-Agent'] = 'VODUM-Memoria/1.0 (https://github.com/Nexius2/VODUM)'
        self.http.mount('https://', HTTPAdapter(max_retries=Retry(
            total=2, backoff_factor=1, status_forcelist=(429,502,503,504),
            allowed_methods=('GET',), respect_retry_after_header=False)))
        self.http.mount('https://query.wikidata.org/',HTTPAdapter(max_retries=0))

    def close(self):
        self.http.close()

    def tmdb(self, path, **params):
        headers = {'Authorization':'Bearer ' + self.key} if '.' in self.key else {}
        if not headers:
            params['api_key'] = self.key
        self.heartbeat()
        response = self.http.get('https://api.themoviedb.org/3' + path,
            params={'language':self.language, **params}, headers=headers, timeout=(10,30))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError('Invalid TMDb response')
        return data

    def recent_deaths(self, now, days, credits):
        start = (now - timedelta(days=days-1)).date().isoformat()
        end = now.date().isoformat()
        cache_key = json.dumps([start,end,credits,self.language])
        self.heartbeat()
        cached = self.db.query_one('SELECT data_json FROM collection_discovery_cache WHERE cache_key=? AND updated_at>?',
            (cache_key,stamp(utcnow()-timedelta(hours=6)))) if self.db is not None else None
        if cached:
            return json.loads(cached['data_json'])
        occupations = {'actors':'wd:Q33999', 'directors':'wd:Q2526255',
                       'actors_directors':'wd:Q33999 wd:Q2526255'}[credits]
        query = f'''PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT DISTINCT ?person ?personLabel ?death ?tmdb ?imdb ?sitelinks WHERE {{
          VALUES ?profession {{ {occupations} }}
          ?person wdt:P31 wd:Q5; wdt:P570 ?death; wdt:P106/wdt:P279* ?profession.
          FILTER(?death >= "{start}T00:00:00Z"^^xsd:dateTime && ?death <= "{end}T23:59:59Z"^^xsd:dateTime)
          OPTIONAL {{?person wikibase:sitelinks ?sitelinks.}}
          OPTIONAL {{?person wdt:P4985 ?tmdb.}} OPTIONAL {{?person wdt:P345 ?imdb.}}
          SERVICE wikibase:label {{bd:serviceParam wikibase:language "{self.language},en".}}
        }} ORDER BY DESC(?death)'''
        self.heartbeat()
        response = self.http.get('https://query.wikidata.org/sparql',
            params={'query':query,'format':'json'}, headers={'Accept':'application/sparql-results+json'}, timeout=(5,30))
        response.raise_for_status()
        bindings = response.json()['results']['bindings']
        result = {}
        for binding in bindings:
            value = lambda name: binding.get(name, {}).get('value', '')
            key = value('person').rsplit('/',1)[-1]
            if not re.fullmatch(r'Q[1-9][0-9]*', key):
                continue
            item = {'person_key':key,'name':value('personLabel'), 'death_date':value('death')[:10],
                    'tmdb_id':int(value('tmdb')) if value('tmdb').isdigit() else None,
                    'imdb_id':value('imdb'), 'popularity_score':int(value('sitelinks')) if value('sitelinks').isdigit() else 0}
            # Conflicting identities/dates must not be selected arbitrarily.
            if key in result and result[key] != item:
                raise RuntimeError('Wikidata supplied conflicting person identities')
            result[key] = item
        people = list(result.values())
        if self.db is not None:
            self.db.execute('INSERT INTO collection_discovery_cache(cache_key,data_json,updated_at) VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at',
                (cache_key,json.dumps(people),stamp()))
            self.db.execute('DELETE FROM collection_discovery_cache WHERE updated_at<?',(stamp(utcnow()-timedelta(days=7)),))
        return people

    def verify_person(self, candidate):
        person_id = candidate.get('tmdb_id')
        if not person_id and re.fullmatch(r'nm[0-9]+', candidate.get('imdb_id') or ''):
            matches = self.tmdb('/find/' + candidate['imdb_id'], external_source='imdb_id').get('person_results', [])
            if len(matches) == 1:
                person_id = matches[0]['id']
        if not person_id:
            return None
        person = self.tmdb('/person/' + str(int(person_id)), append_to_response='external_ids')
        ids = person.get('external_ids') or {}
        if ids.get('wikidata_id') != candidate['person_key']:
            return None
        if not person.get('deathday') or person['deathday'] != candidate['death_date']:
            return None
        return {**candidate, 'tmdb_id':int(person_id), 'name':person['name'],
                'aliases':person.get('also_known_as') or [],'credits':person.get('combined_credits'), 'profile_path':person.get('profile_path')}

    def eligible_credits(self, person, media_type, credits):
        combined = person.get('credits')
        if combined is None:
            combined = self.tmdb('/person/'+str(int(person['tmdb_id']))+'/combined_credits')
            person['credits'] = combined
        selected = []
        if credits in ('actors','actors_directors'):
            selected += combined.get('cast') or []
        if credits in ('directors','actors_directors'):
            selected += [row for row in combined.get('crew') or [] if row.get('job') == 'Director']
        # Do not apply the visible collection limit to the filmography for ARR.
        unique = {int(row['id']):row for row in selected
                  if row.get('media_type') == media_type and type(row.get('id')) is int and row['id'] > 0}
        return sorted(unique.values(), key=lambda row:(row.get('release_date') or row.get('first_air_date') or '', row['id']), reverse=True)

    def media_external_ids(self, media_type, media_id):
        key = (media_type,int(media_id))
        if key not in self.external_ids_cache:
            self.heartbeat()
            cached = self.db.query_one('SELECT data_json FROM collection_external_ids WHERE media_type=? AND media_id=? AND updated_at>?',
                (*key,stamp(utcnow()-timedelta(days=30)))) if self.db is not None else None
            if cached:
                self.external_ids_cache[key] = json.loads(cached['data_json'])
            else:
                data = self.tmdb('/'+media_type+'/'+str(int(media_id))+'/external_ids')
                self.external_ids_cache[key] = data
                if self.db is not None:
                    self.db.execute('INSERT INTO collection_external_ids(media_type,media_id,data_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(media_type,media_id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at',
                        (*key,json.dumps(data),stamp()))
        return self.external_ids_cache[key]

    def search_people(self, query):
        query = str(query or '').strip()
        if not 2<=len(query)<=100:
            raise ValueError('collections.search_query_required')
        rows = self.tmdb('/search/person',query=query,include_adult='false').get('results') or []
        return [{'tmdb_id':int(row['id']),'name':row.get('name',''),
                 'known_for':', '.join(item.get('title') or item.get('name') or '' for item in (row.get('known_for') or [])),
                 'department':row.get('known_for_department') or '', 'profile_path':row.get('profile_path')}
                for row in rows[:20] if type(row.get('id')) is int and row['id']>0]

    def web_score(self, wikidata_id):
        """Use the same Wikidata sitelink metric for manual and automatic people."""
        if not re.fullmatch(r'Q[1-9][0-9]*', wikidata_id):
            return None
        self.heartbeat()
        try:
            response = self.http.get('https://query.wikidata.org/sparql',
                params={'query': 'SELECT ?score WHERE { <http://www.wikidata.org/entity/'
                        + wikidata_id + '> <http://wikiba.se/ontology#sitelinks> ?score. }',
                        'format':'json'},
                headers={'Accept':'application/sparql-results+json'}, timeout=(5,15))
            response.raise_for_status()
            rows = response.json()['results']['bindings']
            return int(rows[0]['score']['value']) if rows else None
        except (requests.RequestException, ValueError, KeyError, TypeError):
            from core.error_reporting import log_handled_failure
            log_handled_failure('collections.memoria.web_score')
            return None

    def manual_person(self, tmdb_id):
        tmdb_id = int(tmdb_id)
        if tmdb_id<=0:
            raise ValueError('collections.person_not_found')
        person = self.tmdb('/person/'+str(tmdb_id),append_to_response='external_ids')
        if person.get('id')!=tmdb_id or not person.get('name'):
            raise ValueError('collections.person_not_found')
        wikidata = (person.get('external_ids') or {}).get('wikidata_id') or ''
        key = wikidata if re.fullmatch(r'Q[1-9][0-9]*',wikidata) else 'TMDB:'+str(tmdb_id)
        return {'person_key':key,'tmdb_id':tmdb_id,'name':person['name'],
                'death_date':person.get('deathday') or '', 'credits':person.get('combined_credits'),
                'aliases':person.get('also_known_as') or [],'profile_path':person.get('profile_path'),
                'popularity_score':self.web_score(wikidata)}
