"""Bounded TMDb portrait proxy; no remote URLs or persistent image cache."""
import re

import requests


def portrait_path(value):
    return value if isinstance(value,str) and re.fullmatch(r'/[A-Za-z0-9_-]+\.(?:jpg|png|webp)',value) else None


def fetch_portrait(path, *, size='w185'):
    if size not in ('w185','w500'):
        raise ValueError('Invalid portrait size')
    if not portrait_path(path):
        raise ValueError('Invalid portrait path')
    response = requests.get('https://image.tmdb.org/t/p/'+size+path,
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
