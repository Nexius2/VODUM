"""Bounded CPU cost for existing Flask text-response compression."""
import gzip
from flask import request

TEXT_MIMETYPES = {'application/javascript', 'application/json', 'application/xml',
                 'image/svg+xml', 'text/css', 'text/html', 'text/javascript', 'text/plain', 'text/xml'}


def compress_text_response(response, *, enabled=True, min_size=1024, level=6):
    if not enabled or request.method == 'HEAD' or 'gzip' not in request.headers.get('Accept-Encoding', '').lower():
        return response
    if response.status_code < 200 or response.status_code in (204, 304):
        return response
    if response.direct_passthrough or response.is_streamed:
        return response
    if response.headers.get('Content-Encoding') or response.headers.get('Content-Range'):
        return response
    if request.path.startswith('/static') or response.mimetype not in TEXT_MIMETYPES:
        return response
    content_length = response.calculate_content_length()
    if content_length is not None and content_length < min_size:
        return response
    payload = response.get_data()
    if len(payload) < min_size:
        return response
    compressed = gzip.compress(payload, compresslevel=level)
    if len(compressed) >= len(payload):
        return response
    response.set_data(compressed)
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = str(len(compressed))
    response.headers.add('Vary', 'Accept-Encoding')
    response.headers.pop('ETag', None)
    return response
