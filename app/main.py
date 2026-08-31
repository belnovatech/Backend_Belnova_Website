import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.contact import router
from app.database import engine, Base
from app.models.contact import ContactSubmission

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Create database tables automatically
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Belnova Mail Notification API",
    version="1.0.0",
    description="Backend API for Website3 Mail Notifications"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
def home():

    return {
        "message":"Backend Running Successfully"
    }