# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import asyncio
import email
import logging
import re
import time
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import aioimaplib
import aiosmtplib

from ainara.framework.connectors.base import BaseConnector, capability

logger = logging.getLogger(__name__)


class HTMLStripper(HTMLParser):
    """Simple HTML stripper to convert email HTML bodies to text."""

    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return "".join(self.text)


class EmailConnector(BaseConnector):
    """
    A connector for IMAP/SMTP email services.
    Supports multiple accounts and maps them to the 'messages' contract.
    """

    @property
    def MANIFEST(self) -> Dict[str, Any]:
        return {
            "id": "email",
            "version": "1.0",
            "description": "Multi-account IMAP/SMTP Email Connector",
            "capabilities": ["messages"],
            "required_config": ["apis.messaging.email.accounts"],
        }

    def _get_accounts(self) -> List[Dict[str, Any]]:
        """Retrieve the list of configured accounts."""
        raw_accounts = self.config.get("apis.messaging.email.accounts", [])
        if not isinstance(raw_accounts, list):
            logger.warning("email.accounts config must be a list of dicts; skipping")
            return []

        valid_accounts = []
        for raw_acc in raw_accounts:
            if self._validate_account(raw_acc):
                valid_accounts.append(raw_acc)
            else:
                acc_id = raw_acc.get("id", "unknown") if isinstance(raw_acc, dict) else "unknown"
                logger.warning(f"Skipped invalid account '{acc_id}'")
        return valid_accounts

    def _validate_account(self, acc: Any) -> bool:
        """Validate account config fields with regex/checks."""
        if not isinstance(acc, dict):
            logger.warning("Account must be dict")
            return False

        acc_id = acc.get("id", "unknown")
        req_fields = ["imap_host", "username", "password"]
        for field in req_fields:
            if not acc.get(field):
                logger.error(f"Missing '{field}' in account '{acc_id}'")
                return False

        # Hostname regex (common email domains)
        host = acc["imap_host"].strip().lower()
        if not re.match(
            r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.(com|net|org|edu|gov|mil|int|io|co\.uk|gmail\.com|outlook\.com|live\.com|icloud\.com|yahoo\.com|protonmail\.com|fastmail\.com)$",
            host
        ):
            logger.error(f"Invalid IMAP host '{acc['imap_host']}' in '{acc_id}' (e.g., imap.gmail.com)")
            return False

        # Port
        try:
            port = int(acc.get("imap_port", 993))
            if port not in (143, 993, 465, 587):
                raise ValueError("Invalid port")
        except ValueError as ve:
            logger.error(f"Invalid port '{acc.get('imap_port')}' in '{acc_id}': {ve}")
            return False

        # Username (basic email)
        username = acc["username"].strip()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", username):
            logger.error(f"Invalid username '{username}' in '{acc_id}'")
            return False

        # Password (warn short/suspicious)
        pw = acc["password"]
        if len(pw) < 8:
            logger.warning(f"Suspicious short password (len={len(pw)}) in '{acc_id}'")

        logger.info(f"Validated account '{acc_id}'")
        return True

    def _get_account_by_id(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Find a specific account configuration by its ID."""
        for acc in self._get_accounts():
            if acc.get("id") == account_id:
                return acc
        return None

    def _decode_header_str(self, header_value: str) -> str:
        """Decode email header values (Subject, From, etc.)."""
        if not header_value:
            return ""
        decoded_list = decode_header(header_value)
        text_parts = []
        for content, encoding in decoded_list:
            if isinstance(content, bytes):
                if encoding:
                    try:
                        text_parts.append(content.decode(encoding))
                    except LookupError:
                        text_parts.append(
                            content.decode("utf-8", errors="replace")
                        )
                else:
                    text_parts.append(
                        content.decode("utf-8", errors="replace")
                    )
            else:
                text_parts.append(str(content))
        return "".join(text_parts)

    def _strip_html(self, html_content: str) -> str:
        """Remove HTML tags to get clean text for the LLM."""
        s = HTMLStripper()
        s.feed(html_content)
        return s.get_data().strip()

    def _extract_body(self, msg: email.message.Message) -> str:
        """
        Extract the best available body content.
        Prioritizes text/plain, falls back to text/html (stripped).
        """
        body_text = ""
        body_html = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    # Attempt to decode with common charsets
                    charset = part.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")

                    if content_type == "text/plain":
                        body_text += decoded
                    elif content_type == "text/html":
                        body_html += decoded
                except Exception as e:
                    logger.warning(f"Error decoding email part: {e}")
        else:
            # Not multipart
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    if msg.get_content_type() == "text/html":
                        body_html = decoded
                    else:
                        body_text = decoded
            except Exception as e:
                logger.warning(f"Error decoding email body: {e}")

        if body_text.strip():
            return body_text.strip()
        if body_html.strip():
            return self._strip_html(body_html)

        return "[No readable content]"

    async def _fetch_account_messages(
        self, account: Dict[str, Any], limit: int, unread_only: bool
    ) -> List[Dict[str, Any]]:
        """Fetch messages from a single account."""
        if not isinstance(account, dict):
            logger.warning(f"Invalid account type: {type(account).__name__}")
            return []
        messages = []
        account_id = account.get("id", "unknown")
        host = account.get("imap_host")
        port = int(account.get("imap_port", 993))
        user = account.get("username")
        password = account.get("password")

        if not (host and user and password):
            logger.error(f"Missing config for email account {account_id}")
            return []

        client = aioimaplib.IMAP4_SSL(host=host, port=port)

        try:
            await client.wait_hello_from_server()
            logger.info(f"Login attempt: user={user} host={host}:{port} unread_only={unread_only}")
            await client.login(user, password)
            await client.select("INBOX")

            criteria = "UNSEEN" if unread_only else "ALL"
            # Search returns: (status, [b'1 2 3'])
            res, data = await client.search(criteria)

            if res != "OK" or not data or not data[0]:
                await client.logout()
                return []

            # Get list of message IDs
            id_list = data[0].split()
            # Reverse to get newest first
            id_list.reverse()

            # Apply limit at the fetch level to save bandwidth
            if limit > 0:
                id_list = id_list[:limit]

            for msg_id in id_list:
                # fetch headers and body structure
                # rfc822 fetches the whole raw message
                res, msg_data = await client.fetch(msg_id.decode(), "(BODY.PEEK[])")
                if res != "OK":
                    logger.info(f"res, msg_data: {res} {msg_data}")
                    continue

                raw_email = msg_data[1] if len(msg_data) > 1 else None
                if not raw_email:
                    continue

                email_msg = email.message_from_bytes(raw_email)

                # Parse Date
                date_str = email_msg.get("Date")
                timestamp = time.time()
                if date_str:
                    try:
                        dt = parsedate_to_datetime(date_str)
                        timestamp = dt.timestamp()
                    except Exception:
                        pass

                # Determine read status (if we searched UNSEEN, it's unread)
                # But if we searched ALL, we need to check flags.
                # For simplicity in this stateless connector, we assume
                # if we asked for unread_only, they are unread.
                # If we asked for ALL, we might need to fetch FLAGS.
                # Let's assume unread=False unless we know otherwise for now,
                # or rely on the fact that 'UNSEEN' search was used.
                is_read = not unread_only

                # If we are not filtering by unread, we should ideally check flags
                # but fetching RFC822 usually doesn't give flags in the same block
                # depending on server response format.
                # To be precise, we'd fetch "(FLAGS RFC822)".

                msg_obj = {
                    "id": f"{account_id}:{msg_id}",
                    "source": "email",
                    "sender": self._decode_header_str(email_msg.get("From")),
                    "content": self._extract_body(email_msg),
                    "timestamp": timestamp,
                    "is_read": (
                        is_read
                    ),  # Approximation if not fetching flags explicitly
                    "subject": self._decode_header_str(
                        email_msg.get("Subject")
                    ),
                    "metadata": {
                        "account": account_id,
                        "to": self._decode_header_str(email_msg.get("To")),
                    },
                }
                messages.append(msg_obj)

            await client.logout()

        except Exception as e:
            logger.error(f"Error fetching emails for {account_id}: {e}")
            try:
                await client.logout()
            except Exception:
                pass

        return messages

    @capability(contract="messages", path="/messages", method="GET")
    async def get_messages(
        self,
        limit: int = 0,
        unread_only: bool = True,
        source: str = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve messages from configured email accounts.
        """
        accounts = self._get_accounts()
        tasks = []

        # If source is specified, check if it matches 'email' or a specific account ID
        target_accounts = accounts
        if source and source != "email":
            # Try to find specific account
            filtered = [a for a in accounts if a.get("id") == source]
            if not filtered:
                # Source specified but not found in email accounts
                return []
            target_accounts = filtered
            if not isinstance(target_accounts, list):
                logger.warning("Invalid target_accounts; returning empty")
                return []

        for acc in target_accounts:
            # Distribute limit across accounts?
            # For now, we pass the full limit to each and slice later.
            tasks.append(self._fetch_account_messages(acc, limit, unread_only))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and filter exceptions
        all_messages = []
        for subres in results:
            if isinstance(subres, Exception):
                logger.warning(f"Account fetch failed: {subres}")
                continue
            all_messages.extend(subres or [])

        # Sort by timestamp descending
        all_messages.sort(key=lambda x: x["timestamp"], reverse=True)

        if limit > 0:
            all_messages = all_messages[:limit]

        return all_messages

    @capability(contract="messages", path="/messages", method="POST")
    async def send_message(
        self, target_id: str, content: str, **kwargs
    ) -> Dict[str, str]:
        """
        Send an email.
        Uses the first configured account as the sender.
        """
        accounts = self._get_accounts()
        if not accounts:
            raise ValueError("No email accounts configured")

        # Default to first account
        account = accounts[0]

        smtp_host = account.get("smtp_host")
        smtp_port = int(account.get("smtp_port", 587))
        username = account.get("username")
        password = account.get("password")

        if not (smtp_host and username and password):
            raise ValueError("Missing SMTP config for primary account")

        message = MIMEText(content)
        message["From"] = username
        message["To"] = target_id
        message["Subject"] = "Message from Ainara"  # Default subject

        try:
            await aiosmtplib.send(
                message,
                hostname=smtp_host,
                port=smtp_port,
                username=username,
                password=password,
                use_tls=True if smtp_port == 465 else False,
                start_tls=True if smtp_port == 587 else False,
            )
            return {"status": "sent", "target": target_id}
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise e

    @capability(contract="messages", path="/messages/{id}", method="GET")
    async def get_message_details(self, id: str, **kwargs) -> Dict[str, Any]:
        """
        Get details for a specific message.
        ID format: account_id:uid
        """
        if ":" not in id:
            return {}

        account_id, uid = id.split(":", 1)
        account = self._get_account_by_id(account_id)

        if not account:
            return {}

        # Reuse fetch logic but for specific ID
        # This is expensive (re-login), but stateless
        host = account.get("imap_host")
        port = int(account.get("imap_port", 993))
        user = account.get("username")
        password = account.get("password")

        client = aioimaplib.IMAP4_SSL(host=host, port=port)

        try:
            await client.wait_hello_from_server()
            await client.login(user, password)
            await client.select("INBOX")

            res, msg_data = await client.fetch(uid, "(RFC822)")
            if res != "OK" or not msg_data:
                await client.logout()
                return {}

            raw_email = msg_data.individual(b'RFC822')
            if not raw_email:
                await client.logout()
                return {}

            email_msg = email.message_from_bytes(raw_email)

            # Parse Date
            date_str = email_msg.get("Date")
            timestamp = time.time()
            if date_str:
                try:
                    dt = parsedate_to_datetime(date_str)
                    timestamp = dt.timestamp()
                except Exception:
                    pass

            result = {
                "id": id,
                "source": "email",
                "sender": self._decode_header_str(email_msg.get("From")),
                "content": self._extract_body(email_msg),
                "timestamp": timestamp,
                "is_read": True,  # If we are reading details, it's likely read
                "subject": self._decode_header_str(email_msg.get("Subject")),
                "metadata": {
                    "account": account_id,
                    "to": self._decode_header_str(email_msg.get("To")),
                    "cc": self._decode_header_str(email_msg.get("Cc")),
                },
            }

            await client.logout()
            return result

        except Exception as e:
            logger.error(f"Error fetching message details {id}: {e}")
            try:
                await client.logout()
            except Exception:
                pass
            return {}

    @capability(contract="messages", path="/messages/{id}", method="PUT")
    async def update_message_status(
        self, id: str, is_read: bool, **kwargs
    ) -> Dict[str, Any]:
        """
        Update message read status (IMAP Flags).
        """
        if ":" not in id:
            return {"status": "error", "message": "Invalid ID format"}

        account_id, uid = id.split(":", 1)
        account = self._get_account_by_id(account_id)

        if not account:
            return {"status": "not_found"}

        host = account.get("imap_host")
        port = int(account.get("imap_port", 993))
        user = account.get("username")
        password = account.get("password")

        client = aioimaplib.IMAP4_SSL(host=host, port=port)

        try:
            await client.wait_hello_from_server()
            await client.login(user, password)
            await client.select("INBOX")

            action = "+FLAGS" if is_read else "-FLAGS"
            res, data = await client.store(uid, action, "(\\Seen)")

            await client.logout()

            if res == "OK":
                return {"status": "updated", "id": id, "is_read": is_read}
            else:
                return {"status": "error", "message": "IMAP store failed"}

        except Exception as e:
            logger.error(f"Error updating status for {id}: {e}")
            try:
                await client.logout()
            except Exception:
                pass
            return {"status": "error", "message": str(e)}
