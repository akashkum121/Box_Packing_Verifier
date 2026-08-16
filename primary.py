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
    """Cleans common EasyOCR mistakes — stray symbols, decimal comma, O/0 in codes."""
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
    """
    Load and preprocess image for EasyOCR.
    - Scale to at least 1600px for better character resolution
    - CLAHE contrast enhancement (no binary threshold — EasyOCR prefers natural images)
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    h, w = img.shape[:2]
    # Ensure image is large enough — thin label fonts need high resolution
    if max(h, w) < 1600:
        scale = 1600.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    elif max(h, w) > 2400:
        scale = 2400.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)

    # CLAHE contrast enhancement — local contrast boost without binary conversion
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return img


def extract_primary(image_path: str):
    """
    Reads a primary box label using EasyOCR with mag_ratio=2 for better thin-font accuracy.
    Extracts MODEL/PART NUMBER using strict priority chain:
      Priority 1: MODEL NAME / MODEL keyword
      Priority 2: Part Number / Part No keyword
      Priority 3: Part Name keyword
    PRODUCT value is never used as the model (it's a generic category).
    """
    img = preprocess_image(image_path)
    if img is None:
        return "", "", json.dumps({"status": "error", "message": "Image not found"})

    # mag_ratio=2 internally doubles resolution inside EasyOCR's recognition network
    # This significantly improves accuracy for thin/small fonts like PISTON-KWPG
    results = reader.readtext(img, mag_ratio=2, adjust_contrast=0.5)

    # ── Build block list ──
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
            "conf": round(float(prob), 4)
        })

    # ── Helpers ──
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

    def value_from_keyword(keyword_pattern):
        for b in blocks:
            if keyword_pattern in b["upper"]:
                remainder = re.sub(
                    r'^.*?' + re.escape(keyword_pattern) + r'\s*[:\-]?\s*',
                    '', b["upper"]
                ).strip()
                remainder = re.sub(r'^[:\-\s]+', '', remainder).strip()
                if remainder and len(remainder) > 1:
                    start = b["text"].upper().find(keyword_pattern)
                    orig = b["text"][start + len(keyword_pattern):].strip()
                    orig = re.sub(r'^[:\-\s]+', '', orig).strip()
                    if orig:
                        return orig
                r_val = find_value_to_right(b)
                if r_val:
                    return r_val
                n_val = find_next_block(b)
                if n_val:
                    return n_val
        return ""

    # ── STRICT PRIORITY CHAIN for Model ──
    model = value_from_keyword("MODEL NAME")
    if not model:
        model = value_from_keyword("MODEL")
    if not model:
        model = value_from_keyword("PART NAME")

    # ── STRICT PRIORITY CHAIN for Part Number ──
    part_no = value_from_keyword("PART NUMBER")
    if not part_no:
        part_no = value_from_keyword("PART NO")
    if not part_no:
        part_no = value_from_keyword("SAP CODE")
    if not part_no:
        part_no = value_from_keyword("SAP")

    # ── Filter generic product-category words ──
    generic_words = {"PISTON", "PISTON SET", "PISTON SETS", "PISTON PINS",
                     "ENGINE", "RING", "PIN", "SHAFT", "PRODUCT", "ITEM"}
    if model and model.upper().strip() in generic_words:
        model = ""

    if not model and blocks:
        model = blocks[0]["text"]

    model   = clean_ocr(model,   is_code=False)
    part_no = clean_ocr(part_no, is_code=True)

    extracted_json = json.dumps({
        "status": "success",
        "ocr_data": [{"text": b["text"], "conf": b["conf"]} for b in blocks],
        "extracted": {"model": model, "part_no": part_no}
    }, indent=2)

    return model, part_no, extracted_json