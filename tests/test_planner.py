from ytm_clean.models import Action, PlanRow, Track
from ytm_clean.planner import build_plan


def _track(
    vid: str | None,
    title: str = "Song",
    artists: list[str] | None = None,
    dur: int | None = 200,
    vtype: str | None = "MUSIC_VIDEO_TYPE_OMV",
    set_vid: str | None = "sv1",
) -> Track:
    return Track(
        video_id=vid,
        set_video_id=set_vid,
        title=title,
        artists=["Artist"] if artists is None else artists,
        duration_s=dur,
        video_type=vtype,
    )


def test_atv_left_alone():
    called = False

    def search(_q: str) -> list[Track]:
        nonlocal called
        called = True
        return []

    t = _track("s1", vtype="MUSIC_VIDEO_TYPE_ATV")
    rows = build_plan([t], search)
    assert len(rows) == 1
    assert isinstance(rows[0], PlanRow)
    assert rows[0].index == 0
    assert rows[0].classification == "song"
    assert rows[0].action == Action.KEEP_SONG
    assert rows[0].replacement is None
    assert not called


def test_replace():
    video = _track("v1", title="Track One (Official Video)", artists=["Alice"], dur=200)
    cand = _track("s1", title="Track One", artists=["Alice"], dur=201, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = build_plan([video], lambda _q: [cand])
    assert len(rows) == 1
    row = rows[0]
    assert row.classification == "video"
    assert row.action == Action.REPLACE
    assert row.replacement is not None
    assert row.replacement.video_id == "s1"
    assert row.confidence is not None and row.confidence >= 0.90


def test_already_present_by_id():
    video = _track("v1", title="Track One (Official Video)", artists=["Alice"], dur=200)
    atv = _track("s1", title="Track One", artists=["Alice"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")
    cand = _track("s1", title="Track One", artists=["Alice"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = build_plan([video, atv], lambda _q: [cand])
    assert [r.action for r in rows] == [Action.REMOVE_DUP, Action.KEEP_SONG]


def test_already_present_by_meta():
    video = _track("v1", title="Track One (Lyrics)", artists=["Alice"], dur=200)
    atv = _track("s_existing", title="Track One", artists=["Alice"], dur=202, vtype="MUSIC_VIDEO_TYPE_ATV")
    cand = _track("s_new", title="Track One", artists=["Alice"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = build_plan([atv, video], lambda _q: [cand])
    assert [r.action for r in rows] == [Action.KEEP_SONG, Action.REMOVE_DUP]


def test_two_videos_one_song():
    v1 = _track("v1", title="Track One (Official Video)", artists=["Alice"], dur=200)
    v2 = _track("v2", title="Track One (Lyrics)", artists=["Alice"], dur=201, vtype="MUSIC_VIDEO_TYPE_UGC")
    cand = _track("s1", title="Track One", artists=["Alice"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = build_plan([v1, v2], lambda _q: [cand])
    assert [r.action for r in rows] == [Action.REPLACE, Action.REMOVE_DUP]
    assert rows[0].replacement is not None
    assert rows[0].replacement.video_id == "s1"


def test_low_conf_keeps():
    video = _track("v1", title="Track One", artists=["Alice", "Bob"], dur=200)
    c1 = _track("s1", title="Track One", artists=["Alice"], dur=204, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = build_plan([video], lambda _q: [c1])
    assert rows[0].action == Action.KEEP_VIDEO
    assert rows[0].replacement is None


def test_none():
    video = _track("v1", title="Track One", artists=["Alice"], dur=200)

    rows = build_plan([video], lambda _q: [])
    assert rows[0].action == Action.NO_MATCH
    assert rows[0].replacement is None


def test_null_video_id_passthrough():
    called = False

    def search(_q: str) -> list[Track]:
        nonlocal called
        called = True
        return []

    ep = _track(None, title="Unavailable Episode", artists=[], dur=None, vtype=None)
    rows = build_plan([ep], search)
    assert len(rows) == 1
    assert rows[0].classification == "other"
    assert rows[0].action == Action.KEEP_VIDEO
    assert rows[0].replacement is None
    assert not called


def test_replan_is_noop():
    tracks = [
        _track("s0", title="Existing", artists=["Bob"], dur=180, vtype="MUSIC_VIDEO_TYPE_ATV"),
        _track("v1", title="Track One (Official Video)", artists=["Alice"], dur=200),
        _track("v2", title="Track One (Lyrics)", artists=["Alice"], dur=201),
        _track("v3", title="Unmatched", artists=["Carol"], dur=240),
        _track(None, title="Unavailable", artists=[], dur=None, vtype=None),
    ]
    cand_one = _track("s1", title="Track One", artists=["Alice"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")

    def search(q: str) -> list[Track]:
        if "track one" in q:
            return [cand_one]
        return []

    plan1 = build_plan(tracks, search)
    rebuilt: list[Track] = []
    for row in plan1:
        if row.action == Action.REMOVE_DUP:
            continue
        if row.action == Action.REPLACE and row.replacement is not None:
            rebuilt.append(row.replacement)
        else:
            rebuilt.append(row.track)

    plan2 = build_plan(rebuilt, search)
    actions2 = {r.action for r in plan2}
    assert Action.REPLACE not in actions2
    assert Action.REMOVE_DUP not in actions2


def test_build_plan_calls_on_progress():
    tracks = [
        _track("s0", title="Song Zero", vtype="MUSIC_VIDEO_TYPE_ATV"),
        _track("v1", title="Video One", vtype="MUSIC_VIDEO_TYPE_OMV"),
    ]
    seen: list[tuple[int, int, str]] = []
    build_plan(
        tracks,
        lambda _q: [],
        on_progress=lambda i, total, t: seen.append((i, total, t.title)),
    )
    assert seen == [(2, 2, "Video One")]


def test_already_present_atv_detected_even_if_search_misses():
    atv = _track("s1", title="Roller Coaster", artists=["NMIXX"], dur=180, vtype="MUSIC_VIDEO_TYPE_ATV")
    mv = _track("v1", title="Roller Coaster", artists=["NMIXX"], dur=214, vtype="MUSIC_VIDEO_TYPE_OMV")
    called = False

    def search(_q: str) -> list[Track]:
        nonlocal called
        called = True
        return []

    rows = build_plan([atv, mv], search)
    assert [r.action for r in rows] == [Action.KEEP_SONG, Action.REMOVE_DUP]
    assert not called


def test_pick_unresolved_replace_keep_custom_search_and_dup():
    from ytm_clean.planner import pick_unresolved

    atv_existing = _track("s_exist", title="Existing Song", artists=["Bob"], dur=180, vtype="MUSIC_VIDEO_TYPE_ATV")
    v_nomatch = _track("v1", title="Super", artists=["SEVENTEEN"], dur=213)
    v_lowconf = _track("v2", title="Ambiguous", artists=["Alice"], dur=200)
    v_null = _track(None, title="Unavailable", artists=[], dur=None, vtype=None)

    cand_kr = _track("s_super", title="손오공", artists=["SEVENTEEN"], dur=201, vtype="MUSIC_VIDEO_TYPE_ATV")
    cand_dup = _track("s_exist", title="Existing Song", artists=["Bob"], dur=180, vtype="MUSIC_VIDEO_TYPE_ATV")

    rows = [
        PlanRow(0, atv_existing, "song", Action.KEEP_SONG, None, None, "already song"),
        PlanRow(1, v_nomatch, "video", Action.NO_MATCH, None, None, "none"),
        PlanRow(2, v_lowconf, "video", Action.KEEP_VIDEO, None, None, "low-confidence"),
        PlanRow(3, v_null, "other", Action.KEEP_VIDEO, None, None, "unavailable/non-music"),
    ]

    def search(q: str) -> list[Track]:
        if "손오공" in q:
            return [cand_kr]
        if "ambiguous" in q.lower():
            return [cand_dup]
        return []

    inputs = iter(["s 손오공", "1", "1"])  # v1: custom search -> pick 1; v2: pick 1 (already in playlist -> REMOVE_DUP); v_null skipped
    printed: list[str] = []
    updated = pick_unresolved(
        rows,
        search,
        input_fn=lambda _p="": next(inputs),
        out_fn=printed.append,
    )

    assert updated[0].action == Action.KEEP_SONG
    assert updated[1].action == Action.REPLACE
    assert updated[1].replacement == cand_kr
    assert updated[1].reason == "manual pick"
    assert updated[2].action == Action.REMOVE_DUP
    assert updated[2].replacement == cand_dup
    assert updated[3].action == Action.KEEP_VIDEO


def test_pick_unresolved_enter_keeps_and_q_stops():
    from ytm_clean.planner import pick_unresolved

    v1 = _track("v1", title="One", artists=["A"], dur=200)
    v2 = _track("v2", title="Two", artists=["A"], dur=200)
    cand = _track("s1", title="One", artists=["A"], dur=200, vtype="MUSIC_VIDEO_TYPE_ATV")
    rows = [
        PlanRow(0, v1, "video", Action.NO_MATCH, None, None, "none"),
        PlanRow(1, v2, "video", Action.KEEP_VIDEO, None, None, "low-confidence"),
    ]
    inputs = iter(["", "q"])
    updated = pick_unresolved(rows, lambda _q: [cand], input_fn=lambda _p="": next(inputs), out_fn=lambda _s: None)
    assert updated[0].action == Action.NO_MATCH
    assert updated[1].action == Action.KEEP_VIDEO
