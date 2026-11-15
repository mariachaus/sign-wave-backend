
import logging
import os
import time

import psutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db.connection import SessionLocal
import routes.ml as ml
from services.scheduler import scheduler

router = APIRouter(tags=["health"])
logger = logging.getLogger("signwave")

_CONFIG_VARS = {
    "cloudinary": [
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
    ],
    "smtp": [
        "MAIL_FROM",
        "MAIL_PASSWORD",
        "MAIL_SERVER",
    ],
}

_EXPECTED_JOBS = {
    "streak_reminder",
    "weekly_summary",
    "purge_auth_attempts",
}

_process = psutil.Process(os.getpid())
_process_start_time = _process.create_time()


@router.get("/health")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    checks = {
        "database": False,
        "model": False,
    }

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        logger.error("Health check: database unavailable", exc_info=True)
    finally:
        db.close()

    checks["model"] = (
        ml.model is not None
        and not ml._model_loading
    )

    is_ready = all(checks.values())

    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "unavailable",
            **checks,
        },
    )


@router.get("/health/details")
def health_details():
    details = {}

    # Database response time
    db = SessionLocal()
    try:
        start = time.perf_counter()
        db.execute(text("SELECT 1"))
        db_time = (time.perf_counter() - start) * 1000

        details["database"] = {
            "status": "ok",
            "response_time_ms": round(db_time, 2),
        }
    except Exception:
        logger.error("Health details: database unavailable", exc_info=True)
        details["database"] = {"status": "error"}
    finally:
        db.close()

    # ML model
    details["model"] = {
        "status": (
            "loading" if ml._model_loading
            else "loaded" if ml.model is not None
            else "unavailable"
        ),
        "name": os.path.basename(ml.model_path),
        "classes_count": len(ml.LABELS),
    }


    # APScheduler
    try:
        jobs = scheduler.get_jobs()
        registered_jobs = {job.id for job in jobs}
        missing_jobs = sorted(_EXPECTED_JOBS - registered_jobs)

        details["scheduler"] = {
            "status": (
                "ok"
                if scheduler.running and not missing_jobs
                else "warning"
            ),
            "running": scheduler.running,
            "registered_jobs": sorted(registered_jobs),
            "missing_jobs": missing_jobs,
        }
    except Exception:
        logger.error("Health details: scheduler check failed", exc_info=True)
        details["scheduler"] = {"status": "error"}

    # Process information
    try:
        details["process"] = {
            "uptime_seconds": round(
                time.time() - _process_start_time, 2
            ),
            "memory_usage_mb": round(
                ml.get_process_memory_mb(), 2
            ),
        }
    except Exception:
        logger.error("Health details: process check failed", exc_info=True)
        details["process"] = {"status": "error"}

    # Environment configuration
    details["config"] = {
        name: all(os.getenv(variable) for variable in variables)
        for name, variables in _CONFIG_VARS.items()
    }

    return {
        "status": "ok",
        "details": details,
    }
