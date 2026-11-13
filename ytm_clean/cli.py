import argparse
import builtins
import sys
from pathlib import Path
from typing import Any

from ytm_clean.apply import rebuild, restore_from_snapshot, rollback
from ytm_clean.client import Ytm, assert_in_scope, parse_playlist_id, playlist_url
from ytm_clean.models import Action, PlanRow, Track
from ytm_clean.planner import build_plan, pick_unresolved
from ytm_clean.preview import counts, render_table, write_csv, write_html

_ORIG_INPUT = builtins.input


def _can_prompt() -> bool:
    if input is not _ORIG_INPUT or builtins.input is not _ORIG_INPUT:
        return True
    return bool(sys.stdin is not None and sys.stdin.isatty())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytm_clean",
        description="Replace video entries in YouTube Music playlists with catalog song versions.",
    )
    parser.add_argument("playlists", nargs="*", help="Playlist IDs or URLs")
    parser.add_argument("--auth", default="browser.json", help="Path to ytmusicapi auth JSON")
    parser.add_argument("--out", default="out", help="Output directory for CSV/snapshots/state")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rebuild playlists with changes after typed confirmation",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Interactively choose replacements for keep-video and no-match entries",
    )
    parser.add_argument(
        "--rollback",
        metavar="PID",
        help="Show original and rebuilt playlist info for PID",
    )
    parser.add_argument(
        "--delete-new",
        action="store_true",
        help="With --rollback, delete the rebuilt playlist after confirmation",
    )
    parser.add_argument(
        "--restore-from",
        metavar="FILE",
        help="Recreate a playlist from a saved snapshot JSON file",
    )
    return parser


def _run_rollback(args: argparse.Namespace) -> int:
    try:
        pid = parse_playlist_id(args.rollback)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.delete_new:
        if not _can_prompt():
            print("Aborted: non-interactive stdin cannot confirm --delete-new.", file=sys.stderr)
            return 1
        try:
            client = Ytm(args.auth)
        except Exception as exc:
            print(f"Auth error loading {args.auth}: {exc}", file=sys.stderr)
            return 1
        rollback(pid, args.out, client=client, delete_new=True, confirm=input)
    else:
        rollback(pid, args.out)
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    snap = Path(args.restore_from)
    if not snap.exists():
        print(f"Error: snapshot file not found: {snap}", file=sys.stderr)
        return 1
    try:
        client = Ytm(args.auth)
        new_id = restore_from_snapshot(client, snap)
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"Restored playlist: {playlist_url(new_id)}")
    return 0


def _plan_one(
    client: Any, raw_pid: str, out_dir: Path, *, pick: bool = False
) -> tuple[str, dict[str, Any], list[PlanRow]]:
    pid = parse_playlist_id(raw_pid)
    assert_in_scope(pid, {})
    print(f"Reading playlist {pid}...", file=sys.stderr, flush=True)
    meta, tracks = client.read_playlist(pid)
    assert_in_scope(pid, meta)

    is_tty = bool(sys.stderr is not None and sys.stderr.isatty())
    wrote_progress = False

    def _on_progress(done: int, total: int, track: Track) -> None:
        nonlocal wrote_progress
        wrote_progress = True
        msg = f"[{done}/{total}] Searching: {track.title[:45]}"
        if is_tty:
            print(f"\r{msg:<79}", end="", file=sys.stderr, flush=True)
        else:
            print(msg, file=sys.stderr, flush=True)

    rows = build_plan(tracks, client.search_songs, on_progress=_on_progress)
    if is_tty and wrote_progress:
        print(f"\r{' ' * 79}\r", end="", file=sys.stderr, flush=True)

    if pick:
        rows = pick_unresolved(rows, client.search_songs, input_fn=input)

    title = meta.get("title") or pid
    print(render_table(rows, title))
    csv_path = out_dir / f"preview-{pid}.csv"
    html_path = out_dir / f"preview-{pid}.html"
    write_csv(rows, csv_path)
    write_html(rows, title, html_path)
    print(f"Preview CSV written: {csv_path}")
    print(f"Preview HTML written: {html_path}")
    return pid, meta, rows


