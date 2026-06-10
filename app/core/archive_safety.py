from __future__ import annotations

import os
import zipfile


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def validate_zip_limits(zipf: zipfile.ZipFile) -> None:
    max_members = _positive_env_int("VODUM_MAX_ZIP_MEMBERS", 10000)
    max_extracted_bytes = (
        _positive_env_int("VODUM_MAX_ZIP_EXTRACTED_MB", 8192) * 1024 * 1024
    )

    members = zipf.infolist()
    if len(members) > max_members:
        raise ValueError(
            f"Backup archive contains too many entries ({len(members)} > {max_members})"
        )

    extracted_bytes = sum(max(0, member.file_size) for member in members)
    if extracted_bytes > max_extracted_bytes:
        raise ValueError(
            "Backup archive is too large after extraction "
            f"({extracted_bytes} > {max_extracted_bytes} bytes)"
        )
