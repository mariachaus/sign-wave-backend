from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# --- AUTH ---

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)

class LoginRequest(BaseModel):
    username: str
    password: str

class GoogleLoginRequest(BaseModel):
    access_token: str


# --- USER BASE ---

class UserBase(BaseModel):
    username: str
    email: EmailStr


# --- CREATE (запит від клієнта) ---

class UserCreate(UserBase):
    password: str


# --- RESPONSE (що повертаємо клієнту) ---

class UserResponse(UserBase):
    id: int
    avatar_url: Optional[str]
    total_xp: int
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# --- LOGIN ---

class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GestureResponse(BaseModel):
    id: int
    name: str
    video_url: str
    difficulty: float
    is_dynamic: bool
    synonyms: list[str]


class UserProfileResponse(BaseModel):
    username: str
    total_xp: int
    avatar_url: str | None



class UserStats(BaseModel):
    total_xp: int
    lessons_completed: int
    current_streak: int
    top_gestures: list[str] # Назви жестів, які юзер знає найкраще

# --- STEP GESTURE (shared shape for all exercise types) ---

class StepGesture(BaseModel):
    id: Optional[int] = None
    name: str
    illustration_url: Optional[str] = None
    description: Optional[str] = None
    model_label: Optional[str] = None


# --- LESSON STEP ---

class LessonStep(BaseModel):
    type: str                                    # theory | imitation | quiz | matching | recall
    gesture: Optional[StepGesture] = None        # theory, imitation, recall
    content: Optional[str] = None               # theory body text
    mode: Optional[str] = None                  # quiz: word_to_image | image_to_word
    target: Optional[StepGesture] = None        # quiz target
    options: Optional[List[StepGesture]] = None # quiz distractor pool
    gestures: Optional[List[StepGesture]] = None # matching pairs


# --- START LESSON RESPONSE ---

class LessonStartResponse(BaseModel):
    lesson_id: int
    lesson_name: str
    steps: List[LessonStep]


    # --- ERROR LOG (Помилка під час вправи) ---

class ErrorLogCreate(BaseModel):
    gesture_id: int
    exercise_type_id: int
    error_type: str  # 'wrong_sign', 'hand_not_visible', тощо


class ErrorDetail(BaseModel):
    gesture_id: int
    exercise_type_id: Optional[int] = None
    error_type: str = 'wrong_answer'


# --- COMPLETE LESSON REQUEST ---

class LessonCompleteRequest(BaseModel):
    score: int
    errors: list[ErrorDetail] = []
    hearts_remaining: int = 0


# --- ADMIN ---

class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class AdminTemplateCreate(BaseModel):
    task_type: str
    target_value: int = 1
    xp_reward: int = 10
    is_active: bool = True


class AdminTemplateUpdate(BaseModel):
    task_type: Optional[str] = None
    target_value: Optional[int] = None
    xp_reward: Optional[int] = None
    is_active: Optional[bool] = None


class AdminGestureCreate(BaseModel):
    model_label: str
    video_url: str
    name_uk: str
    name_en: str = ''
    description_uk: Optional[str] = None
    description_en: Optional[str] = None
    is_dynamic: bool = False
    is_active: bool = True
    illustration_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


class AdminGestureUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_dynamic: Optional[bool] = None
    video_url: Optional[str] = None
    illustration_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    name_uk: Optional[str] = None
    name_en: Optional[str] = None
    description_uk: Optional[str] = None
    description_en: Optional[str] = None


class AdminLessonCreate(BaseModel):
    level_id: Optional[int] = None
    order_index: int = 0
    is_active: bool = True
    name_uk: str
    name_en: str = ''
    description_uk: Optional[str] = None
    description_en: Optional[str] = None


class AdminLessonUpdate(BaseModel):
    level_id: Optional[int] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None
    name_uk: Optional[str] = None
    name_en: Optional[str] = None
    description_uk: Optional[str] = None
    description_en: Optional[str] = None


class AdminPoolAdd(BaseModel):
    gesture_id: int
    is_new_for_this_lesson: bool = True


class AdminContentCreate(BaseModel):
    language_code: str = 'uk'
    title: Optional[str] = None
    body_text: Optional[str] = None
    image_url: Optional[str] = None
    order_index: int = 1


class AdminContentUpdate(BaseModel):
    title: Optional[str] = None
    body_text: Optional[str] = None
    image_url: Optional[str] = None
    order_index: Optional[int] = None


class AdminLevelCreate(BaseModel):
    is_active: bool = True
    name_uk: str
    name_en: str = ''
    description_uk: Optional[str] = None
    description_en: Optional[str] = None


class AdminLevelUpdate(BaseModel):
    is_active: Optional[bool] = None
    name_uk: Optional[str] = None
    name_en: Optional[str] = None
    description_uk: Optional[str] = None
    description_en: Optional[str] = None