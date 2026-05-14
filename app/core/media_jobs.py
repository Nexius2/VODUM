from datetime import datetime, timedelta
import json


_ACCESS_ACTIONS = "('grant', 'revoke', 'sync')"


def _queued_after_running_key(dedupe_key: str) -> str:
	return f"{dedupe_key}:after-running"


def _has_running_access_job(db, *, provider: str, vodum_user_id: int, server_id: int) -> bool:
	row = db.query_one(
		f"""
		SELECT COUNT(*) AS c
		FROM media_jobs
		WHERE provider = ?
		  AND vodum_user_id = ?
		  AND server_id = ?
		  AND action IN {_ACCESS_ACTIONS}
		  AND status = 'running'
		  AND processed = 0
		  AND (locked_until IS NULL OR locked_until > CURRENT_TIMESTAMP)
		""",
		(provider, vodum_user_id, server_id),
	)
	return bool(row and int(row["c"] or 0) > 0)


def _queue_access_job(
	db,
	*,
	provider: str,
	action: str,
	vodum_user_id: int,
	server_id: int,
	library_id: int | None = None,
	dedupe_key: str,
	payload: dict | None = None,
	cancel_reason: str,
):
	if action not in {"grant", "revoke", "sync"}:
		raise ValueError(f"Unsupported media access job action: {action}")

	running_exists = _has_running_access_job(
		db,
		provider=provider,
		vodum_user_id=vodum_user_id,
		server_id=server_id,
	)

	effective_dedupe_key = _queued_after_running_key(dedupe_key) if running_exists else dedupe_key
	run_after = None
	if running_exists:
		run_after = (datetime.utcnow() + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")

	# Important: do NOT cancel live running jobs here.
	# A running worker cannot be stopped by flipping the DB status, and doing so can create
	# concurrent grant/revoke/sync jobs for the same user/server. We only cancel queued jobs.
	db.execute(
		f"""
		UPDATE media_jobs
		SET status = 'canceled',
			processed = 1,
			success = 0,
			processed_at = CURRENT_TIMESTAMP,
			locked_by = NULL,
			locked_until = NULL,
			last_error = ?
		WHERE provider = ?
		  AND vodum_user_id = ?
		  AND server_id = ?
		  AND action IN {_ACCESS_ACTIONS}
		  AND status = 'queued'
		  AND processed = 0
		""",
		(cancel_reason, provider, vodum_user_id, server_id),
	)

	db.execute(
		"""
		DELETE FROM media_jobs
		WHERE dedupe_key = ?
		  AND processed = 1
		""",
		(effective_dedupe_key,),
	)

	cur = db.execute(
		"""
		INSERT OR IGNORE INTO media_jobs(
			provider, action,
			vodum_user_id, server_id, library_id,
			payload_json,
			status, processed, success, attempts,
			dedupe_key, run_after
		)
		VALUES(
			?, ?, ?, ?, ?,
			?,
			'queued', 0, 0, 0,
			?, ?
		)
		""",
		(
			provider,
			action,
			vodum_user_id,
			server_id,
			library_id,
			json.dumps(payload or {}, ensure_ascii=False),
			effective_dedupe_key,
			run_after,
		),
	)

	return getattr(cur, "rowcount", 0) > 0


def insert_plex_media_job(
	db,
	*,
	action: str,
	vodum_user_id: int,
	server_id: int,
	library_id: int | None = None,
	dedupe_key: str,
	payload: dict | None = None,
	cancel_reason: str = "Canceled because a newer Plex access job was queued for the same user/server",
):
	return _queue_access_job(
		db,
		provider="plex",
		action=action,
		vodum_user_id=vodum_user_id,
		server_id=server_id,
		library_id=library_id,
		dedupe_key=dedupe_key,
		payload=payload,
		cancel_reason=cancel_reason,
	)


def insert_jellyfin_media_job(
	db,
	*,
	action: str,
	vodum_user_id: int,
	server_id: int,
	library_id: int | None = None,
	dedupe_key: str,
	payload: dict | None = None,
	cancel_reason: str = "Canceled because a newer Jellyfin access job was queued for the same user/server",
):
	return _queue_access_job(
		db,
		provider="jellyfin",
		action=action,
		vodum_user_id=vodum_user_id,
		server_id=server_id,
		library_id=library_id,
		dedupe_key=dedupe_key,
		payload=payload,
		cancel_reason=cancel_reason,
	)