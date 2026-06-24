# Logs

Logs provide timestamp, level, source and message with level/search filters and
pagination. Task errors are also visible from the Tasks page.

Downloaded logs pass through the anonymization filter. In normal mode VODUM
masks email local parts and common token/authorization patterns. Debug mode may
expose more context; enable it briefly and treat resulting logs as sensitive.

Useful sources include `boot`, provider synchronization, `tasks_engine`,
Communications workers, monitoring collectors, backups and migrations.

For container-start failures, also inspect:

```bash
docker compose logs vodum
```

The persistent entrypoint log is stored under `VODUM_LOG_DIR`.
