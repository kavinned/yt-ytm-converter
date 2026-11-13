from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    KEEP_SONG = "keep-song"
    REPLACE = "replace"
    REMOVE_DUP = "remove-duplicate-video"
    KEEP_VIDEO = "keep-video"
    NO_MATCH = "no-match"


@dataclass(frozen=True)
class Track:
    video_id: str | None
    set_video_id: str | None
    title: str
    artists: list[str]
    duration_s: int | None
    video_type: str | None
