import asyncio
from types import SimpleNamespace

from meshcore_matrix_bridge.commands import CommandHandler, _fmt_hops, fmt_msg


def make_handler(bridge=None):
    return CommandHandler(node=SimpleNamespace(), bridge=bridge, prefix="!mesh")


def test_matches_prefix_only_and_with_args():
    h = make_handler()
    assert h.matches("!mesh")
    assert h.matches("!mesh help")
    assert h.matches("\n\n!mesh status\nsecond line")
    assert not h.matches("!meshx help")
    assert not h.matches("hello !mesh")


def test_dispatch_ping():
    h = make_handler()
    res = asyncio.run(h.dispatch("!mesh ping"))
    assert res.plain == "pong"


def test_dispatch_help_lists_prefix():
    h = make_handler()
    res = asyncio.run(h.dispatch("!mesh help"))
    assert "!mesh" in res.plain
    assert "dm" in res.plain


def test_dispatch_survives_unbalanced_quote():
    sent = {}

    async def send_dm(target, text):
        sent["target"], sent["text"] = target, text
        return {"ok": True}

    bridge = SimpleNamespace(send_dm=send_dm)
    h = make_handler(bridge=bridge)
    # an apostrophe must not raise shlex.ValueError / kill the command
    res = asyncio.run(h.dispatch("!mesh dm Bob don't panic"))
    assert "✓" in res.plain
    assert sent["target"] == "Bob"
    assert sent["text"] == "don't panic"


def test_dispatch_quoted_target_still_works():
    sent = {}

    async def send_dm(target, text):
        sent["target"], sent["text"] = target, text
        return {"ok": True}

    bridge = SimpleNamespace(send_dm=send_dm)
    h = make_handler(bridge=bridge)
    res = asyncio.run(h.dispatch('!mesh dm "Node One" hello'))
    assert "✓" in res.plain
    assert sent["target"] == "Node One"
    assert sent["text"] == "hello"


def test_fmt_hops_conventions():
    assert _fmt_hops(None) == "hops=?"
    assert _fmt_hops(-1) == "hops=flood"
    assert _fmt_hops(0) == "hops=0"
    assert _fmt_hops(3) == "hops=3"
    assert _fmt_hops("junk") == "hops=junk"


def test_fmt_msg_escapes_html_from_the_radio():
    node = SimpleNamespace(mc=None)
    payload = {
        "text": "<script>alert(1)</script>",
        "channel_idx": 2,
        "pubkey_prefix": "ab12cd34ef56",
        "SNR": 9.5,
        "path_len": 1,
        "sender_timestamp": None,
    }
    plain, html = fmt_msg("chan", payload, node)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>" in plain  # plain text is not HTML, no escaping expected
