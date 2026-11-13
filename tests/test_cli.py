import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ytm_clean.models import Track


class FakeYtm:
    def __init__(self, playlists=None, searches=None, fail_create_for=None):
        self.playlists = playlists or {}
        self.searches = searches or {}
        self.fail_create_for = set(fail_create_for or ())
        self.write_calls = []
        self.create_calls = []
        self.deleted = []
        self._counter = 0

    def read_playlist(self, pid: str):
        if pid not in self.playlists:
            raise RuntimeError(f"Playlist not found: {pid}")
        meta, tracks = self.playlists[pid]
        return dict(meta), list(tracks)

    def search_songs(self, query: str):
        return list(self.searches.get(query, []))

    def create_playlist(self, title: str, description: str, privacy: str, video_ids: list[str]) -> str:
        self.write_calls.append(("create_playlist", title, list(video_ids)))
        for prefix in self.fail_create_for:
            if title.startswith(prefix):
                raise RuntimeError(f"Simulated write failure for {title}")
        self._counter += 1
        new_id = f"NEW_{self._counter}"
        self.create_calls.append((new_id, title, description, privacy, list(video_ids)))
        return new_id

    def add_items(self, pid: str, video_ids: list[str]) -> None:
        self.write_calls.append(("add_items", pid, list(video_ids)))

    def remove_items(self, pid: str, videos) -> None:
        self.write_calls.append(("remove_items", pid, list(videos)))

    def delete_playlist(self, pid: str) -> None:
        self.write_calls.append(("delete_playlist", pid))
        self.deleted.append(pid)


def _sample_playlists():
    omv = Track("vid_omv", "set1", "Alpha Song (Official Video)", ["Artist A"], 200, "MUSIC_VIDEO_TYPE_OMV")
    atv = Track("vid_atv", "set2", "Beta Song", ["Artist B"], 180, "MUSIC_VIDEO_TYPE_ATV")
    unmatched = Track("vid_obscure", "set3", "Obscure Jam", ["Nobody"], 210, "MUSIC_VIDEO_TYPE_UGC")
    song_match = Track("song_alpha", None, "Alpha Song", ["Artist A"], 200, "MUSIC_VIDEO_TYPE_ATV")

    playlists = {
        "PL1": (
            {"id": "PL1", "title": "First Mix", "description": "desc1", "privacy": "PRIVATE", "owned": True},
            [omv, atv, unmatched],
        ),
        "PL2": (
            {"id": "PL2", "title": "Second Mix", "description": "desc2", "privacy": "UNLISTED", "owned": True},
            [omv],
        ),
        "PL_CLEAN": (
            {"id": "PL_CLEAN", "title": "Clean Mix", "description": "", "privacy": "PRIVATE", "owned": True},
            [atv],
        ),
        "PL_UNOWNED": (
            {"id": "PL_UNOWNED", "title": "Someone Else", "description": "", "privacy": "PUBLIC", "owned": False},
            [omv],
        ),
    }
    searches = {"alpha song Artist A": [song_match]}
    return playlists, searches


def _patch_ytm(monkeypatch, fake: FakeYtm):
    import ytm_clean.cli as cli

    monkeypatch.setattr(cli, "Ytm", lambda auth_path="browser.json": fake)


