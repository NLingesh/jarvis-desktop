import asyncio
import email
import imaplib
import logging
import os
import smtplib
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class MailSession:
    """A single authenticated IMAP/SMTP connection.

    Each authenticated user gets their own MailSession, so credentials and
    connection state are never shared between tokens. Blocking imaplib/smtplib
    calls are dispatched to a worker thread so the event loop stays responsive.
    """

    def __init__(
        self,
        email_address: str,
        password: str,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.email_address = email_address
        self._password = password
        self.imap_server = imap_server
        self.imap_port = int(imap_port)
        self.smtp_server = smtp_server
        self.smtp_port = int(smtp_port)
        self._connection: imaplib.IMAP4_SSL | None = None

    # -- connection lifecycle -------------------------------------------------

    async def authenticate(self) -> bool:
        """Open an IMAP connection and log in. Returns True on success."""
        return await asyncio.to_thread(self._connect)

    def _connect(self) -> bool:
        try:
            conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            conn.login(self.email_address, self._password)
            self._connection = conn
            logger.info("Authenticated %s via %s", self.email_address, self.imap_server)
            return True
        except Exception as e:
            logger.error("IMAP authentication failed for %s: %s", self.email_address, e)
            self._connection = None
            return False

    def _ensure_connected(self) -> bool:
        if self._connection is not None:
            return True
        return self._connect()

    async def close(self) -> None:
        await asyncio.to_thread(self._logout)

    def _logout(self) -> None:
        conn, self._connection = self._connection, None
        if conn is not None:
            try:
                conn.logout()
            except Exception as e:
                logger.warning("IMAP logout failed: %s", e)

    # -- reading --------------------------------------------------------------

    async def get_recent_emails(self, limit: int = 5, folder: str = "INBOX") -> list[dict]:
        return await asyncio.to_thread(self._get_recent_emails, limit, folder)

    def _get_recent_emails(self, limit: int, folder: str) -> list[dict]:
        if not self._ensure_connected():
            return []

        try:
            self._connection.select(folder)
            _, message_numbers = self._connection.search(None, "ALL")
            email_ids = message_numbers[0].split()[-limit:]

            emails = []
            for email_id in reversed(email_ids):
                _, msg_data = self._connection.fetch(email_id, "(RFC822)")

                msg = email.message_from_bytes(msg_data[0][1])
                emails.append(
                    {
                        "from": self._decode_header(msg.get("From", "Unknown")),
                        "subject": self._decode_header(msg.get("Subject", "(No Subject)")),
                        "body": self._get_email_body(msg)[:200],
                        "date": msg.get("Date", ""),
                        "id": email_id.decode(),
                    }
                )

            return emails
        except Exception as e:
            logger.error("Failed to fetch emails for %s: %s", self.email_address, e)
            return []

    async def get_unread_emails(self, limit: int = 10) -> list[dict]:
        return await asyncio.to_thread(self._get_unread_emails, limit)

    def _get_unread_emails(self, limit: int) -> list[dict]:
        if not self._ensure_connected():
            return []

        try:
            self._connection.select("INBOX")
            _, message_numbers = self._connection.search(None, "UNSEEN")
            email_ids = message_numbers[0].split()[-limit:]

            emails = []
            for email_id in reversed(email_ids):
                _, msg_data = self._connection.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                emails.append(
                    {
                        "from": self._decode_header(msg.get("From", "Unknown")),
                        "subject": self._decode_header(msg.get("Subject", "(No Subject)")),
                        "id": email_id.decode(),
                    }
                )

            return emails
        except Exception as e:
            logger.error("Failed to fetch unread emails for %s: %s", self.email_address, e)
            return []

    # -- writing --------------------------------------------------------------

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> bool:
        return await asyncio.to_thread(self._send_email, to, subject, body, cc, bcc)

    def _send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None,
        bcc: str | None,
    ) -> bool:
        try:
            msg = MIMEMultipart()
            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.email_address, self._password)

                recipients = [to]
                if cc:
                    recipients.extend(cc.split(","))
                if bcc:
                    recipients.extend(bcc.split(","))

                smtp.sendmail(self.email_address, recipients, msg.as_string())

            logger.info("Email sent from %s to %s", self.email_address, to)
            return True
        except Exception as e:
            logger.error("Failed to send email: %s", e)
            return False

    async def mark_as_read(self, email_id: str) -> bool:
        return await asyncio.to_thread(self._set_flag, email_id, "\\Seen")

    async def delete_email(self, email_id: str) -> bool:
        return await asyncio.to_thread(self._set_flag, email_id, "\\Deleted")

    def _set_flag(self, email_id: str, flag: str) -> bool:
        if not self._ensure_connected():
            return False
        try:
            self._connection.store(email_id, "+FLAGS", flag)
            return True
        except Exception as e:
            logger.error("Failed to set flag %s: %s", flag, e)
            return False

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _decode_header(header_text: str) -> str:
        if not header_text:
            return ""
        try:
            decoded_parts = decode_header(header_text)
            result = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    result += part.decode(encoding or "utf-8", errors="ignore")
                else:
                    result += part
            return result
        except Exception:
            return header_text

    @staticmethod
    def _get_email_body(msg) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        return body.strip()


class MailModule:
    """Factory for creating per-user MailSessions from environment defaults."""

    def __init__(
        self,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.imap_server = os.getenv("EMAIL_IMAP_SERVER", imap_server)
        self.imap_port = int(os.getenv("EMAIL_IMAP_PORT", imap_port))
        self.smtp_server = os.getenv("EMAIL_SMTP_SERVER", smtp_server)
        self.smtp_port = int(os.getenv("EMAIL_SMTP_PORT", smtp_port))

    def create_session(self, email_address: str, password: str) -> MailSession:
        return MailSession(
            email_address=email_address,
            password=password,
            imap_server=self.imap_server,
            imap_port=self.imap_port,
            smtp_server=self.smtp_server,
            smtp_port=self.smtp_port,
        )


class MailSessionStore:
    """Maps mail session tokens to live MailSessions.

    Token validity (and expiry) is enforced by MemoryManager's `mail_sessions`
    table; this store only holds the in-memory authenticated connections.
    """

    def __init__(self, memory_manager):
        self._memory = memory_manager
        self._sessions: dict[str, MailSession] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        email: str,
        password: str,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993,
    ) -> tuple[str | None, bool]:
        session = MailSession(
            email_address=email,
            password=password,
            imap_server=imap_server,
            imap_port=imap_port,
        )
        if not await session.authenticate():
            return None, False

        token = await self._memory.create_mail_session(email)
        async with self._lock:
            self._sessions[token] = session
        return token, True

    async def get(self, token: str) -> MailSession | None:
        """Return the live session for a valid, non-expired token, else None."""
        if not await self._memory.get_mail_session(token):
            return None
        async with self._lock:
            return self._sessions.get(token)

    async def most_recent(self) -> MailSession | None:
        """Return the most recently created session (for the voice skill path)."""
        async with self._lock:
            if not self._sessions:
                return None
            return next(reversed(list(self._sessions.values())))
