# yt-ytm-converter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI that replaces video entries in YouTube Music playlists with the catalog song version, previewing everything first and writing nothing until typed confirmation.

**Architecture:** Pure-logic core (normalize, score, plan) with no network, fed by a thin ytmusicapi wrapper. Plan -> preview (console + CSV) -> optional apply. Apply = rebuild into a NEW playlist in original order; the original is never modified.

**Tech Stack:** Python 3 (Windows), `ytmusicapi`, stdlib only otherwise (`difflib`, `csv`, `argparse`, `json`, `unicodedata`), `pytest`. Use `bun` N/A (Python); `pip` + venv.

**Spec:** the user request in this conversation (summarised under Global Constraints).

## Stack check (asked: is something better?)
Python + ytmusicapi stays best. Only maintained library exposing playlist read/search/create/edit/remove with `videoType`. Alternatives (raw innertube HTTP, yt-dlp, Node `ytmusic-api`) re-implement what ytmusicapi has, or lack write support. No change.

## Global Constraints
- Python 3 on Windows; project dir `yt-ytm-converter`.
- Auth: ytmusicapi browser-cookie headers (`browser.json` from `ytmusicapi browser`). Not committed (`.gitignore`).
- Classify ONLY by `videoType`: `MUSIC_VIDEO_TYPE_ATV` = song (leave alone); `OMV`, `UGC`, `OFFICIAL_SOURCE_MUSIC`, other/missing-with-videoId = video candidate. Never title heuristics.
- Search: `search(query, filter="songs")`.
- Title normalization strips: "official video", "(Audio)", "(Lyrics)", "HD", feat./ft./featuring variants, punctuation, case.
- Gates: artist overlap required; duration within 5 s.
- Actions: `replace`, `remove-duplicate-video`, `keep-video`, `no-match` (+ `keep-song` for ATV rows).
- Zero network writes before confirmation. `--apply` + typed confirmation required.
- Non-goals: downloads, audio processing, GUI.

## Review Focus
1. Podcast/episode or unavailable entries (null `videoId`/no `videoType`): keep untouched, report, never crash. Test in Task 3.
2. Two video entries mapping to same song (e.g. OMV + lyric upload): first = replace, second = remove-duplicate-video. Test in Task 4.
3. Same videoId twice in source playlist: both kept in rebuild, order intact. Test in Task 7.
4. Remix/live/acoustic/instrumental mismatch: video "X (Live)" must NOT match studio "X". Test in Task 2.
5. Rebuild crashes midway or rate-limited: re-run resumes into same new playlist, no duplicates. Test in Task 7.

## Decisions (CONFIRMED by user)
| # | Decision | Outcome |
|---|----------|---------|
| D1 | Song already in playlist -> remove video entry, add nothing | Yes |
| D2 | Rebuild-new vs in-place | **Rebuild new** |
| D3 | Confidence threshold | Auto-accept >= 0.90 and margin >= 0.05 over runner-up; else keep-video |
| D4 | Rebuilt playlist name | `<orig> [ytm-clean]`, same privacy as original |
| D5 | Scope | User-owned regular playlists ONLY. Liked Music, mixes, albums, "Episodes for Later" are out of scope: tool refuses them with a clear error (no preview) |

### Order preservation: options
Fact: `add_playlist_items` appends to the end. Replacing in place by add+remove therefore scrambles order. Correction possible only via `edit_playlist(moveItem=...)`.

| Option | Pros | Cons |
|---|---|---|
| **A. Rebuild into new playlist (recommended)** | Original untouched = trivial rollback; order exact; few calls (create with video_ids, chunked); partial failure harmless; idempotent via state file | New playlist ID/URL; lose original shares, collaborators, followers, "date added", description/thumbnail unless copied (copy title/description/privacy). Per-song likes are tied to videoId, not playlist; replaced songs are new videoIds so were never liked anyway - kept entries keep likes |
| B. In-place: add song, `moveItem` into position, remove video | Same URL/shares/followers | ~3 calls per replaced track; new setVideoIds; mid-run failure leaves mixed state; rollback needs the snapshot to rebuild order; more rate-limit exposure |
| C. In-place add+remove only | Simplest | Scrambled order - rejected |

