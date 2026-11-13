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
