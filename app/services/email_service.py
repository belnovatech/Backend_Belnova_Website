import base64
import html
import logging
import os

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition, ContentId, ReplyTo
from python_http_client.exceptions import UnauthorizedError, ForbiddenError

from app.core.config import EMAIL, SENDGRID_API_KEY, require_env

logger = logging.getLogger(__name__)


def _get_sender_email() -> str:
    sender_email = (EMAIL or os.getenv("EMAIL", "")).strip()
    if not sender_email:
        sender_email = require_env("EMAIL")
    return sender_email


def _get_sendgrid_client() -> SendGridAPIClient:
    if SENDGRID_API_KEY:
        return SendGridAPIClient(SENDGRID_API_KEY)
    return SendGridAPIClient(require_env("SENDGRID_API_KEY"))


def _send_sendgrid_mail(sg: SendGridAPIClient, message: Mail, label: str):
    try:
        response = sg.send(message)
    except UnauthorizedError as exc:
        body = getattr(exc, "body", b"")
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
        logger.error(
            "SendGrid %s failed: 401 Unauthorized – API key is invalid, expired, or revoked. "
            "Generate a new API key at https://app.sendgrid.com/settings/api_keys and update "
            "SENDGRID_API_KEY in your .env file. SendGrid error body: %s",
            label, body_text
        )
        raise RuntimeError(
            f"SendGrid {label} rejected with 401 Unauthorized: API key is invalid/expired/revoked. "
            f"Details: {body_text}"
        ) from exc
    except ForbiddenError as exc:
        body = getattr(exc, "body", b"")
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
        logger.error(
            "SendGrid %s failed: 403 Forbidden – sender email may not be verified. "
            "Verify the sender at https://app.sendgrid.com/settings/sender_auth. "
            "SendGrid error body: %s",
            label, body_text
        )
        raise RuntimeError(
            f"SendGrid {label} rejected with 403 Forbidden: sender domain/email not verified. "
            f"Details: {body_text}"
        ) from exc
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        logger.warning("SendGrid response did not include status code for %s", label)
        return
    if status_code < 200 or status_code >= 300:
        body = getattr(response, "body", b"")
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
        logger.error("SendGrid %s failed with status %s: %s", label, status_code, body_text[:500])
        raise RuntimeError(f"SendGrid {label} failed with status {status_code}: {body_text[:250]}")
    logger.info("SendGrid accepted %s email with status=%s", label, status_code)


def send_contact_email(data):
    sender_email = _get_sender_email()
    sg = _get_sendgrid_client()

    # ==========================
    # Admin Email
    # ==========================

    admin_html = f"""
    <h2>New Contact Form Submission</h2>

    <p><b>Name:</b> {data.name}</p>
    <p><b>Email:</b> {data.email}</p>
    <p><b>Phone:</b> {data.phone}</p>
    <p><b>Subject:</b> {data.subject}</p>
    <p><b>Message:</b></p>

    <p>{data.message}</p>
    """

    admin_mail = Mail(
        from_email=sender_email,
        to_emails=sender_email,
        subject=f"New Website Enquiry - {data.subject}",
        html_content=admin_html
    )

    _send_sendgrid_mail(sg, admin_mail, "admin contact")

    # ==========================
    # Customer Auto Reply
    # ==========================

    customer_html = f"""
    <html>

    <body
    style="font-family:Arial;
    background:#f5f7fb;
    padding:30px;">

    <h2>Hello {data.name},</h2>

    <p>

    Thank you for contacting
    <b>Belnova Technologies.</b>

    </p>

    <p>

    We have received your enquiry.

    </p>

    <p>

    Our team will contact you within
    <b>24 hours.</b>

    </p>

    <hr>

    <b>Your Subject:</b>

    {data.subject}

    <br><br>

    <b>Your Message:</b>

    <br>

    {data.message}

    <br><br>

    📞 +91 7382405380

    <br>

    📧 info@belnovatech.com

    </body>

    </html>
    """

    reply_mail = Mail(
        from_email=sender_email,
        to_emails=data.email,
        subject="Thank You for Contacting Belnova Technologies",
        html_content=customer_html
    )

    _send_sendgrid_mail(sg, reply_mail, "customer auto-reply")


