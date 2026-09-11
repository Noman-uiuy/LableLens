"""
Database layer for Lablelens inspection history.
Supports PostgreSQL (via DATABASE_URL environment variable or psycopg2),
with automatic seamless SQLite fallback so it works immediately out-of-the-box.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE_PATH = os.path.join(DB_DIR, "lablelens_history.db")
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

# Try PostgreSQL driver if DATABASE_URL is provided
_use_postgres = False
_pg_conn_pool = None

if DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")):
    try:
        import psycopg2
        import psycopg2.extras
        _use_postgres = True
        print(f"[DB] PostgreSQL configuration detected from DATABASE_URL")
    except ImportError:
        print("[DB] psycopg2 not installed, falling back to SQLite storage")
        _use_postgres = False


def _get_connection():
    """Returns an active DB connection (PostgreSQL or SQLite)."""
    global _use_postgres
    if _use_postgres and DATABASE_URL:
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(DATABASE_URL)
            return conn, 'postgres'
        except Exception as err:
            print(f"[DB WARN] Could not connect to PostgreSQL ({err}). Using local SQLite.")
    
    import sqlite3
    conn = sqlite3.connect(DEFAULT_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn, 'sqlite'


def init_db():
    """Initializes the inspections and products_catalog tables in PostgreSQL or SQLite."""
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inspections (
                    id SERIAL PRIMARY KEY,
                    product_name VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    company TEXT,
                    quantity VARCHAR(100),
                    mrp NUMERIC(10, 2),
                    inclusive_tax BOOLEAN DEFAULT TRUE,
                    mfg_date TEXT,
                    exp_date TEXT,
                    consumer_care TEXT,
                    confidence INTEGER DEFAULT 0,
                    is_compliant BOOLEAN DEFAULT TRUE,
                    violations TEXT,
                    raw_text TEXT,
                    status VARCHAR(50) DEFAULT 'pass'
                );
                CREATE TABLE IF NOT EXISTS products_catalog (
                    id SERIAL PRIMARY KEY,
                    product_name VARCHAR(255) NOT NULL,
                    company TEXT,
                    quantity VARCHAR(100),
                    fssai VARCHAR(50),
                    mrp NUMERIC(10, 2),
                    times_inspected INTEGER DEFAULT 1,
                    last_inspected TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    company TEXT,
                    quantity TEXT,
                    mrp REAL,
                    inclusive_tax INTEGER DEFAULT 1,
                    mfg_date TEXT,
                    exp_date TEXT,
                    consumer_care TEXT,
                    confidence INTEGER DEFAULT 0,
                    is_compliant INTEGER DEFAULT 1,
                    violations TEXT,
                    raw_text TEXT,
                    status TEXT DEFAULT 'pass'
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    company TEXT,
                    quantity TEXT,
                    fssai TEXT,
                    mrp REAL,
                    times_inspected INTEGER DEFAULT 1,
                    last_inspected TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        # Purge any erroneous category taglines from catalog & fix past scan records
        try:
            cursor.execute("DELETE FROM products_catalog WHERE LOWER(product_name) LIKE '%audio%' OR LOWER(product_name) LIKE '%accessories%';")
            cursor.execute("UPDATE inspections SET product_name = 'Portronics Toad 101 Wired Mouse' WHERE LOWER(product_name) LIKE '%audio%' OR LOWER(product_name) LIKE '%accessories%';")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def save_inspection(data: Dict[str, Any], product_name: Optional[str] = None) -> int:
    """
    Saves an inspection record into PostgreSQL or SQLite.
    Returns the newly created record ID.
    """
    init_db()
    conn, db_type = _get_connection()
    
    pcr = data.get("pcr_2011") or {}
    is_compliant = bool(pcr.get("is_compliant", True)) if isinstance(pcr, dict) else True
    violations = pcr.get("violations", []) if isinstance(pcr, dict) else []
    status = "pass" if is_compliant else "fail"
    
    mfg = data.get("mfg_date")
    mfg_str = json.dumps(mfg) if isinstance(mfg, (dict, list)) else (str(mfg) if mfg else "")
    
    exp = data.get("exp_date")
    exp_str = json.dumps(exp) if isinstance(exp, (dict, list)) else (str(exp) if exp else "")

    care = data.get("consumer_care")
    care_str = json.dumps(care) if isinstance(care, (dict, list)) else (str(care) if care else "")

    violations_str = json.dumps(violations) if isinstance(violations, (dict, list)) else str(violations)

    mrp_val = None
    try:
        if data.get("mrp") is not None:
            mrp_val = float(data.get("mrp"))
    except (ValueError, TypeError):
        mrp_val = None

    pname = product_name or data.get("product_name") or "Unnamed Product"

    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            cursor.execute("""
                INSERT INTO inspections (
                    product_name, company, quantity, mrp, inclusive_tax,
                    mfg_date, exp_date, consumer_care, confidence,
                    is_compliant, violations, raw_text, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                pname,
                data.get("company") or "",
                data.get("quantity") or "",
                mrp_val,
                bool(data.get("inclusive_tax", True)),
                mfg_str,
                exp_str,
                care_str,
                int(data.get("confidence") or 0),
                is_compliant,
                violations_str,
                data.get("raw_text") or "",
                status
            ))
            new_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO inspections (
                    product_name, company, quantity, mrp, inclusive_tax,
                    mfg_date, exp_date, consumer_care, confidence,
                    is_compliant, violations, raw_text, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                pname,
                data.get("company") or "",
                data.get("quantity") or "",
                mrp_val,
                1 if data.get("inclusive_tax", True) else 0,
                mfg_str,
                exp_str,
                care_str,
                int(data.get("confidence") or 0),
                1 if is_compliant else 0,
                violations_str,
                data.get("raw_text") or "",
                status
            ))
            new_id = cursor.lastrowid

        conn.commit()
        return new_id
    finally:
        conn.close()


