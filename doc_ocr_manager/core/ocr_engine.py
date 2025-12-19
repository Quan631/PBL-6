# core/ocr_engine.py
from __future__ import annotations
from typing import Tuple
import numpy as np
from PIL import Image, ImageEnhance
import cv2


def preprocess_image_pil(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.2)
    img = ImageEnhance.Sharpness(img).enhance(1.1)
    return img


def pil_to_cv(img: Image.Image) -> np.ndarray:
    arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def preprocess_image_cv(img_bgr: np.ndarray) -> np.ndarray:
    # grayscale + adaptive threshold
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    th = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        31, 7
    )
    return th


def run_easyocr(reader, image_path: str, enhance: bool = True) -> Tuple[str, float]:
    """
    Returns: (text, avg_confidence)
    """
    # EasyOCR
    if not enhance:
        results = reader.readtext(image_path, detail=1)
        if not results:
            return "", 0.0
        text = "\n".join([r[1] for r in results]).strip()
        conf = float(sum([r[2] for r in results]) / max(len(results), 1))
        return text, conf

    # preprocess
    img = Image.open(image_path)
    img = preprocess_image_pil(img)
    cv_img = pil_to_cv(img)
    cv_img = preprocess_image_cv(cv_img)

    results = reader.readtext(cv_img, detail=1)
    if not results:
        return "", 0.0
    text = "\n".join([r[1] for r in results]).strip()
    conf = float(sum([r[2] for r in results]) / max(len(results), 1))
    return text, conf