Recommend A. B only if you need the URL preserved; not built (YAGNI), add later behind `--in-place`.

### ytmusicapi limitations
- Out of scope (D5): Liked Music (`LM`), auto-generated/mixes (`RD*`), albums (`OLAK5uy*`/`MPRE*`), "Episodes for Later" (`SE`). Tool refuses by ID prefix, and also refuses when `get_playlist` meta says not owned.
- Cookie auth expires; no official API, may break on YTM changes; pin `ytmusicapi` version.
- `get_playlist(limit=None)` needed for full read; large playlists slow.
- `videoType` key on playlist tracks may be absent for some items; treated as video candidate only if `videoId` present, else keep.

## File Structure
```
ytm_clean/
  __init__.py
  models.py      # Track, Candidate, PlanRow, Action enum
  normalize.py   # normalize_title, normalize_artists, version_tokens
  matching.py    # score_candidate, pick_match
  client.py      # YTM wrapper: read_playlist, search_songs, create/add; retry
  retry.py       # call_with_retry
  planner.py     # build_plan
  preview.py     # render_table, write_csv, counts
  apply.py       # snapshot, rebuild, state file, rollback
  cli.py         # argparse entry, confirmation
tests/
  fixtures/      # recorded ytmusicapi JSON: playlist_*.json, search_*.json
  test_*.py
.gitignore  requirements.txt  README.md
```
Runtime output dir `out/` (gitignored): `preview-<playlistId>.csv`, `snapshot-<playlistId>-<ts>.json`, `state-<playlistId>.json`.

---

### Task 1: Scaffold, models, normalization

**Files:** Create `ytm_clean/models.py`, `ytm_clean/normalize.py`, `requirements.txt`, `.gitignore`, `tests/test_normalize.py`

**Interfaces:**
- Produces:
  - `models.Track` dataclass: `video_id: str|None, set_video_id: str|None, title: str, artists: list[str], duration_s: int|None, video_type: str|None`
  - `models.Action(str, Enum)`: `KEEP_SONG, REPLACE, REMOVE_DUP, KEEP_VIDEO, NO_MATCH`
  - `normalize.normalize_title(s: str) -> str`
  - `normalize.normalize_artists(names: list[str]) -> set[str]`
  - `normalize.version_tokens(s: str) -> frozenset[str]` (from {remix, live, acoustic, instrumental, cover, karaoke, sped up, slowed, remaster})

- [ ] **Step 1: Failing tests**
```python
def test_strips_noise():
    assert normalize_title("Song Name (Official Video) [HD]") == "song name"
    assert normalize_title("Song - (Lyrics)") == "song"
    assert normalize_title("Song (feat. Bob) (Audio)") == "song"
    assert normalize_title("Song ft. Bob") == "song"
def test_keeps_meaningful_parens():
    assert normalize_title("Song (Live)") == "song live"
def test_artists_split_and_case():
    assert normalize_artists(["A & B", "c"]) == {"a", "b", "c"}
def test_version_tokens():
    assert "live" in version_tokens("Song (Live at X)")
    assert version_tokens("Song") == frozenset()
```
- [ ] **Step 2:** `pytest tests/test_normalize.py -v` -> FAIL (import error)
- [ ] **Step 3:** Implement. Noise list is a module constant; use `unicodedata` NFKD + casefold; version tokens kept in normalized title (not stripped) so they affect similarity and the guard.
- [ ] **Step 4:** run -> PASS
- [ ] **Step 5:** `git init`, commit `feat: models and normalization`

### Task 2: Matching and scoring

**Files:** Create `ytm_clean/matching.py`, `tests/test_matching.py`

**Interfaces:**
- Consumes: `Track`, `normalize.*`
- Produces:
  - `matching.Scored` dataclass: `track: Track, score: float, reason: str`
  - `score_candidate(video: Track, cand: Track) -> Scored | None` — None if gate fails (no artist overlap, `|Δdur| > 5`, either duration missing, or `version_tokens` differ)
  - `pick_match(video: Track, cands: list[Track]) -> tuple[Scored | None, str]` — returns accepted match or None, plus Action-hint string `"accept" | "low-confidence" | "none"`

