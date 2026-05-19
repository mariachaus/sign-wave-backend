from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Numeric, Date, UniqueConstraint, JSON, func
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, date

Base = declarative_base()

# --- СЕКЦІЯ КОРИСТУВАЧІВ ---

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String)
    google_id = Column(String, unique=True)
    avatar_url = Column(String)
    total_xp = Column(Integer, default=0)
    total_practices = Column(Integer, default=0)
    role = Column(String(20), default='user', nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    settings = relationship("UserSetting", back_populates="user", uselist=False, cascade="all, delete-orphan")
    streaks = relationship("UserStreak", back_populates="user", cascade="all, delete-orphan")
    achievements = relationship("UserAchievement", back_populates="user", cascade="all, delete-orphan")

    @property
    def streak(self):
        return next((s for s in self.streaks if s.is_current), None)
    xp_logs = relationship("UserXPLog", back_populates="user", cascade="all, delete-orphan")
    gesture_stats = relationship("UserGestureStat", back_populates="user", cascade="all, delete-orphan")
    error_logs = relationship("UserErrorLog", back_populates="user", cascade="all, delete-orphan")
    daily_tasks = relationship("UserDailyTask", back_populates="user", cascade="all, delete-orphan")
    lessons = relationship("UserLesson", back_populates="user", cascade="all, delete-orphan")


class UserSetting(Base):
    __tablename__ = "user_settings"
    
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    theme = Column(String, default='system')
    font_size_multiplier = Column(Numeric(3,2), default=1.0)
    is_mirror_view_enabled = Column(Boolean, default=True)
    is_landmarks_visible = Column(Boolean, default=True)
    landmark_color = Column(String, default='#00FF00')
    connection_color = Column(String, default='#FF0000')
    camera_fps_limit = Column(Integer, default=30)
    language = Column(String(5), default='en', nullable=False)
    is_email_notifications_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="settings")


class UserStreak(Base):
    __tablename__ = "user_streaks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    started_at = Column(Date)
    streak_length = Column(Integer, default=0)
    ended_at = Column(Date, nullable=True)
    is_current = Column(Boolean, default=False)
    last_activity_at = Column(DateTime)
    freeze_shields_count = Column(Integer, default=0)

    user = relationship("User", back_populates="streaks")

    @property
    def current_streak(self):
        """Backward-compat alias."""
        return self.streak_length


# --- СЕКЦІЯ НАВЧАЛЬНОГО КОНТЕНТУ ---

# Рівень (наприклад, "Початківець", "Середній")
class Level(Base):
    __tablename__ = "levels"
    id = Column(Integer, primary_key=True)
    is_active = Column(Boolean, default=True)
    # Зв'язок з перекладами назв (як ми робили для жестів)
    translations = relationship("LevelI18n", backref="level")
    lessons = relationship("Lesson", backref="level")

class LevelI18n(Base):
    __tablename__ = "levels_i18n"

    id = Column(Integer, primary_key=True)
    level_id = Column(Integer, ForeignKey('levels.id', ondelete="CASCADE"), nullable=False)
    language_code = Column(String(5), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    __table_args__ = (UniqueConstraint('level_id', 'language_code'),)

# Урок (наприклад, "Вітання частина 1")
class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True)
    level_id = Column(Integer, ForeignKey('levels.id'))
    order_index = Column(Integer)
    
    is_active = Column(Boolean, default=True)
    
    translations = relationship("LessonI18n", backref="lesson")
    


class LessonI18n(Base):
    __tablename__ = "lessons_i18n"

    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete="CASCADE"), nullable=False)
    language_code = Column(String(5), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    __table_args__ = (UniqueConstraint('lesson_id', 'language_code'),)


class LessonContent(Base):
    __tablename__ = "lesson_contents"

    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete="CASCADE"))
    language_code = Column(String(10), nullable=False)
    title = Column(String(255))
    body_text = Column(Text)
    image_url = Column(String(255))
    order_index = Column(Integer, default=1)

# --- КАТЕГОРІЇ ---
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Зв'язок з перекладами
    translations = relationship("CategoryI18n", backref="category", cascade="all, delete-orphan")

