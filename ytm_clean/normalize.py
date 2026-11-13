import re
import unicodedata

NOISE_TERMS: tuple[str, ...] = (
    "official music video",
    "official video",
    "official m/v",
    "official audio",
    "audio clip",
    "lyric video",
    "lyrics",
    "audio",
    "m/v",
    "hd",
    "4k",
    "hq",
    "mv",
)

VERSION_TOKENS: frozenset[str] = frozenset({
    "remix",
    "live",
    "acoustic",
    "instrumental",
    "cover",
    "karaoke",
    "sped up",
    "slowed",
    "remaster",
})

_NOISE_ALT = "|".join(re.escape(t).replace(r"\ ", r"\s+") for t in NOISE_TERMS)
_BRACKET_FEAT_RE = re.compile(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\b[^)\]]*[\)\]]")
_BRACKET_NOISE_RE = re.compile(rf"[\(\[]\s*(?:{_NOISE_ALT})\s*[\)\]]")
_INLINE_NOISE_RE = re.compile(
    r"\b(?:official\s+(?:music\s+)?video|official\s+m/v|official\s+audio|audio\s+clip|lyric\s+video|m/v|hd|4k)\b"
)
_TRAILING_MV_RE = re.compile(r"(?<=\S)\s+mv\b")
_LANG_VER_RE = re.compile(r"\b(japanese|english|korean|chinese|spanish)\s+ver(?:sion)?\b")
_TRACK_NUM_RE = re.compile(r"^\d{1,2}\.\s+")
_PARENS_RE = re.compile(r"[\(\[]([^)\]]+)[\)\]]")
_QUERY_FEAT_RE = re.compile(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\b[^)\]]*[\)\]]", re.IGNORECASE)
_QUERY_NOISE_RE = re.compile(rf"[\(\[]\s*(?:{_NOISE_ALT})\s*[\)\]]", re.IGNORECASE)
_QUERY_INLINE_NOISE_RE = re.compile(
    r"\b(?:official\s+(?:music\s+)?video|official\s+m/v|official\s+audio|audio\s+clip|lyric\s+video|m/v|hd|4k)\b",
    re.IGNORECASE,
)
_FEAT_TAIL_RE = re.compile(r"\b(?:feat\.?|ft\.?|featuring)\b.*$")
_ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|&|/|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*")
_NON_WORD_RE = re.compile(r"[^\w\s]")
_VERSION_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tok, re.compile(rf"\b{re.escape(tok)}\b")) for tok in VERSION_TOKENS
)


def _fold(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def normalize_title(s: str) -> str:
    text = _TRACK_NUM_RE.sub("", _fold(s))
    text = _BRACKET_FEAT_RE.sub(" ", text)
    text = _BRACKET_NOISE_RE.sub(" ", text)
    text = _INLINE_NOISE_RE.sub(" ", text)
    text = _FEAT_TAIL_RE.sub(" ", text)
    text = _NON_WORD_RE.sub(" ", text)
    text = " ".join(text.split())
    text = _TRAILING_MV_RE.sub(" ", text)
    return " ".join(text.split())


def search_query_title(s: str) -> str:
    """Strip noise terms and track-number prefix while preserving symbols and accents."""
    text = _TRACK_NUM_RE.sub("", s)
    text = _QUERY_FEAT_RE.sub(" ", text)
    text = _QUERY_NOISE_RE.sub(" ", text)
    text = _QUERY_INLINE_NOISE_RE.sub(" ", text)
    text = re.sub(r"(?<=\S)\s+mv\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def alt_titles(s: str) -> list[str]:
    """Return normalized full title plus any parenthetical alternate title (e.g. bilingual)."""
    primary = normalize_title(s)
    titles = [primary] if primary else []
    for match in _PARENS_RE.finditer(s):
        inner = match.group(1)
        if version_tokens(inner):
            continue
        norm = normalize_title(inner)
        if norm and norm not in titles:
            titles.append(norm)
    return titles


def normalize_artists(names: list[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        for part in _ARTIST_SPLIT_RE.split(_fold(name)):
            chunks = [_PARENS_RE.sub(" ", part), *(m.group(1) for m in _PARENS_RE.finditer(part))]
            for chunk in chunks:
                cleaned = " ".join(_NON_WORD_RE.sub(" ", chunk).split())
                if cleaned:
                    result.add(cleaned)
    return result


def is_single_artist(names: list[str]) -> bool:
    parts = [p for n in names for p in _ARTIST_SPLIT_RE.split(_fold(n)) if p.strip()]
    return len(parts) == 1


def version_tokens(s: str) -> frozenset[str]:
    text = " ".join(_NON_WORD_RE.sub(" ", _fold(s)).split())
    tokens = {tok for tok, pat in _VERSION_RES if pat.search(text)}
    tokens.update(f"{m.group(1)} ver" for m in _LANG_VER_RE.finditer(text))
    return frozenset(tokens)
