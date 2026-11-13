import json
from pathlib import Path

import pytest
from ytmusicapi.exceptions import YTMusicServerError, YTMusicUserError

from ytm_clean.client import ScopeError, Ytm, assert_in_scope, parse_playlist_id
from ytm_clean.models import Track
from ytm_clean.retry import call_with_retry

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeHttpError(Exception):
    def __init__(self, status_code: int, message: str = "http error"):
        super().__init__(message)
        self.status_code = status_code


class _FakeApi:
    def __init__(self, playlist_data=None, search_data=None):
        self.playlist_data = playlist_data or {}
        self.search_data = search_data or []
        self.calls: list[tuple[str, tuple, dict]] = []

    def get_playlist(self, playlistId: str, limit=None):
        self.calls.append(("get_playlist", (playlistId,), {"limit": limit}))
        return self.playlist_data

    def search(self, query: str, filter: str | None = None):
        self.calls.append(("search", (query,), {"filter": filter}))
        return self.search_data

    def create_playlist(self, title: str, description: str, privacy_status: str = "PRIVATE", video_ids=None):
        self.calls.append(("create_playlist", (title, description, privacy_status, video_ids), {}))
        return "PL_NEW_123"

    def add_playlist_items(self, playlistId: str, videoIds=None, duplicates: bool = False):
        self.calls.append(("add_playlist_items", (playlistId, videoIds), {"duplicates": duplicates}))
        return "STATUS_SUCCEEDED"

    def remove_playlist_items(self, playlistId: str, videos):
        self.calls.append(("remove_playlist_items", (playlistId, videos), {}))
        return "STATUS_SUCCEEDED"

    def delete_playlist(self, playlistId: str):
        self.calls.append(("delete_playlist", (playlistId,), {}))
        return "STATUS_SUCCEEDED"


def test_parse_url():
    assert parse_playlist_id("https://music.youtube.com/playlist?list=PLabc") == "PLabc"
    assert parse_playlist_id("https://www.youtube.com/playlist?list=PLxyz&si=123") == "PLxyz"
    assert parse_playlist_id("PLbare_123") == "PLbare_123"


def test_parse_bad():
    for bad in [
        "",
        "   ",
        "https://music.youtube.com/watch?v=123",
        "not a valid id",
        "..\\..\\evil",
        "PL..evil",
        "https://music.youtube.com/playlist?list=../../evil",
        "https://music.youtube.com/playlist?list=PLa/b",
    ]:
        with pytest.raises(ValueError):
            parse_playlist_id(bad)


def test_assert_in_scope():
    for pid in [
        "LM",
        "RDCLAK5uy_abc",
        "OLAK5uy_xyz",
        "MPRE_123",
        "SE",
        "VLLM",
        "VLSE",
        "VLRDCLAK5uy_abc",
        "VLOLAK5uy_xyz",
        "VLMPRE_123",
    ]:
        with pytest.raises(ScopeError):
            assert_in_scope(pid, {"owned": True})

    with pytest.raises(ScopeError):
        assert_in_scope("PLvalid123", {"owned": False})

    assert_in_scope("PLvalid123", {"owned": True})
    assert_in_scope("VLPLvalid123", {"owned": True})


def test_retry_then_ok():
    sleeps: list[float] = []
    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise _FakeHttpError(429, "rate limited")
        return "ok"

    result = call_with_retry(flaky, attempts=5, base=1.0, sleep=sleeps.append)
    assert result == "ok"
    assert len(sleeps) == 2


def test_retry_gives_up():
    sleeps: list[float] = []

    def always_fail():
        raise YTMusicServerError("server down")

    with pytest.raises(YTMusicServerError):
        call_with_retry(always_fail, attempts=5, base=0.5, sleep=sleeps.append)

    assert len(sleeps) == 4


def test_retry_does_not_retry_non_retryable():
    sleeps: list[float] = []

    def bad_user():
        raise YTMusicUserError("bad request")

    with pytest.raises(YTMusicUserError):
        call_with_retry(bad_user, attempts=5, base=0.5, sleep=sleeps.append)

    assert sleeps == []


