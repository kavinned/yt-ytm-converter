from dataclasses import dataclass
from difflib import SequenceMatcher

from ytm_clean.models import Track
from ytm_clean.normalize import normalize_artists, normalize_title, version_tokens

MAX_DURATION_DELTA_S = 5
ACCEPT_SCORE = 0.90
MIN_MARGIN = 0.05


@dataclass(frozen=True)
class Scored:
    track: Track
    score: float
    reason: str


def score_candidate(video: Track, cand: Track) -> Scored | None:
    if not cand.video_id:
        return None
    if video.duration_s is None or cand.duration_s is None:
        return None
    dur_delta = abs(video.duration_s - cand.duration_s)
    if dur_delta > MAX_DURATION_DELTA_S:
        return None
    if version_tokens(video.title) != version_tokens(cand.title):
        return None

    v_title = normalize_title(video.title)
    c_title = normalize_title(cand.title)
    if not v_title or not c_title:
        return None

    v_artists = normalize_artists(video.artists)
    c_artists = normalize_artists(cand.artists)
    overlap = v_artists & c_artists
    if not overlap:
        return None

    title_sim = SequenceMatcher(None, v_title, c_title).ratio()
    artist_jaccard = len(overlap) / len(v_artists | c_artists)
    dur_closeness = 1.0 - dur_delta / MAX_DURATION_DELTA_S
    score = 0.55 * title_sim + 0.30 * artist_jaccard + 0.15 * dur_closeness
    reason = f"title={title_sim:.2f} artist={artist_jaccard:.2f} dur={dur_closeness:.2f} score={score:.2f}"
    return Scored(track=cand, score=score, reason=reason)


def pick_match(video: Track, cands: list[Track]) -> tuple[Scored | None, str]:
    scored = sorted(
        (s for c in cands if (s := score_candidate(video, c)) is not None),
        key=lambda s: s.score,
        reverse=True,
    )
    if not scored:
        return None, "none"
    best = scored[0]
    if best.score < ACCEPT_SCORE:
        return None, "low-confidence"
    if len(scored) >= 2 and (best.score - scored[1].score) < MIN_MARGIN:
        return None, "low-confidence"
    return best, "accept"
