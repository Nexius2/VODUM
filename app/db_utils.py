import sqlite3
from typing import Any, Iterable, Optional

# ⚠️ AUCUNE ouverture de connexion SQLite ici
# Ce module ne fait que des helpers


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    """
    Convertit une liste de sqlite3.Row en liste de dict.
    Utile pour l'UI / JSON.
    """
    return [dict(row) for row in rows]


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    """
    Convertit une sqlite3.Row en dict.
    """
    if row is None:
        return None
    return dict(row)


def placeholders(count: int) -> str:
    """
    Génère des placeholders SQL (?, ?, ?, ...)
    """
    return ",".join("?" for _ in range(count))


def normalize_bool(value: Any) -> int:
    """
    Normalise une valeur booléenne vers SQLite (0 / 1)
    """
    return 1 if bool(value) else 0


def normalize_int(value: Any, default: int = 0) -> int:
    """
    Force une valeur en int, avec fallback.
    """
    try:
        return int(value)
    except Exception:
        return default
