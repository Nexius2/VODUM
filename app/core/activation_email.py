"""Keep configured welcome content and render exactly one activation action."""
import html
import re

from core.communication_i18n import communication_translate


def activation_email_body(body, url, language):
    label = communication_translate('activation.button', language)
    # Replace an explicit placeholder with the canonical button; for old templates append it.
    body = str(body or '').replace('{activation_url}', '')
    body = re.sub(r'<a\b[^>]*>(.*?)</a\s*>', r'\1', body, flags=re.I | re.S)
    if not re.search(r'<[a-zA-Z][^>]*>', body):
        body = html.escape(body).replace('\n', '<br>')
    button = '<p><a href="{}" style="display:inline-block;padding:14px 22px;background:#2563eb;color:#fff;text-decoration:none;border-radius:8px">{}</a></p>'
    return body + button.format(html.escape(url, quote=True), html.escape(label))
