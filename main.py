"""
Tolmaap — FastAPI Backend
Receives product label images, runs OCR + PCR 2011 rules, returns compliance report.

Run:
    uvicorn main:app --reload --port 8000

Test:
    curl -X POST http://localhost:8000/api/analyze \
         -F "image=@your_product.jpg"
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import os
import uvicorn

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

from label_ocr import LabelOCR
from database import (
    save_inspection, get_inspections, get_inspection_by_id,
    lookup_product, register_or_update_product, get_catalog
)


# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(
    title="Tolmaap OCR API",
    description="PCR 2011 compliance checker for packaged goods labels",
    version="1.0.0",
)

@app.on_event("startup")
def prewarm_ocr():
    """Pre-warm OCR models in RAM on server startup so first scan is instantly fast."""
    try:
        from label_ocr import OCREngine
        engine = OCREngine()
        engine._get_paddle()
        print("[Startup] OCR neural models pre-warmed in memory.")
    except Exception as e:
        print(f"[Startup Warn] Pre-warm failed: {e}")

# ── CORS — allows your HTML frontend to call this API ────────────────────────
# Change allow_origins to your actual frontend URL in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Allowed image types ────────────────────────────────────────────────────────
ALLOWED_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/bmp", "image/tiff", "image/pjpeg", "image/x-png",
    "application/octet-stream"
}
MAX_FILE_SIZE  = 15 * 1024 * 1024  # 15 MB


# ============================================================
# RESPONSE MODELS
# ============================================================

from typing import Optional, List, Union, Any, Dict

class DateInfo(BaseModel):
    month: Optional[int] = None
    year:  Optional[int] = None
    month_name: Optional[Any] = None
    day:   Optional[int] = None
    inferred_from_shelf_life: Optional[str] = None
    shelf_life_statement: Optional[str] = None
    display: Optional[str] = None

class PCR2011Result(BaseModel):
    is_compliant: bool
    violations:   List[str]

class ScanResult(BaseModel):
    product_name:   Optional[str]       = None
    mrp:            Optional[float]     = None
    quantity:       Optional[str]       = None
    mfg_date:       Optional[DateInfo]  = None
    exp_date:       Optional[DateInfo]  = None
    company:        Optional[str]       = None
    fssai:          Optional[str]       = None
    consumer_care:  Optional[str]       = None
    inclusive_tax:  bool                = False
    unit_violation: Optional[str]       = None
    confidence:     int                 = 0
    pcr_2011:       Optional[PCR2011Result] = None
    engines_used:   Optional[Dict[str, Any]] = None
    raw_text:       Optional[str]       = None

    class Config:
        extra = "allow"


# ============================================================
# ROUTES
# ============================================================

@app.get("/health")
def health_check():
    """Quick liveness probe — useful for deployment monitoring."""
    return {"status": "ok", "service": "Tolmaap OCR API"}


@app.post("/api/analyze", response_model=ScanResult)
async def analyze_label(image: UploadFile = File(...), product_name: Optional[str] = None):
    """
    Upload a product label image and receive a PCR 2011 compliance report.

    - Accepts: JPEG, PNG, WebP, BMP, TIFF
    - Max size: 10 MB
    - Returns: extracted fields + PCR 2011 violation list
    """

    # ── Validate content type ──────────────────────────────────────────────────
    if image.content_type and not (image.content_type.startswith("image/") or image.content_type in ALLOWED_TYPES):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{image.content_type}'. Please upload an image file."
        )

    # ── Read bytes ─────────────────────────────────────────────────────────────
    contents = await image.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(contents)//1024} KB). Max allowed: 10 MB"
        )

    # ── Run OCR pipeline ───────────────────────────────────────────────────────
    try:
        scanner = LabelOCR(contents)          # pass bytes directly
        results = scanner.scan()              # full extraction with raw text for database and UI
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] OCR pipeline failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR error: {str(e)}"
        )

    # ── Product Name Auto-Resolution (Zero-Typing) ───────────────────────────
    final_product_name = (product_name or "").strip()
    
    # Discard any stale category taglines or default placeholders
    if any(k in final_product_name.lower() for k in ["audio", "mobile accessories", "pc accessories", "unnamed", "bella vita"]):
        final_product_name = ""

    # RULE 1: If product name is detected on the label OCR, ALWAYS use the label directly!
    ocr_name = results.get("product_name")
    if ocr_name and len(ocr_name) >= 3 and not any(k in ocr_name.lower() for k in ["audio", "mobile accessories"]):
        final_product_name = ocr_name
        name_source = "ocr_label"
    elif not final_product_name:
        # RULE 2: Only if label does NOT show product name, check local catalog
        catalog_name = lookup_product(
            fssai=results.get("fssai"),
            company=results.get("company"),
            quantity=results.get("quantity"),
            raw_text=results.get("raw_text")
        )
        if catalog_name:
            final_product_name = catalog_name
            name_source = "learned_catalog"
    else:
        name_source = "user_input"

    if final_product_name:
        results["product_name"] = final_product_name
        results["product_name_source"] = name_source
        # Auto-teach catalog for future zero-typing scans
        try:
            register_or_update_product(
                product_name=final_product_name,
                company=results.get("company"),
                quantity=results.get("quantity"),
                fssai=results.get("fssai"),
                mrp=results.get("mrp")
            )
        except Exception as cat_err:
            print(f"[CATALOG WARN] Could not register product in catalog: {cat_err}")

    # ── Save inspection to history database (PostgreSQL / SQLite) ─────────────
    try:
        record_id = save_inspection(results, product_name=final_product_name)
        results["inspection_id"] = record_id
    except Exception as dberr:
        print(f"[DB WARN] Could not save inspection to database: {dberr}")

    return JSONResponse(content=results)


@app.get("/api/inspections")
def list_inspections(limit: int = 50):
    """Fetch recent inspection history from PostgreSQL / SQLite database."""
    try:
        return get_inspections(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inspections/{inspection_id}")
def get_single_inspection(inspection_id: int):
    """Fetch a single inspection by its ID."""
    rec = get_inspection_by_id(inspection_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return rec


@app.get("/api/catalog")
def list_catalog(limit: int = 50):
    """Fetch learned products catalog."""
    try:
        return get_catalog(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze/multi")
async def analyze_multi_panel(images: List[UploadFile] = File(...)):
    """
    Upload multiple panel images of the same product (front, back, side).
    Results are merged before compliance checking.

    Useful for products where MRP is on back and MFG date is on bottom.
    """
    if len(images) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 images per scan")

    from label_ocr import OCREngine, Extractor, Validator

    engine    = OCREngine()
    extractor = Extractor()
    combined_text = ""

    for img_file in images:
        if img_file.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"File '{img_file.filename}' has unsupported type"
            )
        contents = await img_file.read()
        if len(contents) == 0:
            continue

        try:
            full   = engine.ocr_full(contents)
            bottom = engine.ocr_bottom(contents)
            top    = engine.ocr_top(contents)
            raw    = engine.ocr_raw(contents)
            combined_text = engine.merge_texts(combined_text, full, bottom, top, raw)
        except Exception as e:
            print(f"[WARN] Skipped {img_file.filename}: {e}")
            continue

    if not combined_text.strip():
        raise HTTPException(status_code=422, detail="No readable text found in any image")

    quantity = extractor.extract_quantity(combined_text)
    results  = {
        "mrp":            extractor.extract_mrp(combined_text),
        "quantity":       quantity,
        "mfg_date":       extractor.extract_mfg_date(combined_text),
        "exp_date":       extractor.extract_exp_date(combined_text),
        "company":        extractor.extract_company(combined_text),
        "fssai":          extractor.extract_fssai(combined_text),
        "consumer_care":  extractor.extract_consumer_care(combined_text),
        "inclusive_tax":  extractor.check_inclusive_tax(combined_text),
        "unit_violation": extractor.check_unit_violation(quantity),
    }
    results["confidence"] = extractor.calculate_confidence(results)
    results["pcr_2011"]   = Validator.validate_all(results)

    return JSONResponse(content=results)


@app.get("/")
def serve_index():
    index_path = os.path.join(CURRENT_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "index.html not found"}


# Serve static files (JS, CSS, images in current folder)
app.mount("/", StaticFiles(directory=CURRENT_DIR, html=True), name="static")


# ============================================================
# DEV SERVER
# ============================================================

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
