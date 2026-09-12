from dotenv import load_dotenv
import os

load_dotenv()

EMAIL = os.getenv("EMAIL", "").strip()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
import re
import socket
import urllib.parse

def _resolve_database_url(raw_url: str) -> str:
    if not raw_url:
        return "postgresql://postgres:admin123@localhost:5432/postgres"
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        parsed = urllib.parse.urlparse(url)
        # If the hostname is a bare Render internal ID without domain dots (e.g. dpg-daai4qp42hec73aigqeg-a)
        if parsed.hostname and re.match(r"^dpg-[a-z0-9]+-a$", parsed.hostname):
            # Test candidate hostnames to resolve DNS across regions
            candidates = [
                parsed.hostname,
                f"{parsed.hostname}.oregon-postgres.render.com",
                f"{parsed.hostname}.singapore-postgres.render.com",
                f"{parsed.hostname}.frankfurt-postgres.render.com",
                f"{parsed.hostname}.ohio-postgres.render.com",
                f"{parsed.hostname}.virginia-postgres.render.com",
            ]
            for candidate in candidates:
                try:
                    socket.gethostbyname(candidate)
                    netloc = parsed.netloc.replace(parsed.hostname, candidate)
                    url = parsed._replace(netloc=netloc).geturl()
                    break
                except Exception:
                    continue
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
