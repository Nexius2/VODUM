"""Keep configured welcome content and render exactly one activation action."""
import html
import re

from core.communication_i18n import communication_translate


def activation_email_body(body, url, language, *, provider=None):
    label = communication_translate('activation.button', language)
    intro = communication_translate('activation.instructions', language) if provider=='plex' else ''
    # Replace an explicit placeholder with the canonical button; for old templates append it.
    body = str(body or '').replace('{activation_url}', '')
    if not re.search(r'<[a-zA-Z][^>]*>', body):
        body = html.escape(body).replace('\n', '<br>')
    elif not re.search(r'<(?:br|p|div|table|html|ul|ol)\b',body,re.I):
        body = body.replace('\n','<br>')
    button = '<p><a href="{}" style="display:inline-block;padding:14px 22px;background:#2563eb;color:#fff;text-decoration:none;border-radius:8px">{}</a></p>'
    return ('<p>{}</p>'.format(html.escape(intro)) if intro else '') + button.format(html.escape(url, quote=True), html.escape(label)) + body
