#!/usr/bin/env python3
import os
import json
import re
from typing import Dict, Callable, Optional, Tuple

DEFAULT_BRAND_FALLBACK = "Vodum"


def _load_lang_dict(lang_code: str, lang_dir: str) -> Dict[str, str]:
    path = os.path.join(lang_dir, f"{lang_code}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_script_translator(settings: Dict, lang_dir: str = "/app/lang") -> Callable[[str], str]:
    """
    Traducteur i18n utilisable dans les scripts (hors Flask).
    Langue = settings.default_language sinon 'en'.
    """
    lang = (settings or {}).get("default_language") or "en"
    d = _load_lang_dict(lang, lang_dir)

    def t(key: str) -> str:
        if not key:
            return ""
        return d.get(key, key)

    return t


def get_brand_name(settings: Dict, fallback: str = DEFAULT_BRAND_FALLBACK) -> str:
    """
    brand_name peut être vide => fallback stable.
    """
    val = (settings or {}).get("brand_name")
    val = (val or "").strip()
    return val if val else fallback


def html_to_plain(html: str) -> str:
    """Texte lisible à partir d'un HTML simple."""
    if not html:
        return ""
    txt = re.sub(r"(?i)<br\s*/?>", "\n", html)
    txt = re.sub(r"(?i)</p\s*>", "\n\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def normalize_body_to_html(body: str) -> str:
    """
    Si body est du texte brut (sans balises), on :
    - échappe &, <, >
    - transforme les URLs en liens cliquables
    - transforme \n en <br>
    Si c'est déjà du HTML, on ne touche pas.
    """
    if not body:
        return ""

    # Détection HTML "grossière"
    if re.search(r"<[a-zA-Z][^>]*>", body):
        return body

    # Escape
    escaped = (
        body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )

    # Linkify (sur la version échappée)
    def _linkify(m):
        url = m.group(1)
        return f'<a href="{url}" style="color:#60a5fa;text-decoration:underline;">{url}</a>'

    escaped = re.sub(r"(https?://[^\s]+)", _linkify, escaped)

    # Newlines -> <br>
    return escaped.replace("\n", "<br>\n")


def wrap_email_html(inner_html: str, title: str, footer_text: str) -> str:
    """
    Wrapper email-safe (Gmail/Outlook) via tables + styles inline.
    """
    inner_html = inner_html or ""
    title = title or DEFAULT_BRAND_FALLBACK
    footer_text = footer_text or ""
    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background-color:#0b1220;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0b1220;padding:24px 0;">
      <tr>
        <td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;background:#111a2e;border:1px solid rgba(255,255,255,0.08);border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:bold;color:#ffffff;border-bottom:1px solid rgba(255,255,255,0.08);">
                {title}
              </td>
            </tr>
            <tr>
              <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#e5e7eb;">
                {inner_html}
              </td>
            </tr>
            <tr>
              <td style="padding:14px 22px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#9ca3af;border-top:1px solid rgba(255,255,255,0.08);">
                © {title}{(" — " + footer_text) if footer_text else ""}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def build_email_parts(body: str, settings: Dict, lang_dir: str = "/app/lang") -> Tuple[str, str]:
    """
    Retourne: (plain_text, full_html)
    """
    t = get_script_translator(settings, lang_dir=lang_dir)

    brand = get_brand_name(settings)
    footer = t("email_automatic_notice")

    inner_html = normalize_body_to_html(body)
    full_html = wrap_email_html(inner_html, title=brand, footer_text=footer)
    plain = html_to_plain(inner_html)

    return plain, full_html
