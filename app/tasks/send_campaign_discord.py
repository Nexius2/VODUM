#!/usr/bin/env python3

from tasks_engine import task_logs
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail
from discord_utils import is_discord_ready, enrich_discord_settings, send_discord_dm, DiscordSendError


log = get_logger("send_campaign_discord")


def run(task_id: int, db):
    task_logs(task_id, "info", "Task send_campaign_discord started")
    log.info("=== SEND CAMPAIGN DISCORD : START ===")

    try:
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        settings = enrich_discord_settings(db, settings)

        if not is_discord_ready(settings):
            msg = "Discord disabled or not configured → no action."
            task_logs(task_id, "info", msg)
            log.warning(msg)
            return

        campaigns = db.query(
            """
            SELECT * FROM discord_campaigns
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 20
            """
        )

        if not campaigns:
            task_logs(task_id, "info", "No pending discord campaigns")
            return

        total_sent = 0

        for c in campaigns:
            cid = c["id"]
            title = c["title"]
            body = c["body"]
            server_id = c["server_id"]

            try:
                # Select users
                if server_id:
                    users = db.query(
                        """
                        SELECT DISTINCT u.id, u.username, u.discord_user_id
                        FROM vodum_users u
                        JOIN media_users mu ON mu.vodum_user_id = u.id
                        WHERE mu.server_id = ?
                          AND COALESCE(u.discord_user_id,'') <> ''
                        """,
                        (server_id,),
                    )
                else:
                    users = db.query(
                        """
                        SELECT id, username, discord_user_id
                        FROM vodum_users
                        WHERE COALESCE(discord_user_id,'') <> ''
                        """
                    )

                sent = 0
                for u in users:
                    discord_user_id = (u["discord_user_id"] or "").strip()
                    if not discord_user_id:
                        continue

                    ctx = build_user_context({"username": u["username"]})
                    content_title = render_mail(title or "", ctx).strip()
                    content_body = render_mail(body or "", ctx).strip()
                    content = f"**{content_title}**\n{content_body}" if content_title else content_body

                    try:
                        send_discord_dm(settings.get('discord_bot_token_effective') or '', discord_user_id, content)
                        sent += 1
                    except DiscordSendError as e:
                        log.error(f"[DISCORD] campaign send failed user={u['id']}: {e}")

                db.execute(
                    """
                    UPDATE discord_campaigns
                    SET status='sent', sent_at=CURRENT_TIMESTAMP, error=NULL
                    WHERE id=?
                    """,
                    (cid,),
                )

                total_sent += sent

            except Exception as e:
                db.execute(
                    """
                    UPDATE discord_campaigns
                    SET status='failed', error=?
                    WHERE id=?
                    """,
                    (str(e), cid),
                )
                log.error(f"[DISCORD] campaign failed id={cid}: {e}", exc_info=True)

        msg = f"send_campaign_discord finished — {total_sent} message(s) sent"
        task_logs(task_id, "success" if total_sent else "info", msg)
        log.info(msg)

    except Exception as e:
        log.error("Error in send_campaign_discord", exc_info=True)
        task_logs(task_id, "error", f"Error send_campaign_discord : {e}")
        raise
    finally:
        log.info("=== SEND CAMPAIGN DISCORD : END ===")
