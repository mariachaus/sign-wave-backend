import os
import csv
import json
import base64
import random
import threading
from datetime import datetime
from typing import Any

import numpy as np
import keras
import time
import psutil

from fastapi import APIRouter, HTTPException, Body, WebSocket, WebSocketDisconnect

def get_process_memory_mb():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)




router = APIRouter(prefix="/ml", tags=["ML"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS_DIR = os.path.join(BASE_DIR, "models")


# ---------------- INFERENCE AND MEMORY LOGGING ----------------
_INFERENCE_LOG = os.path.join(BASE_DIR, "logs", "inference_log.csv")

_CSV_HEADER = ["timestamp", "endpoint", "label", "confidence", "inference_ms", "ram_mb", "model"]

def _log_inference(endpoint: str, label: str, confidence: float, inference_ms: float) -> None:
    try:
        write_header = not os.path.exists(_INFERENCE_LOG)
        with open(_INFERENCE_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(_CSV_HEADER)
            w.writerow([
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                endpoint, label,
                round(confidence, 4),
                inference_ms,
                round(get_process_memory_mb(), 1),  # поточний RAM
                os.path.basename(model_path),
            ])
    except Exception:
        pass


_MODEL_LOG = os.path.join(BASE_DIR, "logs", "model_load_log.csv")

def _log_model_load(model_name, ram_before, ram_after):
    try:
        write_header = not os.path.exists(_MODEL_LOG)
        with open(_MODEL_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["timestamp", "model", "ram_before_mb", "ram_after_mb", "model_ram_mb"])
            w.writerow([
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                model_name,
                round(ram_before, 1),
                round(ram_after, 1),
                round(ram_after - ram_before, 1),
            ])
    except Exception:
        pass

# ---------------- LOAD MODEL ----------------



_ACTIVE_MODEL_FILE = os.path.join(BASE_DIR, "logs", "active_model.txt")

# Визначаємо який файл моделі завантажувати
_default_model = "sign_language_transformer_model-20.keras"
if os.path.exists(_ACTIVE_MODEL_FILE):
    with open(_ACTIVE_MODEL_FILE, "r") as f:
        _saved = f.read().strip()
    _chosen = _saved if (_saved and os.path.exists(os.path.join(MODELS_DIR, _saved))) else _default_model
else:
    _chosen = _default_model

model_path = os.path.join(MODELS_DIR, _chosen)

model: Any = None

print("BASE_DIR:", BASE_DIR)
print("MODEL_PATH:", model_path)

if os.path.exists(model_path):
    try:
        mem_before = get_process_memory_mb()

        model = keras.models.load_model(
            model_path,
            compile=False
        )
        

        mem_after = get_process_memory_mb()
        model_ram_used = mem_after - mem_before
        
        print("✅ ML: Model loaded successfully!")
        print(f"📊 RAM before: {mem_before:.2f} MB")
        print(f"📊 RAM after:  {mem_after:.2f} MB")
        print(f"🔥 Model RAM:  {model_ram_used:.2f} MB")

        #_log_model_load(os.path.basename(model_path), mem_before, mem_after)   # type: ignore
    except Exception as e:
        print(f"❌ ML: Model loading error: {e}")
else:
    print(f"❌ ML: Model file not found: {model_path}")


# ---------------- LOAD LABELS ----------------

LABELS = []

import re as _re
_m = _re.match(r"sign_language_(.+)_model-(\d+)\.keras", _chosen)
if _m:
    _lf = f"gesture_classes_{_m.group(1)}-{_m.group(2)}.json"
    labels_path = os.path.join(MODELS_DIR, _lf)
    if not os.path.exists(labels_path):
        labels_path = os.path.join(MODELS_DIR, "gesture_classes_transformer-20.json")
else:
    labels_path = os.path.join(MODELS_DIR, "gesture_classes_transformer-20.json")


if os.path.exists(labels_path):
    with open(labels_path, "r", encoding="utf-8") as f:
        LABELS = json.load(f)
    print(f"✅ ML: Labels loaded: {LABELS}")
else:
    LABELS = ["not-found"]
    print("⚠️ ML: Labels not found, using defaults.")



# ---------------- MODEL RELOAD LOCK ----------------

_reload_lock = threading.Lock()   
_model_loading = False            


# ---------------- PREDICT ----------------

@router.post("/predict")
def predict(data: dict = Body(...)):
    if _model_loading:
        raise HTTPException(status_code=503, detail="Model is reloading, please retry")
    if model is None:
        raise HTTPException(status_code=500, detail="Model is not loaded")

    try:
        features_list = data.get("features")

        if not features_list:
            raise HTTPException(
                status_code=400,
                detail="No features provided"
            )

        # Усередині функції predict
        input_data = np.array(features_list, dtype=np.float32)
        if input_data.shape != (20, 450):
            try:
                input_data = input_data.reshape(1, 20, 450)
            except:
                raise HTTPException(status_code=400, detail=f"Wrong shape: {input_data.shape}")
        else:
            input_data = np.expand_dims(input_data, axis=0)

        start_time = time.time()
        prediction = model(input_data, training=False).numpy()
        inference_ms = round((time.time() - start_time) * 1000, 2)
        print(f"[predict] inference: {inference_ms} ms")

        class_id = int(np.argmax(prediction))
        confidence = float(prediction[0][class_id])
        label_name = LABELS[class_id]
        #_log_inference("predict", label_name, confidence, inference_ms)
        all_scores = {LABELS[i]: round(float(prediction[0][i]), 4) for i in range(len(LABELS))}

        return {
            "label": label_name,
            "confidence": confidence,
            "all_scores": all_scores,
            "inference_ms": inference_ms,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ---------------- PREDICT BATCH ----------------

@router.post("/predict_batch")
def predict_batch(data: dict = Body(...)):
    """Приймає список вікон [[20×450], ...], повертає передбачення для кожного."""
    if model is None:
        raise HTTPException(status_code=500, detail="Model is not loaded")

    windows = data.get("windows")
    if not windows:
        raise HTTPException(status_code=400, detail="No windows provided")

    try:
        arr = np.array(windows, dtype=np.float32)   # (N, 20, 450)
        if arr.ndim != 3 or arr.shape[1:] != (20, 450):
            raise HTTPException(status_code=400, detail=f"Wrong shape: {arr.shape}, expected (N,20,450)")

        preds = model(arr, training=False).numpy()   # (N, num_classes)

        results = []
        for row in preds:
            class_id = int(np.argmax(row))
            results.append({
                "label":      LABELS[class_id],
                "confidence": round(float(row[class_id]), 4),
                "all_scores": {LABELS[i]: round(float(row[i]), 4) for i in range(len(LABELS))},
            })
        return {"predictions": results}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------- MEDIAPIPE PYTHON (для мобільного WebSocket) ----------------

_pose_lm: Any = None
_hand_lm: Any = None
_mp_ready = False


def _init_mp_landmarkers() -> bool:
    global _pose_lm, _hand_lm, _mp_ready
    if _mp_ready:
        return True
    try:
        import cv2  # type: ignore[import-untyped]  # noqa: F401
        import mediapipe as mp  # type: ignore[import-untyped]
        from mediapipe.tasks import python as mpp  # type: ignore[import-untyped]
        from mediapipe.tasks.python import vision as mpv  # type: ignore[import-untyped]

        mp_dir = os.path.join(MODELS_DIR, "mediapipe")
        pose_path = os.path.join(mp_dir, "pose_landmarker_lite.task")
        hand_path = os.path.join(mp_dir, "hand_landmarker.task")

        if not os.path.exists(pose_path) or not os.path.exists(hand_path):
            print(f"❌ ML/WS: .task files not found in {mp_dir}")
            print("   Download from: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker")
            return False

        _pose_lm = mpv.PoseLandmarker.create_from_options(
            mpv.PoseLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=pose_path),
                running_mode=mpv.RunningMode.IMAGE,
                num_poses=1,
            )
        )
        _hand_lm = mpv.HandLandmarker.create_from_options(
            mpv.HandLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=hand_path),
                running_mode=mpv.RunningMode.IMAGE,
                num_hands=2,
            )
        )
        _mp_ready = True
        print("✅ ML/WS: MediaPipe Python landmarkers ready!")
        return True
    except ImportError as e:
        print(f"❌ ML/WS: mediapipe/opencv not installed: {e}")
        return False
    except Exception as e:
        print(f"❌ ML/WS: init error: {e}")
        return False


