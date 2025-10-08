import sqlite3
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import time
from datetime import datetime
from mailer import send_email
from logger import logger
from config import DATABASE_PATH




def mark_campaign_status(cur, campaign_id, new_status):
    if new_status == "sending":
        cur.execute("""
            UPDATE mail_campaigns
            SET status='sending',
                started_at = COALESCE(started_at, datetime('now'))
            WHERE id=?;
        """, (campaign_id,))
    elif new_status in ("finished", "cancelled"):
        cur.execute("""
            UPDATE mail_campaigns
            SET status=?, finished_at=datetime('now')
            WHERE id=?;
        """, (new_status, campaign_id))
    else:
        cur.execute("""
            UPDATE mail_campaigns
            SET status=?
            WHERE id=?;
        """, (new_status, campaign_id))

def cleanup_old_campaigns(cur, conn):
    """
    Nettoie les campagnes bloquées ou anciennes :
    - Marque comme 'finished' celles restées en 'sending' plus de 6h ou sans started_at
    - Supprime les campagnes 'finished' vieilles de plus de 30 jours
    """
    try:
        # 🧹 Campagnes bloquées
        cur.execute("""
            UPDATE mail_campaigns
            SET status='finished', finished_at=datetime('now')
            WHERE status='sending'
              AND (started_at IS NULL OR started_at < datetime('now','-6 hours'));
        """)
        rows_blocked = cur.rowcount
        if rows_blocked > 0:
            logger.info(f"🧹 {rows_blocked} campagne(s) bloquée(s) marquée(s) comme terminée (6h+).")

        # 🗑️ Campagnes trop anciennes
        cur.execute("""
            DELETE FROM mail_campaigns
            WHERE status='finished'
              AND finished_at < datetime('now','-30 days');
        """)
        rows_old = cur.rowcount
        if rows_old > 0:
            logger.info(f"🗑️ {rows_old} campagne(s) terminée(s) supprimée(s) (30j+).")

        conn.commit()

    except Exception as e:
        logger.error(f"❌ Erreur lors du nettoyage des campagnes : {e}")


def main():
    db_path = DATABASE_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 🧹 Nettoyage automatique avant traitement
    cleanup_old_campaigns(cur, conn)

    # Débloquer les campagnes bloquées depuis plus de 2h ou sans started_at
    cur.execute("""
        UPDATE mail_campaigns
        SET status='pending', started_at=NULL, finished_at=NULL
        WHERE status='sending' 
          AND (started_at IS NULL OR started_at < datetime('now','-2 hours'))
    """)
    rows = cur.rowcount
    if rows > 0:
        logger.info(f"🔁 {rows} campagne(s) réinitialisée(s) depuis 'sending' vers 'pending'")
    conn.commit()


    # Récupère la prochaine campagne à envoyer
    cur.execute(
        """
        SELECT id, subject, html_content, attachment_path
        FROM mail_campaigns
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT 1
        """
    )
    campaign = cur.fetchone()

    if not campaign:
        logger.info("⏳ Aucune campagne mail en attente.")
        conn.close()
        return

    campaign_id, subject, html_content, attachment_path = campaign

    mark_campaign_status(cur, campaign_id, "sending")
    conn.commit()
    logger.info(f"🚀 Début de l’envoi de la campagne ID={campaign_id}")

    # Récupère la file d’attente liée
    cur.execute(
        """
        SELECT id, user_id, email
        FROM mail_queue
        WHERE campaign_id = ? AND status = 'pending'
        """,
        (campaign_id,),
    )
    rows = cur.fetchall()

    sent_count = 0
    for row in rows:
        queue_id, user_id, to_email = row
        if not to_email:
            cur.execute(
                "UPDATE mail_queue SET status='error', error='Email vide' WHERE id=?",
                (queue_id,),
            )
            continue

        ok, err = send_email(
            to_email, subject or "(sans sujet)", html_content or "", attachment_path=attachment_path
        )

        if ok:
            cur.execute(
                "UPDATE mail_queue SET status='sent', sent_at=datetime('now') WHERE id=?",
                (queue_id,),
            )
            sent_count += 1
        else:
            cur.execute(
                "UPDATE mail_queue SET status='error', error=? WHERE id=?",
                (err, queue_id),
            )

        conn.commit()
        time.sleep(0.2)  # petit délai entre les mails

    mark_campaign_status(cur, campaign_id, "finished")
    conn.commit()
    conn.close()

    logger.info(f"✅ Campagne terminée ID={campaign_id} ({sent_count} mails envoyés)")


if __name__ == "__main__":
    main()