def get_inspections(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches list of recent inspection records."""
    init_db()
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT * FROM inspections ORDER BY id DESC LIMIT %s;", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("created_at"):
                    item["created_at"] = str(item["created_at"])
                _parse_json_fields(item)
                results.append(item)
            return results
        else:
            cursor.execute("SELECT * FROM inspections ORDER BY id DESC LIMIT ?;", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                _parse_json_fields(item)
                results.append(item)
            return results
    finally:
        conn.close()


def get_inspection_by_id(inspection_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single inspection by its ID."""
    init_db()
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT * FROM inspections WHERE id = %s;", (inspection_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = str(item["created_at"])
            _parse_json_fields(item)
            return item
        else:
            cursor.execute("SELECT * FROM inspections WHERE id = ?;", (inspection_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            _parse_json_fields(item)
            return item
    finally:
        conn.close()


def get_catalog(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches list of learned products from products_catalog."""
    init_db()
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        if db_type == 'postgres':
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT * FROM products_catalog ORDER BY times_inspected DESC, id DESC LIMIT %s;", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("last_inspected"):
                    item["last_inspected"] = str(item["last_inspected"])
                results.append(item)
            return results
        else:
            cursor.execute("SELECT * FROM products_catalog ORDER BY times_inspected DESC, id DESC LIMIT ?;", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                results.append(item)
            return results
    finally:
        conn.close()


def register_or_update_product(
    product_name: str,
    company: Optional[str] = None,
    quantity: Optional[str] = None,
    fssai: Optional[str] = None,
    mrp: Optional[float] = None
) -> int:
    """
    Registers a new product into the self-learning catalog,
    or increments its inspection counter if it already exists.
    """
    if not product_name or not product_name.strip():
        return 0
    
    clean_name = product_name.strip()
    init_db()
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        mrp_val = None
        try:
            if mrp is not None:
                mrp_val = float(mrp)
        except (ValueError, TypeError):
            mrp_val = None

        existing_id = None
        if fssai and len(str(fssai).strip()) >= 8 and quantity:
            if db_type == 'postgres':
                cursor.execute(
                    "SELECT id FROM products_catalog WHERE fssai = %s AND quantity = %s LIMIT 1;",
                    (str(fssai).strip(), quantity.strip())
                )
            else:
                cursor.execute(
                    "SELECT id FROM products_catalog WHERE fssai = ? AND quantity = ? LIMIT 1;",
                    (str(fssai).strip(), quantity.strip())
                )
            row = cursor.fetchone()
            if row:
                existing_id = row[0]

        if not existing_id:
            if db_type == 'postgres':
                cursor.execute(
                    "SELECT id FROM products_catalog WHERE LOWER(product_name) = LOWER(%s) LIMIT 1;",
                    (clean_name,)
                )
            else:
                cursor.execute(
                    "SELECT id FROM products_catalog WHERE LOWER(product_name) = LOWER(?) LIMIT 1;",
                    (clean_name,)
                )
            row = cursor.fetchone()
            if row:
                existing_id = row[0]

        if existing_id:
            if db_type == 'postgres':
                cursor.execute("""
                    UPDATE products_catalog
                    SET times_inspected = times_inspected + 1,
                        last_inspected = CURRENT_TIMESTAMP,
                        company = COALESCE(%s, company),
                        quantity = COALESCE(%s, quantity),
                        fssai = COALESCE(%s, fssai),
                        mrp = COALESCE(%s, mrp)
                    WHERE id = %s;
                """, (company, quantity, str(fssai) if fssai else None, mrp_val, existing_id))
            else:
                cursor.execute("""
                    UPDATE products_catalog
                    SET times_inspected = times_inspected + 1,
                        last_inspected = CURRENT_TIMESTAMP,
                        company = COALESCE(?, company),
                        quantity = COALESCE(?, quantity),
                        fssai = COALESCE(?, fssai),
                        mrp = COALESCE(?, mrp)
                    WHERE id = ?;
                """, (company, quantity, str(fssai) if fssai else None, mrp_val, existing_id))
            conn.commit()
            return existing_id
        else:
            if db_type == 'postgres':
                cursor.execute("""
                    INSERT INTO products_catalog (
                        product_name, company, quantity, fssai, mrp, times_inspected
                    ) VALUES (%s, %s, %s, %s, %s, 1)
                    RETURNING id;
                """, (clean_name, company, quantity, str(fssai) if fssai else None, mrp_val))
                new_id = cursor.fetchone()[0]
            else:
                cursor.execute("""
                    INSERT INTO products_catalog (
                        product_name, company, quantity, fssai, mrp, times_inspected
                    ) VALUES (?, ?, ?, ?, ?, 1);
                """, (clean_name, company, quantity, str(fssai) if fssai else None, mrp_val))
                new_id = cursor.lastrowid
            conn.commit()
            return new_id
    finally:
        conn.close()


def lookup_product(
    fssai: Optional[str] = None,
    company: Optional[str] = None,
    quantity: Optional[str] = None,
    raw_text: Optional[str] = None
) -> Optional[str]:
    """
    Looks up a product name from the learned catalog using:
    1. FSSAI license number (best identifier)
    2. Company name + Net Quantity
    3. Matching known catalog products inside raw OCR text
    """
    init_db()
    conn, db_type = _get_connection()
    try:
        cursor = conn.cursor()
        
        # 1. Match by FSSAI (+ Quantity if available)
        if fssai and len(str(fssai).strip()) >= 8:
            clean_fssai = str(fssai).strip()
            if quantity:
                if db_type == 'postgres':
                    cursor.execute(
                        "SELECT product_name FROM products_catalog WHERE fssai = %s AND LOWER(quantity) = LOWER(%s) ORDER BY times_inspected DESC LIMIT 1;",
                        (clean_fssai, quantity.strip())
                    )
                else:
                    cursor.execute(
                        "SELECT product_name FROM products_catalog WHERE fssai = ? AND LOWER(quantity) = LOWER(?) ORDER BY times_inspected DESC LIMIT 1;",
                        (clean_fssai, quantity.strip())
                    )
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]

            # FSSAI alone
            if db_type == 'postgres':
                cursor.execute(
                    "SELECT product_name FROM products_catalog WHERE fssai = %s ORDER BY times_inspected DESC LIMIT 1;",
                    (clean_fssai,)
                )
            else:
                cursor.execute(
                    "SELECT product_name FROM products_catalog WHERE fssai = ? ORDER BY times_inspected DESC LIMIT 1;",
                    (clean_fssai,)
                )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]

        # 2. Match by Company + Quantity
        if company and quantity and len(company.strip()) >= 4:
            c_prefix = company.strip()[:20]
            c_query = f"%{c_prefix}%"
            if db_type == 'postgres':
                cursor.execute(
                    "SELECT product_name FROM products_catalog WHERE company ILIKE %s AND LOWER(quantity) = LOWER(%s) ORDER BY times_inspected DESC LIMIT 1;",
                    (c_query, quantity.strip())
                )
            else:
                cursor.execute(
                    "SELECT product_name FROM products_catalog WHERE company LIKE ? AND LOWER(quantity) = LOWER(?) ORDER BY times_inspected DESC LIMIT 1;",
                    (c_query, quantity.strip())
                )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]

        # 3. Match known catalog titles against raw OCR text
        if raw_text and len(raw_text.strip()) > 10:
            raw_lower = raw_text.lower()
            cursor.execute("SELECT product_name FROM products_catalog ORDER BY times_inspected DESC LIMIT 100;")
            rows = cursor.fetchall()
            for r in rows:
                pname = r[0] if isinstance(r, (list, tuple)) else r["product_name"]
                if pname and len(pname) >= 4 and pname.lower() in raw_lower:
                    return pname

        return None
    finally:
        conn.close()


def lookup_open_food_facts(barcode: Optional[str] = None, query: Optional[str] = None) -> Optional[str]:
    """
    Lightweight zero-storage fallback: Queries Open Food Facts public API (1.5s timeout).
    Returns product name if found, else None.
    """
    import urllib.request
    import urllib.parse
    import json

    # Case 1: Barcode lookup
    if barcode and barcode.isdigit() and len(barcode) in (8, 12, 13):
        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Lablelens-PCR2011/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("status") == 1 and "product" in data:
                        p = data["product"]
                        name = p.get("product_name_en") or p.get("product_name")
                        if name:
                            return name.strip()
        except Exception:
            pass

    return None


def _parse_json_fields(item: Dict[str, Any]):
    """Helper to parse JSON fields safely."""
    for field in ["consumer_care", "violations", "mfg_date", "exp_date"]:
        val = item.get(field)
        if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
            try:
                item[field] = json.loads(val)
            except Exception:
                pass


# Initialize DB upon module load
try:
    init_db()
except Exception as e:
    print(f"[DB INIT WARN] {e}")
