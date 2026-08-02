import json
import time
from typing import Dict, List, Optional, Tuple

from core.policy_transition_grace import should_defer_stream_violation
from logging_utils import get_logger, is_debug_mode_enabled
from core.stream_policy_i18n import translate_policy
from core.stream_policy_utils import (
    loads_json as _loads_json,
    is_strict_expired_subscription_policy as _is_strict_expired_subscription_policy,
    jellyfin_session_id_from_target as _jellyfin_session_id_from_target,
    actor_key as _actor_key,
    session_started_ts as _session_started_ts,
    pick_kill_target as _pick_kill_target,
    is_global_policy as _is_global_policy,
    normalize_user_key as _normalize_user_key,
    is_local_ip as _is_local_ip,
    is_ip_literal as _is_ip_literal,
    best_account_username as _best_account_username,
    same_actor_reference as _same_actor_reference,
)
from core.stream_enforcer_boost import refresh_boost_state, maybe_boost_after_expired_kill
from core.stream_enforcement_snapshot import build_enforcement_snapshot as _build_enforcement_snapshot
from core.stream_media_metadata import parse_media_height as _parse_media_height
from core.stream_enforcer_repository import (
    load_user_stream_overrides,
    load_enabled_policies,
    load_live_sessions,
    load_server,
)
from core.stream_enforcement_store import (
    log_enforcement,
    upsert_state,
    already_warned_recently,
)
from core.stream_notification_delivery import (
    media_title_from_session as _media_title_from_session,
    policy_display_name as _policy_display_name,
    queue_stream_blocked_notification,
)
from core.stream_notification_context import build_notification_policy_context
from core.stream_household_dedupe import (
    RECENT_SESSION_CACHE as _RECENT_SESSION_CACHE,
    deduplicate_household_sessions as _deduplicate_household_sessions,
)
from core.stream_provider_actions import (
    kill_session as _kill_session,
    warn_session as _warn_session,
)
from core.stream_policy_scope import has_vip_override, policy_applies as _policy_applies
from core.stream_violation_recheck import select_rechecked_violation
from core.stream_session_diagnostics import log_sessions as _debug_log_sessions
from core.stream_enforcer_config import (
    LIVE_WINDOW_SECONDS, LIVE_STABLE_SECONDS, RECHECK_DELAY_SECONDS,
    JELLYFIN_KILL_MESSAGE_SPAM_COUNT, JELLYFIN_KILL_MESSAGE_SPAM_SLEEP,
    JELLYFIN_KILL_MESSAGE_TIMEOUT_MS, JELLYFIN_PRE_KILL_DURATION_SECONDS,
    JELLYFIN_PRE_KILL_INTERVAL_SECONDS, HOUSEHOLD_MEMORY_SECONDS,
    HOUSEHOLD_MEDIA_GRACE_SECONDS,
)
from core.stream_session_identity import (
    extract_machine_identifier as _extract_machine_identifier,
    household_match_score as _household_match_score,
    is_probable_same_household as _is_probable_same_household,
)


logger = get_logger("stream_enforcer")

# DBManager injected by tasks_engine (do not instantiate DBManager in task modules)
_db = None
_USER_STREAM_OVERRIDES: Dict[int, int] = {}

def _policy_t(key: str, **kwargs) -> str:
    return translate_policy(_db, key, **kwargs)

def _set_db(db):
    global _db
    _db = db



# Compatibility aliases: caches remain externally accessible while their
# implementation now lives outside the task module.
from core.stream_sync_dedupe import (
    STREAM_SYNC_GRACE_CACHE as _STREAM_SYNC_GRACE_CACHE,
    deduplicate_user_stream_sessions as _deduplicate_user_stream_sessions,
)
from core.stream_ip_transition_grace import (
    IP_GRACE_CACHE as _IP_GRACE_CACHE,
    should_grace_coherent_ip_switch as _should_grace_coherent_ip_switch,
)

# -------------------------
# Utils
# -------------------------

def _load_user_stream_overrides() -> Dict[int, int]:
    return load_user_stream_overrides(_db)

def _is_vip_override(vodum_user_id: Optional[int]) -> bool:
    return has_vip_override(vodum_user_id, _USER_STREAM_OVERRIDES)



