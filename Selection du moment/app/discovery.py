from datetime import date, datetime, timedelta
import math
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class TMDB:
    def __init__(self, config):
        self.config = config
        self.partial = False
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods={'GET'}, respect_retry_after_header=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    def get(self, path, **params):
        try:
            response = self.session.get('https://api.themoviedb.org/3/' + path,
                params={'api_key': self.config['api_key'], 'language': self.config['language'], **params}, timeout=20)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('TMDB : requête échouée') from None

    def discover(self, now, config):
        self.partial = False
        today = now.date()
        end = recent_movie_end(today)
        start = today - timedelta(days=config['collection']['release_window_days'] - 1)
        trending = {}
        try:
            trending = {m['id']: i for i, m in enumerate(self.get('trending/movie/week')['results'])}
        except RuntimeError:
            self.partial = True
            log.warning('TMDB : tendances indisponibles')
        ids = set(trending)
        page = 1
        while True:
            data = self.get('discover/movie', with_release_type='4',
                            **{'release_date.gte': start.isoformat(), 'release_date.lte': end.isoformat()},
                            sort_by='popularity.desc', page=page, include_adult='false')
            ids.update(m['id'] for m in data['results'])
            if page >= min(data.get('total_pages', 1), 500):
                if data.get('total_pages', 1) > 500:
                    log.warning('TMDB : limite technique de pagination atteinte')
                break
            page += 1
        for movie_id in sorted(ids):
            try:
                movie = self.get(f'movie/{movie_id}', append_to_response='release_dates')
                if movie.get('adult'):
                    continue
                first_release = initial_release(movie)
                earliest = recent_movie_start(today)
                if first_release is None or not earliest <= first_release <= end:
                    log.info('REJECT %s [TMDB=%s] : sortie initiale attendue entre %s et %s',
                             movie.get('title'), first_release or 'inconnue', earliest, end)
                    continue
                events = digital_events(movie, start, end)
                if not events:
                    log.info('REJECT %s : aucune sortie numérique mondiale vérifiée entre %s et %s',
                             movie.get('title'), start, end)
                    continue
                movie['events'] = events
                movie['initial_release'] = first_release
                movie['trend'] = 1 - trending[movie_id] / max(len(trending), 1) if movie_id in trending else 0
                yield movie
            except Exception:
                self.partial = True
                log.error('TMDB : candidat %s indisponible', movie_id)


def recent_movie_start(today):
    """Beginning of the previous calendar month, including year transitions."""
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def recent_movie_end(today):
    return today + timedelta(days=30)


def initial_release(movie):
    """Earliest known release worldwide; a regional reissue cannot reset film age."""
    dates = []
    try:
        dates.append(date.fromisoformat(movie.get('release_date', '')))
    except (ValueError, TypeError):
        pass
    for country in movie.get('release_dates', {}).get('results', []):
        for release in country.get('release_dates', []):
            try:
                dates.append(datetime.fromisoformat(release['release_date'].replace('Z', '+00:00')).date())
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return min(dates) if dates else None


def digital_events(movie, start, today):
    """Recent digital releases in any country, independently of audio language."""
    events = set()
    for country in movie.get('release_dates', {}).get('results', []):
        for release in country['release_dates']:
            if release['type'] != 4:
                continue
            try:
                day = datetime.fromisoformat(release['release_date'].replace('Z', '+00:00')).date()
            except (ValueError, KeyError):
                continue
            if start <= day <= today:
                events.add(day)
    return sorted(events)


def score(movie, now, config):
    s = config['scoring']
    votes, rating, popularity = movie.get('vote_count', 0), movie.get('vote_average', 0), movie.get('popularity', 0)
    weighted = (votes * rating + s['minimum_votes'] * 6) / (votes + s['minimum_votes'])
    age = (now.date() - max(movie['events'])).days
    signals = {'freshness': min(1, max(0, 1-age/config['collection']['release_window_days'])),
               'popularity': min(1, math.log1p(max(0, popularity))/math.log1p(100)),
               'rating': max(0, min(1, (weighted-5)/3)),
               'trending': movie['trend'], 'franchise': float(bool(movie.get('belongs_to_collection')))}
    total = sum(s['weights'][k]*v for k,v in signals.items())
    profiles = []
    p = s['profiles']
    if popularity >= p['blockbuster_popularity']: profiles.append('film événement')
    if votes >= s['minimum_votes'] and weighted >= s['high_rating_threshold'] and popularity >= p['high_rated_popularity']:
        profiles.append('très bons avis')
    if movie.get('belongs_to_collection') and popularity >= p['franchise_popularity']: profiles.append('franchise')
    if movie['trend'] >= p['trend_strength'] and popularity >= p['trending_popularity']: profiles.append('tendance')
    return total, ', '.join(profiles), bool(profiles) and total >= s['min_score']
