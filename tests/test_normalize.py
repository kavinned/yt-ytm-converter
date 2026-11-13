from ytm_clean.normalize import normalize_artists, normalize_title, version_tokens


def test_strips_noise():
    assert normalize_title("Song Name (Official Video) [HD]") == "song name"
    assert normalize_title("Song - (Lyrics)") == "song"
    assert normalize_title("Song (feat. Bob) (Audio)") == "song"
    assert normalize_title("Song ft. Bob") == "song"
    assert normalize_title("Song featuring Bob (Official Music Video) [4K]") == "song"


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
