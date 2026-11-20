import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("clinic_faq.emailer")

def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """
    Sends email using Resend, Brevo, or SMTP based on settings.EMAIL_PROVIDER.
    Returns True if delivery succeeded, False otherwise.
    """
    if not to_email:
        logger.error("No recipient specified for send_email")
        return False
        
    provider = (settings.EMAIL_PROVIDER or "resend").lower()
    
    if provider == "resend":
        try:
            import resend
            if not settings.RESEND_API_KEY:
                logger.warning("Email provider is not configured; no email was sent.")
                return False
                
            resend.api_key = settings.RESEND_API_KEY
            params = {
                "from": settings.MAIL_FROM,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }
            if text_body:
                params["text"] = text_body
                
            response = resend.Emails.send(params)
            if response and getattr(response, "id", None):
                logger.info(f"Email delivered via Resend with ID: {response.id}")
                return True
            elif isinstance(response, dict) and "id" in response:
                logger.info(f"Email delivered via Resend with ID: {response['id']}")
                return True
            else:
                logger.error(f"Resend returned unexpected response: {response}")
                return False
        except Exception as e:
            logger.error(f"Error sending email via Resend: {e}")
            return False

    elif provider == "brevo":
        if not settings.BREVO_API_KEY or not settings.MAIL_FROM:
            logger.warning("Email provider is not configured; no email was sent.")
            return False

        payload = {
            "sender": {"email": settings.MAIL_FROM},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_body,
        }
        if text_body:
            payload["textContent"] = text_body

        try:
            response = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": settings.BREVO_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10.0,
            )
        except Exception as e:
            logger.error(f"Error sending email via Brevo: {type(e).__name__}: {e}")
            return False

        if 200 <= response.status_code < 300:
            logger.info(f"Email delivered via Brevo with status {response.status_code}")
            return True

        try:
            error_message = str(response.json().get("message", ""))
        except Exception:
            error_message = ""
        for sensitive in (to_email, html_body, text_body):
            if sensitive:
                error_message = error_message.replace(sensitive, "[redacted]")
        logger.error(f"Brevo returned status {response.status_code}: {error_message}")
        return False

    elif provider == "smtp":
        try:
            if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
                logger.warning("Email provider is not configured; no email was sent.")
                return False
                
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.MAIL_FROM or settings.SMTP_USER
            msg["To"] = to_email
            
            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
            
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(msg["From"], [to_email], msg.as_string())
                
            logger.info(f"Email delivered via SMTP to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Error sending email via SMTP: {e}")
            return False
    else:
        logger.error(f"Unknown email provider: {provider}")
        return False
