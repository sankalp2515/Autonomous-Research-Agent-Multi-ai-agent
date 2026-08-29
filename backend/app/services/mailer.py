"""Transactional email — currently just org invites.

Design: NEVER fail a user action on email. If SMTP is unconfigured (dev), or a
send errors, we log the intended message (including the invite link) and return
False, so the caller proceeds regardless. Configure SMTP_* to actually send.
"""

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("mailer")


def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    """Best-effort send. Returns True if handed to an SMTP server, else False
    (and logs). Runs synchronously — call via asyncio.to_thread from async code."""
    settings = get_settings()
    if not settings.smtp_host:
        logger.info("email (no SMTP configured — not sent)",
                    extra={"to": to, "subject": subject})
        return False
    try:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text or "This message requires an HTML-capable client.")
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        logger.info("email sent", extra={"to": to, "subject": subject})
        return True
    except Exception as exc:
        logger.warning("email send failed", extra={"to": to, "error": str(exc)[:160]})
        return False


def send_org_invite(to: str, org_name: str, inviter: str, role: str) -> bool:
    settings = get_settings()
    link = settings.app_base_url.rstrip("/")
    subject = f"You're invited to the “{org_name}” workspace on Veriscope"
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#8c2f39">You've been invited to Veriscope</h2>
      <p>{_esc(inviter)} invited you to join the <strong>{_esc(org_name)}</strong>
         workspace as <strong>{_esc(role)}</strong>.</p>
      <p>Sign in with <strong>this email address</strong> to join automatically:</p>
      <p><a href="{link}" style="background:#8c2f39;color:#fff;padding:10px 18px;
         border-radius:8px;text-decoration:none">Open Veriscope →</a></p>
      <p style="color:#77796b;font-size:13px">If you didn't expect this, you can ignore it.</p>
    </div>"""
    text = (f"{inviter} invited you to the '{org_name}' workspace on Veriscope as "
            f"{role}. Sign in with this email to join: {link}")
    return send_email(to, subject, html, text)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
