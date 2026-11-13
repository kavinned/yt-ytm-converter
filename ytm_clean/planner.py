from collections.abc import Callable

from ytm_clean.matching import MAX_DURATION_DELTA_S, pick_match
from ytm_clean.models import Action, PlanRow, Track
from ytm_clean.normalize import normalize_artists, normalize_title

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


def _search_query(track: Track) -> str:
    """Build a song search query from cleaned title and primary artist."""
    title_clean = normalize_title(track.title)
    first_artist = track.artists[0] if track.artists else ""
    query = " ".join(p for p in (title_clean, first_artist) if p)
    return query or track.title


def build_plan(
    tracks: list[Track], search: Callable[[str], list[Track]]
) -> list[PlanRow]:
    """Build an order-preserving replacement plan for playlist tracks."""
    seen_songs: list[Track] = [
        t for t in tracks if t.video_id and t.video_type == ATV_TYPE
    ]
    rows: list[PlanRow] = []

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

        cands = search(_search_query(track))
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
