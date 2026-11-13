from typing import Any
from urllib.parse import parse_qs, urlparse

from ytm_clean.models import Track
from ytm_clean.retry import call_with_retry

_OUT_OF_SCOPE_EXACT = frozenset({"LM", "SE"})
_OUT_OF_SCOPE_PREFIXES = ("RD", "OLAK5uy", "MPRE")


class ScopeError(Exception):
    """Raised when a playlist is outside the supported user-owned regular playlist scope."""


def parse_playlist_id(s: str) -> str:
    """Extract a playlist ID from a bare ID or a YouTube/YTM URL with list=."""
    raw = s.strip()
    if not raw:
        raise ValueError("Playlist ID or URL cannot be empty")
    if "://" in raw or "/" in raw or "?" in raw or "=" in raw:
        vals = parse_qs(urlparse(raw).query).get("list")
        pid = vals[0].strip() if vals else ""
        if not pid:
            raise ValueError(f"URL missing 'list=' playlist parameter: {s!r}")
        return pid
    if any(ch.isspace() for ch in raw):
        raise ValueError(f"Invalid playlist ID: {s!r}")
    return raw


def assert_in_scope(pid: str, meta: dict[str, Any]) -> None:
    """Raise ScopeError for Liked Music, mixes, albums, Episodes for Later, or unowned playlists."""
    if pid in _OUT_OF_SCOPE_EXACT or pid.startswith(_OUT_OF_SCOPE_PREFIXES):
        raise ScopeError(f"Playlist {pid!r} is out of scope (only regular playlists supported)")
    if meta.get("owned") is False:
        raise ScopeError(f"Playlist {pid!r} is not owned by the current user")


def _to_track(item: dict[str, Any]) -> Track:
    artists = [
        a["name"]
        for a in (item.get("artists") or [])
        if isinstance(a, dict) and a.get("name")
    ]
    dur = item.get("duration_seconds")
    return Track(
        video_id=item.get("videoId"),
        set_video_id=item.get("setVideoId"),
        title=item.get("title") or "",
        artists=artists,
        duration_s=int(dur) if dur is not None else None,
        video_type=item.get("videoType"),
    )


class Ytm:
    """Thin ytmusicapi wrapper with retry, query memoization, and isolated write methods."""

    def __init__(self, auth_path: str = "browser.json", api: Any = None) -> None:
        if api is None:
            from ytmusicapi import YTMusic

            api = YTMusic(auth_path)
        self._api = api
        self._search_cache: dict[str, list[Track]] = {}

    def read_playlist(self, pid: str) -> tuple[dict[str, Any], list[Track]]:
        data = call_with_retry(lambda: self._api.get_playlist(pid, limit=None))
        meta = {
            "id": data.get("id", pid),
            "title": data.get("title") or "",
            "description": data.get("description") or "",
            "privacy": data.get("privacy") or "PRIVATE",
            "owned": data.get("owned", True),
        }
        tracks = [_to_track(item) for item in (data.get("tracks") or [])]
        return meta, tracks

    def search_songs(self, query: str) -> list[Track]:
        if query in self._search_cache:
            return self._search_cache[query]
        rows = call_with_retry(lambda: self._api.search(query, filter="songs"))
        tracks = [_to_track(item) for item in (rows or [])]
        self._search_cache[query] = tracks
        return tracks

    def create_playlist(
        self, title: str, description: str, privacy: str, video_ids: list[str]
    ) -> str:
        first, rest = video_ids[:100], video_ids[100:]
        res = call_with_retry(
            lambda: self._api.create_playlist(
                title, description, privacy_status=privacy, video_ids=first or None
            )
        )
        new_id = res["id"] if isinstance(res, dict) else str(res)
        if rest:
            self.add_items(new_id, rest)
        return new_id

    def add_items(self, pid: str, video_ids: list[str]) -> None:
        for i in range(0, len(video_ids), 100):
            chunk = video_ids[i : i + 100]
            call_with_retry(
                lambda c=chunk: self._api.add_playlist_items(pid, videoIds=c, duplicates=True)
            )

    def remove_items(self, pid: str, videos: list[dict[str, Any]]) -> None:
        if not videos:
            return
        call_with_retry(lambda: self._api.remove_playlist_items(pid, videos))

    def delete_playlist(self, pid: str) -> None:
        call_with_retry(lambda: self._api.delete_playlist(pid))
