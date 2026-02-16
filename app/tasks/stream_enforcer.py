import json
import time
import ipaddress
from typing import Dict, List, Optional, Tuple

from core.providers.registry import get_provider
from logging_utils import get_logger

logger = get_logger("stream_enforcer")

# DBManager injected by tasks_engine (do not instantiate DBManager in task modules)
_db = None
_USER_STREAM_OVERRIDES: Dict[int, int] = {}

def _set_db(db):
    global _db
    _db = db


LIVE_WINDOW_SECONDS = 120     # live si last_seen < 120s
RECHECK_DELAY_SECONDS = 30    # recheck après warn
JELLYFIN_KILL_MESSAGE_SPAM_COUNT = 5   # 5 messages
JELLYFIN_KILL_MESSAGE_SPAM_SLEEP = 1.0 # 1 seconde entre chaque
JELLYFIN_KILL_MESSAGE_TIMEOUT_MS = 50000  # durée d'affichage de chaque toast
JELLYFIN_PRE_KILL_DURATION_SECONDS = 60     # 1 minute avant coupure
JELLYFIN_PRE_KILL_INTERVAL_SECONDS = 10     # un message toutes les 10 secondes




# -------------------------
# Utils
# -------------------------

def _loads_json(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}

def _jellyfin_session_id_from_target(target: dict, fallback_session_key: str) -> str:
    """
    Extract real Jellyfin Session Id from raw_json (Session object).
    Fallback to current session_key.
    """
    try:
        raw = _loads_json(target.get("raw_json"))
        sid = raw.get("Id")
        if sid:
            return str(sid)
    except Exception:
        pass
    return str(fallback_session_key)


def _now_sql_window() -> str:
    return f"-{int(LIVE_WINDOW_SECONDS)} seconds"

def _actor_key(vodum_user_id: Optional[int], external_user_id: str) -> str:
    if vodum_user_id is not None:
        return f"vodum:{int(vodum_user_id)}"
    external_user_id = (external_user_id or "").strip()
    return f"ext:{external_user_id}" if external_user_id else "ext:unknown"

def _session_started_ts(row: dict) -> str:
    return row.get("started_at") or row.get("last_seen_at") or ""

def _pick_kill_target(sessions: List[dict], selector: str) -> Optional[dict]:
    if not sessions:
        return None

    selector = (selector or "kill_newest").strip()

    if selector == "kill_newest":
        return sorted(sessions, key=_session_started_ts, reverse=True)[0]

    if selector == "kill_oldest":
        return sorted(sessions, key=_session_started_ts)[0]

    if selector == "kill_transcoding_first":
        trans = [s for s in sessions if int(s.get("is_transcode") or 0) == 1]
        if trans:
            return sorted(trans, key=_session_started_ts, reverse=True)[0]
        return sorted(sessions, key=_session_started_ts, reverse=True)[0]

    return sorted(sessions, key=_session_started_ts, reverse=True)[0]

def _is_global_policy(policy: dict) -> bool:
    # Global = scope global + pas de server_id forcé
    return (policy.get("scope_type") == "global") and (not policy.get("server_id"))


def _normalize_user_key(sess: dict) -> Tuple[Optional[int], str]:
    vodum_user_id = sess.get("vodum_user_id")
    ext = sess.get("external_user_id") or ""
    return (vodum_user_id, str(ext))

