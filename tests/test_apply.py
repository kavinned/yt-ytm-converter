import json
from pathlib import Path

import pytest

from ytm_clean.apply import (
    final_video_ids,
    rebuild,
    restore_from_snapshot,
    rollback,
    write_snapshot,
)
from ytm_clean.client import ScopeError, Ytm
from ytm_clean.models import Action, PlanRow, Track


def _track(
    video_id: str | None,
    title: str = "T",
    video_type: str | None = "MUSIC_VIDEO_TYPE_ATV",
    set_video_id: str | None = None,
) -> Track:
    return Track(
        video_id=video_id,
        set_video_id=set_video_id or (f"sv_{video_id}" if video_id else None),
        title=title,
        artists=["Artist"],
        duration_s=180,
        video_type=video_type,
    )


def _row(
    idx: int,
    action: Action,
    vid: str | None,
    repl_vid: str | None = None,
) -> PlanRow:
    src = _track(vid, title=f"Src{idx}")
    repl = _track(repl_vid, title=f"Repl{idx}") if repl_vid is not None else None
    return PlanRow(
        index=idx,
        track=src,
        classification="song" if action == Action.KEEP_SONG else "video",
        action=action,
        replacement=repl,
        confidence=0.95 if repl else None,
        reason="test",
    )


class FakeYtm:
    def __init__(
        self,
        playlists: dict[str, tuple[dict, list[Track]]] | None = None,
        *,
        on_create: object = None,
        fail_on_add_call: int | None = None,
        commit_before_fail: bool = False,
        commit_prefix_on_fail: int | None = None,
    ) -> None:
        self.playlists: dict[str, tuple[dict, list[Track]]] = {
            pid: (dict(meta), list(tracks))
            for pid, (meta, tracks) in (playlists or {}).items()
        }
        self.calls: list[tuple] = []
        self._next_id = 1
        self._on_create = on_create
        self._fail_on_add_call = fail_on_add_call
        self._commit_before_fail = commit_before_fail
        self._commit_prefix_on_fail = commit_prefix_on_fail
        self._add_call_count = 0

    @property
    def write_calls(self) -> list[tuple]:
        write_ops = {"create_playlist", "add_items", "remove_items", "edit_playlist", "delete_playlist"}
        return [c for c in self.calls if c[0] in write_ops]

    def read_playlist(self, pid: str) -> tuple[dict, list[Track]]:
        self.calls.append(("read_playlist", pid))
        meta, tracks = self.playlists[pid]
        return dict(meta), list(tracks)

    def create_playlist(
        self, title: str, description: str, privacy: str, video_ids: list[str]
    ) -> str:
        if callable(self._on_create):
            self._on_create()
        self.calls.append(("create_playlist", title, description, privacy, list(video_ids)))
        new_id = f"PL_NEW_{self._next_id}"
        self._next_id += 1
        meta = {
            "id": new_id,
            "title": title,
            "description": description,
            "privacy": privacy,
            "owned": True,
        }
        tracks = [_track(vid, title=vid) for vid in video_ids]
        self.playlists[new_id] = (meta, tracks)
        return new_id

    def add_items(self, pid: str, video_ids: list[str]) -> None:
        self._add_call_count += 1
        self.calls.append(("add_items", pid, list(video_ids)))
        if self._fail_on_add_call == self._add_call_count:
            if self._commit_prefix_on_fail is not None:
                _, tracks = self.playlists[pid]
                tracks.extend(_track(vid, title=vid) for vid in video_ids[: self._commit_prefix_on_fail])
            elif self._commit_before_fail:
                _, tracks = self.playlists[pid]
                tracks.extend(_track(vid, title=vid) for vid in video_ids)
            raise RuntimeError("simulated network crash mid-add_items")
        _, tracks = self.playlists[pid]
        tracks.extend(_track(vid, title=vid) for vid in video_ids)

    def remove_items(self, pid: str, videos: list[dict]) -> None:
        self.calls.append(("remove_items", pid, list(videos)))

    def edit_playlist(self, *args, **kwargs) -> None:
        self.calls.append(("edit_playlist", args, kwargs))

    def delete_playlist(self, pid: str) -> None:
        self.calls.append(("delete_playlist", pid))
        self.playlists.pop(pid, None)


