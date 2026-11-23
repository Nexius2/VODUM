"""Selection du moment calendar, digital-release and scoring rules."""
from datetime import date, datetime, timedelta
import math

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
