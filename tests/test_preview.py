import csv

from ytm_clean.apply import final_video_ids
from ytm_clean.models import Action, PlanRow, Track
from ytm_clean.preview import counts, render_table, write_csv, write_html


def _track(
    title: str = "Song",
    artists: list[str] | None = None,
    video_id: str | None = "vid1",
    duration_s: int | None = 200,
    video_type: str | None = "MUSIC_VIDEO_TYPE_OMV",
) -> Track:
    return Track(
        video_id=video_id,
        set_video_id="set1",
        title=title,
        artists=["Artist"] if artists is None else artists,
        duration_s=duration_s,
        video_type=video_type,
    )


def _row(
    index: int,
    action: Action,
    title: str = "Song",
    artists: list[str] | None = None,
    video_id: str | None = "vid1",
    classification: str = "video",
    replacement: Track | None = None,
    confidence: float | None = None,
    reason: str = "ok",
) -> PlanRow:
    return PlanRow(
        index=index,
        track=_track(title=title, artists=artists, video_id=video_id),
        classification=classification,
        action=action,
        replacement=replacement,
        confidence=confidence,
        reason=reason,
    )


def test_csv_roundtrip_unicode_and_commas(tmp_path):
    long_title = 'Å, "q" ' + ("x" * 80)
    repl = _track(
        title="Clean Song",
        artists=["Artist A", "Artist B"],
        video_id="atv12345678",
        duration_s=201,
        video_type="MUSIC_VIDEO_TYPE_ATV",
    )
    rows = [
        _row(
            0,
            Action.REPLACE,
            title=long_title,
            artists=["Årtist, Jr."],
            video_id="omv12345678",
            replacement=repl,
            confidence=0.95,
            reason='matched "studio", high conf',
        ),
        _row(
            1,
            Action.KEEP_SONG,
            title="Plain",
            video_id=None,
            classification="unavailable",
            replacement=None,
            confidence=None,
            reason="no videoId",
        ),
    ]
    out_csv = tmp_path / "preview-PL1.csv"
    write_csv(rows, out_csv)

    raw_bytes = out_csv.read_bytes()
    assert raw_bytes.startswith(b"\xef\xbb\xbf")

    with open(out_csv, "r", encoding="utf-8-sig", newline="") as f:
        parsed = list(csv.reader(f))

    assert parsed[0] == [
        "index",
        "current_title",
        "current_artist",
        "video_id",
        "classification",
        "action",
        "repl_title",
        "repl_artist",
        "repl_duration",
        "repl_video_id",
        "confidence",
        "reason",
    ]
    assert parsed[1] == [
        "0",
        long_title,
        "Årtist, Jr.",
        "omv12345678",
        "video",
        "replace",
        "Clean Song",
        "Artist A, Artist B",
        "201",
        "atv12345678",
        "0.95",
        'matched "studio", high conf',
    ]
    assert parsed[2] == [
        "1",
        "Plain",
        "Artist",
        "",
        "unavailable",
        "keep-song",
        "",
        "",
        "",
        "",
        "",
        "no videoId",
    ]


def test_counts():
    rows = [
        _row(0, Action.REPLACE),
        _row(1, Action.REPLACE),
        _row(2, Action.REMOVE_DUP),
        _row(3, Action.KEEP_VIDEO),
        _row(4, Action.NO_MATCH),
        _row(5, Action.KEEP_SONG),
    ]
    assert counts(rows) == {
        Action.KEEP_SONG: 1,
        Action.REPLACE: 2,
        Action.REMOVE_DUP: 1,
        Action.KEEP_VIDEO: 1,
        Action.NO_MATCH: 1,
    }


def test_table_has_every_row_and_footer():
    long_title = "Very Long Track Title That Exceeds Console Column Width"
    repl = _track(title="Matched Song", video_id="atv99999999", duration_s=199, video_type="MUSIC_VIDEO_TYPE_ATV")
    rows = [
        _row(0, Action.REPLACE, title=long_title, replacement=repl, confidence=0.93),
        _row(1, Action.REPLACE, title="Second", replacement=repl, confidence=0.91),
        _row(2, Action.REMOVE_DUP, title="Dup Video", reason="already in playlist"),
        _row(3, Action.KEEP_VIDEO, title="Low Conf", confidence=0.72),
        _row(4, Action.NO_MATCH, title="Obscure"),
        _row(5, Action.KEEP_SONG, title="Original Song", classification="song"),
    ]
    out = render_table(rows, "My Playlist")
    lines = out.splitlines()

    assert "My Playlist" in lines[0]
    # Header + separator + 6 rows + footer (counts + final length)
    assert len(lines) >= 10
    assert long_title not in out  # truncated in console table
    assert "replace: 2" in out
    assert "remove-duplicate-video: 1" in out
    assert "keep-video: 1" in out
    assert "no-match: 1" in out
    assert "keep-song: 1" in out
    assert "final length 6 -> 5" in out


def test_table_final_length_skips_null_video_id():
    repl = _track(title="Matched", video_id="atv1", video_type="MUSIC_VIDEO_TYPE_ATV")
    rows = [
        _row(0, Action.KEEP_SONG, title="Song", video_id="atv0", classification="song"),
        _row(1, Action.REPLACE, title="Video", video_id="omv1", replacement=repl, confidence=0.95),
        _row(2, Action.REMOVE_DUP, title="Dup", video_id="omv2"),
        _row(3, Action.KEEP_VIDEO, title="Unavailable", video_id=None, classification="other"),
    ]
    out = render_table(rows, "Nulls Playlist")
    expected_final = len(final_video_ids(rows))
    assert expected_final == 2
    assert f"final length 4 -> {expected_final}" in out


def test_write_html_self_contained_and_escaped(tmp_path):
    repl = _track(title="Clean Song", artists=["Artist B"], video_id="atv999", duration_s=199, video_type="MUSIC_VIDEO_TYPE_ATV")
    rows = [
        _row(0, Action.REPLACE, title='Track <script>alert(1)</script>', artists=["Artist A"], video_id="omv111", replacement=repl, confidence=0.95),
        _row(1, Action.KEEP_SONG, title="Original Song", video_id="atv222", classification="song"),
    ]
    out_html = tmp_path / "preview-PL1.html"
    write_html(rows, 'My <Playlist>', out_html)

    html_text = out_html.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_text.lower()
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
    assert "My &lt;Playlist&gt;" in html_text
    assert "https://music.youtube.com/watch?v=omv111" in html_text
    assert "https://music.youtube.com/watch?v=atv999" in html_text
    assert "final length 2 -&gt; 2" in html_text or "final length 2 &rarr; 2" in html_text or "final length 2 -> 2" in html_text