Rules: `score = 0.55*title_sim + 0.30*artist_jaccard + 0.15*dur_closeness`, `title_sim = difflib.SequenceMatcher` ratio on normalized titles; `dur_closeness = 1 - Δ/5`. Accept if best >= 0.90 and best - second >= 0.05. Gate-passing but below threshold/margin -> `"low-confidence"` (action keep-video). No gate-passing candidates -> `"none"` (action no-match). Reason string lists the components.

- [ ] **Step 1: Failing tests**
```python
def test_exact_match_accepts(): ...  # same title/artist, dur 200 vs 201 -> accept, score >= .9
def test_duration_gate(): assert score_candidate(v, cand_dur_210_vs_200) is None
def test_artist_gate(): assert score_candidate(v, other_artist) is None
def test_live_vs_studio_rejected(): assert score_candidate(video("X (Live)"), song("X")) is None
def test_ambiguous_margin(): two near-identical cands -> "low-confidence"
def test_no_cands(): assert pick_match(v, []) == (None, "none")
```
- [ ] **Step 2:** run -> FAIL. **Step 3:** implement. **Step 4:** run -> PASS. **Step 5:** commit `feat: candidate scoring`.

### Task 3: Retry + client wrapper (read/search)

**Files:** Create `ytm_clean/retry.py`, `ytm_clean/client.py`, `tests/test_client.py`, `tests/fixtures/playlist_mixed.json`, `search_*.json`

**Interfaces:**
- Produces:
  - `retry.call_with_retry(fn, *, attempts=5, base=1.0, sleep=time.sleep)` — exponential backoff + jitter on HTTP 429/5xx/`YTMusicServerError`; re-raises after attempts; `sleep` injectable for tests.
  - `client.parse_playlist_id(s: str) -> str` — accepts bare ID or URL with `list=`; raises `ValueError` otherwise.
  - `client.ScopeError(Exception)`; `client.assert_in_scope(pid: str, meta: dict) -> None` — raises for `LM`, `RD*`, `OLAK5uy*`, `MPRE*`, `SE`, or `meta["owned"] is False`.
  - `client.Ytm(auth_path: str)` with:
    - `read_playlist(pid: str) -> tuple[dict, list[Track]]` (meta: title, description, privacy, owned; uses `limit=None`; maps `videoType`->`video_type`, `duration_seconds`, `setVideoId`)
    - `search_songs(query: str) -> list[Track]` (`filter="songs"`; query = `"{title_clean} {first_artist}"`; memoized per query)
    - `create_playlist(title, description, privacy, video_ids: list[str]) -> str`, `add_items(pid, video_ids) -> None` (chunks of 100, `duplicates=True`), `remove_items(pid, videos)` unused until in-place.
  - All writes go through `call_with_retry`; reads too.
  - Writes only in methods named `create_*/add_*/remove_*` — single choke point for the zero-writes test.

- [ ] **Step 1: Failing tests** (fixtures from a recorded real run; sanitize)
```python
def test_parse_url(): assert parse_playlist_id("https://music.youtube.com/playlist?list=PLabc") == "PLabc"
def test_parse_bad(): pytest.raises(ValueError)
def test_retry_then_ok(): fn fails twice with 429 then returns -> result, sleep called twice
def test_retry_gives_up(): raises after 5
def test_read_maps_fields(): fixture playlist -> Track with set_video_id, video_type
def test_unavailable_entry_kept(): fixture row videoId=None -> Track(video_id=None) not dropped
```
- [ ] **Step 2-4:** run FAIL -> implement -> PASS. **Step 5:** commit `feat: ytm client and retry`.

### Task 4: Planner

**Files:** Create `ytm_clean/planner.py`, `tests/test_planner.py`

**Interfaces:**
- Consumes: `Track`, `pick_match`, `normalize`, a `search: Callable[[str], list[Track]]` (injected; no network in tests)
- Produces:
  - `models.PlanRow`: `index:int, track:Track, classification:str ("song"|"video"|"other"), action:Action, replacement:Track|None, confidence:float|None, reason:str`
  - `planner.build_plan(tracks: list[Track], search) -> list[PlanRow]` — pure, order-preserving, one row per entry.