def _is_local_ip(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip or ip.lower() == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
        # RFC1918 + loopback + link-local (IPv4/IPv6)
        return bool(addr.is_private or addr.is_loopback or addr.is_link_local)
    except Exception:
        return False


def _load_user_stream_overrides() -> Dict[int, int]:
    """Return {vodum_user_id: max_streams_override} where override is not NULL."""
    out: Dict[int, int] = {}
    try:
        rows = _db.query(
            "SELECT id, max_streams_override FROM vodum_users WHERE max_streams_override IS NOT NULL"
        )
        for r in rows:
            try:
                out[int(r["id"])] = int(r["max_streams_override"])
            except Exception:
                continue
    except Exception:
        return {}
    return out

def _is_vip_override(vodum_user_id: Optional[int]) -> bool:
    """
    VIP override = user has max_streams_override set and > 0
    (0 is allowed but means 'block' and should NOT bypass other policies)
    """
    if vodum_user_id is None:
        return False
    try:
        return int(_USER_STREAM_OVERRIDES.get(int(vodum_user_id), 0)) > 0
    except Exception:
        return False



# -------------------------
# Policy evaluation
# -------------------------

def _load_enabled_policies() -> List[dict]:
    rows = _db.query("""
        SELECT *
        FROM stream_policies
        WHERE is_enabled=1
        ORDER BY priority ASC, id ASC
    """)
    return [dict(r) for r in rows]


def _load_live_sessions() -> List[dict]:
    rows = _db.query(f"""
        SELECT
          ms.server_id,
          s.type AS provider,
          ms.session_key,
          ms.media_user_id,
          ms.external_user_id,
          mu.vodum_user_id,
          ms.is_transcode,
          ms.bitrate,
          ms.device,
          ms.client_product,
          ms.ip,
          ms.started_at,
          ms.last_seen_at,
          ms.raw_json
        FROM media_sessions ms
        JOIN servers s ON s.id = ms.server_id
        LEFT JOIN media_users mu ON mu.id = ms.media_user_id
        WHERE s.type IN ('plex','jellyfin')
          AND datetime(ms.last_seen_at) >= datetime('now', ?)
        ORDER BY ms.server_id
    """, (_now_sql_window(),))
    return [dict(r) for r in rows]


def _policy_applies(policy: dict, sess: dict) -> bool:
    # provider filter
    p_provider = policy.get("provider")
    if p_provider and p_provider != sess.get("provider"):
        return False

    # server_id filter (optionnel)
    p_server_id = policy.get("server_id")
    if p_server_id and int(p_server_id) != int(sess.get("server_id")):
        return False

    # scope
    scope_type = policy.get("scope_type")
    scope_id = policy.get("scope_id")

    if scope_type == "global":
        return True

    if scope_type == "server":
        return scope_id is not None and int(scope_id) == int(sess.get("server_id"))

    if scope_type == "user":
        vuid = sess.get("vodum_user_id")

        # LOG IMPORTANT : si vodum_user_id est NULL, une policy scope=user ne peut jamais matcher
        if vuid is None:
            logger.debug(
                "[stream_enforcer] policy scope=user skipped (vodum_user_id is NULL) "
                f"scope_id={scope_id} media_user_id={sess.get('media_user_id')} external_user_id={sess.get('external_user_id')} "
                f"server_id={sess.get('server_id')} provider={sess.get('provider')}"
            )
            return False

        return (scope_id is not None) and (int(scope_id) == int(vuid))


    return False


def _parse_media_height(provider: str, raw_json: str) -> Optional[int]:
    data = _loads_json(raw_json)

    if provider == "plex":
        medias = data.get("Media") or []
        if isinstance(medias, list):
            for m in medias:
                if not isinstance(m, dict):
                    continue
                h = m.get("height")
                if isinstance(h, str) and h.isdigit():
                    return int(h)
                if isinstance(h, int):
                    return h
                vr = (m.get("videoResolution") or "").lower()
                if vr in ("4k", "uhd"):
                    return 2160

        parts = data.get("Part") or []
        if isinstance(parts, list):
            for p in parts:
                if not isinstance(p, dict):
                    continue
                h = p.get("height")
                if isinstance(h, str) and h.isdigit():
                    return int(h)
                if isinstance(h, int):
                    return h

        return None

    if provider == "jellyfin":
        npi = data.get("NowPlayingItem") or {}
        if isinstance(npi, dict):
            h = npi.get("Height")
            if isinstance(h, int):
                return h
            if isinstance(h, str) and h.isdigit():
                return int(h)

            streams = npi.get("MediaStreams") or []
            if isinstance(streams, list):
                for st in streams:
                    if not isinstance(st, dict):
                        continue
                    if st.get("Type") == "Video":
                        h2 = st.get("Height")
                        if isinstance(h2, int):
                            return h2
                        if isinstance(h2, str) and h2.isdigit():
                            return int(h2)

        return None

    return None


def _evaluate_policy(policy: dict, sessions: List[dict]) -> List[dict]:
    rule_type = policy.get("rule_type")
    rule = _loads_json(policy.get("rule_value_json"))

    selector = rule.get("selector", "kill_newest")
    warn_title = rule.get("warn_title", "Stream limit")
    warn_text = rule.get(
        "warn_text",
        "You have reached your streaming limit. The most recent stream will be stopped if it continues."
    )

    violations: List[dict] = []

    scoped = [s for s in sessions if _policy_applies(policy, s)]
    
    # Visibilité : combien de sessions sont réellement dans le scope de cette policy
    try:
        logger.debug(
            "[stream_enforcer] policy_scope_check "
            f"id={policy.get('id')} priority={policy.get('priority')} rule={policy.get('rule_type')} "
            f"scope={policy.get('scope_type')}:{policy.get('scope_id')} provider={policy.get('provider') or '*'} "
            f"server_id={policy.get('server_id') or '*'} scoped_sessions={len(scoped)}/{len(sessions)}"
        )
    except Exception:
        pass


    # Helper: regrouper par serveur (évite de kill avec le mauvais token)
    def by_server(items: List[dict]) -> Dict[int, List[dict]]:
        out: Dict[int, List[dict]] = {}
        for x in items:
            out.setdefault(int(x["server_id"]), []).append(x)
        return out

    if rule_type == "max_streams_per_user":
        max_streams = int(rule.get("max", 1))
        allow_local_ip = bool(rule.get("allow_local_ip", False))

        # Group by user (global) OR by (server+user) if policy is server-scoped
        by_key: Dict[Tuple[Optional[int], str], List[dict]] = {}

        if _is_global_policy(policy):
            # ✅ COMPTE SUR TOUS LES SERVEURS
            for s in scoped:
                ukey = _normalize_user_key(s)
                by_key.setdefault(ukey, []).append(s)
        else:
            # ✅ MODE "par serveur" (si scope=server, scope=user, ou server_id forcé)
            tmp: Dict[Tuple[int, Tuple[Optional[int], str]], List[dict]] = {}
            for s in scoped:
                sid = int(s["server_id"])
                ukey = _normalize_user_key(s)
                tmp.setdefault((sid, ukey), []).append(s)
            # on aplati (on gardera la logique kill per violation)
            for (_sid, ukey), lst in tmp.items():
                by_key.setdefault(ukey, []).extend(lst)

        for user_key, user_sessions in by_key.items():
            # Per-user override (vodum_users.max_streams_override) supersedes policy max.
            vodum_user_id = user_key[0]
            eff_max = max_streams
            if vodum_user_id is not None:
                try:
                    eff_max = int(_USER_STREAM_OVERRIDES.get(int(vodum_user_id), eff_max))
                except Exception:
                    pass

            # Optional LAN bypass: local IP sessions do not count.
            counted_sessions = user_sessions
            if allow_local_ip:
                counted_sessions = [s for s in user_sessions if not _is_local_ip((s.get('ip') or '').strip())]

            if len(counted_sessions) <= eff_max:
                continue

            # ✅ On choisit la session à tuer globalement (tous serveurs confondus)
            target = _pick_kill_target(counted_sessions, selector)
            if not target:
                continue

            # ✅ Violation mono-session + server_id DU TARGET (kill garanti sur le bon serveur)
            server_id = int(target["server_id"])
            provider = target["provider"]
            reason = f"max_streams_per_user: {len(counted_sessions)} > {eff_max}"

            violations.append({
                "policy": policy,
                "kind": "user_streams",
                "server_id": server_id,
                "provider": provider,
                "target_user": user_key,
                "sessions": [target],   # important: mono-session
                "reason": reason,
                "selector": selector,
                "warn_title": warn_title,
                "warn_text": warn_text,
            })


    


    elif rule_type == "max_ips_per_user":
        max_ips = int(rule.get("max", 1))
        ignore_unknown = bool(rule.get("ignore_unknown", True))
        allow_local_ip = bool(rule.get("allow_local_ip", False))

        # Group by user across ALL servers if global policy
        by_user: Dict[Tuple[Optional[int], str], List[dict]] = {}

        for s in scoped:
            ukey = _normalize_user_key(s)
            by_user.setdefault(ukey, []).append(s)

        for user_key, user_sessions in by_user.items():
            vodum_user_id = user_key[0]
            if _is_vip_override(vodum_user_id):
                # VIP: override must supersede stream limitation policies
                continue

            ips = set()
            for s in user_sessions:
                ip = (s.get("ip") or "").strip() or "unknown"
                if ip == "unknown" and ignore_unknown:
                    continue
                if allow_local_ip and _is_local_ip(ip):
                    continue
                ips.add(ip)

            if len(ips) <= max_ips:
                continue

            # ✅ On tue une session du user (selector), sur le serveur de la session ciblée
            candidates = user_sessions
            if allow_local_ip:
                candidates = [s for s in user_sessions if not _is_local_ip((s.get('ip') or '').strip())]
                if not candidates:
                    candidates = user_sessions

            target = _pick_kill_target(candidates, selector)
            if not target:
                continue

            server_id = int(target["server_id"])
            provider = target["provider"]
            reason = f"max_ips_per_user: {len(ips)} > {max_ips}"

            violations.append({
                "policy": policy,
                "kind": "user_ips",
                "server_id": server_id,
                "provider": provider,
                "target_user": user_key,
                "sessions": [target],   # important: mono-session
                "reason": reason,
                "selector": selector,
                "warn_title": warn_title,
                "warn_text": warn_text,
            })


    


    elif rule_type == "max_streams_per_ip":
        max_streams = int(rule.get("max", 2))
        ignore_unknown = bool(rule.get("ignore_unknown", True))
        per_server = bool(rule.get("per_server", True))
        allow_local_ip = bool(rule.get("allow_local_ip", False))

        by_key: Dict[str, List[dict]] = {}

        for s in scoped:
            # VIP users should not be limited by per-IP stream policies
            if _is_vip_override(s.get("vodum_user_id")):
                continue
        
            ip = (s.get("ip") or "").strip() or "unknown"

            if ip == "unknown" and ignore_unknown:
                continue

            if allow_local_ip and _is_local_ip(ip):
                continue

            key = f"{s['server_id']}|{ip}" if per_server else ip
            by_key.setdefault(key, []).append(s)

        for key, ip_sessions in by_key.items():
            if len(ip_sessions) > max_streams:
                server_id = int(ip_sessions[0]["server_id"])
                provider = ip_sessions[0]["provider"]

                ip_value = key.split("|", 1)[1] if ("|" in key) else key
                reason = f"max_streams_per_ip({ip_value}): {len(ip_sessions)} > {max_streams}"

                violations.append({
                    "policy": policy,
                    "kind": "ip_streams",
                    "server_id": server_id,
                    "provider": provider,
                    "target_user": (None, ip_value),  # ext:<ip>
                    "sessions": ip_sessions,
                    "reason": reason,
                    "selector": selector,
                    "warn_title": warn_title,
                    "warn_text": warn_text,
                })



    


    elif rule_type == "max_transcodes_global":
        # En pratique ton UI dit "max_transcodes_server"
        # => on applique PAR SERVEUR pour éviter kill cross-server
        max_trans = int(rule.get("max", 1))

        trans = [s for s in scoped if int(s.get("is_transcode") or 0) == 1]
        grouped = by_server(trans)

        for server_id, trans_sessions in grouped.items():
            if len(trans_sessions) > max_trans:
                provider = trans_sessions[0]["provider"]
                reason = f"max_transcodes_server: {len(trans_sessions)} > {max_trans}"
                violations.append({
                    "policy": policy,
                    "kind": "server_transcodes",
                    "server_id": int(server_id),
                    "provider": provider,
                    "target_user": (None, "server"),
                    "sessions": trans_sessions,
                    "reason": reason,
                    "selector": selector,
                    "warn_title": warn_title,
                    "warn_text": warn_text,
                })

    elif rule_type == "ban_4k_transcode":
        viol = []
        for s in scoped:
            if int(s.get("is_transcode") or 0) != 1:
                continue
            h = _parse_media_height(s.get("provider"), s.get("raw_json"))
            if h and h >= 2160:
                viol.append(s)

        grouped = by_server(viol)
        for server_id, ss in grouped.items():
            provider = ss[0]["provider"]
            reason = "ban_4k_transcode: 4K transcode detected"
            violations.append({
                "policy": policy,
                "kind": "4k_transcode",
                "server_id": int(server_id),
                "provider": provider,
                "target_user": (None, "4k"),
                "sessions": ss,
                "reason": reason,
                "selector": selector,
                "warn_title": warn_title,
                "warn_text": warn_text,
            })

    elif rule_type == "max_bitrate_kbps":
        max_kbps = int(rule.get("max_kbps", 0))
        viol = []
        for s in scoped:
            try:
                b = int(s.get("bitrate") or 0)
            except Exception:
                b = 0
            if max_kbps > 0 and b > max_kbps:
                viol.append(s)

        grouped = by_server(viol)
        for server_id, ss in grouped.items():
            provider = ss[0]["provider"]
            reason = f"max_bitrate_kbps: {len(ss)} session(s) above {max_kbps} kbps"
            violations.append({
                "policy": policy,
                "kind": "bitrate",
                "server_id": int(server_id),
                "provider": provider,
                "target_user": (None, "bitrate"),
                "sessions": ss,
                "reason": reason,
                "selector": selector,
                "warn_title": warn_title,
                "warn_text": warn_text,
            })

    elif rule_type == "device_allowlist":
        # ✅ FIX: compat avec l’ancien format + ton format actuel
        allowed_list = rule.get("allowed")
        if isinstance(allowed_list, list):
            allowed = [str(x).strip().lower() for x in allowed_list if str(x).strip()]
        else:
            # fallback si ancienne policy stockée en string
            allowed_raw = rule.get("allowed_devices") or rule.get("allowed") or ""
            allowed = [x.strip().lower() for x in str(allowed_raw).split(",") if x.strip()]

        if not allowed:
            return []

        viol = []
        for s in scoped:
            dev = (s.get("device") or s.get("client_product") or "").strip().lower()
            if dev and dev not in allowed:
                viol.append(s)

        grouped = by_server(viol)
        for server_id, ss in grouped.items():
            provider = ss[0]["provider"]
            reason = "device_allowlist: device not allowed"
            violations.append({
                "policy": policy,
                "kind": "device",
                "server_id": int(server_id),
                "provider": provider,
                "target_user": (None, "device"),
                "sessions": ss,
                "reason": reason,
                "selector": selector,
                "warn_title": warn_title,
                "warn_text": warn_text,
            })

    return violations



# -------------------------
# Enforcement state + actions
# -------------------------

def _log_enforcement(policy_id: int, server_id: int, provider: str, session_key: str,
                     vodum_user_id: Optional[int], external_user_id: str,
                     action: str, reason: str):
    _db.execute("""
        INSERT INTO stream_enforcements(policy_id, server_id, provider, session_key, vodum_user_id, external_user_id, action, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (policy_id, server_id, provider, session_key, vodum_user_id, external_user_id, action, reason))


def _upsert_state(policy_id: int, server_id: int,
                  vodum_user_id: Optional[int], external_user_id: str,
                  warned: bool = False, killed: bool = False, reason: str = ""):
    ak = _actor_key(vodum_user_id, external_user_id)

    row = _db.query_one("""
        SELECT id
        FROM stream_enforcement_state
        WHERE policy_id=? AND server_id=? AND actor_key=?
        LIMIT 1
    """, (policy_id, server_id, ak))

    if row:
        sets = ["last_seen_at=CURRENT_TIMESTAMP", "last_reason=?"]
        params = [reason]
        if warned:
            sets.append("warned_at=CURRENT_TIMESTAMP")
        if killed:
            sets.append("killed_at=CURRENT_TIMESTAMP")

        _db.execute(f"""
            UPDATE stream_enforcement_state
            SET {", ".join(sets)}
            WHERE id=?
        """, (*params, row["id"]))
    else:
        _db.execute("""
            INSERT INTO stream_enforcement_state(
                policy_id, server_id, actor_key,
                vodum_user_id, external_user_id,
                warned_at, killed_at, last_reason
            )
            VALUES (
                ?, ?, ?,
                ?, ?,
                CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                ?
            )
        """, (policy_id, server_id, ak, vodum_user_id, external_user_id, 1 if warned else 0, 1 if killed else 0, reason))


def _already_warned_recently(policy_id: int, server_id: int,
                             vodum_user_id: Optional[int], external_user_id: str,
                             minutes: int = 5) -> bool:
    ak = _actor_key(vodum_user_id, external_user_id)

    row = _db.query_one("""
        SELECT 1
        FROM stream_enforcement_state
        WHERE policy_id=? AND server_id=? AND actor_key=?
          AND warned_at IS NOT NULL
          AND datetime(warned_at) >= datetime('now', ?)
        LIMIT 1
    """, (policy_id, server_id, ak, f"-{int(minutes)} minutes"))
    return bool(row)


def _kill_session(server_row: dict, session_key: str, reason: str) -> bool:
    provider = get_provider(server_row)
    return provider.terminate_session(session_key, reason=reason)


def _warn_session(server_row, session_key, title, text, timeout_ms: int = 8000):
    provider = get_provider(server_row)
    try:
        return provider.send_session_message(session_key, title, text, timeout_ms=timeout_ms)
    except TypeError:
        # fallback if provider signature is older
        return provider.send_session_message(session_key, title, text)




def _load_server(server_id: int) -> Optional[dict]:
    r = _db.query_one("""
        SELECT id, type, url, local_url, public_url, token, server_identifier, settings_json
        FROM servers
        WHERE id=?
        LIMIT 1
    """, (server_id,))
    return dict(r) if r else None


def _recheck_violation(policy: dict, violation: dict) -> bool:
    time.sleep(RECHECK_DELAY_SECONDS)

    sessions = _load_live_sessions()
    v2 = _evaluate_policy(policy, sessions)

    t_user = violation["target_user"]
    for x in v2:
        if x["kind"] == violation["kind"] and x["server_id"] == violation["server_id"] and x["target_user"] == t_user:
            return True
    return False


# -------------------------
# Task entrypoint
# -------------------------

def run(task_id: int, db):
    """
    ✅ MUST match tasks_engine signature: run(task_id, db)
    ✅ DO NOT instantiate DBManager here
    """
    _set_db(db)

    logger.info(f"[TASK {task_id}] stream_enforcer: start")

    policies = _load_enabled_policies()
    global _USER_STREAM_OVERRIDES
    _USER_STREAM_OVERRIDES = _load_user_stream_overrides()
    logger.info(f"[TASK {task_id}] stream_enforcer: loaded_policies={len(policies)}")
    if not policies:
        logger.info(f"[TASK {task_id}] stream_enforcer: no enabled policies")
        return

    live_sessions = _load_live_sessions()
    logger.info(f"[TASK {task_id}] stream_enforcer: live_sessions={len(live_sessions)}")
    if not live_sessions:
        logger.info(f"[TASK {task_id}] stream_enforcer: no live sessions")
        return

    null_map = sum(1 for s in live_sessions if s.get("vodum_user_id") is None)
    if null_map:
        logger.warning(
            f"[TASK {task_id}] stream_enforcer: sessions_with_vodum_user_id_NULL={null_map}/{len(live_sessions)} "
            "(=> scope=user policies may never match if your users are not mapped)"
        )


    violations: List[dict] = []
    for p in policies:
        violations.extend(_evaluate_policy(p, live_sessions))

    if not violations:
        logger.info(f"[TASK {task_id}] stream_enforcer: no violations")
        return

    for v in violations:
        policy = v["policy"]
        policy_id = int(policy["id"])
        server_id = int(v["server_id"])
        provider_type = v["provider"]

        user_vodum_id, user_ext = v["target_user"]
        user_ext = str(user_ext or "")

        server_row = _load_server(server_id)
        if not server_row:
            logger.warning(f"[TASK {task_id}] stream_enforcer: server {server_id} missing")
            continue

        sessions = v["sessions"]
        selector = v.get("selector") or "kill_newest"
        target = _pick_kill_target(sessions, selector)
        if not target:
            continue

        session_key = str(target["session_key"])
        jf_message_key = session_key
        if provider_type == "jellyfin":
            jf_message_key = _jellyfin_session_id_from_target(target, session_key)

        reason = v.get("reason") or "policy violation"

        # Message utilisateur (celui que tu veux voir côté client)
        warn_title = v.get("warn_title", "Stream limit")
        warn_text  = v.get("warn_text", "Limit reached.")

        # Pour Plex, le "reason" est affiché au moment du terminate
        # => on veut un texte user-friendly (warn_text), pas un reason technique.
        kill_reason_for_client = warn_text or reason


        # 1) WARN (une fois) + recheck 30s
        if not _already_warned_recently(policy_id, server_id, user_vodum_id, user_ext, minutes=5):
            warned_ok = False
            if provider_type == "jellyfin":
                warned_ok = _warn_session(
                    server_row,
                    jf_message_key,
                    v.get("warn_title", "Stream limit"),
                    v.get("warn_text", "Limit reached.")
                )

            _log_enforcement(policy_id, server_id, provider_type, session_key, user_vodum_id, user_ext, "warn", reason)
            _upsert_state(policy_id, server_id, user_vodum_id, user_ext, warned=True, killed=False, reason=reason)

            logger.warning(
                f"[TASK {task_id}] [WARN] policy={policy_id} server={server_id} provider={provider_type} "
                f"session={session_key} reason={reason} warned_ok={warned_ok} "
                f"target_vodum_user_id={user_vodum_id} target_external_user_id={user_ext} "
                f"ip={target.get('ip')} device={target.get('device') or target.get('client_product')} "
                f"is_transcode={target.get('is_transcode')} bitrate={target.get('bitrate')}"
            )


        # 2) recheck 30s -> si toujours violation -> KILL
        still_bad = _recheck_violation(policy, v)
        if not still_bad:
            logger.info(f"[TASK {task_id}] stream_enforcer: violation cleared after recheck (policy={policy_id} server={server_id})")
            continue

        try:
            # Jellyfin : affichage "pénible mais lisible" avant coupure
            if provider_type == "jellyfin":
                try:
                    start = time.time()
                    while True:
                        elapsed = time.time() - start
                        if elapsed >= JELLYFIN_PRE_KILL_DURATION_SECONDS:
                            break

                        # Message visible 5s
                        _warn_session(
                            server_row,
                            jf_message_key,
                            warn_title,
                            warn_text,
                            timeout_ms=JELLYFIN_KILL_MESSAGE_TIMEOUT_MS
                        )

                        # Attendre jusqu'au prochain tick (toutes les 10s)
                        remaining = JELLYFIN_PRE_KILL_DURATION_SECONDS - elapsed
                        sleep_for = min(float(JELLYFIN_PRE_KILL_INTERVAL_SECONDS), float(remaining))
                        if sleep_for > 0:
                            time.sleep(sleep_for)
                        else:
                            break

                except Exception as e:
                    logger.warning(
                        f"[TASK {task_id}] jellyfin pre-kill message loop failed "
                        f"session={jf_message_key} server={server_id}: {e}",
                        exc_info=True
                    )




            # Kill stream (Plex affichera kill_reason_for_client ; Jellyfin ignore reason, mais on a déjà envoyé un message)
            ok = _kill_session(server_row, session_key, reason=kill_reason_for_client)

            _log_enforcement(policy_id, server_id, provider_type, session_key, user_vodum_id, user_ext, "kill", reason)
            _upsert_state(policy_id, server_id, user_vodum_id, user_ext, warned=False, killed=True, reason=reason)

            logger.warning(
                f"[TASK {task_id}] [KILL] policy={policy_id} server={server_id} provider={provider_type} "
                f"session={session_key} ok={ok} reason={reason} "
                f"target_vodum_user_id={user_vodum_id} target_external_user_id={user_ext} "
                f"ip={target.get('ip')} device={target.get('device') or target.get('client_product')} "
                f"is_transcode={target.get('is_transcode')} bitrate={target.get('bitrate')}"
            )

        except Exception as e:
            logger.error(f"[TASK {task_id}] stream_enforcer: kill failed server={server_id} session={session_key}: {e}", exc_info=True)


    logger.info(f"[TASK {task_id}] stream_enforcer: done")
