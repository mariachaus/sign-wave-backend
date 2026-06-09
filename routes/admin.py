import os
import cloudinary # type: ignore
import cloudinary.uploader # type: ignore
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from typing import Optional

load_dotenv()
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

from db.connection import get_db
from db.models import User, Gesture, GestureI18n, GestureSynonym, GestureCategory, Category, CategoryI18n, LessonGesturesPool, UserGestureStat, UserErrorLog, Lesson, DailyTaskTemplate, Level, LevelI18n, LessonI18n, LessonContent, UserLesson
from core.dependencies import get_current_user_id
from schemas import AdminUserUpdate, AdminTemplateCreate, AdminTemplateUpdate, AdminGestureCreate, AdminGestureUpdate, AdminLessonCreate, AdminLessonUpdate, AdminPoolAdd, AdminContentCreate, AdminContentUpdate, AdminLevelCreate, AdminLevelUpdate, AdminCategoryCreate, AdminCategoryUpdate

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    user = db.get(User, user_id)
    if not user or user.role != "admin": # type: ignore
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


# ---------------- STATS ----------------

@router.get("/stats")
def get_stats(admin_id: int = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "total_users":    db.query(func.count(User.id)).scalar() or 0,
        "active_users":   db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0,
        "total_gestures": db.query(func.count(Gesture.id)).scalar() or 0,
        "active_gestures":db.query(func.count(Gesture.id)).filter(Gesture.is_active == True).scalar() or 0,
        "total_lessons":  db.query(func.count(Lesson.id)).scalar() or 0,
        "total_xp":       db.query(func.sum(User.total_xp)).scalar() or 0,
    }


@router.get("/model-info")
def get_model_info(admin_id: int = Depends(require_admin)):
    import os
    from routes.ml import model, LABELS, model_path

    model_file = os.path.basename(model_path)
    model_size_mb = round(os.path.getsize(model_path) / (1024 * 1024), 2) if os.path.exists(model_path) else 0

    param_count = None
    if model is not None:
        try:
            param_count = model.count_params()
        except Exception:
            pass

    return {
        "model_file": model_file,
        "model_loaded": model is not None,
        "model_size_mb": model_size_mb,
        "num_classes": len(LABELS),
        "classes": LABELS,
        "window_frames": 20,
        "features_per_frame": 450,
        "param_count": param_count,
    }


@router.get("/models")
def list_models(admin_id: int = Depends(require_admin)):
    import os, re
    from routes.ml import MODELS_DIR, model_path

    active_file = os.path.basename(model_path)
    result = []
    try:
        entries = os.listdir(MODELS_DIR)
    except Exception:
        return []
    for f in sorted(entries):
        if not f.endswith(".keras"):
            continue
        full = os.path.join(MODELS_DIR, f)
        if not os.path.isfile(full):
            continue
        size_mb = round(os.path.getsize(full) / (1024 * 1024), 2)
        m = re.match(r"sign_language_(.+)_model-(\d+)\.keras", f)
        labels_file = None
        has_labels = False
        if m:
            labels_file = f"gesture_classes_{m.group(1)}-{m.group(2)}.json"
            has_labels = os.path.exists(os.path.join(MODELS_DIR, labels_file))
        result.append({
            "filename": f,
            "size_mb": size_mb,
            "labels_file": labels_file,
            "has_labels": has_labels,
            "is_active": f == active_file,
        })
    return result


