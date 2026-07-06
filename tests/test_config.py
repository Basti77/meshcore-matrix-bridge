import pytest

from meshcore_matrix_bridge.config import BridgeConfig, load_env_files


REQUIRED = {
    "MATRIX_HOMESERVER": "https://matrix.example.org/",
    "MATRIX_USER_ID": "@meshcore:matrix.example.org",
    "MATRIX_ACCESS_TOKEN": "syt_secret",
    "MATRIX_DEVICE_ID": "DEVICE",
}


def set_required(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)


def test_from_env_defaults(monkeypatch):
    for key in list(REQUIRED) + ["MATRIX_ALLOWED_USERS", "MESHCORE_TRANSPORT"]:
        monkeypatch.delenv(key, raising=False)
    set_required(monkeypatch)

    cfg = BridgeConfig.from_env()
    assert cfg.matrix_homeserver == "https://matrix.example.org"  # trailing slash stripped
    assert cfg.meshcore_transport == "serial"
    assert cfg.command_prefix == "!mesh"
    assert cfg.matrix_allowed_users == ()


def test_missing_required_var_raises(monkeypatch):
    set_required(monkeypatch)
    monkeypatch.delenv("MATRIX_ACCESS_TOKEN")
    with pytest.raises(RuntimeError, match="MATRIX_ACCESS_TOKEN"):
        BridgeConfig.from_env()


def test_allowed_users_are_parsed_and_trimmed(monkeypatch):
    set_required(monkeypatch)
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", " @a:x.org, @b:y.org ,,")
    cfg = BridgeConfig.from_env()
    assert cfg.matrix_allowed_users == ("@a:x.org", "@b:y.org")


def test_env_file_does_not_override_environment(tmp_path, monkeypatch):
    set_required(monkeypatch)
    monkeypatch.setenv("MESH_COMMAND_PREFIX", "!real")
    env_file = tmp_path / "bridge.env"
    env_file.write_text(
        'MESH_COMMAND_PREFIX="!fromfile"\nMESHCORE_BAUDRATE=57600\n# comment\n',
        encoding="utf-8",
    )
    load_env_files([env_file])
    cfg = BridgeConfig.from_env()
    assert cfg.command_prefix == "!real"  # first-wins: real env beats file
    assert cfg.meshcore_baudrate == 57600  # quotes stripped, value from file