def send_contact_requirement_emails(data: dict, file_data: bytes = None, filename: str = None, content_type: str = None):
    sender_email = _get_sender_email()
    sg = _get_sendgrid_client()

    # 1. Read and base64-encode the logo
    logo_path = "app/static/belnova-logo.png"
    logo_attachment = None
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_bytes = f.read()
        logo_base64 = base64.b64encode(logo_bytes).decode()
        logo_attachment = Attachment(
            FileContent(logo_base64),
            FileName("belnova-logo.png"),
            FileType("image/png"),
            Disposition("inline"),
            ContentId("belnova_logo")
        )

    # 2. Escape fields for safe HTML rendering to prevent HTML injection
    escaped = {
        k: html.escape(str(v)) if v is not None else "Not provided"
        for k, v in data.items()
    }

    # Format attachment description for the admin email
    attachment_info = "None"
    if filename:
        size_kb = len(file_data) / 1024
        attachment_info = f"{html.escape(filename)} ({size_kb:.1f} KB)"

    # 3. Dynamic HTML templates
    admin_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>New Website Requirement</title>
      <style>
        body {{
          font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
          background-color: #f8fafc;
          color: #334155;
          margin: 0;
          padding: 0;
          -webkit-font-smoothing: antialiased;
        }}
        .wrapper {{
          width: 100%;
          background-color: #f8fafc;
          padding: 40px 20px;
          box-sizing: border-box;
        }}
        .container {{
          max-width: 600px;
          margin: 0 auto;
          background-color: #ffffff;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
          border: 1px solid #e2e8f0;
        }}
        .header {{
          background-color: #0f172a;
          padding: 30px;
          text-align: center;
          border-bottom: 3px solid #6366f1;
        }}
        .header img {{
          max-height: 45px;
          display: inline-block;
        }}
        .content {{
          padding: 40px 30px;
        }}
        .title {{
          font-size: 20px;
          font-weight: 700;
          color: #0f172a;
          margin-top: 0;
          margin-bottom: 25px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          border-bottom: 2px solid #f1f5f9;
          padding-bottom: 10px;
        }}
        .section-title {{
          font-size: 14px;
          font-weight: 700;
          color: #6366f1;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-top: 25px;
          margin-bottom: 15px;
        }}
        .info-table {{
          width: 100%;
          border-collapse: collapse;
          margin-bottom: 15px;
        }}
        .info-table td {{
          padding: 10px 0;
          border-bottom: 1px solid #f1f5f9;
          vertical-align: top;
        }}
        .info-table td.label {{
          width: 35%;
          font-weight: 600;
          color: #475569;
          font-size: 14px;
        }}
        .info-table td.value {{
          color: #0f172a;
          font-size: 14px;
        }}
        .message-box {{
          background-color: #f8fafc;
          border-left: 4px solid #6366f1;
          padding: 15px 20px;
          border-radius: 0 8px 8px 0;
          margin-top: 10px;
          font-size: 14px;
          line-height: 1.6;
          color: #334155;
          white-space: pre-wrap;
        }}
        .footer {{
          background-color: #f1f5f9;
          padding: 30px;
          text-align: center;
          font-size: 12px;
          color: #64748b;
          border-top: 1px solid #e2e8f0;
        }}
        .footer p {{
          margin: 5px 0;
        }}
        .footer-tagline {{
          font-weight: 600;
          color: #475569;
          margin-top: 10px !important;
        }}
      </style>
    </head>
    <body>
      <div class="wrapper">
        <div class="container">
          <div class="header">
            <img src="cid:belnova_logo" alt="Belnova Tech">
          </div>
          <div class="content">
            <h2 class="title">New Website Requirement</h2>
            <p style="font-size: 14px; line-height: 1.5; color: #475569; margin-bottom: 20px;">
              A new requirement has been submitted through the Belnova Tech website contact form.
            </p>
            
            <h3 class="section-title">Contact Information</h3>
            <table class="info-table">
              <tr>
                <td class="label">Full Name</td>
                <td class="value">{escaped['full_name']}</td>
              </tr>
              <tr>
                <td class="label">Company Name</td>
                <td class="value">{escaped['company_name']}</td>
              </tr>
              <tr>
                <td class="label">Work Email</td>
                <td class="value">{escaped['work_email']}</td>
              </tr>
              <tr>
                <td class="label">Phone Number</td>
                <td class="value">{escaped['phone_number']}</td>
              </tr>
              <tr>
                <td class="label">Country</td>
                <td class="value">{escaped['country']}</td>
              </tr>
            </table>
            
            <h3 class="section-title">Requirement Details</h3>
            <table class="info-table">
              <tr>
                <td class="label">Looking For</td>
                <td class="value">{escaped['looking_for']}</td>
              </tr>
              <tr>
                <td class="label">Project Title</td>
                <td class="value">{escaped['project_title']}</td>
              </tr>
              <tr>
                <td class="label">Expected Timeline</td>
                <td class="value">{escaped['expected_timeline']}</td>
              </tr>
              <tr>
                <td class="label">Budget Range</td>
                <td class="value">{escaped['budget_range']}</td>
              </tr>
              <tr>
                <td class="label">Tech Preferences</td>
                <td class="value">{escaped['technology_preferences']}</td>
              </tr>
              <tr>
                <td class="label">How Did They Hear</td>
                <td class="value">{escaped['how_did_you_hear']}</td>
              </tr>
              <tr>
                <td class="label">Attachment</td>
                <td class="value">{attachment_info}</td>
              </tr>
            </table>
            
            <h3 class="section-title">Requirement Description</h3>
            <div class="message-box">{escaped['requirement_description']}</div>
          </div>
          <div class="footer">
            <p><strong>Belnova Tech Private Limited</strong></p>
            <p>4th & 5th, Kondapur, 2-91/12/4/NR, Plot No. 4, Doc Bhavan, Hyderabad, Telangana 500081</p>
            <p>Email: info@belnovatech.com | Web: belnovatech.com</p>
            <p class="footer-tagline">Innovate Today. Build the Future.</p>
          </div>
        </div>
      </div>
    </body>
    </html>
    """

    customer_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>We've Received Your Requirement – Belnova Tech</title>
      <style>
        body {{
          font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
          background-color: #f8fafc;
          color: #334155;
          margin: 0;
          padding: 0;
          -webkit-font-smoothing: antialiased;
        }}
        .wrapper {{
          width: 100%;
          background-color: #f8fafc;
          padding: 40px 20px;
          box-sizing: border-box;
        }}
        .container {{
          max-width: 600px;
          margin: 0 auto;
          background-color: #ffffff;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
          border: 1px solid #e2e8f0;
        }}
        .header {{
          background-color: #0f172a;
          padding: 30px;
          text-align: center;
          border-bottom: 3px solid #6366f1;
        }}
        .header img {{
          max-height: 45px;
          display: inline-block;
        }}
        .content {{
          padding: 40px 30px;
        }}
        .greeting {{
          font-size: 18px;
          font-weight: 700;
          color: #0f172a;
          margin-top: 0;
          margin-bottom: 15px;
        }}
        .intro {{
          font-size: 14px;
          line-height: 1.6;
          color: #475569;
          margin-bottom: 25px;
        }}
        .summary-card {{
          background-color: #f8fafc;
          border: 1px solid #e2e8f0;
          border-radius: 8px;
          padding: 20px;
          margin-bottom: 25px;
        }}
        .summary-title {{
          font-size: 13px;
          font-weight: 700;
          color: #6366f1;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-top: 0;
          margin-bottom: 15px;
        }}
        .summary-row {{
          margin-bottom: 10px;
          font-size: 14px;
        }}
        .summary-row:last-child {{
          margin-bottom: 0;
        }}
        .summary-label {{
          font-weight: 600;
          color: #475569;
        }}
        .summary-value {{
          color: #0f172a;
        }}
        .closing {{
          font-size: 14px;
          line-height: 1.6;
          color: #475569;
          margin-bottom: 20px;
        }}
        .signature {{
          font-size: 14px;
          color: #0f172a;
          font-weight: 600;
        }}
        .footer {{
          background-color: #f1f5f9;
          padding: 30px;
          text-align: center;
          font-size: 12px;
          color: #64748b;
          border-top: 1px solid #e2e8f0;
        }}
        .footer p {{
          margin: 5px 0;
        }}
        .footer-tagline {{
          font-weight: 600;
          color: #475569;
          margin-top: 10px !important;
        }}
      </style>
    </head>
    <body>
      <div class="wrapper">
        <div class="container">
          <div class="header">
            <img src="cid:belnova_logo" alt="Belnova Tech">
          </div>
          <div class="content">
            <h2 class="greeting">Hello {escaped['full_name']},</h2>
            <p class="intro">
              Thank you for reaching out to Belnova Tech. We have successfully received your project requirement, and our engineering team is reviewing it. We will get back to you within 24 hours.
            </p>
            
            <div class="summary-card">
              <h3 class="summary-title">Submission Summary</h3>
              <div class="summary-row">
                <span class="summary-label">Project Title:</span>
                <span class="summary-value"> {escaped['project_title']}</span>
              </div>
              <div class="summary-row">
                <span class="summary-label">Category:</span>
                <span class="summary-value"> {escaped['looking_for']}</span>
              </div>
              <div class="summary-row">
                <span class="summary-label">Expected Timeline:</span>
                <span class="summary-value"> {escaped['expected_timeline']}</span>
              </div>
            </div>
            
            <p class="closing">
              If we need any further details or clarifications, one of our solutions architects will reach out to you at this email address or your provided phone number.
            </p>
            
            <p class="signature">
              Best regards,<br>
              <span style="color: #6366f1;">Belnova Tech Solutions Team</span>
            </p>
          </div>
          <div class="footer">
            <p><strong>Belnova Tech Private Limited</strong></p>
            <p>4th & 5th, Kondapur, 2-91/12/4/NR, Plot No. 4, Doc Bhavan, Hyderabad, Telangana 500081</p>
            <p>Email: info@belnovatech.com | Web: belnovatech.com</p>
            <p class="footer-tagline">Innovate Today. Build the Future.</p>
          </div>
        </div>
      </div>
    </body>
    </html>
    """

    # 4. Prepare and send Admin Notification Email
    admin_mail = Mail(
        from_email=sender_email,
        to_emails="info@belnovatech.com",
        subject=f"New Website Requirement – {data['project_title']}",
        html_content=admin_html
    )
    # Set reply-to customer email
    admin_mail.reply_to = ReplyTo(data['work_email'])

    # Add inline logo
    if logo_attachment:
        admin_mail.add_attachment(logo_attachment)

    # Add optional user file attachment
    if file_data and filename:
        file_base64 = base64.b64encode(file_data).decode()
        user_attachment = Attachment(
            FileContent(file_base64),
            FileName(filename),
            FileType(content_type or "application/octet-stream"),
            Disposition("attachment")
        )
        admin_mail.add_attachment(user_attachment)

    _send_sendgrid_mail(sg, admin_mail, "admin requirement notification")

    # 5. Prepare and send Customer Auto-Reply Email
    customer_mail = Mail(
        from_email=sender_email,
        to_emails=data['work_email'],
        subject="We've Received Your Requirement – Belnova Tech",
        html_content=customer_html
    )
    if logo_attachment:
        customer_mail.add_attachment(logo_attachment)

    _send_sendgrid_mail(sg, customer_mail, "customer requirement auto-reply")