@router.post("/model-activate")
def activate_model(body: dict, admin_id: int = Depends(require_admin)):
    import os, re, json as _json, keras as _keras
    import routes.ml as ml_module
    import gc

    filename = (body.get("model_file") or "").strip()
    if not filename.endswith(".keras"):
        raise HTTPException(status_code=400, detail="Invalid model filename")

    new_model_path = os.path.join(ml_module.MODELS_DIR, filename)
    if not os.path.exists(new_model_path):
        raise HTTPException(status_code=404, detail="Model file not found")

    if not ml_module._reload_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Model reload already in progress")

    try:
        ml_module._model_loading = True

        # === MEMORY CLEANUP BEFORE LOADING ===
        print(f"[admin] Clearing memory from previous model...")
        if ml_module.model is not None:
            del ml_module.model 
            ml_module.model = None
        
        _keras.backend.clear_session()  
        gc.collect()  
        # =============================================================

        print(f"[admin] Loading model: {filename}")

        new_model = _keras.models.load_model(new_model_path, compile=False)

        m = re.match(r"sign_language_(.+)_model-(\d+)\.keras", filename)
        new_labels = ml_module.LABELS
        new_labels_path = ml_module.labels_path
        if m:
            lf = f"gesture_classes_{m.group(1)}-{m.group(2)}.json"
            lp = os.path.join(ml_module.MODELS_DIR, lf)
            if os.path.exists(lp):
                with open(lp, "r", encoding="utf-8") as f:
                    new_labels = _json.load(f)
                new_labels_path = lp

        ml_module.model = new_model
        ml_module.LABELS = new_labels
        ml_module.model_path = new_model_path
        ml_module.labels_path = new_labels_path
        print(f"[admin] Model switched to: {filename} ({len(new_labels)} classes)")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load model: {e}")
    finally:
        ml_module._model_loading = False
        ml_module._reload_lock.release()

    return {
        "ok": True,
        "model_file": filename,
        "num_classes": len(new_labels),
        "labels_found": new_labels_path != ml_module.labels_path or os.path.exists(new_labels_path),
    }


# ---------------- USERS ----------------

@router.get("/users")
def get_users(
    search: str = "",
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 25,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if search:
        q = q.filter(
            User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
        )
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    total = q.count()
    users = q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "total_xp": u.total_xp or 0,
                "created_at": u.created_at.strftime("%d %b %Y") if u.created_at else "—", # type: ignore
            }
            for u in users
        ],
    }


