import logging

from fastapi import APIRouter, Form, File, UploadFile, Depends, HTTPException, status
from sqlalchemy.orm import Session
from email_validator import validate_email, EmailNotValidError

from app.schemas.contact import ContactRequest
from app.services.email_service import send_contact_email, send_contact_requirement_emails
from app.database import get_db
from app.models.contact import ContactSubmission

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/contact")
def contact(data: ContactRequest):
    try:
        send_contact_email(data)
    except Exception:
        logger.exception("Fallback contact email send failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Contact email notification could not be sent."
        )

    return {
        "success": True,
        "message": "Mail Sent Successfully"
    }

@router.post("/api/contact")
async def contact_requirement(
    fullName: str = Form(...),
    email: str = Form(...),
    title: str = Form(...),
    message: str = Form(...),
    privacy_accepted: bool = Form(...),
    company: str = Form(None),
    phone: str = Form(None),
    country: str = Form(None),
    lookingFor: str = Form(None),
    technology: str = Form(None),
    timeline: str = Form(None),
    budget: str = Form(None),
    source: str = Form(None),
    attachment: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    # 1. Validation
    if not fullName.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full Name is required and cannot be empty."
        )

    if not email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Work Email is required and cannot be empty."
        )

    try:
        # Validate and normalize email address
        valid_email_info = validate_email(email.strip(), check_deliverability=False)
        normalized_email = valid_email_info.email
    except EmailNotValidError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid email address: {str(e)}"
        )

    if not title.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project / Requirement Title is required and cannot be empty."
        )

    if not message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirement Description is required and cannot be empty."
        )

    if not privacy_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must agree to the Privacy Policy and Terms & Conditions."
        )

    # 2. Process optional file attachment
    attachment_filename = None
    attachment_content_type = None
    attachment_size = None
    attachment_data = None

    if attachment and attachment.filename:
        attachment_data = await attachment.read()
        attachment_size = len(attachment_data)
        attachment_filename = attachment.filename
        attachment_content_type = attachment.content_type

    # 3. Save to database
    db_submission = ContactSubmission(
        full_name=fullName.strip(),
        company_name=company.strip() if company else None,
        work_email=normalized_email,
        phone_number=phone.strip() if phone else None,
        country=country.strip() if country else None,
        looking_for=lookingFor.strip() if lookingFor else "Not provided",
        project_title=title.strip(),
        requirement_description=message.strip(),
        technology_preferences=technology.strip() if technology else None,
        expected_timeline=timeline.strip() if timeline else None,
        budget_range=budget.strip() if budget else None,
        how_did_you_hear=source.strip() if source else None,
        attachment_filename=attachment_filename,
        attachment_content_type=attachment_content_type,
        attachment_size=attachment_size,
        privacy_accepted=privacy_accepted
    )

    try:
        db.add(db_submission)
        db.flush()
        send_contact_requirement_emails(
            data={
                "full_name": db_submission.full_name,
                "company_name": db_submission.company_name,
                "work_email": db_submission.work_email,
                "phone_number": db_submission.phone_number,
                "country": db_submission.country,
                "looking_for": db_submission.looking_for,
                "project_title": db_submission.project_title,
                "requirement_description": db_submission.requirement_description,
                "technology_preferences": db_submission.technology_preferences,
                "expected_timeline": db_submission.expected_timeline,
                "budget_range": db_submission.budget_range,
                "how_did_you_hear": db_submission.how_did_you_hear,
            },
            file_data=attachment_data,
            filename=attachment_filename,
            content_type=attachment_content_type
        )
        db.commit()
        db.refresh(db_submission)
    except Exception:
        db.rollback()
        logger.exception("Contact requirement email workflow failed; database transaction rolled back")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Requirement submitted, but email delivery failed. Please try again later."
        )

    # 5. Return success response matching the required template format
    return {
        "success": True,
        "message": "Requirement submitted successfully",
        "data": {
            "id": db_submission.id
        }
    }
