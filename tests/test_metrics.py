from fastapi import FastAPI
from prometheus_client import generate_latest
from core.metrics import (
    setup_monitoring,
    ML_INFERENCE_DURATION,
    ML_PREDICTIONS_TOTAL,
    WS_ACTIVE_CONNECTIONS,
    RATE_LIMIT_EXCEEDED_TOTAL,
)


def test_metrics_route_registered():
    app = FastAPI()
    setup_monitoring(app)
    routes = [r.path for r in app.routes]
    assert "/metrics" in routes


def test_custom_metrics_generation():
    # Trigger custom metrics
    ML_PREDICTIONS_TOTAL.labels(status="success").inc()
    ML_INFERENCE_DURATION.observe(0.042)
    WS_ACTIVE_CONNECTIONS.set(3)
    RATE_LIMIT_EXCEEDED_TOTAL.labels(endpoint="login").inc()

    output = generate_latest().decode("utf-8")

    assert "ml_predictions_total" in output
    assert 'status="success"' in output
    assert "ml_inference_duration_seconds" in output
    assert "websocket_active_connections" in output
    assert "rate_limit_exceeded_total" in output
