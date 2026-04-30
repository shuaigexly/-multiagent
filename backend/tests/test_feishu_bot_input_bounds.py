def test_bot_text_is_trimmed_and_bounded(monkeypatch):
    from app.api import feishu_bot

    monkeypatch.setattr(feishu_bot, "_MAX_BOT_TEXT_CHARS", 120)

    normalized = feishu_bot._normalize_bot_text("  " + ("x" * 200) + "  ")

    assert len(normalized) == 120
    assert normalized.endswith("[truncated]")
    assert not normalized.startswith(" ")
