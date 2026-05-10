from typing import Any, Dict, List, Optional

import requests
from plexapi.server import PlexServer

from logging_utils import get_logger
from core.plex_rate_limit import install_plex_rate_limit, wait_for_plex_slot

log = get_logger("plex_connection")


def row_get(row: Any, key: str, default: Any = None) -> Any:
	try:
		if isinstance(row, dict):
			return row.get(key, default)
		return row[key]
	except Exception:
		return default


def normalize_plex_url(value: Any) -> str:
	url = str(value or "").strip().rstrip("/")

	if url.lower() in ("", "none", "null"):
		return ""

	if not url.startswith(("http://", "https://")):
		url = "http://" + url

	return url


def plex_candidate_base_urls(server_row: Any) -> List[str]:
	urls = []

	for key in ("url", "local_url", "public_url"):
		url = normalize_plex_url(row_get(server_row, key))
		if url and url not in urls:
			urls.append(url)

	return urls


def get_plex_token(server_row: Any) -> str:
	return str(row_get(server_row, "token") or "").strip()


def find_working_plex_base_url(
	server_row: Any,
	endpoint: str = "/identity",
	accept: str = "application/xml",
	timeout: int = 15,
) -> str:
	token = get_plex_token(server_row)
	server_id = row_get(server_row, "id", "?")
	server_name = row_get(server_row, "name", "?")

	urls = plex_candidate_base_urls(server_row)

	if not urls:
		return ""

	if not token:
		return urls[0]

	for base_url in urls:
		try:
			wait_for_plex_slot(base_url)

			resp = requests.get(
				f"{base_url}{endpoint}",
				headers={
					"X-Plex-Token": token,
					"Accept": accept,
				},
				timeout=timeout,
			)

			if resp.status_code == 200:
				log.info(
					f"[PLEX URL] Working URL selected "
					f"server_id={server_id} name={server_name} "
					f"endpoint={endpoint} base_url={base_url}"
				)
				return base_url

			log.warning(
				f"[PLEX URL] URL failed "
				f"server_id={server_id} name={server_name} "
				f"endpoint={endpoint} base_url={base_url} HTTP={resp.status_code}"
			)

		except Exception as e:
			log.warning(
				f"[PLEX URL] URL unreachable "
				f"server_id={server_id} name={server_name} "
				f"endpoint={endpoint} base_url={base_url}: {e}"
			)

	return urls[0]


def get_plex_server(
	server_row: Any,
	endpoint: str = "/identity",
	accept: str = "application/xml",
	timeout: int = 20,
):
	base_url = find_working_plex_base_url(
		server_row,
		endpoint=endpoint,
		accept=accept,
		timeout=timeout,
	)
	token = get_plex_token(server_row)

	if not base_url or not token:
		name = row_get(server_row, "name", "?")
		raise RuntimeError(f"Incomplete Plex server configuration (URL/token): {name}")

	session = requests.Session()
	install_plex_rate_limit(session, base_url)

	return PlexServer(base_url, token, session=session)