@router.patch("/users/{target_id}")
def update_user(
    target_id: int,
    body: AdminUserUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot modify your own account")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role is not None:
        user.role = body.role # type: ignore
    if body.is_active is not None:
        user.is_active = body.is_active # type: ignore
    db.commit()
    return {"ok": True}


@router.delete("/users/{target_id}")
def delete_user(
    target_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"ok": True}


# ---------------- GESTURES ----------------

@router.get("/gestures")
def get_gestures(
    search: str = "",
    is_active: Optional[bool] = None,
    is_dynamic: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    GestureI18nUK = aliased(GestureI18n)
    GestureI18nEN = aliased(GestureI18n)
    q = (
        db.query(Gesture, GestureI18nUK, GestureI18nEN)
        .outerjoin(GestureI18nUK, (GestureI18nUK.gesture_id == Gesture.id) & (GestureI18nUK.language_code == "uk"))
        .outerjoin(GestureI18nEN, (GestureI18nEN.gesture_id == Gesture.id) & (GestureI18nEN.language_code == "en"))
    )
    if search:
        q = q.filter(
            Gesture.model_label.ilike(f"%{search}%") |
            GestureI18nUK.name.ilike(f"%{search}%") |
            GestureI18nEN.name.ilike(f"%{search}%")
        )
    if is_active is not None:
        q = q.filter(Gesture.is_active == is_active)
    if is_dynamic is not None:
        q = q.filter(Gesture.is_dynamic == is_dynamic)
    total = q.count()
    if search:
        s = search.lower()
        relevance = case(
            (func.lower(GestureI18nUK.name) == s, 0),
            (func.lower(GestureI18nUK.name).ilike(f"{s}%"), 1),
            (func.lower(GestureI18nEN.name) == s, 0),
            (func.lower(GestureI18nEN.name).ilike(f"{s}%"), 1),
            else_=2,
        )
        rows = q.order_by(relevance, Gesture.id).offset(skip).limit(limit).all()
    else:
        rows = q.order_by(Gesture.id).offset(skip).limit(limit).all()
    return {
        "total": total,
        "gestures": [
            {
                "id": g.id,
                "name": (gi_uk.name if gi_uk else None) or (gi_en.name if gi_en else "—"),
                "name_uk": gi_uk.name if gi_uk else "",
                "name_en": gi_en.name if gi_en else "",
                "description_uk": gi_uk.description if gi_uk else "",
                "description_en": gi_en.description if gi_en else "",
                "model_label": g.model_label,
                "is_dynamic": g.is_dynamic,
                "is_active": g.is_active,
                "video_url": g.video_url or "",
                "illustration_url": g.illustration_url or "",
                "thumbnail_url": g.thumbnail_url or "",
                "created_at": g.created_at.strftime("%d %b %Y") if g.created_at else "—",
            }
            for g, gi_uk, gi_en in rows
        ],
    }


@router.post("/gestures")
def create_gesture(
    body: AdminGestureCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    gesture = Gesture(
        model_label=body.model_label,
        video_url=body.video_url,
        is_dynamic=body.is_dynamic,
        is_active=body.is_active,
        illustration_url=body.illustration_url,
        thumbnail_url=body.thumbnail_url,
    )
    db.add(gesture)
    db.flush()
    if body.name_uk.strip():
        db.add(GestureI18n(gesture_id=gesture.id, language_code="uk", name=body.name_uk.strip(), description=body.description_uk))
    if body.name_en.strip():
        db.add(GestureI18n(gesture_id=gesture.id, language_code="en", name=body.name_en.strip(), description=body.description_en))
    db.commit()
    db.refresh(gesture)
    return {"id": gesture.id, "ok": True}


@router.post("/upload-gesture-image")
async def upload_gesture_image(
    file: UploadFile = File(...),
    image_type: str = Query(..., pattern="^(illustration|thumbnail)$"),
    gesture_id: int = Query(...),
    admin_id: int = Depends(require_admin),
):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPEG, PNG or WebP images are allowed")
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5 MB")
    folder = "signwave/illustrations" if image_type == "illustration" else "signwave/thumbnails"
    result = cloudinary.uploader.upload(
        contents,
        folder=folder,
        public_id=f"gesture_{gesture_id}",
        overwrite=True,
    )
    optimized_url = result["secure_url"].replace("/upload/", "/upload/q_auto/f_auto/")
    return {"url": optimized_url}


@router.delete("/gestures/{gesture_id}")
def delete_gesture(
    gesture_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    gesture = db.get(Gesture, gesture_id)
    if not gesture:
        raise HTTPException(status_code=404, detail="Gesture not found")

    db.query(UserErrorLog).filter(UserErrorLog.gesture_id == gesture_id).update({"gesture_id": None})
    db.query(UserGestureStat).filter(UserGestureStat.gesture_id == gesture_id).delete()
    db.query(LessonGesturesPool).filter(LessonGesturesPool.gesture_id == gesture_id).delete()
    db.query(GestureCategory).filter(GestureCategory.gesture_id == gesture_id).delete()
    db.query(GestureSynonym).filter(GestureSynonym.gesture_id == gesture_id).delete()

    db.delete(gesture)
    db.commit()
    return {"ok": True}


@router.patch("/gestures/{gesture_id}")
def update_gesture(
    gesture_id: int,
    body: AdminGestureUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    gesture = db.get(Gesture, gesture_id)
    if not gesture:
        raise HTTPException(status_code=404, detail="Gesture not found")
    if body.is_active is not None:
        gesture.is_active = body.is_active # type: ignore
    if body.is_dynamic is not None:
        gesture.is_dynamic = body.is_dynamic # type: ignore
    if body.video_url is not None:
        gesture.video_url = body.video_url # type: ignore
    if body.illustration_url is not None:
        gesture.illustration_url = body.illustration_url # type: ignore
    if body.thumbnail_url is not None:
        gesture.thumbnail_url = body.thumbnail_url # type: ignore

    for lang, name, desc in [("uk", body.name_uk, body.description_uk), ("en", body.name_en, body.description_en)]:
        if name is not None:
            i18n = db.query(GestureI18n).filter_by(gesture_id=gesture_id, language_code=lang).first()
            if i18n:
                i18n.name = name # type: ignore
                if desc is not None:
                    i18n.description = desc # type: ignore
            else:
                db.add(GestureI18n(gesture_id=gesture_id, language_code=lang, name=name, description=desc))

    db.commit()
    return {"ok": True}


# ---------------- SYNONYMS ----------------

@router.get("/gestures/{gesture_id}/synonyms")
def get_synonyms(
    gesture_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(GestureSynonym).filter_by(gesture_id=gesture_id).order_by(GestureSynonym.language_code).all()
    return [{"id": r.id, "name": r.name, "language_code": r.language_code} for r in rows]


@router.post("/gestures/{gesture_id}/synonyms")
def add_synonym(
    gesture_id: int,
    body: dict,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = (body.get("name") or "").strip()
    lang = body.get("language_code", "uk")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not db.get(Gesture, gesture_id):
        raise HTTPException(status_code=404, detail="Gesture not found")
    syn = GestureSynonym(gesture_id=gesture_id, name=name, language_code=lang)
    db.add(syn)
    db.commit()
    db.refresh(syn)
    return {"id": syn.id, "name": syn.name, "language_code": syn.language_code}


@router.delete("/gestures/{gesture_id}/synonyms/{synonym_id}")
def delete_synonym(
    gesture_id: int,
    synonym_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    syn = db.query(GestureSynonym).filter_by(id=synonym_id, gesture_id=gesture_id).first()
    if not syn:
        raise HTTPException(status_code=404, detail="Synonym not found")
    db.delete(syn)
    db.commit()
    return {"ok": True}


# ---------------- DAILY TASK TEMPLATES ----------------

@router.get("/templates")
def get_templates(
    task_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 25,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(DailyTaskTemplate).order_by(DailyTaskTemplate.id)
    if task_type:
        q = q.filter(DailyTaskTemplate.task_type == task_type)
    if is_active is not None:
        q = q.filter(DailyTaskTemplate.is_active == is_active)
    total = q.count()
    templates = q.offset(skip).limit(limit).all()
    return {
        "total": total,
        "templates": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "target_value": t.target_value,
                "xp_reward": t.xp_reward,
                "is_active": t.is_active,
            }
            for t in templates
        ],
    }


@router.post("/templates")
def create_template(
    body: AdminTemplateCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tmpl = DailyTaskTemplate(
        task_type=body.task_type,
        target_value=body.target_value,
        xp_reward=body.xp_reward,
        is_active=body.is_active,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {"id": tmpl.id, "ok": True}


@router.patch("/templates/{template_id}")
def update_template(
    template_id: int,
    body: AdminTemplateUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tmpl = db.get(DailyTaskTemplate, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.task_type is not None:
        tmpl.task_type = body.task_type # type: ignore
    if body.target_value is not None:
        tmpl.target_value = body.target_value # type: ignore
    if body.xp_reward is not None:
        tmpl.xp_reward = body.xp_reward # type: ignore
    if body.is_active is not None:
        tmpl.is_active = body.is_active # type: ignore
    db.commit()
    return {"ok": True}


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tmpl = db.get(DailyTaskTemplate, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(tmpl)
    db.commit()
    return {"ok": True}


# ---------------- LEVELS (for selectors) ----------------

@router.get("/levels")
def get_levels(admin_id: int = Depends(require_admin), db: Session = Depends(get_db)):
    LevelI18nUK = aliased(LevelI18n)
    LevelI18nEN = aliased(LevelI18n)
    rows = (
        db.query(Level, LevelI18nUK, LevelI18nEN)
        .outerjoin(LevelI18nUK, (LevelI18nUK.level_id == Level.id) & (LevelI18nUK.language_code == "uk"))
        .outerjoin(LevelI18nEN, (LevelI18nEN.level_id == Level.id) & (LevelI18nEN.language_code == "en"))
        .order_by(Level.id)
        .all()
    )
    return [
        {
            "id": lv.id,
            "is_active": lv.is_active,
            "name_uk": li_uk.name if li_uk else "",
            "name_en": li_en.name if li_en else "",
            "description_uk": li_uk.description if li_uk else "",
            "description_en": li_en.description if li_en else "",
        }
        for lv, li_uk, li_en in rows
    ]


@router.post("/levels")
def create_level(
    body: AdminLevelCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    level = Level(is_active=body.is_active)
    db.add(level)
    db.flush()
    if body.name_uk.strip():
        db.add(LevelI18n(level_id=level.id, language_code="uk", name=body.name_uk.strip(), description=body.description_uk))
    if body.name_en.strip():
        db.add(LevelI18n(level_id=level.id, language_code="en", name=body.name_en.strip(), description=body.description_en))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create level")
    db.refresh(level)
    return {"id": level.id, "ok": True}


@router.patch("/levels/{level_id}")
def update_level(
    level_id: int,
    body: AdminLevelUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    level = db.get(Level, level_id)
    if not level:
        raise HTTPException(status_code=404, detail="Level not found")
    if body.is_active is not None:
        level.is_active = body.is_active  # type: ignore
    for lang, name, desc in [("uk", body.name_uk, body.description_uk), ("en", body.name_en, body.description_en)]:
        if name is not None:
            i18n_row = db.query(LevelI18n).filter_by(level_id=level_id, language_code=lang).first()
            if i18n_row:
                i18n_row.name = name  # type: ignore
                if desc is not None:
                    i18n_row.description = desc  # type: ignore
            else:
                db.add(LevelI18n(level_id=level_id, language_code=lang, name=name, description=desc))
    db.commit()
    return {"ok": True}


@router.delete("/levels/{level_id}")
def delete_level(
    level_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    level = db.get(Level, level_id)
    if not level:
        raise HTTPException(status_code=404, detail="Level not found")
    lesson_ids = [r[0] for r in db.query(Lesson.id).filter(Lesson.level_id == level_id).all()]
    if lesson_ids:
        db.query(UserErrorLog).filter(UserErrorLog.lesson_id.in_(lesson_ids)).update({"lesson_id": None}, synchronize_session=False)
        db.query(LessonGesturesPool).filter(LessonGesturesPool.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
        db.query(LessonI18n).filter(LessonI18n.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
        db.query(LessonContent).filter(LessonContent.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
        db.query(Lesson).filter(Lesson.id.in_(lesson_ids)).delete(synchronize_session=False)
    db.query(LevelI18n).filter(LevelI18n.level_id == level_id).delete()
    db.delete(level)
    db.commit()
    return {"ok": True}


# ---------------- LESSONS ----------------

@router.get("/lessons")
def get_lessons(
    search: str = "",
    level_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 25,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    LessonI18nUK = aliased(LessonI18n)
    LessonI18nEN = aliased(LessonI18n)
    q = (
        db.query(Lesson, LessonI18nUK, LessonI18nEN)
        .outerjoin(LessonI18nUK, (LessonI18nUK.lesson_id == Lesson.id) & (LessonI18nUK.language_code == "uk"))
        .outerjoin(LessonI18nEN, (LessonI18nEN.lesson_id == Lesson.id) & (LessonI18nEN.language_code == "en"))
    )
    if search:
        q = q.filter(LessonI18nUK.name.ilike(f"%{search}%") | LessonI18nEN.name.ilike(f"%{search}%"))
    if level_id is not None:
        q = q.filter(Lesson.level_id == level_id)
    if is_active is not None:
        q = q.filter(Lesson.is_active == is_active)
    total = q.count()
    rows = q.order_by(Lesson.level_id, Lesson.order_index).offset(skip).limit(limit).all()
    return {
        "total": total,
        "lessons": [
            {
                "id": ls.id,
                "level_id": ls.level_id,
                "order_index": ls.order_index,
                "is_active": ls.is_active,
                "name_uk": li_uk.name if li_uk else "",
                "name_en": li_en.name if li_en else "",
                "description_uk": li_uk.description if li_uk else "",
                "description_en": li_en.description if li_en else "",
            }
            for ls, li_uk, li_en in rows
        ],
    }


@router.post("/lessons")
def create_lesson(
    body: AdminLessonCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    lesson = Lesson(level_id=body.level_id, order_index=body.order_index, is_active=body.is_active)
    db.add(lesson)
    db.flush()
    if body.name_uk.strip():
        db.add(LessonI18n(lesson_id=lesson.id, language_code="uk", name=body.name_uk.strip(), description=body.description_uk))
    if body.name_en.strip():
        db.add(LessonI18n(lesson_id=lesson.id, language_code="en", name=body.name_en.strip(), description=body.description_en))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A lesson with this order index already exists in this level")
    db.refresh(lesson)
    return {"id": lesson.id, "ok": True}


@router.patch("/lessons/{lesson_id}")
def update_lesson(
    lesson_id: int,
    body: AdminLessonUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if body.level_id is not None:
        lesson.level_id = body.level_id  # type: ignore
    if body.order_index is not None:
        lesson.order_index = body.order_index  # type: ignore
    if body.is_active is not None:
        lesson.is_active = body.is_active  # type: ignore
    for lang, name, desc in [("uk", body.name_uk, body.description_uk), ("en", body.name_en, body.description_en)]:
        if name is not None:
            i18n_row = db.query(LessonI18n).filter_by(lesson_id=lesson_id, language_code=lang).first()
            if i18n_row:
                i18n_row.name = name  # type: ignore
                if desc is not None:
                    i18n_row.description = desc  # type: ignore
            else:
                db.add(LessonI18n(lesson_id=lesson_id, language_code=lang, name=name, description=desc))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A lesson with this order index already exists in this level")
    return {"ok": True}


@router.delete("/lessons/{lesson_id}")
def delete_lesson(
    lesson_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    db.query(UserErrorLog).filter(UserErrorLog.lesson_id == lesson_id).update({"lesson_id": None})
    db.query(LessonGesturesPool).filter(LessonGesturesPool.lesson_id == lesson_id).delete()
    db.query(LessonI18n).filter(LessonI18n.lesson_id == lesson_id).delete()
    db.query(LessonContent).filter(LessonContent.lesson_id == lesson_id).delete()
    db.delete(lesson)
    db.commit()
    return {"ok": True}


# ---------------- LESSON GESTURES POOL ----------------

@router.get("/lessons/{lesson_id}/pool")
def get_lesson_pool(
    lesson_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(LessonGesturesPool, Gesture, GestureI18n)
        .join(Gesture, LessonGesturesPool.gesture_id == Gesture.id)
        .outerjoin(GestureI18n, (GestureI18n.gesture_id == Gesture.id) & (GestureI18n.language_code == "uk"))
        .filter(LessonGesturesPool.lesson_id == lesson_id)
        .all()
    )
    return [
        {
            "id": p.id,
            "gesture_id": p.gesture_id,
            "is_new_for_this_lesson": p.is_new_for_this_lesson,
            "gesture_name": (gi.name if gi else None) or g.model_label,
        }
        for p, g, gi in rows
    ]


@router.post("/lessons/{lesson_id}/pool")
def add_to_pool(
    lesson_id: int,
    body: AdminPoolAdd,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not db.get(Lesson, lesson_id):
        raise HTTPException(status_code=404, detail="Lesson not found")
    if db.query(LessonGesturesPool).filter_by(lesson_id=lesson_id, gesture_id=body.gesture_id).first():
        raise HTTPException(status_code=400, detail="Gesture already in pool")
    item = LessonGesturesPool(lesson_id=lesson_id, gesture_id=body.gesture_id, is_new_for_this_lesson=body.is_new_for_this_lesson)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "ok": True}


@router.delete("/lessons/{lesson_id}/pool/{pool_id}")
def remove_from_pool(
    lesson_id: int,
    pool_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    item = db.query(LessonGesturesPool).filter_by(id=pool_id, lesson_id=lesson_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Pool item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ---------------- LESSON CONTENT (Theory) ----------------

@router.get("/lessons/{lesson_id}/content")
def get_lesson_content(
    lesson_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = (
        db.query(LessonContent)
        .filter(LessonContent.lesson_id == lesson_id)
        .order_by(LessonContent.order_index, LessonContent.language_code)
        .all()
    )
    return [
        {
            "id": c.id,
            "language_code": c.language_code,
            "title": c.title or "",
            "body_text": c.body_text or "",
            "image_url": c.image_url or "",
            "order_index": c.order_index,
        }
        for c in items
    ]


@router.post("/lessons/{lesson_id}/content")
def create_content(
    lesson_id: int,
    body: AdminContentCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not db.get(Lesson, lesson_id):
        raise HTTPException(status_code=404, detail="Lesson not found")
    item = LessonContent(
        lesson_id=lesson_id,
        language_code=body.language_code,
        title=body.title,
        body_text=body.body_text,
        image_url=body.image_url,
        order_index=body.order_index,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "ok": True}


@router.patch("/lessons/{lesson_id}/content/{content_id}")
def update_content(
    lesson_id: int,
    content_id: int,
    body: AdminContentUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    item = db.query(LessonContent).filter_by(id=content_id, lesson_id=lesson_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    if body.title is not None:
        item.title = body.title  # type: ignore
    if body.body_text is not None:
        item.body_text = body.body_text  # type: ignore
    if body.image_url is not None:
        item.image_url = body.image_url  # type: ignore
    if body.order_index is not None:
        item.order_index = body.order_index  # type: ignore
    db.commit()
    return {"ok": True}


@router.delete("/lessons/{lesson_id}/content/{content_id}")
def delete_content(
    lesson_id: int,
    content_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    item = db.query(LessonContent).filter_by(id=content_id, lesson_id=lesson_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ---------------- CATEGORIES ----------------

def _category_row(cat: Category):
    uk = next((t for t in cat.translations if t.language_code == "uk"), None)
    en = next((t for t in cat.translations if t.language_code == "en"), None)
    return {
        "id": cat.id,
        "is_active": cat.is_active,
        "created_at": cat.created_at.strftime("%d %b %Y") if cat.created_at else "—", # type: ignore
        "name_uk": uk.name if uk else "",
        "name_en": en.name if en else "",
        "description_uk": uk.description if uk else "",
        "description_en": en.description if en else "",
    }


@router.get("/categories")
def get_categories(
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cats = db.query(Category).order_by(Category.id).all()
    return [_category_row(c) for c in cats]


@router.post("/categories")
def create_category(
    body: AdminCategoryCreate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = Category(is_active=body.is_active)
    db.add(cat)
    db.flush()
    if body.name_uk.strip():
        db.add(CategoryI18n(category_id=cat.id, language_code="uk", name=body.name_uk.strip(), description=body.description_uk))
    if body.name_en.strip():
        db.add(CategoryI18n(category_id=cat.id, language_code="en", name=body.name_en.strip(), description=body.description_en))
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "ok": True}


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int,
    body: AdminCategoryUpdate,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if body.is_active is not None:
        cat.is_active = body.is_active  # type: ignore
    for lang, name, desc in [("uk", body.name_uk, body.description_uk), ("en", body.name_en, body.description_en)]:
        if name is not None:
            i18n = db.query(CategoryI18n).filter_by(category_id=category_id, language_code=lang).first()
            if i18n:
                i18n.name = name  # type: ignore
                if desc is not None:
                    i18n.description = desc  # type: ignore
            else:
                db.add(CategoryI18n(category_id=category_id, language_code=lang, name=name, description=desc))
    db.commit()
    return {"ok": True}


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.query(GestureCategory).filter(GestureCategory.category_id == category_id).delete()
    db.delete(cat)
    db.commit()
    return {"ok": True}


# ---------------- GESTURE CATEGORIES ----------------

@router.get("/gestures/{gesture_id}/categories")
def get_gesture_categories(
    gesture_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(GestureCategory, Category, CategoryI18n)
        .join(Category, GestureCategory.category_id == Category.id)
        .outerjoin(CategoryI18n, (CategoryI18n.category_id == Category.id) & (CategoryI18n.language_code == "uk"))
        .filter(GestureCategory.gesture_id == gesture_id)
        .order_by(GestureCategory.id)
        .all()
    )
    return [{"id": gc.id, "category_id": cat.id, "name": i18n.name if i18n else str(cat.id)} for gc, cat, i18n in rows]


@router.post("/gestures/{gesture_id}/categories")
def add_gesture_category(
    gesture_id: int,
    body: dict,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    category_id = body.get("category_id")
    if not category_id:
        raise HTTPException(status_code=400, detail="category_id is required")
    if not db.get(Gesture, gesture_id):
        raise HTTPException(status_code=404, detail="Gesture not found")
    if not db.get(Category, category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    existing = db.query(GestureCategory).filter_by(gesture_id=gesture_id, category_id=category_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already assigned")
    gc = GestureCategory(gesture_id=gesture_id, category_id=category_id)
    db.add(gc)
    db.commit()
    db.refresh(gc)
    return {"id": gc.id, "category_id": category_id}


@router.delete("/gestures/{gesture_id}/categories/{gc_id}")
def remove_gesture_category(
    gesture_id: int,
    gc_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    gc = db.query(GestureCategory).filter_by(id=gc_id, gesture_id=gesture_id).first()
    if not gc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(gc)
    db.commit()
    return {"ok": True}
