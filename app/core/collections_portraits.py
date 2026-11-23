"""Bounded TMDb / IMDb image proxy; no arbitrary remote URLs."""
import re
import os
import hashlib
import threading
import time
from pathlib import Path
from uuid import uuid4
from core.monitoring.artwork_cache import detect_image_content_type

import requests


def portrait_path(value):
    return value if isinstance(value,str) and len(value)<=1024 and (re.fullmatch(r'/[A-Za-z0-9_-]+\.(?:jpg|png|webp)',value) or re.fullmatch(r'imdb:/images/M/[A-Za-z0-9_@.,-]+\.(?:jpg|png|webp)',value)) else None


def _download_portrait(path, *, size='w185'):
    if size not in ('w185','w500'):
        raise ValueError('Invalid portrait size')
    if not portrait_path(path):
        raise ValueError('Invalid portrait path')
    url = 'https://m.media-amazon.com'+path[5:] if path.startswith('imdb:') else 'https://image.tmdb.org/t/p/'+size+path
    if path.startswith('imdb:'):
        # IMDb originals can exceed 2 MB. Ask its CDN for a bounded thumbnail.
        width='185' if size=='w185' else '500'
        url=re.sub(r'(?:\._V1_[^.]*|\._V1_)\.(jpg|png|webp)$', r'._V1_QL80_UX'+width+r'_.\1',url)
        if not re.search(r'\._V1_',url):
            url=re.sub(r'\.(jpg|png|webp)$',r'._V1_QL80_UX'+width+r'_.\1',url)
    response = requests.get(url,
        timeout=(5,12),allow_redirects=False,stream=True)
    try:
        content_type = response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
        if response.status_code!=200 or content_type not in ('image/jpeg','image/png','image/webp'):
            return None
        chunks, size = [], 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size>2*1024*1024:
                raise ValueError('Portrait exceeds size limit')
            chunks.append(chunk)
        if not size:
            return None
        return b''.join(chunks),content_type
    finally:
        response.close()


_CACHE_LOCKS=[threading.Lock() for _ in range(32)]
_PRUNE_LOCK=threading.Lock()
_last_prune=float('-inf')
_CACHE_TTL=30*24*3600
_CACHE_BUDGET=256*1024*1024


def _cache_root():
    return Path(os.environ.get('VODUM_COLLECTION_POSTER_CACHE_DIR') or
                str(Path(os.environ.get('DATABASE_PATH','/appdata/database.db')).parent/'collection_posters'))


def _read_cached(path):
    try:
        if path.stat().st_size>2*1024*1024:return None
        data=path.read_bytes()
        mime=detect_image_content_type(data)
        if mime in ('image/jpeg','image/png','image/webp'):return data,mime
    except OSError:pass
    return None


def _prune_cache(root):
    global _last_prune
    with _PRUNE_LOCK:
        if time.monotonic()-_last_prune<3600:return
        _last_prune=time.monotonic()
        try:
            files=[]
            for path in root.glob('*.img'):
                if not re.fullmatch(r'[0-9a-f]{64}\.img',path.name):continue
                stat=path.stat();files.append((stat.st_mtime,stat.st_size,path))
            total=sum(size for _,size,_ in files)
            for _,size,path in sorted(files):
                if total<=_CACHE_BUDGET:break
                path.unlink(missing_ok=True);total-=size
        except OSError:pass


def fetch_portrait(path, *, size='w185'):
    if size not in ('w185','w500') or not portrait_path(path):
        raise ValueError('Invalid portrait path or size')
    key=hashlib.sha256(('v2|'+size+'|'+path).encode()).hexdigest()
    cache=_cache_root()/(key+'.img')
    with _CACHE_LOCKS[int(key[:2],16)%len(_CACHE_LOCKS)]:
        cached=_read_cached(cache)
        try:fresh=time.time()-cache.stat().st_mtime<_CACHE_TTL
        except OSError:fresh=False
        if cached and fresh:return cached
        try:
            result=_download_portrait(path,size=size)
        except (requests.RequestException,ValueError):
            if cached:return cached
            raise
        if result is None:return cached
        # Validate bytes, not just the upstream Content-Type, before persisting.
        mime=detect_image_content_type(result[0])
        if mime not in ('image/jpeg','image/png','image/webp'):return cached
        result=(result[0],mime)
        temporary=None
        try:
            cache.parent.mkdir(parents=True,exist_ok=True)
            temporary=cache.with_suffix('.'+uuid4().hex+'.tmp')
            temporary.write_bytes(result[0]);os.replace(temporary,cache)
            _prune_cache(cache.parent)
        except OSError:pass  # A read-only/full volume must not prevent display.
        finally:
            if temporary:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
        return result