Rules: `ATV` -> KEEP_SONG. No `video_id` -> classification "other", KEEP_SONG-like keep (action `KEEP_VIDEO`, reason "unavailable/non-music"). Video: `pick_match`; accept -> already-present check against ATV entries of the playlist and against replacements already chosen earlier (same `video_id`, or equal normalized title + artist overlap + Δdur<=5) -> `REMOVE_DUP`, else `REPLACE`; low-confidence -> `KEEP_VIDEO`; none -> `NO_MATCH`. Idempotent: output of a rebuilt playlist (all ATV or kept videos) yields no REPLACE.

- [ ] **Step 1: Failing tests**
```python
def test_atv_left_alone(): action == KEEP_SONG
def test_replace(): OMV + good candidate -> REPLACE, replacement.video_id == cand
def test_already_present_by_id(): ATV same videoId elsewhere -> REMOVE_DUP
def test_already_present_by_meta(): ATV different videoId, same title/artist, dur +-2 -> REMOVE_DUP
def test_two_videos_one_song(): [replace, remove-dup]
def test_low_conf_keeps(): KEEP_VIDEO; test_none: NO_MATCH
def test_null_video_id_passthrough()
def test_replan_is_noop(): applying plan then planning result has zero REPLACE/REMOVE_DUP
```
- [ ] **Step 2-4:** FAIL -> implement -> PASS. **Step 5:** commit `feat: plan builder`.

### Task 5: Preview (console + CSV)

**Files:** Create `ytm_clean/preview.py`, `tests/test_preview.py`

**Interfaces:**
- Consumes: `list[PlanRow]`
- Produces: `render_table(rows, playlist_title) -> str`; `write_csv(rows, path) -> None`; `counts(rows) -> dict[Action,int]`

Columns (both): `index, current_title, current_artist, video_id, classification, action, repl_title, repl_artist, repl_duration, repl_video_id, confidence, reason`. Console: fixed-width table, long text truncated (CSV never truncated); footer counts per action, plus "final length N -> M". CSV: `utf-8-sig` (Excel on Windows), `newline=""`.

- [ ] **Step 1: Failing tests**
```python
def test_csv_roundtrip_unicode_and_commas(tmp_path): title 'Å, "q"' survives csv.reader
def test_counts(): known rows -> exact dict
def test_table_has_every_row_and_footer(): len(lines) and "replace: 2" in out
```
- [ ] **Step 2-4:** FAIL -> implement -> PASS. **Step 5:** commit `feat: preview and csv`.

### Task 6: Apply (rebuild), snapshot, state, rollback

**Files:** Create `ytm_clean/apply.py`, `tests/test_apply.py`

**Interfaces:**
- Consumes: `Ytm` (write methods; faked in tests), `list[PlanRow]`, playlist meta
- Produces:
  - `apply.final_video_ids(rows) -> list[str]` — KEEP_SONG/KEEP_VIDEO/NO_MATCH -> own id; REPLACE -> replacement id; REMOVE_DUP -> nothing; entries with null id skipped and listed in report.
  - `apply.write_snapshot(pid, meta, tracks, out_dir) -> Path` — full JSON (all fields incl. setVideoId); written BEFORE any write.
  - `apply.rebuild(client, pid, meta, rows, out_dir) -> str` (new playlist id) — state file `state-<pid>.json` `{new_id, expected_ids, done_count}`; if state exists: resume by re-reading new playlist and appending only the missing tail; if complete -> no-op, print existing URL.
  - `apply.rollback(pid, out_dir) -> str` — rollback = original is untouched, so: print original URL + new playlist ID, and `--delete-new` flag deletes the new playlist (typed confirm). If original was ever lost, `--restore-from snapshot.json` recreates a playlist from snapshot in order.

- [ ] **Step 1: Failing tests (FakeYtm records calls)**
```python
def test_final_ids_order(): replace in place, remove-dup dropped, order preserved
def test_duplicate_video_id_preserved(): [a,b,a] -> [a,b,a]
def test_snapshot_written_before_create(): call log order: snapshot file exists when create called
def test_original_never_mutated(): FakeYtm.remove/edit calls == []
def test_resume_after_crash(): add_items raises mid-way; rerun -> final new playlist == expected, no dup
def test_rerun_complete_noop(): second run makes 0 write calls
def test_restore_from_snapshot(): creates playlist with snapshot order
def test_refuse_out_of_scope(): pids "LM", "RDCLAK1", "OLAK5uy_x", "SE" and meta owned=False -> raise ScopeError (in client.assert_in_scope)
```
- [ ] **Step 2-4:** FAIL -> implement -> PASS. **Step 5:** commit `feat: rebuild apply with snapshot and resume`.