def test_final_ids_order() -> None:
    rows = [
        _row(0, Action.KEEP_SONG, "s1"),
        _row(1, Action.REPLACE, "v2", repl_vid="s2"),
        _row(2, Action.REMOVE_DUP, "v3", repl_vid="s1"),
        _row(3, Action.KEEP_VIDEO, "v4"),
        _row(4, Action.NO_MATCH, "v5"),
        _row(5, Action.KEEP_VIDEO, None),
    ]
    assert final_video_ids(rows) == ["s1", "s2", "v4", "v5"]


def test_duplicate_video_id_preserved(tmp_path: Path) -> None:
    rows = [
        _row(0, Action.KEEP_SONG, "a"),
        _row(1, Action.KEEP_SONG, "b"),
        _row(2, Action.KEEP_SONG, "a"),
    ]
    assert final_video_ids(rows) == ["a", "b", "a"]

    meta = {"id": "PL1", "title": "My Mix", "description": "Desc", "privacy": "UNLISTED", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    new_meta, new_tracks = fake.playlists[new_id]
    assert [t.video_id for t in new_tracks] == ["a", "b", "a"]
    assert new_meta["title"] == "My Mix [ytm-clean]"
    assert new_meta["description"] == "Desc"
    assert new_meta["privacy"] == "UNLISTED"


def test_snapshot_written_before_create(tmp_path: Path) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a"), _row(1, Action.REPLACE, "v1", repl_vid="s1")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    snapshots_at_create: list[Path] = []

    def check_snapshot() -> None:
        snapshots_at_create.extend(tmp_path.glob("snapshot-PL1-*.json"))

    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])}, on_create=check_snapshot)
    rebuild(fake, "PL1", meta, rows, tmp_path)

    assert len(snapshots_at_create) == 1
    data = json.loads(snapshots_at_create[0].read_text(encoding="utf-8"))
    assert data["playlist_id"] == "PL1"
    assert data["meta"]["title"] == "Orig"
    assert [t["video_id"] for t in data["tracks"]] == ["a", "v1"]
    assert [t["set_video_id"] for t in data["tracks"]] == ["sv_a", "sv_v1"]


def test_original_never_mutated(tmp_path: Path) -> None:
    orig_tracks = [_track("a"), _track("v1", video_type="MUSIC_VIDEO_TYPE_OMV")]
    rows = [
        PlanRow(0, orig_tracks[0], "song", Action.KEEP_SONG, None, None, "already song"),
        PlanRow(1, orig_tracks[1], "video", Action.REPLACE, _track("s1"), 0.99, "match"),
    ]
    meta = {"id": "PL1", "title": "Orig", "description": "D", "privacy": "PUBLIC", "owned": True}
    fake = FakeYtm({"PL1": (meta, orig_tracks)})

    rebuild(fake, "PL1", meta, rows, tmp_path)

    assert not any(c[0] in {"remove_items", "edit_playlist", "delete_playlist"} for c in fake.calls)
    assert fake.playlists["PL1"][1] == orig_tracks


def test_resume_after_crash(tmp_path: Path) -> None:
    vids = [f"v{i}" for i in range(250)]
    rows = [_row(i, Action.KEEP_SONG, vid) for i, vid in enumerate(vids)]
    meta = {"id": "PL1", "title": "Big", "description": "", "privacy": "PRIVATE", "owned": True}

    fake1 = FakeYtm({"PL1": (meta, [r.track for r in rows])}, fail_on_add_call=2)
    with pytest.raises(RuntimeError, match="simulated network crash"):
        rebuild(fake1, "PL1", meta, rows, tmp_path)

    state_path = tmp_path / "state-PL1.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    new_id = state["new_id"]
    assert state["expected_ids"] == vids
    assert state["done_count"] == 200
    assert [t.video_id for t in fake1.playlists[new_id][1]] == vids[:200]

    fake1._fail_on_add_call = None
    resumed_id = rebuild(fake1, "PL1", meta, rows, tmp_path)
    assert resumed_id == new_id
    assert [t.video_id for t in fake1.playlists[new_id][1]] == vids

    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["done_count"] == 250


def test_resume_when_server_committed_last_chunk_before_crash(tmp_path: Path) -> None:
    vids = [f"v{i}" for i in range(150)]
    rows = [_row(i, Action.KEEP_SONG, vid) for i, vid in enumerate(vids)]
    meta = {"id": "PL1", "title": "Lag", "description": "", "privacy": "PRIVATE", "owned": True}

    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])}, fail_on_add_call=1, commit_before_fail=True)
    with pytest.raises(RuntimeError):
        rebuild(fake, "PL1", meta, rows, tmp_path)

    fake._fail_on_add_call = None
    calls_before = len(fake.write_calls)
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    assert len(fake.write_calls) == calls_before
    assert [t.video_id for t in fake.playlists[new_id][1]] == vids


