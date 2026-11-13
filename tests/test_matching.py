from ytm_clean.matching import Scored, pick_match, score_candidate
from ytm_clean.models import Track


def _track(
    title: str,
    artists: list[str] | None = None,
    duration_s: int | None = 200,
    video_id: str = "vid1",
    video_type: str = "MUSIC_VIDEO_TYPE_OMV",
) -> Track:
    return Track(
        video_id=video_id,
        set_video_id=None,
        title=title,
        artists=["Artist A"] if artists is None else artists,
        duration_s=duration_s,
        video_type=video_type,
    )


def test_exact_match_accepts() -> None:
    video = _track("Song Name (Official Video)", ["Artist A"], 200)
    cand = _track("Song Name", ["Artist A"], 201, video_id="song1", video_type="MUSIC_VIDEO_TYPE_ATV")

    scored = score_candidate(video, cand)
    assert isinstance(scored, Scored)
    assert scored.score >= 0.90
    assert "title=" in scored.reason and "artist=" in scored.reason and "dur=" in scored.reason

    match, hint = pick_match(video, [cand])
    assert hint == "accept"
    assert match == scored


def test_duration_gate() -> None:
    video = _track("Song Name", ["Artist A"], 200)
    fuzzy_video = _track("Song Names", ["Artist A"], 200)
    fuzzy_far = _track("Song Name", ["Artist A"], 210, video_type="MUSIC_VIDEO_TYPE_ATV")
    way_too_far = _track("Song Name", ["Artist A"], 300, video_type="MUSIC_VIDEO_TYPE_ATV")
    missing_cand = _track("Song Name", ["Artist A"], None, video_type="MUSIC_VIDEO_TYPE_ATV")
    missing_video = _track("Song Name", ["Artist A"], None)

    assert score_candidate(fuzzy_video, fuzzy_far) is None
    assert score_candidate(video, way_too_far) is None
    assert score_candidate(video, missing_cand) is None
    assert score_candidate(missing_video, _track("Song Name", ["Artist A"], 200)) is None


