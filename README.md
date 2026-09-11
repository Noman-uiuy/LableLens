# LableLens — Packaged Commodity Inspection System

Automated compliance verification under Legal Metrology (Packaged Commodities) Rules, 2011 (PCR 2011).

## Features
- **Statutory 6-Declaration Compliance Grid**: Validates Manufacturer/Packer, Commodity Name, Net Quantity, MRP, Month & Year of Packing/Import, and Consumer Care Details under PCR 2011.
- **Accessible PDF Report Generation**: Simple and clean statutory compliance report with one-click export and interactive transcript permission modal.
- **Multi-Image / Multi-Angle Scanning**: Inspect packaging from front, back, and side panels simultaneously.
- **Integrated Admin Console**: System statistics, rule configuration, audit log history, and database overview.
- **FastAPI & Dual-Engine OCR Pipeline**: Fast OCR extraction powered by concurrent RapidOCR & Tesseract engines with bilateral pre-processing.

## Quick Start Options

### 1. Instant Frontend Preview (No Python Required)
Open index.html or rontend_preview.html in any modern web browser (Chrome, Edge, Firefox, Safari).
- Full interactive UI, language switching (English, Hindi, Marathi, Tamil), sample packages, compliance rulebook, offline reader, and demo workflows work immediately.

### 2. Full Live Server with Real-Time OCR
To run the full backend with real-time OCR and database archiving:

1. **Install Requirements:**
   `ash
   pip install -r requirements.txt
   `

2. **Start the Server:**
   `ash
   python main.py
   `
   *Or double-click 
un_live.bat on Windows.*

3. **Open in Browser:**
   Navigate to [http://localhost:8000](http://localhost:8000).
   Admin console is available at [http://localhost:8000/admin.html](http://localhost:8000/admin.html).

## Project Files
- index.html: Main application interface with left sidebar, centered camera/upload scanner, and Legal Metrology 6-declarations compliance panel.
- dmin.html: Integrated Admin Console for compliance officers and system administration.
- rontend_preview.html: Standalone browser preview file.
- main.py: FastAPI backend server with endpoints for label scanning, database history, and reports.
- label_ocr.py: High-speed dual-engine OCR pipeline with bilateral pre-processing.
- database.py: SQLite persistent audit trail and inspection database.
- 
equirements.txt: Python dependencies.
