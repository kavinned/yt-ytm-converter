import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ytm_clean.client import assert_in_scope, playlist_url
from ytm_clean.models import Action, PlanRow, Track

CHUNK_SIZE = 100


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _target_video_id(row: PlanRow) -> str | None:
    if row.action == Action.REMOVE_DUP:
        return None
    if row.action == Action.REPLACE:
        return row.replacement.video_id if row.replacement else None
    return row.track.video_id


def final_video_ids(rows: list[PlanRow]) -> list[str]:
    """Resolve the ordered list of target video IDs from plan rows, preserving duplicates."""
    ids: list[str] = []
    for row in rows:
        vid = _target_video_id(row)
        if vid:
            ids.append(vid)
    return ids


def write_snapshot(
    pid: str, meta: dict[str, Any], tracks: list[Track], out_dir: Path | str = "out"
) -> Path:
    """Persist a full JSON snapshot of the source playlist before any write operation."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S%fZ")
    path = Path(out_dir) / f"snapshot-{pid}-{ts}.json"
    payload = {
        "playlist_id": pid,
        "created_at": now.isoformat(),
        "meta": meta,
        "tracks": [asdict(t) for t in tracks],
    }
    _write_json(path, payload)
    return path


def _add_in_chunks(
    client: Any,
    new_id: str,
    ids: list[str],
    state_path: Path,
    expected_ids: list[str],
    done_count: int,
) -> None:
    for i in range(0, len(ids), CHUNK_SIZE):
        chunk = ids[i : i + CHUNK_SIZE]
        client.add_items(new_id, chunk)
        done_count += len(chunk)
        _write_json(
            state_path,
            {"new_id": new_id, "expected_ids": expected_ids, "done_count": done_count},
        )


def rebuild(
    client: Any,
    pid: str,
    meta: dict[str, Any],
    rows: list[PlanRow],
    out_dir: Path | str = "out",
) -> str:
    """Rebuild the planned playlist into a new playlist, with snapshot and crash resume."""
    assert_in_scope(pid, meta)
    out_path = Path(out_dir)
    state_path = out_path / f"state-{pid}.json"

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        new_id: str = state["new_id"]
        expected_ids: list[str] = state["expected_ids"]
        done_count: int = state["done_count"]

        if done_count >= len(expected_ids):
            print(f"Already complete: {playlist_url(new_id)}")
            return new_id

        _, existing = client.read_playlist(new_id)
        actual_ids = [t.video_id for t in existing if t.video_id]
        if len(actual_ids) > len(expected_ids) or expected_ids[: len(actual_ids)] != actual_ids:
            raise RuntimeError(
                f"Playlist {new_id} contents diverge from expected state; aborting resume"
            )

        done_count = len(actual_ids)
        missing = expected_ids[done_count:]
        if not missing:
            _write_json(
                state_path,
                {"new_id": new_id, "expected_ids": expected_ids, "done_count": done_count},
            )
            print(f"Already complete: {playlist_url(new_id)}")
            return new_id

        _add_in_chunks(client, new_id, missing, state_path, expected_ids, done_count)
        return new_id

    write_snapshot(pid, meta, [r.track for r in rows], out_path)
    for r in rows:
        if r.action != Action.REMOVE_DUP and not _target_video_id(r):
            print(f"Skipped null video_id at index {r.index}: {r.track.title}")

    expected_ids = final_video_ids(rows)
    orig_title = meta.get("title") or pid
    new_title = f"{orig_title} [ytm-clean]"
    description = meta.get("description") or ""
    privacy = meta.get("privacy") or "PRIVATE"

    first, rest = expected_ids[:CHUNK_SIZE], expected_ids[CHUNK_SIZE:]
    new_id = client.create_playlist(new_title, description, privacy, first)
    done_count = len(first)
    _write_json(
        state_path,
        {"new_id": new_id, "expected_ids": expected_ids, "done_count": done_count},
    )
    if rest:
        _add_in_chunks(client, new_id, rest, state_path, expected_ids, done_count)
    return new_id


def rollback(
    pid: str,
    out_dir: Path | str = "out",
    *,
    client: Any = None,
    delete_new: bool = False,
    confirm: Callable[[str], str] | None = None,
) -> str:
    """Report original (untouched) URL and new playlist ID; optionally delete the new playlist."""
    state_path = Path(out_dir) / f"state-{pid}.json"
    new_id = (
        json.loads(state_path.read_text(encoding="utf-8")).get("new_id")
        if state_path.exists()
        else None
    )
    lines = [
        f"Original playlist (untouched): {playlist_url(pid)}",
        f"New playlist ID: {new_id or '(none)'}",
    ]
    if delete_new and new_id and client is not None:
        prompt_fn = confirm or input
        try:
            answer = prompt_fn(f"Type {new_id} to delete new playlist: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer == new_id:
            client.delete_playlist(new_id)
            state_path.unlink(missing_ok=True)
            lines.append(f"Deleted new playlist: {new_id}")
        else:
            lines.append("Delete cancelled.")

    msg = "\n".join(lines)
    print(msg)
    return msg


def restore_from_snapshot(
    client: Any, snapshot_path: Path | str, *, title: str | None = None
) -> str:
    """Recreate a playlist in exact order from a saved JSON snapshot."""
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    video_ids = [t["video_id"] for t in data.get("tracks", []) if t.get("video_id")]
    restore_title = title or meta.get("title") or data.get("playlist_id") or "Restored Playlist"
    description = meta.get("description") or ""
    privacy = meta.get("privacy") or "PRIVATE"

    first, rest = video_ids[:CHUNK_SIZE], video_ids[CHUNK_SIZE:]
    new_id = client.create_playlist(restore_title, description, privacy, first)
    for i in range(0, len(rest), CHUNK_SIZE):
        client.add_items(new_id, rest[i : i + CHUNK_SIZE])
    return new_id
