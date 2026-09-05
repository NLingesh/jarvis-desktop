"""Secret-pattern filtering for long-term memory persistence."""

from modules.memory_safety import is_sensitive_memory


def test_plain_preferences_are_allowed():
    assert not is_sensitive_memory("I prefer a male voice")
    assert not is_sensitive_memory("This is my main JARVIS project")
    assert not is_sensitive_memory("I like concise answers")


def test_passwords_are_rejected():
    assert is_sensitive_memory("my password is hunter2")
    assert is_sensitive_memory("password: correct-horse-battery")
    assert is_sensitive_memory("remember my password")


def test_api_keys_and_tokens_are_rejected():
    assert is_sensitive_memory("my api key is sk-abc123def456ghi789")
    assert is_sensitive_memory("access token = ghp_16CharactersXXXXXXXXX")
    assert is_sensitive_memory("bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc")
    assert is_sensitive_memory("AWS key AKIAIOSFODNN7EXAMPLE")
    assert is_sensitive_memory("google api key AIzaSyA1234567890abcdefghijklmnopqrstuv")


def test_private_key_material_is_rejected():
    assert is_sensitive_memory("-----BEGIN RSA PRIVATE KEY-----")
    assert is_sensitive_memory("-----BEGIN OPENSSH PRIVATE KEY-----")


def test_long_hex_and_token_shaped_blobs_are_rejected():
    assert is_sensitive_memory("checksum d41d8cd98f00b204e9800998ecf8427eaa")
    assert is_sensitive_memory("the secret is AbC123+/xyZ456==_more-than-24-chars")


def test_storage_verbs_with_credential_nouns_are_rejected():
    assert is_sensitive_memory("remember my credentials for work")
    assert is_sensitive_memory("store the private key in memory")


def test_empty_is_safe():
    assert not is_sensitive_memory("")
    assert not is_sensitive_memory(None)