class CategoryI18n(Base):
    __tablename__ = "categories_i18n"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id', ondelete="CASCADE"), nullable=False)
    language_code = Column(String(5), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    __table_args__ = (UniqueConstraint('category_id', 'language_code'),) # type: ignore


# --- ЖЕСТИ ---
class Gesture(Base):
    __tablename__ = "gestures"
    id = Column(Integer, primary_key=True)
    video_url = Column(String, nullable=False)
    model_label = Column(String, nullable=False)
    base_difficulty_rate = Column(Numeric(4,2), default=1.0)
    is_dynamic = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    thumbnail_url = Column(String(255))
    illustration_url = Column(String(255))

    translations = relationship("GestureI18n", backref="gesture", cascade="all, delete-orphan")

class GestureI18n(Base):
    __tablename__ = "gestures_i18n"
    id = Column(Integer, primary_key=True)
    gesture_id = Column(Integer, ForeignKey('gestures.id', ondelete="CASCADE"), nullable=False)
    language_code = Column(String(5), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    __table_args__ = (UniqueConstraint('gesture_id', 'language_code'),)


class GestureSynonym(Base):
    __tablename__ = "gesture_synonyms"
    id = Column(Integer, primary_key=True)
    gesture_id = Column(Integer, ForeignKey('gestures.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    language_code = Column(String(5), default='uk')


class GestureCategory(Base):
    __tablename__ = "gesture_categories"

    id = Column(Integer, primary_key=True)
    gesture_id = Column(Integer, ForeignKey('gestures.id', ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)



# --- СЕКЦІЯ ВПРАВ ---

class ExerciseType(Base):
    __tablename__ = "exercise_types"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    technical_component_name = Column(String, nullable=False)
    base_xp = Column(Integer, default=10)




class LessonGesturesPool(Base):
    __tablename__ = "lesson_gestures_pool"
    
    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('lessons.id'), nullable=False)
    gesture_id = Column(Integer, ForeignKey('gestures.id', ondelete="CASCADE"), nullable=False)
    is_new_for_this_lesson = Column(Boolean, default=True)


# --- СЕКЦІЯ ПРОГРЕСУ ---

# Прогрес користувача (що пройдено)

class UserGestureStat(Base):
    __tablename__ = "user_gesture_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    gesture_id = Column(Integer, ForeignKey('gestures.id', ondelete="CASCADE"), nullable=False)
    correct_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    mastery_level = Column(Numeric, default=0)
    next_review_at = Column(DateTime)

    user = relationship("User", back_populates="gesture_stats")


class UserErrorLog(Base):
    __tablename__ = "user_error_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    lesson_id = Column(Integer, ForeignKey("lessons.id")) # Додали це
    gesture_id = Column(Integer, ForeignKey("gestures.id", ondelete="SET NULL"))
    exercise_type_id = Column(Integer, ForeignKey("exercise_types.id")) # Оновили назву
    
    error_type = Column(String(50))
    timestamp = Column(DateTime, default=func.now())
    
    user = relationship("User", back_populates="error_logs")

# --- ГЕЙМІФІКАЦІЯ ---

class Achievement(Base):
    __tablename__ = "achievements"
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    icon_url = Column(String)
    points_awarded = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    achievement_id = Column(Integer, ForeignKey('achievements.id'), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="achievements")


class UserXPLog(Base):
    __tablename__ = "user_xp_log"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Integer, nullable=False)
    source_type = Column(String)
    source_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="xp_logs")


class DailyTaskTemplate(Base):
    __tablename__ = "daily_task_templates"
    
    id = Column(Integer, primary_key=True)
    description = Column(String)
    task_type = Column(String)
    target_value = Column(Integer)
    xp_reward = Column(Integer)
    is_active = Column(Boolean, default=True)


class UserDailyTask(Base):
    __tablename__ = "user_daily_tasks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    task_template_id = Column(Integer, ForeignKey('daily_task_templates.id'), nullable=False)
    target_id = Column(Integer, nullable=True)
    current_value = Column(Integer, default=0)
    is_completed = Column(Boolean, default=False)
    assigned_at = Column(Date, default=date.today)

    user = relationship("User", back_populates="daily_tasks")


class UserLesson(Base):
    __tablename__ = "user_lessons"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"))
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete="CASCADE"))
    status = Column(String(20), default='started')
    is_completed = Column(Boolean, default=False)
    best_score = Column(Integer, default=0)
    total_attempts = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_attempt_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="lessons")

    __table_args__ = (UniqueConstraint('user_id', 'lesson_id'),)