### Task 7: CLI and confirmation UX

**Files:** Create `ytm_clean/cli.py`, `README.md`, `tests/test_cli.py`

**Interfaces:**
- Produces: `cli.main(argv: list[str] | None = None) -> int`; entry `python -m ytm_clean`.

Flags: positional `playlists...`; `--auth browser.json`; `--out out/`; `--apply`; `--yes-i-mean-it` NOT provided (no bypass); `--rollback PID [--delete-new]`; `--restore-from FILE`.

UX: default = dry-run: read, plan, print table, write CSV, exit 0 ("dry run, nothing written"). With `--apply`: after full preview of ALL playlists, print summary (`N playlists, X replacements, Y duplicate removals; new playlists will be created, originals untouched`) and require typing exact string `REBUILD <N>` (N = number of playlists with changes). Anything else -> abort, exit 1. Playlists with zero REPLACE/REMOVE_DUP are skipped. Non-interactive stdin -> abort. Per-playlist failures are reported, remaining playlists continue; exit code 2 if any failed. Final report: counts, unmatched list, new URLs.

- [ ] **Step 1: Failing tests** (monkeypatch `Ytm` with fake, `input`)
```python
def test_dry_run_zero_writes(): FakeYtm.write_calls == []
def test_apply_wrong_confirmation_zero_writes(): input -> "yes" -> return 1, write_calls == []
def test_apply_correct_confirmation_creates(): input -> "REBUILD 1" -> 1 create call
def test_all_previews_before_prompt(): output order
def test_one_playlist_fails_others_continue(): rc == 2
```
- [ ] **Step 2-4:** FAIL -> implement -> PASS. **Step 5:** commit `feat: cli with typed confirmation`.

### Task 8: Live verification (manual, you run)

- [ ] **Step 1:** `python -m venv .venv; .venv\Scripts\pip install -r requirements.txt`; `ytmusicapi browser` -> paste request headers -> `browser.json`.
- [ ] **Step 2:** Make a small TEST playlist (5-10 tracks: 2 OMV, 1 UGC, 1 ATV, 1 with both OMV and its ATV, 1 obscure upload). Dry run: `python -m ytm_clean <url>`. Expected: every row classified as you'd expect by eye, CSV opens in Excel, no new playlist exists.
- [ ] **Step 3:** `python -m ytm_clean <url> --apply`, type wrong text -> aborted, nothing created. Then type `REBUILD 1` -> new playlist, check order, count = expected, original unchanged.
- [ ] **Step 4:** Re-run apply -> "already rebuilt" no-op. Re-run dry-run on the NEW playlist -> zero replace.
- [ ] **Step 5:** Run `python -m ytm_clean "LM"` -> refused with scope error.
- [ ] **Step 6:** Capture real JSON (sanitized) into `tests/fixtures/` to refresh fixtures.

## Risks
- Cookie expiry / YTM internal changes break ytmusicapi -> pin version, clear auth error message.
- Search recall: song catalog may only have remaster/other-region version -> falls to keep-video (safe).
- Wrong match auto-accepted -> mitigated by gates + 0.90 + margin + full preview; CSV review; originals untouched.
- Rate limits / account flags on bulk search -> memoize, small jittered sleep between searches, retry.
- Playlist metadata not copyable (thumbnail, collaborators, followers) -> documented tradeoff of D2.
- `videoType` absent on some entries -> treated as keep with reason.

## Self-Review
- Coverage: 1 (Task 3/7), 2 (3), 3 (4), 4 (1,2,4), 5 (4), 6 (5; zero writes Task 7), 7 (7), 8 (tradeoff table + Task 6), 9 (3,6,7), 10 (non-goals), decisions (table + limitations). Gap check: none found.
- Names consistent: `Action.REMOVE_DUP` = "remove-duplicate-video" in preview text; `KEEP_VIDEO` = "keep-video"; `NO_MATCH` = "no-match".
- Size proportional.