# -------------------------
# Policy evaluation
# -------------------------

def _load_enabled_policies() -> List[dict]:
    return load_enabled_policies(_db)


def _load_live_sessions(stable_seconds: Optional[int] = None) -> List[dict]:
    if stable_seconds is None:
        stable_seconds = LIVE_STABLE_SECONDS
    return load_live_sessions(_db, LIVE_WINDOW_SECONDS, stable_seconds)


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

    # --------------------------------------------------
    # Fast pre-checks to avoid useless policy scans
    # --------------------------------------------------

    scope_type = policy.get("scope_type")
    scope_id = policy.get("scope_id")
    server_id = policy.get("server_id")
    provider = (policy.get("provider") or "").strip().lower()

    # Skip provider instantly
    if provider:
        has_provider_match = any(
            (s.get("provider") or "").strip().lower() == provider
            for s in sessions
        )

        if not has_provider_match:
            return violations

    # Skip server instantly
    if server_id:
        has_server_match = any(
            int(s.get("server_id", 0)) == int(server_id)
            for s in sessions
        )

        if not has_server_match:
            return violations

    # Skip user instantly
    if scope_type == "user" and scope_id:
        has_user_match = any(
            int(s.get("vodum_user_id") or 0) == int(scope_id)
            for s in sessions
        )

        if not has_user_match:
            return violations

    # Real scoped filtering only if needed
    scoped = [s for s in sessions if _policy_applies(policy, s)]

    # Nothing in scope
    if not scoped:
        return violations

    # Visibilité : combien de sessions sont réellement dans le scope de cette policy
    try:
        # Only log policies that actually match sessions
        if scoped:
            if is_debug_mode_enabled():
                logger.debug(
                    "[stream_enforcer] policy_scope_check "
                    f"id={policy.get('id')} "
                    f"rule={policy.get('rule_type')} "
                    f"scoped_sessions={len(scoped)}"
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

        # Group by user:
        # - If policy is explicitly global => count across all servers
        # - If policy forces a server context (server_id set OR scope_type='server') => count per server
        # - Otherwise (scope=user without server_id) => count across all servers (user-wide limit)
        per_server_counting = bool(policy.get("server_id")) or (policy.get("scope_type") == "server")

        by_key: Dict[Tuple[Optional[int], str, Optional[int]], List[dict]] = {}

        if _is_global_policy(policy) or not per_server_counting:
            # ✅ COMPTE SUR TOUS LES SERVEURS
            for s in scoped:
                vodum_user_id, ext = _normalize_user_key(s)
                by_key.setdefault((vodum_user_id, ext, None), []).append(s)
        else:
            # ✅ COMPTE PAR SERVEUR
            for s in scoped:
                sid = int(s["server_id"])
                vodum_user_id, ext = _normalize_user_key(s)
                by_key.setdefault((vodum_user_id, ext, sid), []).append(s)

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

            counted_sessions = _deduplicate_user_stream_sessions(policy, user_key, counted_sessions)

            defer_probable_switch = should_defer_stream_violation(
                policy_id=int(policy.get("id") or 0),
                user_key=user_key,
                sessions=counted_sessions,
                limit=eff_max,
                current_count=len(counted_sessions),
            )

            if len(counted_sessions) <= eff_max:
                continue

            if defer_probable_switch:
                logger.info(
                    "[max_streams_grace] probable device switch | policy=%s | user=%s | streams=%s | max=%s | grace=%ss",
                    policy.get("id"),
                    user_key,
                    len(counted_sessions),
                    eff_max,
                    HOUSEHOLD_MEDIA_GRACE_SECONDS,
                )
                continue

            # ✅ On choisit la session à tuer globalement (tous serveurs confondus)
            target = _pick_kill_target(counted_sessions, selector)
            if not target:
                continue

            # ✅ Violation mono-session + server_id DU TARGET (kill garanti sur le bon serveur)
            server_id = int(target["server_id"])
            provider = target["provider"]
            reason = f"max_streams_per_user: {len(counted_sessions)} > {eff_max}"

            target_user = _normalize_user_key(target)

            violations.append({
                "policy": policy,
                "kind": "ip_streams",
                "server_id": server_id,
                "provider": provider,
                "target_user": target_user,
                "sessions": [target],   # mono-session => kill toujours sur le bon serveur
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

            deduped_sessions = _deduplicate_household_sessions(user_sessions)

            if len(deduped_sessions) > 1:
                _debug_log_sessions(
                    str(user_key),
                    deduped_sessions,
                    "before_ip_count",
                )

            ips = set()

            for s in deduped_sessions:
                ip = (s.get("ip") or "").strip() or "unknown"

                if ip == "unknown" and ignore_unknown:
                    continue

                if allow_local_ip and _is_local_ip(ip):
                    continue

                ips.add(ip)

            if len(ips) <= max_ips:
                continue

            if _should_grace_coherent_ip_switch(policy, user_key, deduped_sessions, ips, max_ips):
                continue

            # ✅ On tue une session du user (selector), sur le serveur de la session ciblée
            candidates = deduped_sessions
            if allow_local_ip:
                candidates = [s for s in deduped_sessions if not _is_local_ip((s.get('ip') or '').strip())]

                if not candidates:
                    candidates = deduped_sessions

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
                "sessions": deduped_sessions,
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
            counted_ip_sessions = _deduplicate_household_sessions(ip_sessions)

            if len(counted_ip_sessions) <= max_streams:
                continue

            ip_value = key.split("|", 1)[1] if ("|" in key) else key
            reason = f"max_streams_per_ip({ip_value}): {len(counted_ip_sessions)} > {max_streams}"

            # IMPORTANT: choisir la cible ICI pour garantir server_id/provider cohérents
            target = _pick_kill_target(counted_ip_sessions, selector)
            if not target:
                continue

            server_id = int(target["server_id"])
            provider = target["provider"]



            violations.append({
                "policy": policy,
                "kind": "ip_streams",
                "server_id": server_id,
                "provider": provider,
                "target_user": _normalize_user_key(target),
                "sessions": counted_ip_sessions,
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
                     action: str, reason: str,
                     account_username: Optional[str] = None,
                     ips_json: Optional[str] = None,
                     details_json: Optional[str] = None):
    log_enforcement(
        _db, policy_id, server_id, provider, session_key, vodum_user_id,
        external_user_id, action, reason, account_username, ips_json, details_json,
    )


def _upsert_state(policy_id: int, server_id: int,
                  vodum_user_id: Optional[int], external_user_id: str,
                  warned: bool = False, killed: bool = False, reason: str = ""):
    upsert_state(
        _db, policy_id, server_id, vodum_user_id, external_user_id,
        warned=warned, killed=killed, reason=reason,
    )


def _already_warned_recently(policy_id: int, server_id: int,
                             vodum_user_id: Optional[int], external_user_id: str,
                             minutes: int = 5) -> bool:
    return already_warned_recently(
        _db, policy_id, server_id, vodum_user_id, external_user_id, minutes,
    )


def _notification_policy_context(policy: dict, target: dict, related_sessions: list[dict] | None) -> dict:
    return build_notification_policy_context(policy, target, related_sessions, _policy_t)




def _queue_stream_blocked_notification(
    *,
    task_id: int,
    policy: dict,
    server_row: dict,
    target: dict,
    reason: str,
    kill_reason_for_client: str,
    related_sessions: list[dict] | None = None,
) -> None:
    queue_stream_blocked_notification(
        _db,
        task_id=task_id,
        policy=policy,
        server_row=server_row,
        target=target,
        reason=reason,
        kill_reason_for_client=kill_reason_for_client,
        policy_context_builder=lambda: _notification_policy_context(policy, target, related_sessions),
    )




def _load_server(server_id: int) -> Optional[dict]:
    return load_server(_db, server_id)


def _recheck_violation(policy: dict, violation: dict) -> Optional[dict]:
    time.sleep(RECHECK_DELAY_SECONDS)

    sessions = _load_live_sessions()
    v2 = _evaluate_policy(policy, sessions)

    return select_rechecked_violation(violation, v2)

# -------------------------
# Task entrypoint
# -------------------------

def run(task_id: int, db):
    """
    ✅ MUST match tasks_engine signature: run(task_id, db)
    ✅ DO NOT instantiate DBManager here
    """
    _set_db(db)
    refresh_boost_state(_db, task_id)

    if is_debug_mode_enabled():
        logger.debug(f"[TASK {task_id}] stream_enforcer: start")

    policies = _load_enabled_policies()
    global _USER_STREAM_OVERRIDES
    _USER_STREAM_OVERRIDES = _load_user_stream_overrides()
    if is_debug_mode_enabled():
        logger.debug(f"[TASK {task_id}] stream_enforcer: loaded_policies={len(policies)}")
    if not policies:
        if is_debug_mode_enabled():
            logger.debug(f"[TASK {task_id}] stream_enforcer: no enabled policies")
        return

    live_sessions = _load_live_sessions()
    fresh_live_sessions = _load_live_sessions(stable_seconds=0)

    if is_debug_mode_enabled():
        logger.debug(f"[TASK {task_id}] stream_enforcer: live_sessions={len(live_sessions)}")
    if not live_sessions and not fresh_live_sessions:
        if is_debug_mode_enabled():
            logger.debug(f"[TASK {task_id}] stream_enforcer: no live sessions")
        return

    debug_sessions = fresh_live_sessions if fresh_live_sessions else live_sessions

    null_map = sum(1 for s in debug_sessions if s.get("vodum_user_id") is None)
    if null_map:
        logger.warning(
            f"[TASK {task_id}] stream_enforcer: sessions_with_vodum_user_id_NULL={null_map}/{len(debug_sessions)} "
            "(=> scope=user policies may never match if your users are not mapped)"
        )


    violations: List[dict] = []
    for p in policies:
        if _is_strict_expired_subscription_policy(p):
            violations.extend(_evaluate_policy(p, fresh_live_sessions))
        else:
            violations.extend(_evaluate_policy(p, live_sessions))

    if not violations:
        if is_debug_mode_enabled():
            logger.debug(f"[TASK {task_id}] stream_enforcer: no violations")
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

        warn_account_username, warn_ips_json, warn_details_json = _build_enforcement_snapshot(
            target=target,
            violation_sessions=sessions,
            live_sessions=live_sessions,
            policy=policy,
            reason=reason,
        )

        # Message utilisateur (celui que tu veux voir côté client)
        warn_title = v.get("warn_title", "Stream limit")
        warn_text  = v.get("warn_text", "Limit reached.")

        # Pour Plex, le "reason" est affiché au moment du terminate
        # => on veut un texte user-friendly (warn_text), pas un reason technique.
        kill_reason_for_client = warn_text or reason

        # Policy système "abonnement expiré" :
        # on coupe immédiatement, sans warning, sans délai de recheck.
        if _is_strict_expired_subscription_policy(policy):
            try:
                kill_live_sessions = _load_live_sessions(stable_seconds=0)

                kill_account_username, kill_ips_json, kill_details_json = _build_enforcement_snapshot(
                    target=target,
                    violation_sessions=sessions,
                    live_sessions=kill_live_sessions,
                    policy=policy,
                    reason=reason,
                )

                ok = _kill_session(server_row, session_key, reason=kill_reason_for_client)

                if ok:
                    _queue_stream_blocked_notification(
                        task_id=task_id,
                        policy=policy,
                        server_row=server_row,
                        target=target,
                        reason=reason,
                        kill_reason_for_client=kill_reason_for_client,
                        related_sessions=sessions,
                    )

                _log_enforcement(
                    policy_id, server_id, provider_type, session_key,
                    user_vodum_id, user_ext,
                    "kill" if ok else "kill_failed", reason,
                    account_username=kill_account_username,
                    ips_json=kill_ips_json,
                    details_json=kill_details_json,
                )

                _upsert_state(
                    policy_id, server_id,
                    user_vodum_id, user_ext,
                    warned=False,
                    killed=ok,
                    reason=reason,
                )

                logger.warning(
                    f"[TASK {task_id}] [KILL_IMMEDIATE] policy={policy_id} server={server_id} provider={provider_type} "
                    f"session={session_key} ok={ok} reason={reason} "
                    f"target_vodum_user_id={user_vodum_id} target_external_user_id={user_ext} "
                    f"ip={target.get('ip')} device={target.get('device') or target.get('client_product')} "
                    f"is_transcode={target.get('is_transcode')} bitrate={target.get('bitrate')}"
                )

                maybe_boost_after_expired_kill(
                    _db,
                    task_id,
                    policy_id,
                    user_vodum_id,
                )

            except Exception as e:
                logger.error(
                    f"[TASK {task_id}] stream_enforcer: immediate kill failed "
                    f"server={server_id} session={session_key}: {e}",
                    exc_info=True
                )

            continue

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

            _log_enforcement(
                policy_id, server_id, provider_type, session_key,
                user_vodum_id, user_ext,
                "warn", reason,
                account_username=warn_account_username,
                ips_json=warn_ips_json,
                details_json=warn_details_json,
            )
            _upsert_state(policy_id, server_id, user_vodum_id, user_ext, warned=True, killed=False, reason=reason)

            logger.warning(
                f"[TASK {task_id}] [WARN] policy={policy_id} server={server_id} provider={provider_type} "
                f"session={session_key} reason={reason} warned_ok={warned_ok} "
                f"target_vodum_user_id={user_vodum_id} target_external_user_id={user_ext} "
                f"ip={target.get('ip')} device={target.get('device') or target.get('client_product')} "
                f"is_transcode={target.get('is_transcode')} bitrate={target.get('bitrate')}"
            )


        # 2) recheck 30s -> si toujours violation -> KILL
        rechecked_violation = _recheck_violation(policy, v)
        if not rechecked_violation:
            if is_debug_mode_enabled():
                logger.debug(f"[TASK {task_id}] stream_enforcer: violation cleared after recheck (policy={policy_id} server={server_id})")
            continue

        # La session ciblée peut avoir changé pendant le délai d'avertissement.
        # Recalculer toute la cible depuis le relevé qui vient de confirmer la violation.
        v = rechecked_violation
        sessions = v["sessions"]
        selector = v.get("selector") or "kill_newest"
        target = _pick_kill_target(sessions, selector)
        if not target:
            continue

        server_id = int(v["server_id"])
        provider_type = v["provider"]
        server_row = _load_server(server_id)
        if not server_row:
            logger.warning(f"[TASK {task_id}] stream_enforcer: server {server_id} missing after recheck")
            continue

        session_key = str(target["session_key"])
        jf_message_key = session_key
        if provider_type == "jellyfin":
            jf_message_key = _jellyfin_session_id_from_target(target, session_key)

        reason = v.get("reason") or reason
        kill_reason_for_client = (v.get("warn_text") or reason)

        kill_live_sessions = _load_live_sessions()
        kill_account_username, kill_ips_json, kill_details_json = _build_enforcement_snapshot(
            target=target,
            violation_sessions=sessions,
            live_sessions=kill_live_sessions,
            policy=policy,
            reason=reason,
        )

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

            if ok:
                _queue_stream_blocked_notification(
                    task_id=task_id,
                    policy=policy,
                    server_row=server_row,
                    target=target,
                    reason=reason,
                    kill_reason_for_client=kill_reason_for_client,
                    related_sessions=sessions,
                )

            _log_enforcement(
                policy_id, server_id, provider_type, session_key,
                user_vodum_id, user_ext,
                "kill" if ok else "kill_failed", reason,
                account_username=kill_account_username,
                ips_json=kill_ips_json,
                details_json=kill_details_json,
            )
            _upsert_state(policy_id, server_id, user_vodum_id, user_ext, warned=False, killed=ok, reason=reason)

            logger.warning(
                f"[TASK {task_id}] [KILL] policy={policy_id} server={server_id} provider={provider_type} "
                f"session={session_key} ok={ok} reason={reason} "
                f"target_vodum_user_id={user_vodum_id} target_external_user_id={user_ext} "
                f"ip={target.get('ip')} device={target.get('device') or target.get('client_product')} "
                f"is_transcode={target.get('is_transcode')} bitrate={target.get('bitrate')}"
            )

        except Exception as e:
            logger.error(f"[TASK {task_id}] stream_enforcer: kill failed server={server_id} session={session_key}: {e}", exc_info=True)


    if is_debug_mode_enabled():
        logger.debug(f"[TASK {task_id}] stream_enforcer: done")