def test_dry_run_zero_writes(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)

    rc = main(["PL1", "--out", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert fake.write_calls == []
    assert (tmp_path / "preview-PL1.csv").exists()
    assert "dry run" in out.lower()
    assert "nothing written" in out.lower()


def test_apply_wrong_confirmation_zero_writes(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "yes")

    rc = main(["PL1", "--out", str(tmp_path), "--apply"])
    assert rc == 1
    assert fake.write_calls == []
    assert (tmp_path / "preview-PL1.csv").exists()


def test_apply_correct_confirmation_creates(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")

    rc = main(["PL1", "--out", str(tmp_path), "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert len(fake.create_calls) == 1
    new_id, title, _, _, video_ids = fake.create_calls[0]
    assert title == "First Mix [ytm-clean]"
    assert video_ids == ["song_alpha", "vid_atv", "vid_obscure"]
    assert f"https://music.youtube.com/playlist?list={new_id}" in out
    assert "Obscure Jam" in out


def test_all_previews_before_prompt(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)

    seen_before_prompt = []

    def fake_input(prompt=""):
        seen_before_prompt.append(capsys.readouterr().out)
        assert "REBUILD 2" in prompt
        return "REBUILD 2"

    monkeypatch.setattr("builtins.input", fake_input)

    rc = main(["PL1", "PL2", "--out", str(tmp_path), "--apply"])
    assert rc == 0
    assert len(seen_before_prompt) == 1
    pre_prompt = seen_before_prompt[0]
    assert "Playlist: First Mix" in pre_prompt
    assert "Playlist: Second Mix" in pre_prompt
    assert pre_prompt.index("Playlist: First Mix") < pre_prompt.index("Playlist: Second Mix")
    assert "2 playlists, 2 replacements, 0 duplicate removals" in pre_prompt
    assert len(fake.create_calls) == 2


def test_one_playlist_fails_others_continue(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")

    rc = main(["LM", "PL1", "--out", str(tmp_path), "--apply"])
    captured = capsys.readouterr()

    assert rc == 2
    assert not (tmp_path / "preview-LM.csv").exists()
    assert (tmp_path / "preview-PL1.csv").exists()
    assert len(fake.create_calls) == 1
    assert "LM" in captured.err

    # Also verify write-phase failure continues remaining playlists and returns 2
    fake2 = FakeYtm(playlists, searches, fail_create_for={"First Mix"})
    _patch_ytm(monkeypatch, fake2)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 2")

    rc2 = main(["PL1", "PL2", "--out", str(tmp_path / "run2"), "--apply"])
    captured2 = capsys.readouterr()
    assert rc2 == 2
    assert len(fake2.create_calls) == 1
    assert fake2.create_calls[0][1] == "Second Mix [ytm-clean]"
    assert "NEW_1" in captured2.out
    assert "PL1" in captured2.err


def test_non_interactive_stdin_aborts(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr(sys, "stdin", io.StringIO("REBUILD 1\n"))

    rc = main(["PL1", "--out", str(tmp_path), "--apply"])
    assert rc == 1
    assert fake.write_calls == []


def test_skips_playlist_with_zero_changes(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")

    rc = main(["PL_CLEAN", "PL1", "--out", str(tmp_path), "--apply"])
    assert rc == 0
    assert len(fake.create_calls) == 1
    assert fake.create_calls[0][1] == "First Mix [ytm-clean]"

    # All clean -> no prompt needed, zero writes
    fake2 = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake2)
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("Should not prompt when 0 actionable"))
    rc2 = main(["PL_CLEAN", "--out", str(tmp_path / "clean")])
    assert rc2 == 0
    rc3 = main(["PL_CLEAN", "--out", str(tmp_path / "clean"), "--apply"])
    assert rc3 == 0
    assert fake2.write_calls == []


def test_out_of_scope_refused(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)

    rc = main(["PL_UNOWNED", "--out", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert not (tmp_path / "preview-PL_UNOWNED.csv").exists()
    assert "PL_UNOWNED" in captured.err


def test_rollback_and_restore(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")

    assert main(["PL1", "--out", str(tmp_path), "--apply"]) == 0
    capsys.readouterr()

    assert main(["--rollback", "PL1", "--out", str(tmp_path)]) == 0
    rb_out = capsys.readouterr().out
    assert "https://music.youtube.com/playlist?list=PL1" in rb_out
    assert "NEW_1" in rb_out

    snap = next(tmp_path.glob("snapshot-PL1-*.json"))
    assert main(["--restore-from", str(snap), "--out", str(tmp_path)]) == 0
    res_out = capsys.readouterr().out
    assert "NEW_2" in res_out


def test_duplicate_ids_and_resume_via_cli(monkeypatch, tmp_path):
    from ytm_clean.cli import main

    omv = Track("vid_omv", "s1", "Alpha Song (Official Video)", ["Artist A"], 200, "MUSIC_VIDEO_TYPE_OMV")
    atv = Track("vid_atv", "s2", "Beta Song", ["Artist B"], 180, "MUSIC_VIDEO_TYPE_ATV")
    song_match = Track("song_alpha", None, "Alpha Song", ["Artist A"], 200, "MUSIC_VIDEO_TYPE_ATV")

    playlists = {
        "PL_DUP": (
            {"id": "PL_DUP", "title": "Dup Mix", "description": "", "privacy": "PRIVATE", "owned": True},
            [atv, omv, atv],
        )
    }
    fake = FakeYtm(playlists, {"alpha song Artist A": [song_match]})
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")

    rc = main(["PL_DUP", "--out", str(tmp_path), "--apply"])
    assert rc == 0
    assert fake.create_calls[0][4] == ["vid_atv", "song_alpha", "vid_atv"]

    # Second --apply run finds completed state and makes zero additional writes
    writes_before = len(fake.write_calls)
    rc2 = main(["PL_DUP", "--out", str(tmp_path), "--apply"])
    assert rc2 == 0
    assert len(fake.write_calls) == writes_before


def test_python_m_ytm_clean_help():
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "ytm_clean", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--apply" in proc.stdout
    assert "--rollback" in proc.stdout
    assert "--yes-i-mean-it" not in proc.stdout


def test_delete_new_without_rollback_rejected(capsys):
    from ytm_clean.cli import main

    rc = main(["--delete-new"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "--rollback" in err


def test_rollback_delete_new_eof_aborts_cleanly(monkeypatch, tmp_path, capsys):
    from ytm_clean.cli import main

    playlists, searches = _sample_playlists()
    fake = FakeYtm(playlists, searches)
    _patch_ytm(monkeypatch, fake)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "REBUILD 1")
    assert main(["PL1", "--out", str(tmp_path), "--apply"]) == 0
    capsys.readouterr()

    def _raise_eof(_prompt=""):
        raise EOFError()

    monkeypatch.setattr("builtins.input", _raise_eof)
    rc = main(["--rollback", "PL1", "--delete-new", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Delete cancelled." in out
    assert fake.deleted == []