def test_rerun_complete_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a"), _row(1, Action.KEEP_SONG, "b")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})

    first_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    write_count_after_first = len(fake.write_calls)
    assert write_count_after_first == 1

    second_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    assert second_id == first_id
    assert len(fake.write_calls) == write_count_after_first
    out = capsys.readouterr().out
    assert f"https://music.youtube.com/playlist?list={first_id}" in out


def test_restore_from_snapshot(tmp_path: Path) -> None:
    meta = {"id": "PL1", "title": "My List", "description": "Saved", "privacy": "PRIVATE", "owned": True}
    tracks = [_track("a"), _track(None, title="Unavailable"), _track("b"), _track("a")]
    snap = write_snapshot("PL1", meta, tracks, tmp_path)

    fake = FakeYtm()
    restored_id = restore_from_snapshot(fake, snap)
    restored_meta, restored_tracks = fake.playlists[restored_id]
    assert restored_meta["title"] == "My List"
    assert restored_meta["description"] == "Saved"
    assert restored_meta["privacy"] == "PRIVATE"
    assert [t.video_id for t in restored_tracks] == ["a", "b", "a"]


@pytest.mark.parametrize(
    "pid,owned",
    [
        ("LM", True),
        ("RDCLAK1", True),
        ("OLAK5uy_x", True),
        ("MPRE123", True),
        ("SE", True),
        ("PL_OTHER", False),
    ],
)
def test_refuse_out_of_scope(tmp_path: Path, pid: str, owned: bool) -> None:
    meta = {"id": pid, "title": "Bad", "description": "", "privacy": "PRIVATE", "owned": owned}
    rows = [_row(0, Action.KEEP_SONG, "a")]
    fake = FakeYtm({pid: (meta, [r.track for r in rows])})

    with pytest.raises(ScopeError):
        rebuild(fake, pid, meta, rows, tmp_path)

    assert fake.write_calls == []
    assert list(tmp_path.iterdir()) == []


def test_rollback_prints_urls_and_optional_delete(tmp_path: Path) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)

    msg = rollback("PL1", tmp_path)
    assert "https://music.youtube.com/playlist?list=PL1" in msg
    assert new_id in msg

    rollback("PL1", tmp_path, client=fake, delete_new=True, confirm=lambda _: new_id)
    assert new_id not in fake.playlists
    assert ("delete_playlist", new_id) in fake.calls
    assert not (tmp_path / "state-PL1.json").exists()


def test_rollback_cancelled_confirmation_does_nothing(tmp_path: Path) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)

    msg = rollback("PL1", tmp_path, client=fake, delete_new=True, confirm=lambda _: "wrong")
    assert "Delete cancelled." in msg
    assert new_id in fake.playlists
    assert (tmp_path / "state-PL1.json").exists()
    assert not any(c[0] == "delete_playlist" for c in fake.calls)


def test_rerun_after_rollback_delete_creates_fresh_playlist(tmp_path: Path) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a"), _row(1, Action.KEEP_SONG, "b")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})

    first_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    rollback("PL1", tmp_path, client=fake, delete_new=True, confirm=lambda _: first_id)

    second_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    assert second_id != first_id
    assert [t.video_id for t in fake.playlists[second_id][1]] == ["a", "b"]


def test_resume_partial_chunk_failure(tmp_path: Path) -> None:
    vids = [f"v{i}" for i in range(250)]
    rows = [_row(i, Action.KEEP_SONG, vid) for i, vid in enumerate(vids)]
    meta = {"id": "PL1", "title": "Partial", "description": "", "privacy": "PRIVATE", "owned": True}

    fake = FakeYtm(
        {"PL1": (meta, [r.track for r in rows])},
        fail_on_add_call=1,
        commit_prefix_on_fail=40,
    )
    with pytest.raises(RuntimeError, match="simulated network crash"):
        rebuild(fake, "PL1", meta, rows, tmp_path)

    state = json.loads((tmp_path / "state-PL1.json").read_text(encoding="utf-8"))
    new_id = state["new_id"]
    assert [t.video_id for t in fake.playlists[new_id][1]] == vids[:140]

    fake._fail_on_add_call = None
    fake._commit_prefix_on_fail = None
    resumed_id = rebuild(fake, "PL1", meta, rows, tmp_path)
    assert resumed_id == new_id
    assert [t.video_id for t in fake.playlists[new_id][1]] == vids


