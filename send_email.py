import os
import smtplib
from email.mime.text import MIMEText

# שולח מייל עם קישור לאתר הסורק - מופעל רק כשנמצאו תוצאות

DEFAULT_URL = "https://gabi-stocks.github.io/capitulation-scanner/"


def main():
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    mail_to = os.environ.get("MAIL_TO") or user
    recipients = [r.strip() for r in mail_to.split(",") if r.strip()]

    count = os.environ.get("SCAN_COUNT", "0")
    tickers = os.environ.get("SCAN_TICKERS", "")
    site_url = os.environ.get("SITE_URL") or DEFAULT_URL

    body = f"""
    <div dir="rtl" style="font-family: Arial; font-size: 15px;">
      <h2>💎 סורק התאוששות אחרי צניחה – נמצאו {count} מניות</h2>
      <p><b>מניות:</b> {tickers}</p>
      <p><a href="{site_url}">לצפייה בטבלה המלאה באתר</a></p>
    </div>
    """

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = f"סורק התאוששות: נמצאו {count} מניות"
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.sendmail(user, recipients, msg.as_string())
    print(f"Email sent ({count} results)")


if __name__ == "__main__":
    main()
