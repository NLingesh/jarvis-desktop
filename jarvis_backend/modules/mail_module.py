import imaplib
import email
import os
from email.header import decode_header
from typing import List, Dict, Optional
import logging
import secrets

logger = logging.getLogger(__name__)

class MailModule:
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
        self.email_address = None
        self.password = None
        self.connection = None

    def authenticate(self, email_address: str, password: str) -> bool:
        """Authenticate with email provider"""
        try:
            self.email_address = email_address
            self.password = password
            self.connection = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.connection.login(email_address, password)
            logger.info(f"Successfully authenticated with {email_address}")
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def create_session_token(self) -> str:
        return secrets.token_urlsafe(32)
    
    async def get_recent_emails(self, limit: int = 5, folder: str = "INBOX") -> List[Dict]:
        """Get recent emails from inbox"""
        if not self.connection:
            return []
        
        try:
            self.connection.select(folder)
            _, message_numbers = self.connection.search(None, "ALL")
            
            # Get the latest emails
            email_ids = message_numbers[0].split()[-limit:]
            
            emails = []
            for email_id in reversed(email_ids):
                _, msg_data = self.connection.fetch(email_id, "(RFC822)")
                
                msg = email.message_from_bytes(msg_data[0][1])
                
                # Extract email details
                sender = self._decode_header(msg.get("From", "Unknown"))
                subject = self._decode_header(msg.get("Subject", "(No Subject)"))
                body = self._get_email_body(msg)
                date = msg.get("Date", "")
                
                emails.append({
                    "from": sender,
                    "subject": subject,
                    "body": body[:200],  # First 200 chars
                    "date": date,
                    "id": email_id.decode()
                })
            
            return emails
        
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return []
    
    async def get_unread_emails(self, limit: int = 10) -> List[Dict]:
        """Get unread emails"""
        if not self.connection:
            return []
        
        try:
            self.connection.select("INBOX")
            _, message_numbers = self.connection.search(None, "UNSEEN")
            
            email_ids = message_numbers[0].split()[-limit:]
            
            emails = []
            for email_id in reversed(email_ids):
                _, msg_data = self.connection.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                
                sender = self._decode_header(msg.get("From", "Unknown"))
                subject = self._decode_header(msg.get("Subject", "(No Subject)"))
                
                emails.append({
                    "from": sender,
                    "subject": subject,
                    "id": email_id.decode()
                })
            
            return emails
        
        except Exception as e:
            logger.error(f"Failed to fetch unread emails: {e}")
            return []
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None
    ) -> bool:
        """Send an email"""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart()
            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject
            
            if cc:
                msg["Cc"] = cc
            
            msg.attach(MIMEText(body, "plain"))
            
            smtp_server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            smtp_server.starttls()
            smtp_server.login(self.email_address, self.password)
            
            recipients = [to]
            if cc:
                recipients.extend(cc.split(","))
            if bcc:
                recipients.extend(bcc.split(","))
            
            smtp_server.sendmail(self.email_address, recipients, msg.as_string())
            smtp_server.quit()
            
            logger.info(f"Email sent to {to}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    async def mark_as_read(self, email_id: str) -> bool:
        """Mark email as read"""
        try:
            self.connection.store(email_id, "+FLAGS", "\\Seen")
            return True
        except Exception as e:
            logger.error(f"Failed to mark email as read: {e}")
            return False
    
    async def delete_email(self, email_id: str) -> bool:
        """Delete an email"""
        try:
            self.connection.store(email_id, "+FLAGS", "\\Deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete email: {e}")
            return False
    
    def _decode_header(self, header_text: str) -> str:
        """Decode email header"""
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
        except:
            return header_text
    
    def _get_email_body(self, msg) -> str:
        """Extract email body"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        
        return body.strip()
