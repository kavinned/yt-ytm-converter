import re
import unicodedata

NOISE_TERMS: tuple[str, ...] = (
    "official music video",
    "official video",
    "official m/v",
    "official audio",
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
    r"\b(?:official\s+(?:music\s+)?video|official\s+m/v|official\s+audio|lyric\s+video|m/v|hd|4k)\b"
)
_LANG_VER_RE = re.compile(r"\b(japanese|english|korean|chinese|spanish)\s+ver(?:sion)?\b")
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
    text = _fold(s)
    text = _BRACKET_FEAT_RE.sub(" ", text)
    text = _BRACKET_NOISE_RE.sub(" ", text)
    text = _INLINE_NOISE_RE.sub(" ", text)
    text = _FEAT_TAIL_RE.sub(" ", text)
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_artists(names: list[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        for part in _ARTIST_SPLIT_RE.split(_fold(name)):
            cleaned = " ".join(_NON_WORD_RE.sub(" ", part).split())
            if cleaned:
                result.add(cleaned)
    return result


def version_tokens(s: str) -> frozenset[str]:
    text = " ".join(_NON_WORD_RE.sub(" ", _fold(s)).split())
    tokens = {tok for tok, pat in _VERSION_RES if pat.search(text)}
    tokens.update(f"{m.group(1)} ver" for m in _LANG_VER_RE.finditer(text))
    return frozenset(tokens)
