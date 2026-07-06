import json

from meshcore_matrix_bridge.droplog import DropLog


PAYLOAD = {
    "text": "hello",
    "SNR": 11.5,
    "path_len": 2,
    "pubkey_prefix": "ab12cd34ef5600ff",
    "sender_timestamp": 1745221230,
}


def test_record_and_snapshot(tmp_path):
    dl = DropLog(tmp_path / "drops.jsonl")
    dl.record_chan(3, "relay-off", PAYLOAD)
    dl.record_chan(3, "relay-off", PAYLOAD)
    dl.record_dm("send-failed", PAYLOAD)

    chans = dl.snapshot_channels()
    assert chans[3]["dropped"] == 2
    assert len(chans[3]["samples"]) == 2
    assert chans[3]["samples"][0]["pubkey_prefix"] == "ab12cd34ef56"  # capped at 12

    dm = dl.snapshot_dm()
    assert dm["dropped"] == 1


def test_record_chan_without_index_is_a_noop(tmp_path):
    dl = DropLog(tmp_path / "drops.jsonl")
    dl.record_chan(None, "relay-off", PAYLOAD)
    assert dl.snapshot_channels() == {}


def test_state_survives_restart(tmp_path):
    path = tmp_path / "drops.jsonl"
    dl = DropLog(path)
    dl.record_chan(7, "no-room", PAYLOAD)
    dl.record_dm("send-failed", PAYLOAD)

    reloaded = DropLog(path)
    assert reloaded.snapshot_channels()[7]["dropped"] == 1
    assert reloaded.snapshot_dm()["dropped"] == 1


def test_corrupt_lines_are_skipped(tmp_path):
    path = tmp_path / "drops.jsonl"
    good = {"t": 1, "kind": "chan", "idx": 1, "reason": "x", "text": "ok"}
    path.write_text("not json at all\n" + json.dumps(good) + "\n{broken\n", encoding="utf-8")

    dl = DropLog(path)
    assert dl.snapshot_channels()[1]["dropped"] == 1


def test_rotation_keeps_one_generation(tmp_path):
    path = tmp_path / "drops.jsonl"
    dl = DropLog(path, max_bytes=200)
    for _ in range(20):
        dl.record_chan(1, "relay-off", PAYLOAD)

    rotated = path.with_suffix(path.suffix + ".1")
    assert rotated.is_file()
    assert path.is_file()
    # everything is still counted after a restart (both generations read)
    reloaded = DropLog(path, max_bytes=200)
    assert reloaded.snapshot_channels()[1]["dropped"] > 0
