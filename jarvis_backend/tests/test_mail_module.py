"""Tests for MailModule / MailSession — auth, per-session isolation, and IMAP interaction."""

import asyncio
from unittest.mock import MagicMock, patch

from modules.mail_module import MailModule, MailSession


def run(coro):
    return asyncio.run(coro)


def test_default_imap_server_from_env(monkeypatch):
    monkeypatch.setenv("EMAIL_IMAP_SERVER", "imap.custom.com")
    monkeypatch.setenv("EMAIL_IMAP_PORT", "993")
    mail = MailModule()
    assert mail.imap_server == "imap.custom.com"
    assert mail.imap_port == 993


def test_create_session_builds_isolated_session():
    mail = MailModule()
    session = mail.create_session("user@example.com", "password123")
    assert isinstance(session, MailSession)
    assert session.email_address == "user@example.com"
    assert session.imap_server == mail.imap_server


def test_authenticate_failure_returns_false():
    session = MailSession("user@example.com", "wrong")
    with patch("modules.mail_module.imaplib.IMAP4_SSL") as mock_imap:
        mock_imap.side_effect = Exception("Connection refused")
        assert run(session.authenticate()) is False


def test_authenticate_success():
    session = MailSession("user@example.com", "password123")
    mock_conn = MagicMock()
    with patch("modules.mail_module.imaplib.IMAP4_SSL", return_value=mock_conn):
        assert run(session.authenticate()) is True
    assert session.email_address == "user@example.com"
    mock_conn.login.assert_called_once_with("user@example.com", "password123")


def test_get_recent_emails_without_connection_returns_empty():
    session = MailSession("user@example.com", "password123")
    with patch.object(session, "_connect", return_value=False):
        assert run(session.get_recent_emails(limit=5)) == []


def test_get_unread_emails_without_connection_returns_empty():
    session = MailSession("user@example.com", "password123")
    with patch.object(session, "_connect", return_value=False):
        assert run(session.get_unread_emails(limit=5)) == []


def test_decode_header_plain_text():
    assert MailSession._decode_header("Hello World") == "Hello World"


def test_decode_header_empty():
    assert MailSession._decode_header("") == ""
    assert MailSession._decode_header(None) == ""
