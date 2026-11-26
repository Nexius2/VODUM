import re
from difflib import SequenceMatcher
from db_manager import isolated_read_operation


USER_MERGE_COLUMNS = """
    id, username, firstname, lastname, email, second_email,
    expiration_date, renewal_method, renewal_date, status, created_at, notes
"""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _email_local(email: str) -> str:
    email = _norm(email)
    return email.split("@", 1)[0] if "@" in email else email


def _tokens_from_user(user: dict) -> list[str]:
    raw = " ".join([
        _norm(user.get("firstname") or ""), _norm(user.get("lastname") or ""),
        _norm(user.get("username") or ""), _email_local(user.get("email") or ""),
        _email_local(user.get("second_email") or ""),
    ])
    return list(dict.fromkeys(
        part.strip() for part in re.split(r"[ \t\.\-_]+", raw) if len(part.strip()) >= 3
    ))


def _prepare_user(user):
    prepared = {key: _norm(user.get(key) or '')
                for key in ('username', 'firstname', 'lastname', 'email', 'second_email')}
    prepared['email_similarity'] = _norm(_email_local(user.get('email') or ''))
    prepared['tokens'] = _tokens_from_user(user)
    return prepared


def _prepared_similarity(left, right):
    return SequenceMatcher(None, left, right).ratio() if left and right else 0.0


def _score_prepared(user, candidate):
    score = 0
    user_email, user_second = user['email'], user['second_email']
    candidate_email = _norm(candidate.get("email") or "")
    candidate_second = _norm(candidate.get("second_email") or "")
    candidate_username = _norm(candidate.get('username') or '')
    candidate_firstname = _norm(candidate.get('firstname') or '')
    candidate_lastname = _norm(candidate.get('lastname') or '')
    candidate_local = _email_local(candidate_email)
    candidate_second_local = _email_local(candidate_second)
    for matches, points in (
        (user_email and candidate_email and user_email == candidate_email, 500),
        (user_email and candidate_second and user_email == candidate_second, 420),
        (user_second and candidate_email and user_second == candidate_email, 420),
        (user_second and candidate_second and user_second == candidate_second, 300),
    ):
        if matches:
            score += points

    fields = (
        (candidate_username, (260, 220, 180)),
        (candidate_firstname, (200, 160, 120)),
        (candidate_lastname, (200, 160, 120)),
        (candidate_local, (170, 140, 110)),
        (candidate_second_local, (120, 90, 70)),
    )
    for token in user['tokens']:
        for value, (exact, prefix, contains) in fields:
            if value == token:
                score += exact
            elif value.startswith(token):
                score += prefix
            elif token in value:
                score += contains

    score += int(120 * _prepared_similarity(user['email_similarity'], _norm(candidate_local)))
    score += int(80 * _prepared_similarity(user['firstname'], candidate_firstname))
    score += int(80 * _prepared_similarity(user['lastname'], candidate_lastname))
    score += int(50 * _prepared_similarity(user['username'], candidate_username))
    return score


def score_candidate(user: dict, candidate: dict) -> int:
    return _score_prepared(_prepare_user(user), candidate)


@isolated_read_operation
def _load_merge_candidates(db, user_id: int):
    user = db.query_one(f"SELECT {USER_MERGE_COLUMNS} FROM vodum_users WHERE id=?", (user_id,))
    if not user:
        return None, []
    user = dict(user)
    candidates = db.query(
        """SELECT id, username, firstname, lastname, email, second_email,
                  expiration_date, status, created_at
           FROM vodum_users WHERE id != ?""",
        (user_id,),
    )
    return user, [dict(candidate) for candidate in candidates]


def load_ranked_merge_candidates(db, user_id: int):
    """Picker list from current accounts, ranked by the prepared scores.

    Scoring runs in the background task. Returns (candidates, pending); while
    the first ranking is pending, accounts are listed without a score.
    """
    from core.monitoring.precomputed_views import load_merge_scores
    user, candidates = _load_merge_candidates(db, user_id)
    if user is None:
        return [], False
    scores, _ = load_merge_scores(db, user_id)
    for candidate in candidates:
        candidate["merge_score"] = None if scores is None else scores.get(int(candidate["id"]), 0)
    if scores is not None:
        candidates.sort(key=lambda item: item["merge_score"], reverse=True)
    return candidates, scores is None


def get_merge_suggestions(db, user_id: int, limit: int | None = None):
    user, candidates = _load_merge_candidates(db, user_id)
    if user is None:
        return []
    # Scoring is CPU work: release the SQLite snapshot before ranking.
    prepared_user = _prepare_user(user)
    scored = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["merge_score"] = _score_prepared(prepared_user, candidate)
        scored.append(candidate)
    scored.sort(key=lambda item: item["merge_score"], reverse=True)
    return scored if limit is None else scored[:limit]
