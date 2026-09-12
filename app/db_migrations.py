import logging
from sqlalchemy import text, inspect
from app.database import engine, Base
from app.models.contact import ContactSubmission

logger = logging.getLogger("app.migrations")

# Expected column definitions for PostgreSQL
MIGRATION_COLUMNS = [
    ("id", "SERIAL PRIMARY KEY"),
    ("full_name", "VARCHAR(255)"),
    ("company_name", "VARCHAR(255)"),
    ("work_email", "VARCHAR(255)"),
    ("phone_number", "VARCHAR(100)"),
    ("country", "VARCHAR(100)"),
    ("looking_for", "VARCHAR(255) DEFAULT 'Not provided'"),
    ("project_title", "VARCHAR(255)"),
    ("requirement_description", "TEXT"),
    ("technology_preferences", "TEXT"),
    ("expected_timeline", "VARCHAR(100)"),
    ("budget_range", "VARCHAR(100)"),
    ("how_did_you_hear", "VARCHAR(255)"),
    ("attachment_filename", "VARCHAR(255)"),
    ("attachment_content_type", "VARCHAR(100)"),
    ("attachment_size", "INTEGER"),
    ("privacy_accepted", "BOOLEAN DEFAULT TRUE"),
    ("created_at", "TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"),
]


def run_database_migrations():
    """
    Safely inspects and applies schema migrations to ensure the `contact_submissions`
    table matches the SQLAlchemy ContactSubmission model without data loss.
    """
    logger.info("Checking database schema for contact_submissions...")
    
    try:
        # First, make sure the table exists
        Base.metadata.create_all(bind=engine)

        with engine.begin() as conn:
            # Query existing columns in contact_submissions
            inspector = inspect(conn)
            table_names = inspector.get_table_names()
            
            if "contact_submissions" not in table_names:
                logger.info("Table contact_submissions does not exist yet; create_all created it.")
                return

            existing_cols = {col["name"]: col for col in inspector.get_columns("contact_submissions")}
            logger.info("Existing columns in contact_submissions: %s", list(existing_cols.keys()))

            # Check and add missing columns
            added_cols = []
            for col_name, col_def in MIGRATION_COLUMNS:
                if col_name == "id":
                    continue
                if col_name not in existing_cols:
                    logger.info("Column '%s' is missing in contact_submissions. Adding column...", col_name)
                    alter_query = text(f"ALTER TABLE contact_submissions ADD COLUMN IF NOT EXISTS {col_name} {col_def};")
                    conn.execute(alter_query)
                    added_cols.append(col_name)

            if added_cols:
                logger.info("Successfully added missing columns to contact_submissions: %s", added_cols)
            else:
                logger.info("All required columns already exist in contact_submissions.")

            # Safe backfill and constraint validation
            if "privacy_accepted" in existing_cols or "privacy_accepted" in added_cols:
                conn.execute(text("UPDATE contact_submissions SET privacy_accepted = TRUE WHERE privacy_accepted IS NULL;"))
                try:
                    conn.execute(text("ALTER TABLE contact_submissions ALTER COLUMN privacy_accepted SET DEFAULT TRUE;"))
                except Exception as e:
                    logger.warning("Could not set default on privacy_accepted: %s", e)

            if "looking_for" in existing_cols or "looking_for" in added_cols:
                conn.execute(text("UPDATE contact_submissions SET looking_for = 'Not provided' WHERE looking_for IS NULL;"))

            # Log updated column schema
            updated_cols = [col["name"] for col in inspect(conn).get_columns("contact_submissions")]
            logger.info("Final columns in contact_submissions: %s", updated_cols)

    except Exception:
        logger.exception("Error executing database schema migration for contact_submissions.")
        raise


def get_table_schema() -> list:
    """Returns the list of column details from contact_submissions."""
    run_database_migrations()
    with engine.connect() as conn:
        inspector = inspect(conn)
        cols = inspector.get_columns("contact_submissions")
        return [
            {
                "name": c["name"],
                "type": str(c["type"]),
                "nullable": c["nullable"]
            }
            for c in cols
        ]

