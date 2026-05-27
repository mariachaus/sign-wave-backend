# SignWave — Backend

FastAPI backend for the SignWave Ukrainian Sign Language learning app.

## Stack

- **FastAPI** — REST API + WebSocket
- **PostgreSQL** + SQLAlchemy — database
- **Keras / TensorFlow** — gesture recognition (multiple architectures: GRU, GRU+Attention, LSTM, LSTM+Attention, Transformer, CNN1D; 20 frames × 450 features)
- **MediaPipe** + **OpenCV** — server-side landmark extraction (WebSocket inference for mobile)
- **Cloudinary** — avatar/image storage
- **JWT** + Google OAuth — authentication
- **APScheduler** — background job scheduler (email notifications)
- **smtplib** — email delivery via Gmail SMTP (built-in)

## Project Structure

```
backend/
├── server.py                     # app entry point, routers, CORS, logging
├── schemas.py                    # Pydantic request/response schemas
├── test_email.py                 # send test emails to subscribed users
├── requirements.txt
├── core/
│   └── dependencies.py           # get_current_user_id dependency
├── db/
│   ├── models.py                 # SQLAlchemy ORM models
│   └── connection.py             # engine & session
├── routes/
│   ├── auth.py                   # /api/auth — register, login, Google OAuth, password reset
│   ├── user.py                   # /api/user — profile & avatar
│   ├── settings.py               # /api/settings — user settings
│   ├── gestures.py               # /api/gestures — gesture library
│   ├── lesson.py                 # /api/lessons — lessons & practice
│   ├── daily.py                  # /api — daily tasks & streak
│   ├── flashcards.py             # /api — flashcard sessions (SM-2)
│   ├── admin.py                  # /api/admin — admin panel (users, content, ML model)
│   └── ml.py                     # /ml — inference endpoints & WebSocket
├── services/
│   ├── auth_utils.py             # JWT token creation & verification
│   ├── achievement_engine.py     # achievement check & award logic
│   ├── gesture_stat_engine.py    # SM-2 per-gesture statistics
│   ├── email_service.py          # email templates & SMTP sending
│   └── scheduler.py              # APScheduler jobs (streak reminders, weekly summary)
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_gesture_stat.py
│   ├── test_ml_features.py
│   ├── test_schemas.py
│   └── test_streak.py
└── models/                       # ML model files (not tracked by git)
    ├── sign_language_<arch>_model-<frames>.keras
    ├── gesture_classes_<arch>-<frames>.json
    ├── legacy/                   # older model versions kept for rollback
    └── mediapipe/
        ├── pose_landmarker_lite.task
        └── hand_landmarker.task
```

## Setup

### 1. Clone and create virtual environment

```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux / macOS
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```env
DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/sign-language-db

CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

JWT_SECRET_KEY=your_random_secret

