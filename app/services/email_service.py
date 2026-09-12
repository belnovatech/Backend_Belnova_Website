import base64
import html
import logging
import os
import httpx

from app.core.config import EMAIL, BREVO_API_KEY, require_env

logger = logging.getLogger(__name__)

BREVO_SMTP_URL = "https://api.brevo.com/v3/smtp/email"


def _get_sender_email() -> str:
    sender_email = (EMAIL or os.getenv("EMAIL", "info@belnovatech.com")).strip()
    if not sender_email:
        sender_email = "info@belnovatech.com"
    return sender_email


def _get_brevo_api_key() -> str:
    api_key = (BREVO_API_KEY or os.getenv("BREVO_API_KEY", "")).strip()
    if not api_key:
        api_key = require_env("BREVO_API_KEY")
    return api_key


def _send_brevo_email(payload: dict, label: str) -> dict:
    api_key = _get_brevo_api_key()
    headers = {
        "api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        timeout_val = float(os.getenv("BREVO_TIMEOUT", "15.0"))
    except (ValueError, TypeError):
        timeout_val = 15.0

    try:
        with httpx.Client(timeout=timeout_val) as client:
            response = client.post(BREVO_SMTP_URL, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        logger.error("Brevo %s connection timed out: %s", label, exc)
        raise RuntimeError(f"Brevo {label} connection timeout: {exc}") from exc
    except httpx.RequestError as exc:
        logger.error("Brevo %s network request failed: %s", label, exc)
        raise RuntimeError(f"Brevo {label} network error: {exc}") from exc
    except Exception as exc:
        logger.error("Brevo %s failed unexpectedly: %s", label, exc)
        raise

    status_code = response.status_code
    resp_text = response.text

    if status_code == 401:
        logger.error(
            "Brevo %s FAILED: 401 Unauthorized – The BREVO_API_KEY is invalid, expired, or revoked. "
            "Please verify BREVO_API_KEY in Render environment settings.",
            label
        )
        raise RuntimeError(f"Brevo {label} rejected with 401 Unauthorized")
    elif status_code == 403:
        logger.error(
            "Brevo %s FAILED: 403 Forbidden – The sender email '%s' may not be verified in Brevo. "
            "Brevo error: %s",
            label, payload.get("sender", {}).get("email", "unknown"), resp_text[:300]
        )
        raise RuntimeError(f"Brevo {label} rejected with 403 Forbidden: {resp_text[:200]}")
    elif status_code < 200 or status_code >= 300:
        logger.error("Brevo %s failed with status %s: %s", label, status_code, resp_text[:500])
        raise RuntimeError(f"Brevo {label} failed with status {status_code}: {resp_text[:250]}")

    try:
        resp_json = response.json()
        message_id = resp_json.get("messageId") or "N/A"
    except Exception:
        message_id = "N/A"

    logger.info("Brevo accepted %s email [status=%s, message_id=%s]", label, status_code, message_id)
    return {"status_code": status_code, "message_id": message_id}


def send_contact_email(data):
    """Handles standard contact inquiries from /contact endpoint."""
    try:
        sender_email = _get_sender_email()

        # ==========================
        # 1. Admin Notification
        # ==========================
        try:
            admin_html = f"""
            <h2>New Contact Form Submission</h2>
            <p><b>Name:</b> {html.escape(str(data.name))}</p>
            <p><b>Email:</b> {html.escape(str(data.email))}</p>
            <p><b>Phone:</b> {html.escape(str(data.phone))}</p>
            <p><b>Subject:</b> {html.escape(str(data.subject))}</p>
            <p><b>Message:</b></p>
            <p>{html.escape(str(data.message))}</p>
            """
            admin_payload = {
                "sender": {"name": "Belnova Tech", "email": sender_email},
                "to": [{"email": sender_email, "name": "Belnova Admin"}],
                "replyTo": {"email": data.email, "name": str(data.name)},
                "subject": f"New Website Enquiry - {data.subject}",
                "htmlContent": admin_html
            }
            _send_brevo_email(admin_payload, "admin contact")
        except Exception as exc:
            logger.error("Failed sending admin contact email: %s", exc)

        # ==========================
        # 2. Customer Auto Reply
        # ==========================
        try:
            customer_html = f"""
            <html>
            <body style="font-family:Arial;background:#f5f7fb;padding:30px;">
            <h2>Hello {html.escape(str(data.name))},</h2>
            <p>Thank you for contacting <b>Belnova Technologies.</b></p>
            <p>We have received your enquiry.</p>
            <p>Our team will contact you within <b>24 hours.</b></p>
            <hr>
            <b>Your Subject:</b> {html.escape(str(data.subject))}<br><br>
            <b>Your Message:</b><br>{html.escape(str(data.message))}<br><br>
            📞 +91 7382405380<br>
            📧 info@belnovatech.com
            </body>
            </html>
            """
            customer_payload = {
                "sender": {"name": "Belnova Tech", "email": sender_email},
                "to": [{"email": data.email, "name": str(data.name)}],
                "subject": "Thank You for Contacting Belnova Technologies",
                "htmlContent": customer_html
            }
            _send_brevo_email(customer_payload, "customer auto-reply")
        except Exception as exc:
            logger.error("Failed sending customer auto-reply email: %s", exc)

    except Exception as exc:
        logger.exception("Background contact email delivery encountered top-level error: %s", exc)


def _send_contact_requirement_emails_impl(data: dict, file_data: bytes = None, filename: str = None, content_type: str = None):
    sender_email = _get_sender_email()

    # 1. Read and base64-encode the logo for inline HTML embedding
    logo_path = "app/static/belnova-logo.png"
    logo_data_uri = ""
    if os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                logo_bytes = f.read()
            logo_base64 = base64.b64encode(logo_bytes).decode()
            logo_data_uri = f"data:image/png;base64,{logo_base64}"
        except Exception as e:
            logger.warning("Could not read inline logo: %s", e)

    # 2. Escape fields for safe HTML rendering to prevent HTML injection
    escaped = {
        k: html.escape(str(v)) if v is not None else "Not provided"
        for k, v in data.items()
    }

    # Format attachment description for the admin email
    attachment_info = "None"
    if filename and file_data:
        size_kb = len(file_data) / 1024
        attachment_info = f"{html.escape(filename)} ({size_kb:.1f} KB)"
    elif filename:
        attachment_info = html.escape(filename)

    logo_img_tag = f'<img src="{logo_data_uri}" alt="Belnova Tech" style="max-height: 45px; display: inline-block;">' if logo_data_uri else '<h2 style="color: #ffffff; margin: 0;">Belnova Tech</h2>'

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
            {logo_img_tag}
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
            {logo_img_tag}
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

    # 4. Prepare and send Admin Notification Email (isolated in its own block)
    try:
        admin_payload = {
            "sender": {"name": "Belnova Tech", "email": sender_email},
            "to": [{"email": "info@belnovatech.com", "name": "Belnova Admin"}],
            "replyTo": {"email": data['work_email'], "name": data.get('full_name', 'Customer')},
            "subject": f"New Website Requirement – {data['project_title']}",
            "htmlContent": admin_html
        }

        # Add optional user file attachment to admin email (safely handle size limits)
        if file_data and filename:
            if len(file_data) <= 12 * 1024 * 1024:
                file_base64 = base64.b64encode(file_data).decode()
                admin_payload["attachment"] = [
                    {
                        "name": filename,
                        "content": file_base64
                    }
                ]
            else:
                logger.warning(
                    "Attachment %s exceeds 12MB limit for email payload (%d bytes); omitted from email.",
                    filename, len(file_data)
                )

        _send_brevo_email(admin_payload, "admin requirement notification")
    except Exception as exc:
        logger.error("Failed to send admin requirement notification email: %s", exc)

    # 5. Prepare and send Customer Auto-Reply Email (isolated in its own block)
    try:
        customer_payload = {
            "sender": {"name": "Belnova Tech", "email": sender_email},
            "to": [{"email": data['work_email'], "name": data.get('full_name', 'Customer')}],
            "subject": "We've Received Your Requirement – Belnova Tech",
            "htmlContent": customer_html
        }
        _send_brevo_email(customer_payload, "customer requirement auto-reply")
    except Exception as exc:
        logger.error("Failed to send customer requirement auto-reply email: %s", exc)


def send_contact_requirement_emails(data: dict, file_data: bytes = None, filename: str = None, content_type: str = None):
    try:
        _send_contact_requirement_emails_impl(
            data=data,
            file_data=file_data,
            filename=filename,
            content_type=content_type
        )
    except Exception as exc:
        logger.exception("Background requirement email delivery encountered top-level error: %s", exc)
