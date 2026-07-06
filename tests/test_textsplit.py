from meshcore_matrix_bridge.textsplit import MAX_CHARS_DEFAULT, split_for_radio


def test_empty_text_yields_nothing():
    assert split_for_radio("") == []
    assert split_for_radio("   \n  ") == []


def test_short_text_passes_through_unsplit():
    assert split_for_radio("hello mesh") == ["hello mesh"]


def test_crlf_is_normalised():
    assert split_for_radio("a\r\nb") == ["a\nb"]


def test_exact_limit_is_not_split():
    text = "x" * MAX_CHARS_DEFAULT
    assert split_for_radio(text) == [text]


def test_long_text_is_split_with_index_prefix():
    words = " ".join(f"word{i:03d}" for i in range(60))
    parts = split_for_radio(words)
    assert len(parts) > 1
    for i, part in enumerate(parts, start=1):
        assert part.startswith(f"({i}/{len(parts)}) ")
        assert len(part) <= MAX_CHARS_DEFAULT


def test_split_reassembles_to_original_words():
    words = " ".join(f"word{i:03d}" for i in range(60))
    parts = split_for_radio(words)
    stripped = [p.split(") ", 1)[1] for p in parts]
    assert " ".join(stripped).split() == words.split()


def test_overlong_single_word_is_hard_split():
    blob = "y" * 500
    parts = split_for_radio(blob)
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= MAX_CHARS_DEFAULT
    reassembled = "".join(p.split(") ", 1)[1] for p in parts)
    assert reassembled == blob


def test_custom_max_chars_is_respected():
    parts = split_for_radio("aa bb cc dd ee ff gg hh", max_chars=12)
    assert all(len(p) <= 12 for p in parts)
