"""Bound application logs by both age and disk usage."""
import re
import time
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler


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
                    lines = path.read_bytes().splitlines(keepends=True)
                    keep = path.stat().st_mtime >= cutoff
                    retained = []
                    for line in lines:
                        if re.match(rb"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line):
                            try:
                                keep = datetime.strptime(line[:19].decode("ascii"), "%Y-%m-%d %H:%M:%S") >= cutoff_local
                            except ValueError:
                                pass
                        if keep:
                            retained.append(line)
                    if retained != lines:
                        if retained:
                            path.write_bytes(b"".join(retained))
                        else:
                            path.unlink()
                self.next_age_check = now + 3600
            paths = [p for p in self.paths() if p.exists()]
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
