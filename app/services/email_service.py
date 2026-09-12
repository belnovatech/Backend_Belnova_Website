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
    logger.info("[EMAIL] Background email task START for %s (email: %s)", data.get("project_title"), data.get("work_email"))
    sender_email = _get_sender_email()

    # 1. Escape fields for safe HTML rendering to prevent HTML injection
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

    # 2. Dynamic HTML templates
    admin_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Website Requirement</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #334155;">
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0;">
          <tr>
            <td style="background-color: #0b1120; padding: 24px 20px; text-align: center;">
              <div style="font-size: 20px; font-weight: 800; letter-spacing: 2.5px; color: #ffffff; text-transform: uppercase;">
                BELNOVA <span style="color: #06b6d4;">TECH</span>
              </div>
              <div style="font-size: 10px; font-weight: 600; letter-spacing: 3px; color: #94a3b8; text-transform: uppercase; margin-top: 4px;">
                PRIVATE LIMITED
              </div>
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-top: 14px;">
                <tr>
                  <td style="height: 3px; background: #06b6d4; width: 50%; font-size: 0; line-height: 0;">&nbsp;</td>
                  <td style="height: 3px; background: #8b5cf6; width: 50%; font-size: 0; line-height: 0;">&nbsp;</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 24px;">
              <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; margin: 0 0 16px 0; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #f1f5f9; padding-bottom: 8px;">
                New Website Requirement
              </h2>
              <p style="font-size: 14px; line-height: 1.5; color: #475569; margin-bottom: 20px;">
                A new requirement has been submitted through the Belnova Tech website contact form.
              </p>

              <div style="font-size: 12px; font-weight: 700; color: #6366f1; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                Contact Information
              </div>
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size: 13px; margin-bottom: 20px; border-collapse: collapse;">
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600; width: 35%;">Full Name:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a; font-weight: 600;">{escaped['full_name']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Company Name:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['company_name']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Work Email:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['work_email']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Phone Number:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['phone_number']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Country:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['country']}</td></tr>
              </table>

              <div style="font-size: 12px; font-weight: 700; color: #6366f1; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                Requirement Details
              </div>
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size: 13px; margin-bottom: 20px; border-collapse: collapse;">
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600; width: 35%;">Looking For:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['looking_for']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Project Title:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a; font-weight: 600;">{escaped['project_title']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Expected Timeline:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['expected_timeline']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Budget Range:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['budget_range']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Tech Preferences:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['technology_preferences']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">How Did They Hear:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{escaped['how_did_you_hear']}</td></tr>
                <tr><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #64748b; font-weight: 600;">Attachment:</td><td style="padding: 6px 0; border-bottom: 1px solid #f1f5f9; color: #0f172a;">{attachment_info}</td></tr>
              </table>

              <div style="font-size: 12px; font-weight: 700; color: #6366f1; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                Requirement Description
              </div>
              <div style="background-color: #f8fafc; border-left: 4px solid #6366f1; padding: 14px 16px; border-radius: 0 6px 6px 0; font-size: 13px; line-height: 1.6; color: #334155; white-space: pre-wrap;">{escaped['requirement_description']}</div>
            </td>
          </tr>
          <tr>
            <td style="background-color: #f1f5f9; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b;">
              <p style="margin: 0 0 4px 0; font-weight: 700; color: #334155;">Belnova Tech Private Limited</p>
              <p style="margin: 0 0 6px 0;">4th & 5th Floor, Kondapur, Hyderabad, Telangana 500081</p>
              <p style="margin: 0;">Email: info@belnovatech.com | Web: belnovatech.com</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    customer_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>We've Received Your Requirement – Belnova Tech</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; color: #334155;">
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 30px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
          
          <!-- Header -->
          <tr>
            <td style="background-color: #0b1120; padding: 26px 24px; text-align: center;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <div style="font-size: 22px; font-weight: 800; letter-spacing: 2.5px; color: #ffffff; text-transform: uppercase; margin: 0;">
                      BELNOVA <span style="color: #06b6d4;">TECH</span>
                    </div>
                    <div style="font-size: 10px; font-weight: 600; letter-spacing: 3px; color: #94a3b8; text-transform: uppercase; margin-top: 5px;">
                      PRIVATE LIMITED
                    </div>
                  </td>
                </tr>
                <tr>
                  <td style="padding-top: 18px;">
                    <!-- Cyan to Purple Accent Line -->
                    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                      <tr>
                        <td style="height: 3px; background: #06b6d4; width: 50%; font-size: 0; line-height: 0;">&nbsp;</td>
                        <td style="height: 3px; background: #8b5cf6; width: 50%; font-size: 0; line-height: 0;">&nbsp;</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 32px 28px;">
              <p style="font-size: 16px; font-weight: 700; color: #0f172a; margin: 0 0 16px 0;">
                Hello {escaped['full_name']},
              </p>
              
              <p style="font-size: 14px; line-height: 1.6; color: #334155; margin: 0 0 24px 0;">
                Thank you for reaching out to <strong>Belnova Tech</strong>. We have successfully received your project requirement, and our engineering team is reviewing it. We will get back to you within <strong>24 hours</strong>.
              </p>

              <!-- Submission Summary Card -->
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; margin: 0 0 24px 0;">
                <tr>
                  <td style="padding: 18px 20px;">
                    <div style="font-size: 11px; font-weight: 700; color: #6366f1; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                      SUBMISSION SUMMARY
                    </div>
                    
                    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size: 13px;">
                      <tr>
                        <td width="38%" style="padding: 6px 0; color: #64748b; font-weight: 600; vertical-align: top;">Project Title:</td>
                        <td style="padding: 6px 0; color: #0f172a; font-weight: 600; vertical-align: top;">{escaped['project_title']}</td>
                      </tr>
                      <tr>
                        <td style="padding: 6px 0; color: #64748b; font-weight: 600; vertical-align: top;">Category:</td>
                        <td style="padding: 6px 0; color: #0f172a; vertical-align: top;">{escaped['looking_for']}</td>
                      </tr>
                      <tr>
                        <td style="padding: 6px 0; color: #64748b; font-weight: 600; vertical-align: top;">Expected Timeline:</td>
                        <td style="padding: 6px 0; color: #0f172a; vertical-align: top;">{escaped['expected_timeline']}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <p style="font-size: 14px; line-height: 1.6; color: #334155; margin: 0 0 24px 0;">
                If we need any further details or clarification, one of our solutions architects will reach out to you using the email address or phone number you provided.
              </p>

              <table role="presentation" border="0" cellspacing="0" cellpadding="0" style="font-size: 14px; line-height: 1.5;">
                <tr>
                  <td style="color: #0f172a;">
                    Best regards,<br>
                    <strong style="color: #6366f1;">Belnova Tech Solutions Team</strong>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f1f5f9; padding: 24px 20px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b;">
              <p style="margin: 0 0 4px 0; font-weight: 700; color: #334155;">Belnova Tech Private Limited</p>
              <p style="margin: 0 0 8px 0; line-height: 1.4;">4th & 5th Floor, Kondapur, Hyderabad, Telangana 500081</p>
              <p style="margin: 0 0 12px 0;">
                Email: <a href="mailto:info@belnovatech.com" style="color: #6366f1; text-decoration: none; font-weight: 600;">info@belnovatech.com</a> &nbsp;|&nbsp; 
                Website: <a href="https://belnovatech.com" style="color: #6366f1; text-decoration: none; font-weight: 600;">belnovatech.com</a>
              </p>
              <p style="margin: 0; font-size: 11px; font-weight: 600; color: #94a3b8; letter-spacing: 0.5px;">
                Innovate Today. Build the Future.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    import time
    import concurrent.futures

    t_task_start = time.perf_counter()
    logger.info(
        "[EMAIL] task_started (submission_title=%s, customer_email=%s)",
        data.get("project_title"), data.get("work_email")
    )

    # 4. Prepare Admin Notification Payload
    admin_payload = {
        "sender": {"name": "Belnova Tech", "email": sender_email},
        "to": [{"email": "info@belnovatech.com", "name": "Belnova Admin"}],
        "replyTo": {"email": data['work_email'], "name": data.get('full_name', 'Customer')},
        "subject": f"New Website Requirement – {data['project_title']}",
        "htmlContent": admin_html
    }

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

    # 5. Prepare Customer Auto-Reply Payload (lightweight, zero large attachments)
    customer_email = data['work_email'].strip()
    customer_payload = {
        "sender": {"name": "Belnova Tech", "email": sender_email},
        "to": [{"email": customer_email, "name": data.get('full_name', 'Customer')}],
        "subject": "We've Received Your Requirement – Belnova Tech",
        "htmlContent": customer_html
    }

    # 6. Execute both email dispatches concurrently so neither blocks the other
    def _dispatch_admin():
        t0 = time.perf_counter()
        logger.info("[EMAIL] admin_send_started")
        try:
            res_admin = _send_brevo_email(admin_payload, "admin requirement notification")
            dur_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "[EMAIL] admin_brevo_response (status=%s, message_id=%s, elapsed_ms=%d)",
                res_admin.get("status_code"), res_admin.get("message_id"), dur_ms
            )
            return res_admin
        except Exception as exc:
            dur_ms = int((time.perf_counter() - t0) * 1000)
            logger.error("[EMAIL] admin_brevo_response FAILED (elapsed_ms=%d): %s", dur_ms, exc)
            return None

    def _dispatch_customer():
        t0 = time.perf_counter()
        logger.info("[EMAIL] customer_send_started (recipient=%s)", customer_email)
        try:
            res_cust = _send_brevo_email(customer_payload, "customer requirement auto-reply")
            dur_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "[EMAIL] customer_brevo_response (status=%s, message_id=%s, elapsed_ms=%d)",
                res_cust.get("status_code"), res_cust.get("message_id"), dur_ms
            )
            return res_cust
        except Exception as exc:
            dur_ms = int((time.perf_counter() - t0) * 1000)
            logger.error("[EMAIL] customer_brevo_response FAILED (elapsed_ms=%d): %s", dur_ms, exc)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_cust = executor.submit(_dispatch_customer)
        fut_admin = executor.submit(_dispatch_admin)
        concurrent.futures.wait([fut_cust, fut_admin])

    t_task_total_ms = int((time.perf_counter() - t_task_start) * 1000)
    logger.info("[EMAIL] task_completed (total_email_ms=%d)", t_task_total_ms)


def send_contact_requirement_emails(data: dict, file_data: bytes = None, filename: str = None, content_type: str = None):
    try:
        _send_contact_requirement_emails_impl(
            data=data,
            file_data=file_data,
            filename=filename,
            content_type=content_type
        )
    except Exception as exc:
        logger.exception("[EMAIL] Background requirement email delivery encountered top-level error: %s", exc)
