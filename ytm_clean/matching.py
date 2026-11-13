from dataclasses import dataclass
from difflib import SequenceMatcher

from ytm_clean.models import Track
from ytm_clean.normalize import normalize_artists, normalize_title, version_tokens

MAX_DURATION_DELTA_S = 5
MAX_MV_DURATION_DELTA_S = 90
EXACT_TITLE_FOR_MV = 0.95
MIN_TITLE_SIM = 0.65
ACCEPT_SCORE = 0.90
MIN_MARGIN = 0.05


@dataclass(frozen=True)
class Scored:
    track: Track
    score: float
    reason: str


def _same_song_cand(a: Track, b: Track) -> bool:
    if a.duration_s is None or b.duration_s is None:
        return False
    if abs(a.duration_s - b.duration_s) > MAX_DURATION_DELTA_S:
        return False
    if version_tokens(a.title) != version_tokens(b.title):
        return False
    ta = normalize_title(a.title)
    tb = normalize_title(b.title)
    if not ta or ta != tb:
        return False
    return bool(normalize_artists(a.artists) & normalize_artists(b.artists))


def score_candidate(video: Track, cand: Track) -> Scored | None:
    if not cand.video_id:
        return None
    if video.duration_s is None or cand.duration_s is None:
        return None
    dur_delta = abs(video.duration_s - cand.duration_s)
    if dur_delta > MAX_MV_DURATION_DELTA_S:
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

    if v_title.endswith(" " + c_title):
        prefix = v_title[: -len(c_title)]
        if any(a in prefix for a in v_artists):
            v_title = c_title

    title_sim = SequenceMatcher(None, v_title, c_title).ratio()
    if title_sim < MIN_TITLE_SIM:
        return None
    if dur_delta > MAX_DURATION_DELTA_S and title_sim < EXACT_TITLE_FOR_MV:
        return None

    artist_jaccard = len(overlap) / len(v_artists | c_artists)
    if dur_delta <= MAX_DURATION_DELTA_S:
        dur_closeness = 1.0 - 0.5 * (dur_delta / MAX_DURATION_DELTA_S)
    else:
        dur_closeness = 0.5 * (
            1.0 - (dur_delta - MAX_DURATION_DELTA_S) / (MAX_MV_DURATION_DELTA_S - MAX_DURATION_DELTA_S)
        )
    score = 0.60 * title_sim + 0.30 * artist_jaccard + 0.10 * dur_closeness
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
    if (
        len(scored) >= 2
        and (best.score - scored[1].score) < MIN_MARGIN
        and not _same_song_cand(best.track, scored[1].track)
    ):
        return None, "low-confidence"
    return best, "accept"
