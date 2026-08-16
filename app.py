from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import re, os, sys, shutil, tempfile

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

app = FastAPI(title="Box Packing Verifier", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

sessions: dict = {}

def normalise(text: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', text.upper())

def model_match(prim: str, sec: str) -> bool:
    np_ = normalise(prim)
    ns_ = normalise(sec)
    if not np_ or not ns_:
        return False
    return np_ == ns_ or np_ in ns_ or ns_ in np_

class SecondarySetup(BaseModel):
    station_id: str = "main"
    model: str
    qty: int

class PrimaryScan(BaseModel):
    station_id: str = "main"
    model: str

@app.post("/api/secondary/setup")
def setup_secondary(data: SecondarySetup):
    if not data.model.strip():
        raise HTTPException(400, "Model cannot be empty")
    if data.qty <= 0:
        raise HTTPException(400, "QTY must be greater than 0")

    sessions[data.station_id] = {
        "secondary_model": data.model.strip().upper(),
        "qty": data.qty,
        "count": 0,
        "box_no": sessions.get(data.station_id, {}).get("box_no", 0) + 1,
        "rejected": 0,
        "history": []
    }
    s = sessions[data.station_id]
    return {
        "status": "ok",
        "message": f"Secondary box #{s['box_no']} setup complete",
        "secondary_model": s["secondary_model"],
        "qty": s["qty"],
        "box_no": s["box_no"]
    }

@app.post("/api/secondary/upload")
async def upload_secondary(file: UploadFile = File(...), station_id: str = "main"):
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        from secondary import extract_secondary
        model, qty_str, raw_json = extract_secondary(tmp_path)
    except Exception as e:
        raise HTTPException(500, f"OCR extraction error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if not model:
        raise HTTPException(400, "Could not extract Model Name from label image.")

    try:
        qty = int(qty_str)
        if qty <= 0:
            qty = 36
    except Exception:
        qty = 36

    sessions[station_id] = {
        "secondary_model": model.strip().upper(),
        "qty": qty,
        "count": 0,
        "box_no": sessions.get(station_id, {}).get("box_no", 0) + 1,
        "rejected": 0,
        "history": []
    }
    s = sessions[station_id]
    return {
        "status": "ok",
        "message": "Secondary label scanned successfully",
        "secondary_model": s["secondary_model"],
        "qty": s["qty"],
        "box_no": s["box_no"]
    }

@app.post("/api/primary/scan")
def scan_primary(data: PrimaryScan):
    sid = data.station_id
    if sid not in sessions:
        raise HTTPException(400, "No active secondary box session. Setup secondary box first.")

    s = sessions[sid]
    if s["count"] >= s["qty"]:
        return {
            "status": "full",
            "message": "Secondary box is already full! Please change it.",
            "count": s["count"],
            "qty": s["qty"]
        }

    primary_model = data.model.strip().upper()
    matched = model_match(primary_model, s["secondary_model"])

    if matched:
        s["count"] += 1
        s["history"].append({"model": primary_model, "result": "match"})
        is_full = s["count"] >= s["qty"]
        return {
            "status": "full" if is_full else "match",
            "message": (
                f"Box #{s['box_no']} is FULL! Please change the secondary box."
                if is_full
                else f"Matched! Packed {s['count']}/{s['qty']}"
            ),
            "count": s["count"],
            "qty": s["qty"],
            "box_no": s["box_no"],
            "rejected": s["rejected"]
        }
    else:
        s["rejected"] += 1
        s["history"].append({"model": primary_model, "result": "mismatch"})
        return {
            "status": "mismatch",
            "message": f"Model NOT matched! Expected: {s['secondary_model']}, Got: {primary_model}",
            "expected": s["secondary_model"],
            "got": primary_model,
            "count": s["count"],
            "qty": s["qty"],
            "rejected": s["rejected"]
        }

@app.post("/api/primary/upload")
async def upload_primary(file: UploadFile = File(...), station_id: str = "main"):
    sid = station_id
    if sid not in sessions:
        raise HTTPException(400, "No active secondary box session. Setup secondary box first.")

    s = sessions[sid]
    if s["count"] >= s["qty"]:
        return {
            "status": "full",
            "message": "Secondary box is already full! Please change it.",
            "count": s["count"],
            "qty": s["qty"]
        }

    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        from primary import extract_primary
        primary_model, part_no, raw_json = extract_primary(tmp_path)
    except Exception as e:
        raise HTTPException(500, f"OCR extraction error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if not primary_model:
        raise HTTPException(400, "Could not extract Model Name from label image.")

    primary_model = primary_model.strip().upper()
    matched = model_match(primary_model, s["secondary_model"])

    if matched:
        s["count"] += 1
        s["history"].append({"model": primary_model, "result": "match"})
        is_full = s["count"] >= s["qty"]
        return {
            "status": "full" if is_full else "match",
            "message": (
                f"Box #{s['box_no']} is FULL! Please change the secondary box."
                if is_full
                else f"Matched! Packed {s['count']}/{s['qty']}"
            ),
            "primary_model": primary_model,
            "count": s["count"],
            "qty": s["qty"],
            "box_no": s["box_no"],
            "rejected": s["rejected"]
        }
    else:
        s["rejected"] += 1
        s["history"].append({"model": primary_model, "result": "mismatch"})
        return {
            "status": "mismatch",
            "message": f"Model NOT matched! Expected: {s['secondary_model']}, Got: {primary_model}",
            "primary_model": primary_model,
            "expected": s["secondary_model"],
            "got": primary_model,
            "count": s["count"],
            "qty": s["qty"],
            "rejected": s["rejected"]
        }

@app.get("/api/session/{station_id}")
def get_session(station_id: str = "main"):
    if station_id not in sessions:
        return {"active": False}
    s = sessions[station_id]
    return {
        "active": True,
        "secondary_model": s["secondary_model"],
        "qty": s["qty"],
        "count": s["count"],
        "box_no": s["box_no"],
        "rejected": s["rejected"]
    }

@app.post("/api/session/{station_id}/reset")
def reset_session(station_id: str = "main"):
    if station_id in sessions:
        del sessions[station_id]
    return {"status": "ok", "message": "Session cleared"}

if __name__ == "__main__":
    import uvicorn
    import socket
    ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  Open in browser:  http://{ip}:8000")
    print(f"  Local access:     http://localhost:8000\n")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)