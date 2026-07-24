import re
from difflib import SequenceMatcher


USER_MERGE_COLUMNS = """
    id, username, firstname, lastname, email, second_email,
    expiration_date, renewal_method, renewal_date, status, created_at, notes
"""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _email_local(email: str) -> str:
    email = _norm(email)
    return email.split("@", 1)[0] if "@" in email else email


def _sim(left: str, right: str) -> float:
    left, right = _norm(left), _norm(right)
    return SequenceMatcher(None, left, right).ratio() if left and right else 0.0


def _tokens_from_user(user: dict) -> list[str]:
    raw = " ".join([
        _norm(user.get("firstname") or ""), _norm(user.get("lastname") or ""),
        _norm(user.get("username") or ""), _email_local(user.get("email") or ""),
        _email_local(user.get("second_email") or ""),
    ])
    return list(dict.fromkeys(
        part.strip() for part in re.split(r"[ \t\.\-_]+", raw) if len(part.strip()) >= 3
    ))


def score_candidate(user: dict, candidate: dict) -> int:
    score = 0
    user_email, user_second = _norm(user.get("email") or ""), _norm(user.get("second_email") or "")
    candidate_email = _norm(candidate.get("email") or "")
    candidate_second = _norm(candidate.get("second_email") or "")
    for matches, points in (
        (user_email and candidate_email and user_email == candidate_email, 500),
        (user_email and candidate_second and user_email == candidate_second, 420),
        (user_second and candidate_email and user_second == candidate_email, 420),
        (user_second and candidate_second and user_second == candidate_second, 300),
    ):
        if matches:
            score += points

    fields = (
        (_norm(candidate.get("username") or ""), (260, 220, 180)),
        (_norm(candidate.get("firstname") or ""), (200, 160, 120)),
        (_norm(candidate.get("lastname") or ""), (200, 160, 120)),
        (_email_local(candidate.get("email") or ""), (170, 140, 110)),
        (_email_local(candidate.get("second_email") or ""), (120, 90, 70)),
    )
    for token in _tokens_from_user(user):
        for value, (exact, prefix, contains) in fields:
            if value == token:
                score += exact
            elif value.startswith(token):
                score += prefix
            elif token in value:
                score += contains

    score += int(120 * _sim(_email_local(user.get("email") or ""), _email_local(candidate.get("email") or "")))
    score += int(80 * _sim(user.get("firstname") or "", candidate.get("firstname") or ""))
    score += int(80 * _sim(user.get("lastname") or "", candidate.get("lastname") or ""))
    score += int(50 * _sim(user.get("username") or "", candidate.get("username") or ""))
    return score


def get_merge_suggestions(db, user_id: int, limit: int | None = None):
    user = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (user_id,))
    if not user:
        return []
    user = dict(user)
    candidates = db.query(
        """SELECT id, username, firstname, lastname, email, second_email,
                  expiration_date, status, created_at
           FROM vodum_users WHERE id != ?""",
        (user_id,),
    )
    scored = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["merge_score"] = score_candidate(user, candidate)
        scored.append(candidate)
    scored.sort(key=lambda item: item["merge_score"], reverse=True)
    return scored if limit is None else scored[:limit]
