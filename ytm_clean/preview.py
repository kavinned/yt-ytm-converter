import csv
import html
from pathlib import Path
from urllib.parse import quote

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


def _final_length(rows: list[PlanRow]) -> int:
    return sum(1 for r in rows if r.action != Action.REMOVE_DUP and r.track.video_id is not None)


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
    final_len = _final_length(rows)
    lines.append(summary)
    lines.append(f"final length {len(rows)} -> {final_len}")
    return "\n".join(lines)


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(val: str) -> str:
    stripped = val.lstrip(" ")
    if stripped.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + val
    return val


def write_csv(rows: list[PlanRow], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([_csv_safe(v) for v in _row_values(row)])


def _watch_cell(vid: str) -> str:
    if not vid:
        return ""
    esc = html.escape(vid, quote=True)
    href_id = html.escape(quote(vid, safe=""), quote=True)
    return f'<a href="https://music.youtube.com/watch?v={href_id}" target="_blank" rel="noopener">{esc}</a>'


def write_html(rows: list[PlanRow], playlist_title: str, path: str | Path) -> None:
    """Write a self-contained filterable HTML preview of the replacement plan."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    action_counts = counts(rows)
    final_len = _final_length(rows)
    esc_title = html.escape(playlist_title, quote=True)

    pills = [f'<button class="pill active" data-filter="all">all ({len(rows)})</button>']
    for action in Action:
        val = action.value
        pills.append(
            f'<button class="pill {val}" data-filter="{val}">{val} ({action_counts[action]})</button>'
        )

    body_rows: list[str] = []
    for row in rows:
        vals = _row_values(row)
        search_blob = html.escape(" ".join(vals).lower(), quote=True)
        act = row.action.value
        cells: list[str] = []
        for col, val in zip(COLUMNS, vals):
            if col in ("video_id", "repl_video_id"):
                cells.append(f"<td>{_watch_cell(val)}</td>")
            elif col == "action":
                cells.append(f'<td><span class="badge {act}">{html.escape(val)}</span></td>')
            else:
                cells.append(f"<td>{html.escape(val)}</td>")
        body_rows.append(
            f'<tr data-action="{act}" data-search="{search_blob}">{"".join(cells)}</tr>'
        )

    headers = "".join(f"<th>{html.escape(c)}</th>" for c in COLUMNS)
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc_title} — ytm-clean preview</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 16px; background: #111; color: #eee; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 6px; }}
  .meta {{ color: #aaa; margin-bottom: 12px; font-size: .9rem; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 12px; }}
  input {{ padding: 6px 10px; border-radius: 6px; border: 1px solid #444; background: #1c1c1c; color: #eee; min-width: 240px; }}
  .pill {{ padding: 5px 10px; border-radius: 999px; border: 1px solid #444; background: #1c1c1c; color: #ddd; cursor: pointer; font-size: .82rem; }}
  .pill.active {{ border-color: #fff; background: #333; color: #fff; }}
  .badge {{ padding: 2px 7px; border-radius: 999px; font-size: .78rem; white-space: nowrap; display: inline-block; }}
  .replace {{ background: #14532d; color: #bbf7d0; }}
  .remove-duplicate-video {{ background: #7f1d1d; color: #fecaca; }}
  .keep-video {{ background: #78350f; color: #fde68a; }}
  .no-match {{ background: #3f3f46; color: #e4e4e7; }}
  .keep-song {{ background: #1e3a5f; color: #bfdbfe; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
  th, td {{ border-bottom: 1px solid #2a2a2a; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ position: sticky; top: 0; background: #1a1a1a; }}
  tr:hover td {{ background: #1b1b1b; }}
  a {{ color: #7dd3fc; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>{esc_title}</h1>
<div class="meta">final length {len(rows)} -&gt; {final_len}</div>
<div class="controls">
  <input id="q" type="search" placeholder="Filter title, artist, id, reason...">
  {"".join(pills)}
</div>
<table>
  <thead><tr>{headers}</tr></thead>
  <tbody>{"".join(body_rows)}</tbody>
</table>
<script>
const q = document.getElementById('q');
const pills = document.querySelectorAll('.pill');
const trs = document.querySelectorAll('tbody tr');
let act = 'all';
function apply() {{
  const term = q.value.trim().toLowerCase();
  trs.forEach(tr => {{
    const okAct = act === 'all' || tr.dataset.action === act;
    const okQ = !term || tr.dataset.search.includes(term);
    tr.hidden = !(okAct && okQ);
  }});
}}
pills.forEach(p => p.addEventListener('click', () => {{
  pills.forEach(x => x.classList.remove('active'));
  p.classList.add('active');
  act = p.dataset.filter;
  apply();
}}));
q.addEventListener('input', apply);
</script>
</body>
</html>
"""
    target.write_text(doc, encoding="utf-8")
