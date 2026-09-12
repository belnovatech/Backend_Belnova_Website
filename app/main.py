import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.contact import router
from app.database import engine, Base
from app.models.contact import ContactSubmission
from app.db_migrations import run_database_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Non-blocking startup: start HTTP server immediately, run DB migrations in background task
    async def _async_startup_migrate():
        try:
            logger.info("Initializing database tables and running migrations in background...")
            await asyncio.to_thread(run_database_migrations)
            logger.info("Database initialized and migrations applied successfully.")
        except Exception as e:
            logger.warning("Background database migration deferred: %s", e)

    asyncio.create_task(_async_startup_migrate())
    yield


app = FastAPI(
    title="Belnova Mail Notification API",
    version="1.0.0",
    description="Backend API for Website3 Mail Notifications",
    lifespan=lifespan
)

# Configure CORS with explicit allowed origins and regex for previews
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
else:
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:4173",
        "https://belnovatech.com",
        "https://www.belnovatech.com",
        "https://backend-belnova-website.onrender.com",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*belnova.*|https://.*vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
def home():
    return {
        "message": "Backend Running Successfully"
    }


@app.get("/health")
def liveness_health():
    """Lightweight health check that returns immediately without DB overhead."""
    return {
        "status": "ok",
        "service": "Belnova Backend API"
    }



@app.get("/api/health")
def health():
    try:
        from app.db_migrations import get_table_schema
        cols = get_table_schema()
        brevo_key = os.getenv("BREVO_API_KEY", "").strip()
        return {
            "status": "healthy",
            "database": "connected",
            "email_service": "configured" if bool(brevo_key) else "missing_BREVO_API_KEY",
            "columns": cols
        }
    except Exception as e:
        logger.exception("Health check failed: %s", e)
        return {
            "status": "unhealthy",
            "error": f"{type(e).__name__}: {str(e)}"
        }