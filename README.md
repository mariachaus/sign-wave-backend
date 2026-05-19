# SignWave — Backend

FastAPI backend for the SignWave Ukrainian Sign Language learning app.

## Stack

- **FastAPI** — REST API
- **PostgreSQL** + SQLAlchemy — database
- **Keras** — gesture recognition model (GRU with attention, 20 frames × 450 features)
- **Cloudinary** — avatar/image storage
- **JWT** + Google OAuth — authentication

## Project Structure

```
backend/
├── server.py                 # app entry point, routers, CORS, logging
├── database.py               # SQLAlchemy models
├── database_connection.py    # engine & session
├── schemas.py                # Pydantic request/response schemas
├── dependencies.py           # get_current_user_id dependency
├── auth.py                   # /api/auth — register, login, Google OAuth
├── auth_utils.py             # JWT token creation
├── routes_user.py            # /api/user — profile
├── routes_settings.py        # /api/settings — user settings
├── routes_gestures.py        # /api/gestures — gesture library
├── routes_lesson.py          # /api/lessons — lessons & practice
├── routes_daily.py           # /api — daily tasks & streak
├── routes_flashcards.py      # /api — flashcards
├── routes_admin.py           # /api — admin panel
├── routes_ml.py              # /ml — inference endpoints
├── achievement_engine.py     # achievement check logic
├── gesture_stat_engine.py    # per-gesture statistics
├── models/                   # Keras .keras files (not tracked by git)
└── .env.example              # environment variable template
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
pip install fastapi uvicorn sqlalchemy psycopg2-binary python-jose werkzeug keras tensorflow numpy cloudinary pydantic python-multipart requests
```

> If a `requirements.txt` is present: `pip install -r requirements.txt`

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
```

### 4. Add ML model

Place the Keras model file in `models/`:

```
models/sign_language_gru_attention_model-20.keras
models/gesture_classes_gru_attention-20.json
```

The model expects input shape `(batch, 20, 450)` — 20 frames, 225 raw features + 225 delta features per frame.

### 5. Run

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

API available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## API Overview

| Prefix | Description |
|---|---|
| `POST /ml/predict` | Single gesture prediction (20 frames) |
| `POST /ml/predict_batch` | Sliding window batch prediction |
| `POST /api/auth/register` | Register with email/password |
| `POST /api/auth/login` | Login, returns JWT |
| `POST /api/auth/google` | Login via Google OAuth token |
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

## Notes

- CORS is configured for `localhost` and local network IPs (`192.168.x.x`, `10.x.x.x`)
- Logs are written to `logs/app.log` with rotation (max 10 MB, 7 backups)
- Database tables are auto-created on startup via `Base.metadata.create_all`
