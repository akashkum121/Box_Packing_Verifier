import easyocr
import cv2
import re
import json
import numpy as np

# Initialize EasyOCR reader once globally
reader = easyocr.Reader(['en'], gpu=False)

# ─────────────────────────────────────────────────────────────
#  OCR POST-PROCESSING — cleans common EasyOCR noise
# ─────────────────────────────────────────────────────────────
def clean_ocr(text: str, is_code: bool = False) -> str:
    if not text:
        return text
    text = text.strip()
    text = re.sub(r'[{}|\\`~@#\[\]]', '', text)
    text = re.sub(r'(?<=[A-Z0-9])\?(?=[A-Z0-9])', '', text)
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    text = text.strip('.,;:-_')
    if is_code:
        text = re.sub(r'(?<=\d)O(?=\d)', '0', text)
        text = re.sub(r'(?<=\d)o(?=\d)', '0', text)
        text = re.sub(r'(?<=\d)[lI](?=\d)', '1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def preprocess_image(image_path: str):
    """Load and preprocess image for EasyOCR — scale to 1600px + CLAHE."""
    img = cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) < 1600:
        scale = 1600.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    elif max(h, w) > 2400:
        scale = 2400.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return img


def extract_secondary(image_path: str):
    """
    Reads a secondary box label using EasyOCR with mag_ratio=2.
    Extracts MODEL (priority: MODEL NAME > MODEL > PART NAME > ITEM) and QUANTITY.
    """
    img = preprocess_image(image_path)
    if img is None:
        return "", "", json.dumps({"status": "error", "message": "Image not found"})

    results = reader.readtext(img, mag_ratio=2, adjust_contrast=0.5)

    blocks = []
    for bbox, text, prob in results:
        clean_text = text.strip()
        if not clean_text:
            continue
        x0 = int(bbox[0][0])
        y0 = int(bbox[0][1])
        x1 = int(bbox[2][0])
        y1 = int(bbox[2][1])
        blocks.append({
            "text": clean_text,
            "upper": clean_text.upper(),
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "cx": (x0 + x1) / 2.0,
            "cy": (y0 + y1) / 2.0,
            "h": y1 - y0,
            "confidence": round(float(prob), 4)
        })

    model = ""
    qty = ""

    def find_value_to_right(key_block):
        candidates = []
        for b in blocks:
            if b["cx"] > key_block["x1"]:
                if abs(b["cy"] - key_block["cy"]) < key_block["h"] * 1.2:
                    candidates.append(b)
        if candidates:
            candidates.sort(key=lambda x: x["x0"])
            return candidates[0]["text"]
        return ""

    def find_next_block(key_block):
        try:
            idx = blocks.index(key_block)
            if idx + 1 < len(blocks):
                return blocks[idx + 1]["text"]
        except ValueError:
            pass
        return ""

    def clean_prefix(text, keyword):
        pat = re.compile(
            rf'\b{keyword}\b\s*(NAME|NO|NO\.|NUMBER)?\s*[:\-]*\s*',
            re.IGNORECASE
        )
        cleaned = pat.sub('', text).strip()
        return re.sub(r'^[:\-\s]+', '', cleaned).strip()

    found_model_block = None
    model_keywords = ["MODEL NAME", "MODEL", "PART NAME", "ITEM"]
    for kw in model_keywords:
        for b in blocks:
            if kw in b["upper"]:
                val = clean_prefix(b["text"], kw)
                if val:
                    model = val
                    found_model_block = b
                    break
                r_val = find_value_to_right(b)
                if r_val:
                    model = r_val
                    found_model_block = b
                    break
                n_val = find_next_block(b)
                if n_val:
                    model = n_val
                    found_model_block = b
                    break
        if model:
            break

    qty_keywords = ["QUANTITY", "QTY.", "QTY"]
    for kw in qty_keywords:
        for b in blocks:
            if found_model_block and b == found_model_block:
                continue
            if kw in b["upper"]:
                val = clean_prefix(b["text"], kw)
                nums = re.findall(r'\d+', val)
                if nums:
                    qty = nums[0]; break
                r_val = find_value_to_right(b)
                nums = re.findall(r'\d+', r_val)
                if nums:
                    qty = nums[0]; break
                n_val = find_next_block(b)
                nums = re.findall(r'\d+', n_val)
                if nums:
                    qty = nums[0]; break
        if qty:
            break

    if not model and blocks:
        model = blocks[0]["text"]

    model = clean_ocr(model, is_code=False)
    qty   = clean_ocr(qty,   is_code=False)

    extracted_json = json.dumps({
        "status": "success",
        "ocr_data": [{"text": b["text"], "confidence": b["confidence"]} for b in blocks],
        "extracted": {"model": model, "qty": qty}
    }, indent=2)

    return model, qty, extracted_json