def test_read_maps_fields():
    data = json.loads((FIXTURES / "playlist_mixed.json").read_text(encoding="utf-8"))
    api = _FakeApi(playlist_data=data)
    ytm = Ytm(api=api)

    meta, tracks = ytm.read_playlist("PLtest123")

    assert meta == {
        "id": "PLtest123",
        "title": "Test Mixed Playlist",
        "description": "Sample playlist for tests",
        "privacy": "PRIVATE",
        "owned": True,
    }
    assert api.calls == [("get_playlist", ("PLtest123",), {"limit": None})]
    assert len(tracks) == 4
    assert tracks[0] == Track(
        video_id="atv_001",
        set_video_id="set_001",
        title="Studio Song",
        artists=["Artist One"],
        duration_s=210,
        video_type="MUSIC_VIDEO_TYPE_ATV",
    )
    assert tracks[1].video_type == "MUSIC_VIDEO_TYPE_OMV"
    assert tracks[2].video_type == "MUSIC_VIDEO_TYPE_UGC"


def test_unavailable_entry_kept():
    data = json.loads((FIXTURES / "playlist_mixed.json").read_text(encoding="utf-8"))
    ytm = Ytm(api=_FakeApi(playlist_data=data))

    _, tracks = ytm.read_playlist("PLtest123")

    assert tracks[3] == Track(
        video_id=None,
        set_video_id="set_004",
        title="Unavailable Episode",
        artists=[],
        duration_s=None,
        video_type=None,
    )


def test_search_songs_memoized():
    search_data = json.loads((FIXTURES / "search_songs.json").read_text(encoding="utf-8"))
    api = _FakeApi(search_data=search_data)
    ytm = Ytm(api=api)

    res1 = ytm.search_songs("Hit Track Artist Two")
    res2 = ytm.search_songs("Hit Track Artist Two")

    assert res1 == res2
    assert len(res1) == 2
    assert res1[0].video_id == "song_repl_002"
    assert res1[0].artists == ["Artist Two"]
    assert res1[0].duration_s == 194
    assert len(api.calls) == 1
    assert api.calls[0] == ("search", ("Hit Track Artist Two",), {"filter": "songs"})


def test_add_items_chunks_of_100():
    api = _FakeApi()
    ytm = Ytm(api=api)
    ids = [f"v{i}" for i in range(205)]

    ytm.add_items("PL_NEW_123", ids)

    assert len(api.calls) == 3
    assert len(api.calls[0][1][1]) == 100
    assert len(api.calls[1][1][1]) == 100
    assert len(api.calls[2][1][1]) == 5
    assert all(c[2] == {"duplicates": True} for c in api.calls)


def test_create_playlist_chunks_over_100():
    api = _FakeApi()
    ytm = Ytm(api=api)
    ids = [f"v{i}" for i in range(150)]

    new_id = ytm.create_playlist("My List", "Desc", "PRIVATE", ids)

    assert new_id == "PL_NEW_123"
    assert api.calls[0][0] == "create_playlist"
    assert len(api.calls[0][1][3]) == 100
    assert api.calls[1][0] == "add_playlist_items"
    assert len(api.calls[1][1][1]) == 50


def test_delete_playlist():
    api = _FakeApi()
    ytm = Ytm(api=api)

    ytm.delete_playlist("PL_NEW_123")

    assert api.calls == [("delete_playlist", ("PL_NEW_123",), {})]


def test_add_items_raises_on_failed_dict_status():
    api = _FakeApi()
    api.add_playlist_items = lambda pid, videoIds=None, duplicates=False: {"status": "STATUS_FAILED"}
    ytm = Ytm(api=api)

    with pytest.raises(RuntimeError, match="add_playlist_items failed"):
        ytm.add_items("PL_NEW_123", ["v1", "v2"])

    api.add_playlist_items = lambda pid, videoIds=None, duplicates=False: {"status": "STATUS_SUCCEEDED"}
    ytm.add_items("PL_NEW_123", ["v1"])


def test_create_playlist_raises_on_error_dict():
    api = _FakeApi()
    api.create_playlist = lambda *args, **kwargs: {"status": "ERROR", "message": "denied"}
    ytm = Ytm(api=api)

    with pytest.raises(RuntimeError, match="create_playlist failed"):
        ytm.create_playlist("My List", "Desc", "PRIVATE", ["v1"])

    api.create_playlist = lambda *args, **kwargs: {"id": "PL_DICT_1"}
    assert ytm.create_playlist("My List", "Desc", "PRIVATE", ["v1"]) == "PL_DICT_1"
