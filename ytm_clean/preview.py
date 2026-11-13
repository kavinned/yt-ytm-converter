import csv
from pathlib import Path

from ytm_clean.models import Action, PlanRow

COLUMNS = (
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
)

_WIDTHS = (5, 24, 18, 12, 14, 22, 24, 18, 13, 13, 10, 24)


def _row_values(row: PlanRow) -> list[str]:
    repl = row.replacement
    return [
        str(row.index),
        row.track.title,
        ", ".join(row.track.artists),
        row.track.video_id or "",
        row.classification,
        row.action.value,
        repl.title if repl else "",
        ", ".join(repl.artists) if repl else "",
        str(repl.duration_s) if repl and repl.duration_s is not None else "",
        (repl.video_id or "") if repl else "",
        f"{row.confidence:.2f}" if row.confidence is not None else "",
        row.reason,
    ]


def _cell(value: str, width: int) -> str:
    flat = " ".join(value.splitlines())
    if len(flat) > width:
        flat = flat[: width - 3] + "..."
    return flat.ljust(width)


def counts(rows: list[PlanRow]) -> dict[Action, int]:
    result = {action: 0 for action in Action}
    for row in rows:
        result[row.action] += 1
    return result


def render_table(rows: list[PlanRow], playlist_title: str) -> str:
    lines = [
        f"Playlist: {playlist_title}",
        " | ".join(_cell(col, w) for col, w in zip(COLUMNS, _WIDTHS)),
        "-+-".join("-" * w for w in _WIDTHS),
    ]
    for row in rows:
        lines.append(" | ".join(_cell(val, w) for val, w in zip(_row_values(row), _WIDTHS)))

    action_counts = counts(rows)
    summary = ", ".join(f"{action.value}: {action_counts[action]}" for action in Action)
    final_len = sum(1 for r in rows if r.action != Action.REMOVE_DUP and r.track.video_id is not None)
    lines.append(summary)
    lines.append(f"final length {len(rows)} -> {final_len}")
    return "\n".join(lines)


def write_csv(rows: list[PlanRow], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(_row_values(row))
