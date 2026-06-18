"""Skill for a daily 9 a.m. Eastern reminder to Jordan about the morning ritual.

Scheduling is handled by the framework OrakleScheduler via the `default_schedule`
class attribute below (persistent SQLAlchemy jobstore, survives Orakle restarts).
This skill only implements immediate delivery ('send_now') and a 'status' query;
it does NOT hand-roll its own scheduler.
"""

import logging
import re
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated, Any, Dict, Literal, Optional

from ainara.framework.config import config
from ainara.framework.skill import Skill


def _camel_to_snake(name: str) -> str:
    """Mirror the capability registry's class-name -> capability-name mapping."""
    name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


class MessagingDailyMorningRitualReminder(Skill):
    """Sends a daily 9 a.m. Eastern reminder to Jordan about completing the morning ritual"""

    embeddings_boost_factor = 2

    matcher_info = (
        "Use when the user wants to send, test, schedule, or check the status of "
        "the daily morning ritual / habit reminder (workout, meditation, diet rules, "
        "gym sessions). Also use for 'send me a test reminder/notification', "
        "'email me my reminder', or 'is my reminder scheduled / what time'."
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        # Registered automatically by the framework OrakleScheduler at startup.
        # Persistent across restarts (SQLAlchemy jobstore). Must be set as an
        # instance attribute (the base class resets default_schedule to None).
        # To disable or retime, set in ainara.yaml:
        #   scheduler:
        #     overrides:
        #       messaging_daily_morning_ritual_reminder: false   # disable
        self.default_schedule = {
            "trigger": "cron",
            "hour": 9,
            "minute": 0,
            "timezone": "America/New_York",
            "kwargs": {"action": "send_now", "delivery_method": "email"},
            "default": True,
        }

    def _build_message(self, recipient_name: str, ritual_items: str) -> str:
        items = [item.strip() for item in ritual_items.split(',') if item.strip()]
        ritual_text = '\n'.join(f"• {item}" for item in items)
        return f"Good morning {recipient_name},\n\nTime for your morning ritual:\n{ritual_text}\n\nHave a great day!"

    def _resolve_smtp_credentials(self):
        """Resolve SMTP send credentials.

        Prefers an explicit notifications.email.* block, but falls back to the
        IMAP accounts the setup wizard stores under apis.messaging.email.accounts.
        For most providers (Gmail, Outlook, etc.) the same username/password used
        for IMAP also works for SMTP, so we derive the SMTP host from the IMAP host.
        """
        smtp_user = config.get("notifications.email.smtp_user") or ""
        smtp_password = config.get("notifications.email.smtp_password") or ""
        smtp_host = config.get("notifications.email.smtp_host") or ""
        smtp_port = config.get("notifications.email.smtp_port")
        from_addr = config.get("notifications.email.from_address") or ""

        # Fall back to the wizard's IMAP account if no explicit SMTP config
        if not smtp_user or not smtp_password:
            accounts = config.get("apis.messaging.email.accounts") or []
            if accounts:
                acc = accounts[0]
                smtp_user = acc.get("username", "")
                smtp_password = acc.get("password", "")
                imap_host = acc.get("imap_host", "")
                # imap.gmail.com -> smtp.gmail.com, imap-mail.outlook.com -> smtp-mail.outlook.com
                if imap_host and not smtp_host:
                    smtp_host = imap_host.replace("imap", "smtp", 1)

        smtp_host = smtp_host or "smtp.gmail.com"
        smtp_port = int(smtp_port or 587)
        from_addr = from_addr or smtp_user
        # Gmail app passwords are shown as "xxxx xxxx xxxx xxxx" but must be sent
        # without spaces over SMTP, otherwise auth fails with BadCredentials.
        smtp_password = smtp_password.replace(" ", "")

        return smtp_host, smtp_port, smtp_user, smtp_password, from_addr

    def _resolve_recipient(self, recipient_email: Optional[str]) -> str:
        accounts = config.get("apis.messaging.email.accounts") or []
        wizard_user = accounts[0].get("username") if accounts else None
        return (
            recipient_email
            or config.get("notifications.email.default_recipient")
            or wizard_user
            or ""
        )

    def _send_email(self, recipient_email: str, message_body: str) -> str:
        smtp_host, smtp_port, smtp_user, smtp_password, from_addr = (
            self._resolve_smtp_credentials()
        )

        if not smtp_user or not smtp_password:
            return (
                "Email not configured. Either add an email account in the Ainara "
                "setup wizard (Messaging section), or add an explicit SMTP block to "
                "ainara.yaml under notifications.email (smtp_user, smtp_password)."
            )

        msg = MIMEMultipart()
        msg['Subject'] = 'Morning Ritual Reminder'
        msg['From'] = from_addr
        msg['To'] = recipient_email
        msg.attach(MIMEText(message_body, 'plain'))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            return (
                "Email login was rejected by the mail server. For Gmail this means "
                "the App Password is wrong, revoked, or 2-Step Verification is off. "
                "Generate a fresh App Password at myaccount.google.com/apppasswords "
                "and paste it into the setup wizard."
            )
        return f"Email sent to {recipient_email}"

    def _send_desktop_notification(self, title: str, message: str) -> str:
        safe_title = title.replace('"', "'")
        safe_message = message[:200].replace('"', "'").replace('\n', ' ')

        if sys.platform == 'win32':
            # Use PowerShell's pre-registered AppUserModelID. A custom/unregistered
            # AppId (e.g. "Ainara") causes Windows to silently SUPPRESS the toast —
            # the script returns success but nothing ever appears on screen.
            app_id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
            ps_script = (
                '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;'
                '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;'
                f'$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;'
                f'$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric"><text>{safe_title}</text><text>{safe_message}</text></binding></visual></toast>\');'
                '$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);'
                f'$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}");'
                '$notifier.Show($toast)'
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
                capture_output=True, timeout=15
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip())
        elif sys.platform == 'darwin':
            subprocess.run(
                ['osascript', '-e', f'display notification "{safe_message}" with title "{safe_title}"'],
                capture_output=True, timeout=10
            )
        else:
            subprocess.run(
                ['notify-send', title, message[:200]],
                capture_output=True, timeout=10
            )
        return (
            "Desktop notification sent. If you don't see it, check that Windows "
            "Focus Assist / Do Not Disturb is off and notifications are enabled."
        )

    def _schedule_status(self) -> Dict[str, Any]:
        """Report whether the framework scheduler has the daily job registered."""
        snake = _camel_to_snake(self.name)
        try:
            from ainara.orakle import scheduler as orakle_scheduler
            inst = orakle_scheduler._scheduler_instance
            if inst is not None:
                job = inst.scheduler.get_job(f"job_{snake}")
                if job is not None and getattr(job, "next_run_time", None):
                    when = job.next_run_time.strftime('%A %Y-%m-%d at %H:%M %Z')
                    return {
                        "success": True,
                        "result": f"The daily reminder is active. Next send: {when}.",
                    }
            return {
                "success": True,
                "result": (
                    "Configured to send daily at 09:00 America/New_York by email, "
                    "but no live scheduled job was found. Restart Orakle so the "
                    "schedule registers."
                ),
            }
        except Exception as e:
            return {
                "success": True,
                "result": (
                    "Configured to send daily at 09:00 America/New_York by email. "
                    f"(Could not read the live scheduler: {e})"
                ),
            }

    async def run(
        self,
        action: Annotated[
            Literal['send_now', 'status'],
            "send_now: deliver the reminder immediately; status: report whether the daily 9am schedule is active",
        ] = 'send_now',
        delivery_method: Annotated[
            Literal['email', 'desktop_notification'],
            "How the reminder should be delivered",
        ] = 'email',
        recipient_name: Annotated[str, "First name of the person receiving the reminder"] = "Jordan",
        recipient_email: Annotated[Optional[str], "Email address (optional; falls back to configured account)"] = None,
        ritual_items: Annotated[Optional[str], "Comma-separated list of ritual activities to include in reminder"] = "light workout, meditation, no sugar, no processed food, gym workout, clean eating",
    ) -> Dict[str, Any]:
        """Executes the daily morning ritual reminder skill"""
        try:
            if action == 'status':
                return self._schedule_status()

            message_body = self._build_message(recipient_name, ritual_items or "")

            if delivery_method == 'email':
                email_addr = self._resolve_recipient(recipient_email)
                if not email_addr:
                    return {
                        "success": False,
                        "error": "No recipient email available. Pass recipient_email or configure an email account.",
                    }
                result = self._send_email(email_addr, message_body)
            else:
                result = self._send_desktop_notification(
                    "Morning Ritual Reminder", message_body
                )

            return {"success": True, "result": result}
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            return {"success": False, "error": str(e)}
