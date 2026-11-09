from dataclasses import dataclass
from datetime import date, datetime
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from plexapi.server import PlexServer


@dataclass
class Movie:
    key: str
    tmdb: int | None
    title: str
    raw: object = None
    release_date: date | None = None

    @property
    def label(self):
        return f'{self.title} [Plex={self.release_date or "inconnue"}]'


class PlexClient:
    def __init__(self, config):
        self.config = config
        session = requests.Session()
        for scheme in ('http://', 'https://'):
            session.mount(scheme, HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, allowed_methods={'GET'})))
        self.server = PlexServer(config['url'], config['token'], session=session, timeout=20)
        self.section = self.server.library.section(config['library'])
        if self.section.type != 'movie':
            raise ValueError('Bibliothèque de films requise')
        self.collection()

    def collection(self):
        matches = [c for c in self.section.collections() if c.title == self.config['collection']]
        if len(matches) > 1:
            raise ValueError('Plusieurs collections portent ce nom')
        if not matches:
            return None
        if matches[0].smart:
            raise ValueError('Collection standard requise')
        return matches[0]

    @staticmethod
    def movie(item):
        ids = {int(m.group(1)) for guid in item.guids if (m := re.fullmatch(r'tmdb://(\d+)', guid.id))}
        released = getattr(item, 'originallyAvailableAt', None)
        if isinstance(released, datetime):
            released = released.date()
        if not isinstance(released, date):
            released = None
        return Movie(str(item.ratingKey), next(iter(ids)) if len(ids) == 1 else None, item.title, item, released)

    def members(self):
        collection = self.collection()
        return [self.movie(item) for item in collection.items()] if collection else []

    def library(self):
        return [self.movie(item) for item in self.section.all()]

    def has_french_audio(self, movie):
        # Library listings may omit streams: fetch the full item before deciding.
        movie.raw.reload()
        for media in movie.raw.media:
            parts = media.parts
            if parts and all(any(is_french_audio(stream) for stream in part.audioStreams())
                             for part in parts):
                return True
        return False

    def add(self, movie):
        collection = self.collection()
        if collection:
            collection.addItems([movie.raw])
        else:
            collection = self.section.createCollection(self.config['collection'], items=[movie.raw])
        self.move_to_front(movie, collection)

    def move_to_front(self, movie, collection=None):
        collection = collection if collection is not None else self.collection()
        if collection is None:
            raise RuntimeError('Collection introuvable pour le placement')
        # Preserve the displayed order when converting an existing sorted collection.
        if collection.collectionSort != 2:
            previous = collection.items()
            collection.sortUpdate(sort='custom')
            after = None
            for item in previous:
                collection.moveItem(item, after=after)
                after = item
        collection.moveItem(movie.raw, after=None)
        collection.reload()
        items = collection.items()
        if not items or str(items[0].ratingKey) != movie.key:
            raise RuntimeError('Placement en tête non confirmé')

    def remove(self, movie):
        collection = self.collection()
        if collection:
            collection.removeItems([movie.raw])


def is_french_audio(stream):
    """Use Plex language metadata, never filenames, track titles or subtitles."""
    for field in ('languageCode', 'languageTag', 'language'):
        value = str(getattr(stream, field, '') or '').strip().lower().replace('_', '-')
        if value.split('-')[0] in {'fr', 'fra', 'fre', 'french', 'français', 'francais'}:
            return True
    return False
