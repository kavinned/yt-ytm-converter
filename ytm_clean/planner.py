from collections.abc import Callable

from ytm_clean.matching import MAX_DURATION_DELTA_S, MAX_MV_DURATION_DELTA_S, pick_match
from ytm_clean.models import Action, PlanRow, Track
from ytm_clean.normalize import (
    alt_titles,
    normalize_artists,
    normalize_title,
    search_query_title,
    version_tokens,
)

ATV_TYPE = "MUSIC_VIDEO_TYPE_ATV"


def _same_song(a: Track, b: Track) -> bool:
    """Return True if two tracks represent the same song by ID or normalized metadata."""
    if a.video_id and b.video_id and a.video_id == b.video_id:
        return True
    if a.duration_s is None or b.duration_s is None:
        return False
    if abs(a.duration_s - b.duration_s) > MAX_DURATION_DELTA_S:
        return False
    ta = normalize_title(a.title)
    tb = normalize_title(b.title)
    if not ta or ta != tb:
        return False
    return bool(normalize_artists(a.artists) & normalize_artists(b.artists))


def _video_matches_existing_song(video: Track, song: Track) -> Track | None:
    if video.duration_s is None or song.duration_s is None:
        return None
    if abs(video.duration_s - song.duration_s) > MAX_MV_DURATION_DELTA_S:
        return None
    if version_tokens(video.title) != version_tokens(song.title):
        return None
    v_alts = set(alt_titles(video.title))
    s_alts = set(alt_titles(song.title))
    if not (v_alts & s_alts):
        return None
    if not (normalize_artists(video.artists) & normalize_artists(song.artists)):
        return None
    return song


def _search_query(track: Track) -> str:
    """Build a song search query from cleaned title and primary artist."""
    title_clean = normalize_title(track.title)
    first_artist = track.artists[0] if track.artists else ""
    query = " ".join(p for p in (title_clean, first_artist) if p)
    return query or track.title


def _raw_search_query(track: Track) -> str:
    title_clean = search_query_title(track.title)
    first_artist = track.artists[0] if track.artists else ""
    return " ".join(p for p in (title_clean, first_artist) if p) or track.title


def build_plan(
    tracks: list[Track],
    search: Callable[[str], list[Track]],
    *,
    on_progress: Callable[[int, int, Track], None] | None = None,
) -> list[PlanRow]:
    """Build an order-preserving replacement plan for playlist tracks."""
    seen_songs: list[Track] = [
        t for t in tracks if t.video_id and t.video_type == ATV_TYPE
    ]
    rows: list[PlanRow] = []
    total = len(tracks)

    for idx, track in enumerate(tracks):
        if not track.video_id:
            rows.append(
                PlanRow(
                    idx,
                    track,
                    "other",
                    Action.KEEP_VIDEO,
                    None,
                    None,
                    "unavailable/non-music",
                )
            )
            continue

        if track.video_type == ATV_TYPE:
            rows.append(
                PlanRow(
                    idx, track, "song", Action.KEEP_SONG, None, None, "already song"
                )
            )
            continue

        existing = next(
            (s for s in seen_songs if _video_matches_existing_song(track, s) is not None),
            None,
        )
        if existing is not None:
            rows.append(
                PlanRow(
                    idx,
                    track,
                    "video",
                    Action.REMOVE_DUP,
                    existing,
                    1.0,
                    "duplicate (already in playlist)",
                )
            )
            continue

        if on_progress is not None:
            on_progress(idx + 1, total, track)
        q_norm = _search_query(track)
        cands = search(q_norm)
        match, hint = pick_match(track, cands)
        if match is None:
            q_raw = _raw_search_query(track)
            if q_raw.casefold() != q_norm.casefold():
                cands = search(q_raw)
                match, hint = pick_match(track, cands)
        if match is None:
            action = Action.KEEP_VIDEO if hint == "low-confidence" else Action.NO_MATCH
            rows.append(PlanRow(idx, track, "video", action, None, None, hint))
        elif any(_same_song(match.track, s) for s in seen_songs):
            rows.append(
                PlanRow(
                    idx,
                    track,
                    "video",
                    Action.REMOVE_DUP,
                    match.track,
                    match.score,
                    f"duplicate ({match.reason})",
                )
            )
        else:
            seen_songs.append(match.track)
            rows.append(
                PlanRow(
                    idx,
                    track,
                    "video",
                    Action.REPLACE,
                    match.track,
                    match.score,
                    match.reason,
                )
            )

    return rows
