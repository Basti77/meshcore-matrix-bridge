from meshcore_matrix_bridge.state import State


def test_set_get_roundtrip(tmp_path):
    st = State(tmp_path / "state.json")
    st.set("room", "!abc:example.org")
    assert st.get("room") == "!abc:example.org"
    assert st.get("missing") is None
    assert st.get("missing", 42) == 42


def test_state_is_persisted_atomically(tmp_path):
    path = tmp_path / "state.json"
    State(path).set("k", {"nested": [1, 2, 3]})
    assert State(path).get("k") == {"nested": [1, 2, 3]}
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_corrupt_state_file_starts_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken json", encoding="utf-8")
    st = State(path)
    assert st.get("anything") is None
    st.set("fresh", 1)
    assert State(path).get("fresh") == 1
