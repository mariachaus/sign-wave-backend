from prometheus_client import Counter, Histogram, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi import FastAPI

# ----------------- CUSTOM METRICS -----------------

# ML Model Inference Duration
ML_INFERENCE_DURATION = Histogram(
    "ml_inference_duration_seconds",
    "Time spent running ML model inference",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5],
)

# ML Predictions Counter
ML_PREDICTIONS_TOTAL = Counter(
    "ml_predictions_total",
    "Total number of gesture predictions performed",
    ["status"],  # "success", "error", "no_hands"
)

# Active WebSocket connections for real-time video/gesture streaming
WS_ACTIVE_CONNECTIONS = Gauge(
    "websocket_active_connections",
    "Number of active WebSocket connections for gesture streaming",
)

# Rate Limiting Hits Counter
RATE_LIMIT_EXCEEDED_TOTAL = Counter(
    "rate_limit_exceeded_total",
    "Total number of requests blocked by rate limiting",
    ["endpoint"],
)


def setup_monitoring(app: FastAPI) -> Instrumentator:
    """
    Initializes Prometheus metrics instrumentation on the FastAPI application.
    Exposes metrics at /metrics and collects default HTTP metrics (latency, status codes, request count).
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics", "/health", "/docs", "/openapi.json", "/redoc"],
    )

    instrumentator.instrument(app)
    instrumentator.expose(app, endpoint="/metrics", tags=["Monitoring"])

    return instrumentator
