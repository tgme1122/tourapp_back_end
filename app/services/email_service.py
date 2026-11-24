import smtplib
from email.message import EmailMessage

from app.config import settings


def send_email(to: str, subject: str, body: str) -> None:
    # SMTP sozlanmagan bo'lsa (development) terminalga chiqaramiz
    if not settings.SMTP_HOST:
        print(f"\n[EMAIL -> {to}] {subject}\n{body}\n")
        return

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


def send_verification_code(to: str, code: str) -> None:
    send_email(
        to,
        "SayohatApp: emailni tasdiqlash kodi",
        f"Tasdiqlash kodingiz: {code}\n"
        f"Kod {settings.EMAIL_CODE_TTL_MINUTES} daqiqa amal qiladi.\n"
        "Agar bu so'rovni siz yubormagan bo'lsangiz, xatni e'tiborsiz qoldiring.",
    )

def send_agency_decision(to: str, agency_name: str, decision: str, reason: str | None = None) -> None:
    if decision == "approved":
        subject = "SayohatApp: agentligingiz tasdiqlandi"
        body = (f"«{agency_name}» agentligi tasdiqlandi.\n"
                "Endi tur qo'shishingiz va bronlarni qabul qilishingiz mumkin.")
    elif decision == "rejected":
        subject = "SayohatApp: ariza rad etildi"
        body = (f"«{agency_name}» agentligi arizasi rad etildi.\nSabab: {reason}\n"
                "Hujjatlarni to'g'rilab, arizani qayta yuborishingiz mumkin.")
    else:
        subject = "SayohatApp: agentligingiz bloklandi"
        body = f"«{agency_name}» agentligi bloklandi.\nSabab: {reason}"
    send_email(to, subject, body)