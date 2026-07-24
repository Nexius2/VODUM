LIBRARY_TYPE_SQL = """
                CASE LOWER(TRIM(COALESCE(l.type, '')))
                    WHEN 'tvshows' THEN 'shows'
                    WHEN 'tvshow' THEN 'shows'
                    WHEN 'show' THEN 'shows'
                    WHEN 'series' THEN 'shows'
                    WHEN 'movies' THEN 'movie'
                    WHEN 'film' THEN 'movie'
                    WHEN 'films' THEN 'movie'
                    WHEN 'music' THEN 'music'
                    WHEN 'artist' THEN 'music'
                    WHEN 'artists' THEN 'music'
                    WHEN 'audio' THEN 'music'
                    ELSE COALESCE(NULLIF(LOWER(TRIM(l.type)), ''), 'unknown')
                END
"""

SERVERS_LIST_COLUMNS = """
                s.id,
                s.name,
                s.type,
                s.url,
                s.local_url,
                s.public_url,
                s.status,
                s.server_version
"""

LIBRARIES_LIST_COLUMNS = f"""
                l.id,
                l.server_id,
                l.name,
{LIBRARY_TYPE_SQL} AS type,
                l.section_id
"""

SERVER_DETAIL_COLUMNS = """
            id,
            name,
            type,
            url,
            local_url,
            public_url,
            status,
            settings_json
"""

SERVER_DETAIL_LIBRARY_COLUMNS = f"""
                l.id,
                l.name,
{LIBRARY_TYPE_SQL} AS type,
                l.section_id
"""