def _extract_features_py(pose_result, hand_result) -> list:
    """Python mirror of feature_extractor.js — нормалізація відносно носа."""
    frame = [0.0] * 225
    nose_x = nose_y = 0.0

    if pose_result.pose_landmarks:
        nose_x = pose_result.pose_landmarks[0][0].x
        nose_y = pose_result.pose_landmarks[0][0].y
        for i, lm in enumerate(pose_result.pose_landmarks[0][:33]):
            frame[i * 3]     = lm.x - nose_x
            frame[i * 3 + 1] = lm.y - nose_y
            frame[i * 3 + 2] = lm.z

    if hand_result.hand_landmarks and hand_result.handedness:
        for idx, hand_lms in enumerate(hand_result.hand_landmarks):
            label = hand_result.handedness[idx][0].category_name
            offset = 99 if label == "Left" else 162
            for i, lm in enumerate(hand_lms[:21]):
                base = offset + i * 3
                frame[base]     = lm.x - nose_x
                frame[base + 1] = lm.y - nose_y
                frame[base + 2] = lm.z

    return frame


def _add_delta(buf: list) -> np.ndarray:
    """Python mirror of computeDeltaFeatures — дельта між кадрами."""
    arr = np.array(buf, dtype=np.float32)   # (20, 225)
    deltas = np.zeros_like(arr)
    deltas[1:] = arr[1:] - arr[:-1]
    return np.concatenate([arr, deltas], axis=1)  # (20, 450)