# Email notifications (Gmail SMTP)
MAIL_FROM=your_email@gmail.com
MAIL_PASSWORD=your_gmail_app_password
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
APP_URL=http://localhost:5173
```

> **Gmail App Password:** `myaccount.google.com` → Security → Two-step verification → App passwords → create one for "SignWave"

### 4. Add ML model files

Model and labels files follow a naming convention:

```
models/sign_language_<arch>_model-<frames>.keras
models/gesture_classes_<arch>-<frames>.json
```

Example for the default Transformer model:

```
models/sign_language_transformer_model-20.keras
models/gesture_classes_transformer-20.json
```

The active model is set via `model_path` in `routes/ml.py` (line 25) or switched at runtime through the admin panel without restarting the server.

The model expects input shape `(batch, 20, 450)` — 20 frames, 225 raw keypoint features + 225 delta features per frame.

For WebSocket inference (mobile app), also add MediaPipe task files:

```
models/mediapipe/pose_landmarker_lite.task
models/mediapipe/hand_landmarker.task
```

Download from: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker

### 5. Run

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

`--host 0.0.0.0` makes the server accessible from other devices on the local network (e.g. mobile app on a phone — use the machine's local IP instead of `localhost`).

## API Overview

| Prefix | Description |
|---|---|
| `POST /ml/predict` | Single gesture prediction (20 frames × 450 features) |
| `POST /ml/predict_batch` | Sliding-window batch prediction |
| `WS /ml/ws/predict` | WebSocket: receives pre-extracted features, returns prediction (web client) |
| `WS /ml/ws/gesture` | WebSocket: receives raw JPEG frames, runs MediaPipe + inference (mobile) |
| `POST /api/auth/register` | Register with email/password |
| `POST /api/auth/login` | Login, returns JWT |
| `POST /api/auth/google` | Login via Google OAuth token |
| `POST /api/auth/forgot-password` | Send password reset email |
| `POST /api/auth/reset-password` | Reset password via token |
| `GET/PUT /api/user/...` | Profile & avatar |
| `GET/PUT /api/settings/...` | User settings |
| `GET /api/gestures` | Gesture library |
| `GET/POST /api/lessons/...` | Lessons, practice, completion |
| `GET /api/flashcards/...` | Flashcard sessions (SM-2) |
| `GET /api/daily/...` | Daily tasks & streak |
| `GET /api/admin/stats` | Dashboard stats (admin only) |
| `GET /api/admin/model-info` | Active ML model info (admin only) |
| `GET /api/admin/models` | List all available `.keras` files (admin only) |
| `POST /api/admin/model-activate` | Switch active model at runtime (admin only) |
| `GET/PATCH/DELETE /api/admin/users` | User management (admin only) |
| `GET/POST/PATCH/DELETE /api/admin/gestures` | Gesture content (admin only) |
| `GET/POST/PATCH/DELETE /api/admin/levels` | Level content (admin only) |
| `GET/POST/PATCH/DELETE /api/admin/lessons` | Lesson content (admin only) |

## ML Inference Format

**`POST /ml/predict`**
```json
{
  "features": [[...450 values...], ...]
}
```

Response:
```json
{
  "label": "thank-you",
  "confidence": 0.94,
  "all_scores": { "thank-you": 0.94, "love": 0.03, ... },
  "inference_ms": 12.5
}
```

**`POST /ml/predict_batch`**
```json
{
  "windows": [[[...450...], ...], ...]
}
```

Response:
```json
{
  "predictions": [
    { "label": "love", "confidence": 0.91, "all_scores": { ... } }
  ]
}
```

**`WS /ml/ws/predict`** — web client (pre-extracted features)

Send: `{ "features": [[...450...], ...] }` (20 frames)

Receive:
```json
{ "label": "love", "confidence": 0.89, "all_scores": { ... }, "inference_ms": 11.2 }
```

**`WS /ml/ws/gesture`** — mobile client (raw frames)

Send: `{ "frame": "<base64-encoded JPEG>" }`

Receive:
```json
{ "status": "collecting",  "buffer_size": 12, "lm": { ... } }
{ "status": "prediction",  "label": "love", "confidence": 0.87, "buffer_size": 20, "lm": { ... }, "inference_ms": 13.1 }
{ "status": "no_person",   "buffer_size": 0 }
{ "status": "model_reloading", "buffer_size": 20, "lm": { ... } }
```

`lm` contains raw landmark coordinates (`pose`, `left_hand`, `right_hand`) for skeleton drawing on the client.

During model reload, endpoints return HTTP 503 (`/predict`) or `{"error": "model_reloading"}` (WebSocket) until the new model is ready.

## Admin: ML Model Management

The active model can be switched at runtime from the admin panel (Overview tab) without restarting the server.

**How it works:**
- `GET /api/admin/models` scans `models/*.keras` and returns a list with size, labels file status, and whether each model is currently active.
- `POST /api/admin/model-activate` loads the new model under a `threading.Lock` to prevent concurrent reloads. While loading, inference requests receive a 503 response. Labels are automatically switched by deriving the labels filename from the model filename (`sign_language_<arch>_model-<frames>.keras` → `gesture_classes_<arch>-<frames>.json`).

**Naming convention** (required for automatic label switching):
```
sign_language_gru_attention_model-20.keras  →  gesture_classes_gru_attention-20.json
sign_language_transformer_model-20.keras    →  gesture_classes_transformer-20.json
```

Old model versions can be kept in `models/legacy/` — they are not listed in the admin panel.

## Email Notifications

Users can enable email notifications in Settings. Two scheduled jobs run automatically:

| Job | Schedule | Description |
|-----|----------|-------------|
| Streak reminder | Daily at 19:00 | Sent to users who haven't logged in today and have an active streak |
| Weekly summary | Every Monday at 10:00 | XP earned, lessons completed, current streak for the past 7 days |

Email language matches the user's language setting (Ukrainian / English).

**Test sending** to all subscribed users:
```bash
python test_email.py
```

## Tests

```bash
pytest tests/
# with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

56 tests across 5 modules (auth, SM-2 algorithm, streak logic, ML feature extraction, Pydantic schemas). Overall coverage: 99%.

## Deployment

```bash
# 1. Pull latest changes
git pull

# 2. Install new dependencies (if any)
pip install -r requirements.txt

# 3. Start server
uvicorn server:app --host 0.0.0.0 --port 8000
```

**Database backup / restore:**
```bash
pg_dump -U postgres sign-language-db > sign-wave.sql
psql  -U postgres -d sign-language-db < sign-wave.sql
```

## Notes

- CORS is configured for `localhost`, GitHub Pages (`mariachaus.github.io`), and local network IPs (`192.168.x.x`, `10.x.x.x`)
- Logs are written to `logs/app.log` with rotation (max 10 MB, 7 backups)
- Database tables are auto-created on first startup via `Base.metadata.create_all`
- Scheduler starts automatically with the server and stops on shutdown
- MediaPipe WebSocket endpoint silently skips if `mediapipe`/`opencv` packages are not installed
- Model binary files (`.keras`, `.task`) are excluded from git via `.gitignore`
