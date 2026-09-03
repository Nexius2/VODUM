from __future__ import annotations

import os
import stat
import zipfile
from pathlib import PurePosixPath


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

    seen_names = set()
    for member in members:
        normalized_name = member.filename.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        if (
            not normalized_name
            or normalized_name.startswith("/")
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and ":" in path.parts[0])
        ):
            raise ValueError(f"Unsafe zip member path: {member.filename}")
        canonical = path.as_posix().rstrip("/")
        if canonical in seen_names:
            raise ValueError(f"Duplicate zip member path: {member.filename}")
        seen_names.add(canonical)
        if member.flag_bits & 0x1:
            raise ValueError(f"Encrypted zip members are not supported: {member.filename}")
        unix_mode = member.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if stat.S_ISLNK(unix_mode) or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"Unsupported special zip member: {member.filename}")