def _landmarks_for_drawing(pose_result, hand_result) -> dict:
    """Повертає оригінальні (ненормалізовані) координати для малювання скелету на мобайлі."""
    result: dict = {"pose": [], "left_hand": [], "right_hand": []}
    if pose_result.pose_landmarks:
        result["pose"] = [
            {"x": round(lm.x, 4), "y": round(lm.y, 4)}
            for lm in pose_result.pose_landmarks[0]
        ]
    if hand_result.hand_landmarks and hand_result.handedness:
        for idx, hand_lms in enumerate(hand_result.hand_landmarks):
            label = hand_result.handedness[idx][0].category_name
            key = "left_hand" if label == "Left" else "right_hand"
            result[key] = [
                {"x": round(lm.x, 4), "y": round(lm.y, 4)}
                for lm in hand_lms
            ]
    return result


# _init_mp_landmarkers()


def _process_frame(img_bytes: bytes):
    """CPU-bound MediaPipe processing — виконується в thread pool."""
    import cv2  # type: ignore[import-untyped]
    import mediapipe as mp  # type: ignore[import-untyped]

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return None, None, None
    img_bgr = cv2.resize(img_bgr, (320, 240))
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
    pose_res = _pose_lm.detect(mp_img)
    hand_res = _hand_lm.detect(mp_img)
    lm = _landmarks_for_drawing(pose_res, hand_res)
    return pose_res, hand_res, lm


