from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.connection import get_db
from db.models import Gesture, Category, GestureCategory, GestureSynonym, GestureI18n, CategoryI18n

router = APIRouter( tags=["Gestures"])

# ---------------- CATEGORIES ----------------

@router.get("/categories")
def get_categories(lang: str = "en", db: Session = Depends(get_db)):
    # З'єднуємо категорію з її перекладом за вказаною мовою
    categories = db.query(Category, CategoryI18n).join(CategoryI18n).filter(
        Category.is_active == True,
        CategoryI18n.language_code == lang
    ).all()

    return [
        {
            "id": c.id,
            "name": t.name,
            "description": t.description
        }
        for c, t in categories
    ]


# ---------------- GESTURES ----------------

@router.get("")
def get_gestures(lang: str = "en", db: Session = Depends(get_db)):
    # Витягуємо жести разом із перекладами одним запитом (Join)
    gestures_query = db.query(Gesture, GestureI18n).join(GestureI18n).filter(
        Gesture.is_active == True,
        GestureI18n.language_code == lang
    ).all()

    output = []

    for g, t in gestures_query:
        # Отримуємо синоніми для конкретної мови
        synonyms = db.query(GestureSynonym).filter(
            GestureSynonym.gesture_id == g.id,
            GestureSynonym.language_code == lang
        ).all()
        
        # Отримуємо назви категорій (теж через i18n таблицю)
        categories = db.query(CategoryI18n.name).join(
            GestureCategory, CategoryI18n.category_id == GestureCategory.category_id
        ).filter(
            GestureCategory.gesture_id == g.id,
            CategoryI18n.language_code == lang
        ).all()

        output.append({
            "id": g.id,
            "name": t.name,
            "video_url": g.video_url,
            "difficulty": float(g.base_difficulty_rate),
            "is_dynamic": g.is_dynamic,
            "synonyms": [s.name for s in synonyms],
            "description": t.description,
            "thumbnail_url": g.thumbnail_url,
            "illustration_url": g.illustration_url or g.thumbnail_url,
            "model_label": g.model_label,
            "categories": [c.name for c in categories]
        })

    return output


# ---------------- DAILY GESTURE ----------------

@router.get("/daily")
def get_daily_gesture(lang: str = "en", db: Session = Depends(get_db)):
    gesture_ids = [row.id for row in db.query(Gesture.id).filter(Gesture.is_active == True).all()]
    if not gesture_ids:
        raise HTTPException(status_code=404, detail="No gestures available")
    daily_id = gesture_ids[date.today().toordinal() % len(gesture_ids)]
    res = db.query(Gesture, GestureI18n).join(GestureI18n).filter(
        Gesture.id == daily_id,
        GestureI18n.language_code == lang
    ).first()
    if not res:
        raise HTTPException(status_code=404, detail="Daily gesture not found")
    gesture, translation = res
    return {
        "id": gesture.id,
        "name": translation.name,
        "description": translation.description,
        "illustration_url": gesture.illustration_url,
        "video_url": gesture.video_url,
    }


# ---------------- GESTURE DETAILS ----------------

@router.get("/{gesture_id}")
def get_gesture_details(gesture_id: int, lang: str = "en", db: Session = Depends(get_db)):
    # 1. Отримуємо жест та його переклад
    res = db.query(Gesture, GestureI18n).join(GestureI18n).filter(
        Gesture.id == gesture_id,
        Gesture.is_active == True,
        GestureI18n.language_code == lang
    ).first()
    
    if not res:
        raise HTTPException(status_code=404, detail="Gesture not found")

    gesture, translation = res

    # 2. Синоніми мовою користувача
    synonyms = db.query(GestureSynonym).filter(
        GestureSynonym.gesture_id == gesture.id,
        GestureSynonym.language_code == lang
    ).all()

    # 3. Схожі жести
    category_mapping = db.query(GestureCategory).filter(GestureCategory.gesture_id == gesture.id).first()
    
    similar_gestures_output = []
    category_name = "General"

    if category_mapping:
        # Назва категорії мовою користувача
        cat_trans = db.query(CategoryI18n).filter(
            CategoryI18n.category_id == category_mapping.category_id,
            CategoryI18n.language_code == lang
        ).first()
        
        if cat_trans:
            category_name = cat_trans.name
            
        # Схожі жести (теж з перекладами назв)
        similar_items = db.query(Gesture, GestureI18n).join(GestureI18n).join(
            GestureCategory, Gesture.id == GestureCategory.gesture_id
        ).filter(
            GestureCategory.category_id == category_mapping.category_id,
            Gesture.is_active == True,
            GestureI18n.language_code == lang,
        ).limit(6).all()

        similar_gestures_output = [
            {"id": sg.id, "name": st.name, "thumbnail_url": sg.thumbnail_url} 
            for sg, st in similar_items
        ]

    return {
        "id": gesture.id,
        "name": translation.name,
        "description": translation.description,
        "video_url": gesture.video_url,
        "illustration_url": gesture.illustration_url,
        "synonyms": [s.name for s in synonyms],
        "category_name": category_name,
        "similar_gestures": similar_gestures_output,
        "is_active": gesture.is_active
    }