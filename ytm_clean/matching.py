from dataclasses import dataclass
from difflib import SequenceMatcher

from ytm_clean.models import Track
from ytm_clean.normalize import (
    alt_titles,
    is_single_artist,
    normalize_artists,
    normalize_title,
    version_tokens,
)

MAX_DURATION_DELTA_S = 5
MAX_SAME_SONG_DELTA_S = 15
MAX_MV_DURATION_DELTA_S = 90
MAX_LONG_MV_DELTA_S = 120
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
    if abs(a.duration_s - b.duration_s) > MAX_SAME_SONG_DELTA_S:
        return False
    if version_tokens(a.title) != version_tokens(b.title):
        return False
    ta = set(alt_titles(a.title))
    tb = set(alt_titles(b.title))
    if not (ta & tb):
        return False
    return bool(normalize_artists(a.artists) & normalize_artists(b.artists))


def _best_title_sim(v_titles: list[str], c_titles: list[str], v_artists: set[str]) -> float:
    best = 0.0
    for vt in v_titles:
        variants = [vt]
        for a in v_artists:
            if vt.startswith(a + " "):
                variants.append(vt[len(a) + 1 :])
        for ct in c_titles:
            for cand_vt in variants:
                eff = ct if (cand_vt.endswith(" " + ct) and any(a in cand_vt[: -len(ct)] for a in v_artists)) else cand_vt
                sim = SequenceMatcher(None, eff, ct).ratio()
                if sim > best:
                    best = sim
    return best


def score_candidate(video: Track, cand: Track) -> Scored | None:
    if not cand.video_id:
        return None
    if video.duration_s is None or cand.duration_s is None:
        return None
    dur_delta = abs(video.duration_s - cand.duration_s)
    max_mv_delta = MAX_LONG_MV_DELTA_S if video.duration_s > cand.duration_s else MAX_MV_DURATION_DELTA_S
    if dur_delta > max_mv_delta:
        return None
    if version_tokens(video.title) != version_tokens(cand.title):
        return None

    v_titles = alt_titles(video.title)
    c_titles = alt_titles(cand.title)
    if not v_titles or not c_titles:
        return None

    v_artists = normalize_artists(video.artists)
    c_artists = normalize_artists(cand.artists)
    overlap = v_artists & c_artists
    if not overlap:
        return None

    title_sim = _best_title_sim(v_titles, c_titles, v_artists)
    if title_sim < MIN_TITLE_SIM:
        return None
    if dur_delta > MAX_DURATION_DELTA_S and title_sim < EXACT_TITLE_FOR_MV:
        return None

    if is_single_artist(video.artists) and is_single_artist(cand.artists):
        artist_jaccard = 1.0
    else:
        artist_jaccard = len(overlap) / len(v_artists | c_artists)
    if dur_delta <= MAX_DURATION_DELTA_S:
        dur_closeness = 1.0 - 0.5 * (dur_delta / MAX_DURATION_DELTA_S)
    else:
        dur_closeness = 0.5 * (
            1.0 - (dur_delta - MAX_DURATION_DELTA_S) / (max_mv_delta - MAX_DURATION_DELTA_S)
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