@router.websocket("/ws/predict")
async def predict_ws(websocket: WebSocket):
    """WebSocket для веб-клієнта: приймає координати (20×450), повертає передбачення."""
    await websocket.accept()
    if model is None:
        await websocket.send_text(json.dumps({"error": "Model not loaded"}))
        await websocket.close()
        return
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            features = data.get("features")
            if not features:
                await websocket.send_text(json.dumps({"error": "no features"}))
                continue
            if _model_loading:
                await websocket.send_text(json.dumps({"error": "model_reloading"}))
                continue
            input_data = np.array(features, dtype=np.float32)
            if input_data.shape != (20, 450):
                input_data = input_data.reshape(1, 20, 450)
            else:
                input_data = np.expand_dims(input_data, axis=0)
            t0 = time.time()
            prediction = model(input_data, training=False).numpy()
            inference_ms = round((time.time() - t0) * 1000, 2)
            print(f"[ws/predict] inference: {inference_ms} ms")
            class_id = int(np.argmax(prediction))
            confidence = float(prediction[0][class_id])
            label = LABELS[class_id]
            #_log_inference("ws/predict", label, confidence, inference_ms)
            all_scores = {LABELS[i]: round(float(prediction[0][i]), 4) for i in range(len(LABELS))}
            await websocket.send_text(json.dumps({
                "label": label,
                "confidence": confidence,
                "all_scores": all_scores,
                "inference_ms": inference_ms,
            }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS/predict] {e}")


@router.websocket("/ws/gesture")
async def gesture_ws(websocket: WebSocket):
    await websocket.accept()

    if not _mp_ready:
        await websocket.send_text(json.dumps({"error": "MediaPipe not available on server"}))
        await websocket.close()
        return

    import asyncio

    frame_buffer: list = []
    pred_history: list = []

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            b64 = data.get("frame", "")
            if not b64:
                continue

            img_bytes = base64.b64decode(b64)

            loop = asyncio.get_event_loop()
            pose_res, hand_res, lm = await loop.run_in_executor(None, _process_frame, img_bytes)

            if pose_res is None:
                continue

            visible = bool(pose_res.pose_landmarks or hand_res.hand_landmarks) # type: ignore

            if not visible:
                frame_buffer.clear()
                pred_history.clear()
                await websocket.send_text(json.dumps({"status": "no_person", "buffer_size": 0}))
                continue

            frame_buffer.append(_extract_features_py(pose_res, hand_res))
            if len(frame_buffer) > 20:
                frame_buffer.pop(0)

            if len(frame_buffer) < 20:
                await websocket.send_text(json.dumps({
                    "status": "collecting",
                    "buffer_size": len(frame_buffer),
                    "lm": lm,
                }))
                continue

            if _model_loading:
                await websocket.send_text(json.dumps({"status": "model_reloading", "buffer_size": 20, "lm": lm}))
                continue

            inp = np.expand_dims(_add_delta(frame_buffer), axis=0)
            t0 = time.time()
            preds = model(inp, training=False).numpy()[0]
            inference_ms = round((time.time() - t0) * 1000, 2)
            print(f"[ws/gesture] inference: {inference_ms} ms")
            cls = int(np.argmax(preds))
            #_log_inference("ws/gesture", LABELS[cls], float(preds[cls]), inference_ms)
            conf = float(preds[cls])
            label = LABELS[cls]

            if conf > 0.6:
                pred_history.append({"label": label, "confidence": conf})
                if len(pred_history) > 5:
                    pred_history.pop(0)
                scores: dict = {}
                for p in pred_history:
                    scores[p["label"]] = scores.get(p["label"], 0) + p["confidence"]
                best = max(scores, key=lambda k: scores[k])
                smoothed = round(scores[best] / len(pred_history), 3)
            else:
                best, smoothed = label, round(conf, 3)

            await websocket.send_text(json.dumps({
                "status": "prediction",
                "label": best,
                "confidence": smoothed,
                "buffer_size": 20,
                "lm": lm,
                "inference_ms": inference_ms,
            }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS/gesture] {e}")