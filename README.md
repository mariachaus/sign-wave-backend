# SignWave — Backend

FastAPI backend for the SignWave Ukrainian Sign Language learning app.

## Stack

- **FastAPI** — REST API
- **PostgreSQL** + SQLAlchemy — database
- **Keras / TensorFlow** — gesture recognition model (GRU with attention, 20 frames × 450 features)
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
│   ├── models.py                 # SQLAlchemy models
│   └── connection.py             # engine & session
├── routes/
│   ├── auth.py                   # /api/auth — register, login, Google OAuth, password reset
│   ├── user.py                   # /api/user — profile
│   ├── settings.py               # /api/settings — user settings
│   ├── gestures.py               # /api/gestures — gesture library
│   ├── lesson.py                 # /api/lessons — lessons & practice
│   ├── daily.py                  # /api — daily tasks & streak
│   ├── flashcards.py             # /api — flashcards
│   ├── admin.py                  # /api — admin panel
│   └── ml.py                     # /ml — inference endpoints & WebSocket
├── services/
│   ├── auth_utils.py             # JWT token creation
│   ├── achievement_engine.py     # achievement check logic
│   ├── gesture_stat_engine.py    # per-gesture statistics
│   ├── email_service.py          # email templates & SMTP sending
│   └── scheduler.py              # APScheduler jobs (streak reminders, weekly summary)
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_gesture_stat.py
│   ├── test_ml_features.py
│   ├── test_schemas.py
│   └── test_streak.py
└── models/                       # Keras .keras files + MediaPipe .task files (not tracked by git)
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

Place the following files in `models/`:

```
models/sign_language_gru_attention_model-20.keras
models/gesture_classes_cnn1d-20.json
```

For WebSocket inference (mobile app), also add MediaPipe task files:

```
models/mediapipe/pose_landmarker_lite.task
models/mediapipe/hand_landmarker.task
```

Download from: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker

The model expects input shape `(batch, 20, 450)` — 20 frames, 225 raw features + 225 delta features per frame.

### 5. Run

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

API available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

`--host 0.0.0.0` makes the server accessible from other devices on the local network (e.g. mobile app running on a phone — use the machine's local IP instead of `localhost`).

## API Overview

| Prefix | Description |
|---|---|
| `POST /ml/predict` | Single gesture prediction (20 frames) |
| `POST /ml/predict_batch` | Sliding window batch prediction |
| `WS /ml/ws/gesture` | WebSocket: frame-by-frame inference with MediaPipe (mobile) |
| `POST /api/auth/register` | Register with email/password |
| `POST /api/auth/login` | Login, returns JWT |
| `POST /api/auth/google` | Login via Google OAuth token |
| `POST /api/auth/forgot-password` | Send password reset email |
| `POST /api/auth/reset-password` | Reset password via token |
| `GET/PUT /api/user/...` | Profile & avatar |
| `GET/PUT /api/settings/...` | User settings |
| `GET /api/gestures` | Gesture library |
| `GET/POST /api/lessons/...` | Lessons, practice, completion |
| `GET /api/flashcards/...` | Flashcard sessions |
| `GET /api/daily/...` | Daily tasks & streak |
| `GET /api/admin/...` | Admin panel (users, content) |

## ML Inference Format

**`POST /ml/predict`**
```json
{
  "features": [[...450 values...], ...]  // 20 frames × 450 features
}
```

Response:
```json
{
  "label": "thank-you",
  "confidence": 0.94,
  "all_scores": { "thank-you": 0.94, "love": 0.03, ... }
}
```

**`POST /ml/predict_batch`**
```json
{
  "windows": [[[...450...], ...], ...]  // N windows × 20 frames × 450 features
}
```

**`WS /ml/ws/gesture`**

Send frames as JSON: `{ "frame": "<base64-encoded JPEG>" }`

Responses:
```json
{ "status": "collecting", "buffer_size": 12, "lm": { ... } }
{ "status": "prediction", "label": "love", "confidence": 0.87, "buffer_size": 20, "lm": { ... } }
{ "status": "no_person", "buffer_size": 0 }
```

`lm` contains raw landmark coordinates for skeleton drawing on the client.

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
```

## Notes

- CORS is configured for `localhost` and local network IPs (`192.168.x.x`, `10.x.x.x`)
- Logs are written to `logs/app.log` with rotation (max 10 MB, 7 backups)
- Database tables are auto-created on startup via `Base.metadata.create_all`
- Scheduler starts automatically with the server and stops on shutdown
- MediaPipe WebSocket endpoint silently skips if `mediapipe`/`opencv` packages are not installed
