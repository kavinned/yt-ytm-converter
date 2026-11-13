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


def _fmt_dur(seconds: int | None) -> str:
    if seconds is None:
        return "?:??"
    mins, secs = divmod(seconds, 60)
    return f"{mins}:{secs:02d}"


def _initial_candidates(track: Track, search: Callable[[str], list[Track]]) -> list[Track]:
    seen_ids: set[str] = set()
    merged: list[Track] = []
    q_norm = _search_query(track)
    queries = [q_norm]
    q_raw = _raw_search_query(track)
    if q_raw.casefold() != q_norm.casefold():
        queries.append(q_raw)
    for query in queries:
        for cand in search(query):
            if cand.video_id and cand.video_id not in seen_ids:
                seen_ids.add(cand.video_id)
                merged.append(cand)
            if len(merged) >= 8:
                return merged
    return merged


def pick_unresolved(
    rows: list[PlanRow],
    search: Callable[[str], list[Track]],
    *,
    input_fn: Callable[[str], str] = input,
    out_fn: Callable[[str], None] = print,
    limit: int = 8,
) -> list[PlanRow]:
    """Interactively resolve keep-video and no-match rows from search results."""
    seen_songs: list[Track] = []
    for row in rows:
        if row.action == Action.KEEP_SONG and row.track.video_id:
            seen_songs.append(row.track)
        elif row.action == Action.REPLACE and row.replacement is not None:
            seen_songs.append(row.replacement)

    updated = list(rows)
    targets = [
        pos
        for pos, row in enumerate(updated)
        if row.action in (Action.KEEP_VIDEO, Action.NO_MATCH) and row.track.video_id
    ]
    total_targets = len(targets)
    for pick_num, pos in enumerate(targets, 1):
        row = updated[pos]
        cands = _initial_candidates(row.track, search)[:limit]
        while True:
            artists = ", ".join(row.track.artists) or "Unknown"
            out_fn(
                f"\n[{pick_num}/{total_targets}] (#{row.index}) {row.track.title} - {artists} "
                f"({_fmt_dur(row.track.duration_s)}) [{row.action.value}: {row.reason}] "
                f"https://music.youtube.com/watch?v={row.track.video_id}"
            )
            if not cands:
                out_fn("  (no search results)")
            for i, cand in enumerate(cands, 1):
                c_artists = ", ".join(cand.artists) or "Unknown"
                out_fn(
                    f"  {i}. {cand.title} - {c_artists} ({_fmt_dur(cand.duration_s)}) "
                    f"https://music.youtube.com/watch?v={cand.video_id}"
                )
            try:
                raw = input_fn(
                    "Choose [1-N], 's <query>' to search, Enter to keep, 'q' to stop picking: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                return updated

            if raw in ("", "0"):
                break
            if raw.lower() == "q":
                return updated
            if raw.lower().startswith("s "):
                custom_q = raw[2:].strip()
                if custom_q:
                    cands = [c for c in search(custom_q) if c.video_id][:limit]
                continue
            if raw.isdigit() and 1 <= int(raw) <= len(cands):
                chosen = cands[int(raw) - 1]
                if any(_same_song(chosen, s) for s in seen_songs):
                    updated[pos] = PlanRow(
                        row.index,
                        row.track,
                        row.classification,
                        Action.REMOVE_DUP,
                        chosen,
                        1.0,
                        "manual pick (duplicate)",
                    )
                else:
                    seen_songs.append(chosen)
                    updated[pos] = PlanRow(
                        row.index,
                        row.track,
                        row.classification,
                        Action.REPLACE,
                        chosen,
                        1.0,
                        "manual pick",
                    )
                break
            out_fn("Invalid choice.")
    return updated
