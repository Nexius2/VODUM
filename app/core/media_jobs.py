import json


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
	db.execute(
		"""
		UPDATE media_jobs
		SET status = 'canceled',
			processed = 1,
			success = 0,
			processed_at = CURRENT_TIMESTAMP,
			locked_by = NULL,
			locked_until = NULL,
			last_error = ?
		WHERE provider = 'plex'
		  AND vodum_user_id = ?
		  AND server_id = ?
		  AND action IN ('grant', 'revoke', 'sync')
		  AND (
				status IN ('queued', 'running')
			 OR processed = 0
		  )
		""",
		(cancel_reason, vodum_user_id, server_id),
	)

	db.execute(
		"""
		DELETE FROM media_jobs
		WHERE dedupe_key = ?
		  AND processed = 1
		""",
		(dedupe_key,),
	)

	cur = db.execute(
		"""
		INSERT OR IGNORE INTO media_jobs(
			provider, action,
			vodum_user_id, server_id, library_id,
			payload_json,
			status, processed, success, attempts,
			dedupe_key
		)
		VALUES(
			'plex', ?, ?, ?, ?,
			?,
			'queued', 0, 0, 0,
			?
		)
		""",
		(
			action,
			vodum_user_id,
			server_id,
			library_id,
			json.dumps(payload or {}, ensure_ascii=False),
			dedupe_key,
		),
	)

	return getattr(cur, "rowcount", 0) > 0

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
	db.execute(
		"""
		UPDATE media_jobs
		SET status = 'canceled',
			processed = 1,
			success = 0,
			processed_at = CURRENT_TIMESTAMP,
			locked_by = NULL,
			locked_until = NULL,
			last_error = ?
		WHERE provider = 'jellyfin'
		  AND vodum_user_id = ?
		  AND server_id = ?
		  AND action IN ('grant', 'revoke', 'sync')
		  AND (
				status IN ('queued', 'running')
			 OR processed = 0
		  )
		""",
		(cancel_reason, vodum_user_id, server_id),
	)

	db.execute(
		"""
		DELETE FROM media_jobs
		WHERE dedupe_key = ?
		  AND processed = 1
		""",
		(dedupe_key,),
	)

	cur = db.execute(
		"""
		INSERT OR IGNORE INTO media_jobs(
			provider, action,
			vodum_user_id, server_id, library_id,
			payload_json,
			status, processed, success, attempts,
			dedupe_key
		)
		VALUES(
			'jellyfin', ?, ?, ?, ?,
			?,
			'queued', 0, 0, 0,
			?
		)
		""",
		(
			action,
			vodum_user_id,
			server_id,
			library_id,
			json.dumps(payload or {}, ensure_ascii=False),
			dedupe_key,
		),
	)

	return getattr(cur, "rowcount", 0) > 0