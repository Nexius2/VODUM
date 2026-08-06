MIGRATION_CAMPAIGN_DETAIL_COLUMNS = """
          mc.id,
          mc.name,
          mc.source_server_id,
          mc.destination_server_id,
          mc.migration_type,
          mc.migration_mode,
          mc.intent,
          mc.status,
          mc.options_json,
          mc.library_mapping_json,
          mc.analysis_json,
          mc.scheduled_at,
          mc.batch_size,
          mc.created_at,
          mc.updated_at,
          mc.started_at,
          mc.completed_at
"""


def get_campaign(db, campaign_id: int, *, with_server_details: bool = False):
    if with_server_details:
        return db.query_one(
            f"""
            SELECT
{MIGRATION_CAMPAIGN_DETAIL_COLUMNS},
              source.name AS source_name,
              source.type AS source_type,
              destination.name AS destination_name,
              destination.type AS destination_type
            FROM migration_campaigns mc
            JOIN servers source ON source.id = mc.source_server_id
            JOIN servers destination ON destination.id = mc.destination_server_id
            WHERE mc.id = ?
            """,
            (campaign_id,),
        )
    return db.query_one(
        f"""
        SELECT
{MIGRATION_CAMPAIGN_DETAIL_COLUMNS}
        FROM migration_campaigns mc
        WHERE mc.id = ?
        """,
        (campaign_id,),
    )


def load_report_users(db, campaign_id: int):
    return db.query(
        """
        SELECT id,vodum_user_id,status,eligibility,attempts,last_error,
               result_json,source_snapshot_json
        FROM migration_users
        WHERE campaign_id=?
        ORDER BY id
        """,
        (campaign_id,),
    )