def _print_final_report(
    rebuilt: list[tuple[str, dict[str, Any], list[PlanRow], str]],
) -> None:
    if not rebuilt:
        return
    totals = {action: 0 for action in Action}
    unmatched: list[tuple[str, PlanRow]] = []
    for pid, meta, rows, _ in rebuilt:
        row_counts = counts(rows)
        for action, n in row_counts.items():
            totals[action] += n
        title = meta.get("title") or pid
        for row in rows:
            if row.action == Action.NO_MATCH:
                unmatched.append((title, row))

    summary = ", ".join(f"{action.value}: {totals[action]}" for action in Action)
    print(f"\nFinal report: {summary}")
    if unmatched:
        print("Unmatched tracks:")
        for pl_title, row in unmatched:
            artists = ", ".join(row.track.artists) or "Unknown"
            print(f"  - [{pl_title}] {row.track.title} - {artists} ({row.track.video_id})")
    print("New playlists:")
    for pid, meta, _, new_id in rebuilt:
        title = meta.get("title") or pid
        print(f"  - {title}: {playlist_url(new_id)}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for previewing and rebuilding YouTube Music playlists."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.delete_new and not args.rollback:
        print("Error: --delete-new requires --rollback.", file=sys.stderr)
        return 1
    if args.rollback:
        return _run_rollback(args)
    if args.restore_from:
        return _run_restore(args)
    if not args.playlists:
        print("Error: provide at least one playlist ID/URL, --rollback, or --restore-from.", file=sys.stderr)
        return 2

    if args.pick and not _can_prompt():
        print("Aborted: non-interactive stdin cannot use --pick.", file=sys.stderr)
        return 1

    try:
        client = Ytm(args.auth)
    except Exception as exc:
        print(f"Auth error loading {args.auth}: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    planned: list[tuple[str, dict[str, Any], list[PlanRow]]] = []
    failures = 0

    for raw_pid in args.playlists:
        try:
            planned.append(_plan_one(client, raw_pid, out_dir, pick=args.pick))
        except Exception as exc:
            print(f"Error [{raw_pid}]: {exc}", file=sys.stderr)
            failures += 1

    if not planned:
        return 2

    if not args.apply:
        print("Dry run complete; nothing written.")
        return 2 if failures else 0

    actionable: list[tuple[str, dict[str, Any], list[PlanRow]]] = []
    for pid, meta, rows in planned:
        row_counts = counts(rows)
        if row_counts[Action.REPLACE] == 0 and row_counts[Action.REMOVE_DUP] == 0:
            print(f"Skipping {meta.get('title') or pid} ({pid}): zero replacements or duplicate removals.")
        else:
            actionable.append((pid, meta, rows))

    if not actionable:
        print("Nothing to apply; all playlists already clean.")
        return 2 if failures else 0

    n_playlists = len(actionable)
    total_repl = sum(counts(rows)[Action.REPLACE] for _, _, rows in actionable)
    total_dup = sum(counts(rows)[Action.REMOVE_DUP] for _, _, rows in actionable)
    print(
        f"\n{n_playlists} playlists, {total_repl} replacements, {total_dup} duplicate removals; "
        "new playlists will be created, originals untouched."
    )

    if not _can_prompt():
        print("Aborted: non-interactive stdin cannot confirm --apply.", file=sys.stderr)
        return 1

    expected = f"REBUILD {n_playlists}"
    try:
        answer = input(f"Type '{expected}' to proceed: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 1

    if answer != expected:
        print("Confirmation did not match; aborted, nothing written.")
        return 1

    rebuilt: list[tuple[str, dict[str, Any], list[PlanRow], str]] = []
    for pid, meta, rows in actionable:
        try:
            new_id = rebuild(client, pid, meta, rows, out_dir=out_dir)
            rebuilt.append((pid, meta, rows, new_id))
        except Exception as exc:
            print(f"Error rebuilding {pid}: {exc}", file=sys.stderr)
            failures += 1

    _print_final_report(rebuilt)
    return 2 if failures else 0
