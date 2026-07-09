"""邮件发送：支持 SSL(465) 与 STARTTLS(587)，multipart 同时携带纯文本与 HTML。"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@retry(reraise=True, stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=15))
def send_email(html: str, text: str, subject: str, env: dict) -> None:
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT") or 465)
    user = env["SMTP_USER"]
    password = env["SMTP_PASSWORD"]
    mail_from = env.get("MAIL_FROM") or user
    mail_to = [x.strip() for x in str(env["MAIL_TO"]).split(",") if x.strip()]
    use_ssl = _truthy(env.get("SMTP_USE_SSL")) or port == 465

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, password)
            s.sendmail(mail_from, mail_to, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(user, password)
            s.sendmail(mail_from, mail_to, msg.as_string())
    logger.info("邮件已发送 -> %s", ", ".join(mail_to))
