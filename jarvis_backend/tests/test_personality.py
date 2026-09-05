"""Personality configuration: one consistent, concise, honest voice."""

from modules import personality


def test_canned_phrases_are_concise_and_clean():
    samples = [
        personality.done(),
        personality.failure("file not found"),
        personality.unknown_tool(),
        personality.saved("I prefer a male voice"),
        personality.already_saved(),
        personality.forgotten(1),
        personality.forgotten(0),
        personality.nothing_found("voice"),
        personality.confirm_save("likes short replies"),
        personality.confirm_action(),
        personality.confirm_clear_all(),
        personality.cancelled(),
        personality.clarify(None),
    ]
    for text in samples:
        assert 0 < len(text) <= 200
        assert personality.is_in_style(text), text
        # No theatrical exclamation storms or robotic status phrasing.
        assert text.count("!") <= 1
        assert "successfully" not in text.lower()
        assert "sir" not in text.lower()


def test_failure_is_specific_and_honest():
    assert personality.failure("file not found") == "I couldn't complete that — file not found."
    assert personality.failure("") == "I couldn't complete that."


def test_forgotten_variants():
    assert personality.forgotten(1) == "Forgotten."
    assert personality.forgotten(3) == "Forgot 3 items."
    assert "couldn't find" in personality.forgotten(0)


def test_confirm_save_truncates_long_facts():
    long_fact = "x" * 300
    text = personality.confirm_save(long_fact)
    assert len(text) < 200
    assert text.startswith('I picked up a possible preference: "xxx')


def test_style_guard_rejects_banned_phrases():
    assert not personality.is_in_style("Command executed successfully.")
    assert not personality.is_in_style("As you wish, sir.")
    assert not personality.is_in_style("At your service, sir!")


def test_style_guard_rejects_stuttering_repetition():
    assert not personality.is_in_style("Opened the folder opened the folder opened the folder.")


def test_style_guard_accepts_normal_replies():
    assert personality.is_in_style("VS Code is already running.")
    assert personality.is_in_style("I couldn't find that file.")
    assert personality.is_in_style("Done. Anything else?")