def test_mv_duration_and_five_sec_accept() -> None:
    # Exact title+artist with 5s delta (Sweet Venom / Ditto / Psycho pattern) accepts
    v5 = _track("Ditto", ["NewJeans"], 190)
    c5 = _track("Ditto", ["NewJeans"], 185, video_id="s5", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(v5, [c5])[1] == "accept"

    # MV intro/outro up to 90s on exact title+artist (Magnetic / DASH / Deja Vu pattern) accepts
    mv = _track("Deja Vu", ["TOMORROW X TOGETHER"], 241)
    song = _track("Deja Vu", ["TOMORROW X TOGETHER"], 172, video_id="s_dv", video_type="MUSIC_VIDEO_TYPE_ATV")
    unrelated_5s = _track("Touch", ["TOMORROW X TOGETHER"], 240, video_id="s_other", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert score_candidate(mv, unrelated_5s) is None
    matched, hint = pick_match(mv, [song, unrelated_5s])
    assert hint == "accept"
    assert matched is not None and matched.track.video_id == "s_dv"


def test_artist_prefix_stripped_in_scoring() -> None:
    video = _track(
        "LE SSERAFIM (르세라핌) 'UNFORGIVEN ' OFFICIAL M/V (feat. Nile Rodgers & Ado)",
        ["LE SSERAFIM"],
        260,
    )
    cand = _track(
        "UNFORGIVEN (feat. Nile Rodgers)",
        ["LE SSERAFIM"],
        183,
        video_id="s_unf",
        video_type="MUSIC_VIDEO_TYPE_ATV",
    )
    matched, hint = pick_match(video, [cand])
    assert hint == "accept"
    assert matched is not None and matched.track.video_id == "s_unf"


def test_bilingual_parenthetical_title_and_track_num_accept() -> None:
    v1 = _track("Hypnosis", ["IVE"], 147)
    c1 = _track("섬찟 (Hypnosis)", ["IVE"], 147, video_id="s_hyp", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(v1, [c1])[1] == "accept"

    v2 = _track("I Am the Best", ["2NE1"], 215)
    c2 = _track("내가 제일 잘 나가 (I Am The Best)", ["2NE1"], 211, video_id="s_2ne1", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(v2, [c2])[1] == "accept"

    v3 = _track("03. IVE - BlueHeart", ["IVE"], 189)
    c3 = _track("Blue Heart", ["IVE"], 188, video_id="s_bh", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(v3, [c3])[1] == "accept"


def test_identical_song_tie_within_15s_accepts() -> None:
    video = _track("Everybody", ["SHINee"], 277)
    c1 = _track("Everybody", ["SHINee"], 250, video_id="s1", video_type="MUSIC_VIDEO_TYPE_ATV")
    c2 = _track("Everybody", ["SHINee"], 258, video_id="s2", video_type="MUSIC_VIDEO_TYPE_ATV")
    matched, hint = pick_match(video, [c1, c2])
    assert hint == "accept"
    assert matched is not None and matched.track.video_id == "s2"


def test_artist_gate() -> None:
    video = _track("Song Name", ["Artist A"], 200)
    other = _track("Song Name", ["Artist B"], 200, video_type="MUSIC_VIDEO_TYPE_ATV")
    assert score_candidate(video, other) is None


def test_live_vs_studio_rejected() -> None:
    video = _track("Song Name (Live)", ["Artist A"], 200)
    studio = _track("Song Name", ["Artist A"], 200, video_type="MUSIC_VIDEO_TYPE_ATV")
    assert score_candidate(video, studio) is None


def test_ambiguous_margin() -> None:
    video = _track("Song Name", ["Artist A"], 200)
    c1 = _track("Song Name 1", ["Artist A"], 200, video_id="s1", video_type="MUSIC_VIDEO_TYPE_ATV")
    c2 = _track("Song Name 2", ["Artist A"], 200, video_id="s2", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(video, [c1, c2]) == (None, "low-confidence")


def test_identical_song_tie_accepts() -> None:
    video = _track("Gee", ["Girls' Generation"], 230)
    c1 = _track("Gee", ["Girls' Generation"], 203, video_id="s1", video_type="MUSIC_VIDEO_TYPE_ATV")
    c2 = _track("Gee", ["Girls' Generation"], 202, video_id="s2", video_type="MUSIC_VIDEO_TYPE_ATV")
    matched, hint = pick_match(video, [c1, c2])
    assert hint == "accept"
    assert matched is not None and matched.track.video_id == "s1"


def test_below_threshold_is_low_confidence() -> None:
    video = _track("Song Name", ["Artist A", "Artist B"], 200)
    cand = _track("Song Name", ["Artist A"], 204, video_type="MUSIC_VIDEO_TYPE_ATV")
    scored = score_candidate(video, cand)
    assert scored is not None
    assert scored.score < 0.90
    assert pick_match(video, [cand]) == (None, "low-confidence")


def test_no_cands() -> None:
    video = _track("Song Name", ["Artist A"], 200)
    assert pick_match(video, []) == (None, "none")
    gated_out = _track("Song Name", ["Other Artist"], 200, video_type="MUSIC_VIDEO_TYPE_ATV")
    assert pick_match(video, [gated_out]) == (None, "none")


def test_empty_video_id_or_normalized_title_returns_none() -> None:
    video = _track("Song Name", ["Artist A"], 200)
    cand_no_id = Track(
        video_id=None,
        set_video_id=None,
        title="Song Name",
        artists=["Artist A"],
        duration_s=200,
        video_type="MUSIC_VIDEO_TYPE_ATV",
    )
    cand_empty_id = _track("Song Name", ["Artist A"], 200, video_id="", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert score_candidate(video, cand_no_id) is None
    assert score_candidate(video, cand_empty_id) is None

    noise_only_video = _track("(Official Video)", ["Artist A"], 200)
    noise_only_cand = _track("(Official Audio)", ["Artist A"], 200, video_id="s1", video_type="MUSIC_VIDEO_TYPE_ATV")
    assert score_candidate(noise_only_video, noise_only_cand) is None
    assert score_candidate(noise_only_video, _track("Song Name", ["Artist A"], 200, video_id="s2")) is None
    assert score_candidate(video, noise_only_cand) is None
