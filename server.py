from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from db.connection import engine, SessionLocal
from db.models import Base

# routes
from routes.ml import router as ml_router
from routes.auth import router as auth_router
from routes.user import router as user_router
from routes.settings import router as settings_router
from routes.gestures import router as gestures_router
from routes.lesson import router as lessons_router
from routes.daily import router as daily_router
from routes.admin import router as admin_router
from routes.flashcards import router as flashcards_router

import os
import logging
from logging.handlers import RotatingFileHandler
from services.scheduler import start_scheduler, stop_scheduler

os.environ["GLOG_minloglevel"] = "3"

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("signwave")
logger.setLevel(logging.INFO)
_handler = RotatingFileHandler("logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logger.addHandler(_handler)
logging.basicConfig(level=logging.INFO)


# ---------------- APP ----------------

app = FastAPI(title="Sign Language API")


@app.on_event("startup")
def on_startup():
    start_scheduler()

@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


# ---------------- EXCEPTION HANDLERS ----------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"{request.method} {request.url} → {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Validation error", "details": exc.errors()})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ---------------- CORS ----------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mariachaus.github.io"],
    allow_origin_regex=r"https?://(localhost|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- DB INIT ----------------

Base.metadata.create_all(bind=engine)


# ---------------- ROUTERS ----------------

app.include_router(ml_router)
app.include_router(auth_router, prefix="/api/auth")
app.include_router(user_router, prefix="/api/user")
app.include_router(settings_router, prefix="/api/settings")
app.include_router(gestures_router, prefix="/api/gestures")
app.include_router(lessons_router, prefix="/api")
app.include_router(daily_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(flashcards_router, prefix="/api")


# ---------------- ROOT ----------------

@app.get("/")
def root():
    return {"message": "Server is running: FastAPI + ML + DB connected"}


# ---------------- DB TEST ----------------

@app.get("/test_db")
def test_db():
    try:
        db = SessionLocal()
        from db.models import User
        count = db.query(User).count()
        db.close()
        return {"status": "connected", "users_in_db": count}
    except Exception:
        logger.error("DB connection test failed", exc_info=True)
        return {"status": "error", "detail": "Database unavailable"}