def test_resume_divergence_raises(tmp_path: Path) -> None:
    vids = [f"v{i}" for i in range(150)]
    rows = [_row(i, Action.KEEP_SONG, vid) for i, vid in enumerate(vids)]
    meta = {"id": "PL1", "title": "Drift", "description": "", "privacy": "PRIVATE", "owned": True}

    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])}, fail_on_add_call=1)
    with pytest.raises(RuntimeError):
        rebuild(fake, "PL1", meta, rows, tmp_path)

    state = json.loads((tmp_path / "state-PL1.json").read_text(encoding="utf-8"))
    new_id = state["new_id"]
    fake.playlists[new_id][1][0] = _track("TAMPERED")
    writes_before = len(fake.write_calls)

    fake._fail_on_add_call = None
    with pytest.raises(RuntimeError, match="diverge"):
        rebuild(fake, "PL1", meta, rows, tmp_path)
    assert len(fake.write_calls) == writes_before


def test_null_video_id_and_empty_replace_skipped_and_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        _row(0, Action.KEEP_SONG, "a"),
        _row(1, Action.KEEP_VIDEO, None),
        _row(2, Action.REPLACE, "v_orig", repl_vid=None),
        _row(3, Action.KEEP_SONG, "b"),
    ]
    assert final_video_ids(rows) == ["a", "b"]

    meta = {"id": "PL1", "title": "Nulls", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)

    out = capsys.readouterr().out
    assert [t.video_id for t in fake.playlists[new_id][1]] == ["a", "b"]
    assert "index 1" in out
    assert "index 2" in out


def test_add_in_chunks_does_not_advance_state_on_silent_api_failure(tmp_path: Path) -> None:
    vids = [f"v{i}" for i in range(250)]
    rows = [_row(i, Action.KEEP_SONG, vid) for i, vid in enumerate(vids)]
    meta = {"id": "PL1", "title": "SilentFail", "description": "", "privacy": "PRIVATE", "owned": True}

    class _RawApi:
        def __init__(self) -> None:
            self.created: list[str] = []
            self.add_calls = 0

        def get_playlist(self, playlistId: str, limit=None):
            return {
                "id": playlistId,
                "title": "SilentFail [ytm-clean]",
                "description": "",
                "privacy": "PRIVATE",
                "owned": True,
                "tracks": [{"videoId": v, "title": v} for v in self.created],
            }

        def create_playlist(self, title: str, description: str, privacy_status: str = "PRIVATE", video_ids=None):
            self.created.extend(video_ids or [])
            return "PL_NEW_RAW"

        def add_playlist_items(self, playlistId: str, videoIds=None, duplicates: bool = False):
            self.add_calls += 1
            if self.add_calls == 2:
                return {"status": "STATUS_FAILED"}
            self.created.extend(videoIds or [])
            return {"status": "STATUS_SUCCEEDED"}

    raw_api = _RawApi()
    client = Ytm(api=raw_api)

    with pytest.raises(RuntimeError, match="add_playlist_items failed"):
        rebuild(client, "PL1", meta, rows, tmp_path)

    state_path = tmp_path / "state-PL1.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["done_count"] == 200
    assert len(raw_api.created) == 200

    resumed_id = rebuild(client, "PL1", meta, rows, tmp_path)
    assert resumed_id == "PL_NEW_RAW"
    assert raw_api.created == vids
    assert json.loads(state_path.read_text(encoding="utf-8"))["done_count"] == 250


@pytest.mark.parametrize("exc_cls", [EOFError, KeyboardInterrupt])
def test_rollback_eof_and_keyboard_interrupt_abort_cleanly(
    tmp_path: Path, exc_cls: type[BaseException]
) -> None:
    rows = [_row(0, Action.KEEP_SONG, "a")]
    meta = {"id": "PL1", "title": "Orig", "description": "", "privacy": "PRIVATE", "owned": True}
    fake = FakeYtm({"PL1": (meta, [r.track for r in rows])})
    new_id = rebuild(fake, "PL1", meta, rows, tmp_path)

    def _raise(_prompt: str) -> str:
        raise exc_cls()

    msg = rollback("PL1", tmp_path, client=fake, delete_new=True, confirm=_raise)
    assert "Delete cancelled." in msg
    assert new_id in fake.playlists
    assert (tmp_path / "state-PL1.json").exists()
    assert not any(c[0] == "delete_playlist" for c in fake.calls)
