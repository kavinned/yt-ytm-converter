# yt-ytm-converter (`ytm_clean`)

CLI tool that converts video entries (`OMV`, `UGC`, etc.) in YouTube Music playlists to catalog song versions (`MUSIC_VIDEO_TYPE_ATV`), preserving track order by rebuilding into a new playlist (`<original> [ytm-clean]`). The original playlist is never modified.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\ytmusicapi browser
```

Follow the `ytmusicapi browser` prompt to paste YouTube Music request headers and create `browser.json` in the project root (or pass `--auth path/to/browser.json`). `browser.json` is gitignored and must not be committed.

## Dry Run (default, zero writes)

```powershell
.venv\Scripts\python -m ytm_clean <playlist_url_or_id> [<playlist_2> ...]
```

Reads playlists, searches catalog songs, prints a preview table, and writes `out/preview-<playlistId>.csv` (UTF-8 with BOM for Excel) and `out/preview-<playlistId>.html` (filterable browser view). Nothing is created or modified on YouTube Music.

Pass `--pick` (in dry-run or with `--apply`) to interactively pick a song from search results (or run a custom `s <query>` search) for any `keep-video` / `no-match` entry before the final preview and `REBUILD <N>` prompt.

## Apply (`--apply`)

```powershell
.venv\Scripts\python -m ytm_clean <playlist_url_or_id> --apply
```

1. Prints the full preview and writes `out/preview-<playlistId>.csv` for every playlist first.
2. Skips playlists with zero replacements or duplicate removals.
3. Prints a summary and requires interactive typed confirmation (`REBUILD <N>`, where `N` is the number of playlists with changes). Non-interactive stdin aborts with no writes.
4. Writes a JSON snapshot (`out/snapshot-<playlistId>-<timestamp>.json`), creates `<title> [ytm-clean]` with the original privacy/description, and records progress in `out/state-<playlistId>.json` so interrupted runs can resume safely without duplicates.

If a playlist fails, remaining playlists continue and the process exits with code `2`.

## Rollback & Restore

Because the original playlist is never touched, rollback is a no-op on the source playlist:

```powershell
.venv\Scripts\python -m ytm_clean --rollback <playlist_url_or_id>
```

To also delete the rebuilt playlist (prompts to type the new playlist ID):

```powershell
.venv\Scripts\python -m ytm_clean --rollback <playlist_url_or_id> --delete-new
```

To recreate a playlist in exact order from a saved snapshot:

```powershell
.venv\Scripts\python -m ytm_clean --restore-from out/snapshot-<playlistId>-<timestamp>.json
```

## Scope Limits

Only user-owned regular playlists are supported. Liked Music (`LM`), mixes/radios (`RD*`), albums (`OLAK5uy*` / `MPRE*`), "Episodes for Later" (`SE`), and playlists not owned by your account are refused with an error.
