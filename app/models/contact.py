from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from app.database import Base

class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    work_email = Column(String(255), nullable=False)
    phone_number = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    looking_for = Column(String(255), nullable=False)
    project_title = Column(String(255), nullable=False)
    requirement_description = Column(Text, nullable=False)
    technology_preferences = Column(Text, nullable=True)
    expected_timeline = Column(String(100), nullable=True)
    budget_range = Column(String(100), nullable=True)
    how_did_you_hear = Column(String(255), nullable=True)
    attachment_filename = Column(String(255), nullable=True)
    attachment_content_type = Column(String(100), nullable=True)
    attachment_size = Column(Integer, nullable=True)
    privacy_accepted = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
