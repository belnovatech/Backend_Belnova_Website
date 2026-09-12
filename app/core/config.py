from dotenv import load_dotenv
import os

load_dotenv()

EMAIL = os.getenv("EMAIL", "info@belnovatech.com").strip()
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
import re
import socket
import urllib.parse

def _resolve_database_url(raw_url: str) -> str:
    # New PostgreSQL instance credentials provided by Render
    NEW_DB_DEFAULT = (
        "postgresql://belnova_db_user:yzV7IiS7pqivO04nir9QqgNT4vgPpmzk@"
        "dpg-daiiv1h594qs738v3pm0-a.oregon-postgres.render.com/belnova_db?sslmode=require"
    )
    if not raw_url:
        return NEW_DB_DEFAULT
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    
    # If the environment still points to the old dead database instance, map to new instance
    if "dpg-daai4qp42hec73aigqeg-a" in url:
        return NEW_DB_DEFAULT

    try:
        parsed = urllib.parse.urlparse(url)
        # If the hostname is a bare Render internal ID without domain dots (e.g. dpg-daiiv1h594qs738v3pm0-a)
        if parsed.hostname and "." not in parsed.hostname and parsed.hostname.startswith("dpg-"):
            region = os.getenv("RENDER_REGION", "oregon")
            target_host = f"{parsed.hostname}.{region}-postgres.render.com"
            netloc = parsed.netloc.replace(parsed.hostname, target_host)
            url = parsed._replace(netloc=netloc).geturl()
        
        # Render external Postgres connections require SSL
        if "sslmode" not in url and "-postgres.render.com" in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}sslmode=require"
    except Exception:
        pass
    return url

DATABASE_URL = _resolve_database_url(os.getenv("DATABASE_URL", ""))


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Add it to the .env file before sending emails."
        )
    return value
