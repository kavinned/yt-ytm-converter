from ytm_clean.normalize import (
    alt_titles,
    normalize_artists,
    normalize_title,
    search_query_title,
    version_tokens,
)


def test_strips_noise():
    assert normalize_title("Song Name (Official Video) [HD]") == "song name"
    assert normalize_title("Song - (Lyrics)") == "song"
    assert normalize_title("Song (feat. Bob) (Audio)") == "song"
    assert normalize_title("Song ft. Bob") == "song"
    assert normalize_title("Song featuring Bob (Official Music Video) [4K]") == "song"
    assert normalize_title("Song OFFICIAL M/V (feat. Bob)") == "song"
    assert normalize_title("Song [M/V]") == "song"


def test_keeps_meaningful_parens():
    assert normalize_title("Song (Live)") == "song live"
    assert normalize_title("Song (Acoustic Version)") == "song acoustic version"


def test_unicode_and_punctuation():
    assert normalize_title("Café — Song!") == "cafe song"


def test_artists_split_and_case():
    assert normalize_artists(["A & B", "c"]) == {"a", "b", "c"}
    assert normalize_artists(["A, B", "D feat. E"]) == {"a", "b", "d", "e"}


def test_version_tokens():
    assert "live" in version_tokens("Song (Live at X)")
    assert "sped up" in version_tokens("Song (Sped Up)")
    assert version_tokens("Song") == frozenset()
    assert version_tokens("Song (Japanese Version)") == version_tokens("Song -Japanese ver.-")
    assert version_tokens("Song (English Version)") != version_tokens("Song")


def test_search_query_title_preserves_symbols_and_accents():
    assert search_query_title("Long Chat (#♥)") == "Long Chat (#♥)"
    assert search_query_title("Soñar (Breaker)") == "Soñar (Breaker)"
    assert search_query_title("03. IVE - BlueHeart (Official Video)") == "IVE - BlueHeart"
    assert search_query_title("ITZY - Blossom (Audio Clip)") == "ITZY - Blossom"


def test_alt_titles_extracts_bilingual_parens_without_version_tokens():
    assert alt_titles("섬찟 (Hypnosis)") == [normalize_title("섬찟 (Hypnosis)"), "hypnosis"]
    assert alt_titles("Song (Live)") == ["song live"]
