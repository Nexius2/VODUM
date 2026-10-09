"""Bound application logs by both age and disk usage."""
import re
import time
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from functools import lru_cache


@lru_cache(maxsize=4096)
def _record_datetime(stamp):
    try:
        return datetime.strptime(stamp.decode("ascii"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def validate_log_retention(days, size_mb):
    days, size_mb = int(days), int(size_mb)
    if days not in (7, 14, 30, 90) or not 5 <= size_mb <= 1000:
        raise ValueError("Invalid log retention settings")
    return days, size_mb


class RetentionFileHandler(RotatingFileHandler):
    def __init__(self, filename, policy):
        super().__init__(filename, maxBytes=5_000_000, backupCount=10,
                         encoding="utf-8", delay=True)
        self.policy = policy
        self.retention_days = 30
        self.limit_bytes = 50_000_000
        self.next_policy_check = 0
        self.next_age_check = 0
        self._age_checks = {}

    def paths(self):
        base = Path(self.baseFilename)
        archives = [p for p in base.parent.glob(base.name + ".*")
                    if p.name[len(base.name) + 1:].isdigit()]
        return sorted(archives, key=lambda p: int(p.suffix[1:]), reverse=True) + [base]

    def maintain(self, force=False):
        self.acquire()
        try:
            now = time.time()
            if force or now >= self.next_policy_check:
                days, size = validate_log_retention(*self.policy())
                if days != self.retention_days:
                    self.next_age_check = 0
                self.retention_days, self.limit_bytes = days, size * 1_000_000
                self.backupCount = max(1, self.limit_bytes // self.maxBytes)
                self.next_policy_check = now + 10
            if force or now >= self.next_age_check:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                cutoff = now - self.retention_days * 86400
                cutoff_local = datetime.fromtimestamp(cutoff)
                for path in self.paths():
                    if not path.exists():
                        continue
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size,
                                 self.retention_days)
                    checked = self._age_checks.get(path)
                    if checked and checked[0] == signature and cutoff_local < checked[1]:
                        continue
                    lines = path.read_bytes().splitlines(keepends=True)
                    keep = stat.st_mtime >= cutoff
                    # A conservative earliest retained timestamp also covers
                    # unstructured legacy lines and malformed timestamp fallbacks.
                    earliest = datetime.fromtimestamp(stat.st_mtime)
                    retained = []
                    for line in lines:
                        if re.match(rb"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line):
                            stamp = _record_datetime(line[:19])
                            if stamp is not None:
                                keep = stamp >= cutoff_local
                                if keep:
                                    earliest = min(earliest, stamp)
                        if keep:
                            retained.append(line)
                    if retained != lines:
                        if retained:
                            path.write_bytes(b"".join(retained))
                        else:
                            path.unlink()
                    if path.exists():
                        stat = path.stat()
                        self._age_checks[path] = (
                            (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size,
                             self.retention_days), earliest)
                    else:
                        self._age_checks.pop(path, None)
                self.next_age_check = now + 3600
            paths = [p for p in self.paths() if p.exists()]
            self._age_checks = {p: checked for p, checked in self._age_checks.items()
                                if p in paths}
            total = sum(p.stat().st_size for p in paths)
            for path in paths:
                if total <= self.limit_bytes:
                    break
                size = path.stat().st_size
                if str(path) == self.baseFilename and self.stream:
                    self.stream.close()
                    self.stream = None
                path.unlink()
                total -= size
        finally:
            self.release()

    def emit(self, record):
        try:
            self.maintain()
        except Exception:
            self.handleError(record)
        # A cleanup failure must not prevent recording the original event.
        super().emit(record)
        try:
            self.maintain()
        except Exception:
            self.handleError(record)
