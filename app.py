import os
import re
import json
import secrets
import hashlib
import sqlite3
import pymysql
import pymysql.cursors
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Load environment variables securely from .env
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.secret_key = os.environ.get('SECRET_KEY', 'heena_imitation_jewellery_super_secret_key_2026')

# --- Secure Config ---
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
ADMIN_ID = os.environ.get('ADMIN_ID', 'heena imitation jewellery')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'HeenaAdmin#2026')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'heenaimitationjewellery06@gmail.com')
ADMIN_WHATSAPP_NUMBER = os.environ.get('ADMIN_WHATSAPP_NUMBER', '919777166165')
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '919777166165')

# --- Supabase / PostgreSQL Config (Netlify Extension & Production) ---
POSTGRES_URL = (
    os.environ.get('DATABASE_URL') or
    os.environ.get('SUPABASE_DB_URL') or
    os.environ.get('SUPABASE_DATABASE_URL') or
    os.environ.get('POSTGRES_URL') or
    os.environ.get('SUPABASE_POSTGRES_URL')
)

if not POSTGRES_URL and os.environ.get('SUPABASE_DB_HOST'):
    _pg_host = os.environ.get('SUPABASE_DB_HOST')
    _pg_port = os.environ.get('SUPABASE_DB_PORT', '5432')
    _pg_user = os.environ.get('SUPABASE_DB_USER', 'postgres')
    _pg_pass = os.environ.get('SUPABASE_DB_PASSWORD', '')
    _pg_name = os.environ.get('SUPABASE_DB_NAME', 'postgres')
    POSTGRES_URL = f"postgresql://{_pg_user}:{_pg_pass}@{_pg_host}:{_pg_port}/{_pg_name}"

# --- MySQL Config (Local Laragon) ---
MYSQL_HOST = os.environ.get('MYSQL_HOST', '127.0.0.1')
MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
MYSQL_DB = os.environ.get('MYSQL_DB', 'heena imitation jewellery')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))

# --- SQLite & Uploads Config (Local Fallback & Serverless Resilient) ---
SQLITE_DB = os.environ.get('SQLITE_DB_PATH')
if not SQLITE_DB:
    if os.access(BASE_DIR, os.W_OK):
        SQLITE_DB = os.path.join(BASE_DIR, 'database.db')
    else:
        SQLITE_DB = os.path.join('/tmp', 'database.db')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except Exception:
    tmp_upload = os.path.join('/tmp', 'uploads')
    try:
        os.makedirs(tmp_upload, exist_ok=True)
        app.config['UPLOAD_FOLDER'] = tmp_upload
    except Exception:
        pass

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_string(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

# --- PostgreSQL / Supabase Adapters ---
class PostgresCursorWrapper:
    """Wraps psycopg2 cursor to provide MySQL-compatible cursor.lastrowid and dict rows."""
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, query, vars=None):
        cleaned_query = query.strip()
        is_insert = cleaned_query.upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in cleaned_query.upper()

        if is_insert and not has_returning:
            # Check if target table has an auto-increment primary key 'id'
            table_match = re.search(r"INSERT\s+INTO\s+([a-zA-Z0-9_`\"']+)", cleaned_query, re.IGNORECASE)
            table_name = table_match.group(1).strip('`"\'').lower() if table_match else ''
            if table_name in ('orders', 'products', 'users', 'reviews', 'password_resets', 'categories'):
                query_with_returning = f"{cleaned_query.rstrip(';')} RETURNING id"
                self._cursor.execute(query_with_returning, vars)
                try:
                    ret_row = self._cursor.fetchone()
                    if ret_row:
                        self.lastrowid = ret_row.get('id') if isinstance(ret_row, dict) else ret_row[0]
                except Exception:
                    pass
                return self

        self._cursor.execute(query, vars)
        return self

    def executemany(self, query, vars_list):
        return self._cursor.executemany(query, vars_list)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size else self._cursor.fetchmany()

    def close(self):
        return self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresConnectionWrapper:
    """Wraps psycopg2 connection to ensure autocommit and dict cursors by default."""
    def __init__(self, raw_conn):
        self._conn = raw_conn
        try:
            self._conn.autocommit = True
        except Exception:
            pass

    def cursor(self):
        if HAS_PSYCOPG2:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = self._conn.cursor()
        return PostgresCursorWrapper(cur)

    def commit(self):
        try:
            self._conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_postgres_connection():
    """Establishes connection to Supabase PostgreSQL."""
    if not POSTGRES_URL:
        return None

    url = POSTGRES_URL.strip()
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]

    if HAS_PSYCOPG2:
        try:
            if 'sslmode' not in url:
                sep = '&' if '?' in url else '?'
                url_ssl = f"{url}{sep}sslmode=require"
            else:
                url_ssl = url
            raw_conn = psycopg2.connect(url_ssl)
            return PostgresConnectionWrapper(raw_conn)
        except Exception:
            try:
                raw_conn = psycopg2.connect(url)
                return PostgresConnectionWrapper(raw_conn)
            except Exception as e:
                print(f"Supabase / PostgreSQL connection error (psycopg2): {e}")

    return None


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        # 1. Supabase / PostgreSQL (Production on Netlify)
        if POSTGRES_URL:
            pg_conn = get_postgres_connection()
            if pg_conn:
                g._database = pg_conn
                g.db_type = 'postgres'
                return g._database

        # 2. MySQL (Local Laragon)
        try:
            db = g._database = pymysql.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                port=MYSQL_PORT,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor
            )
            g.db_type = 'mysql'
            return db
        except Exception:
            pass

        # 3. SQLite Fallback (Local file fallback)
        db = g._database = sqlite3.connect(SQLITE_DB)
        db.row_factory = sqlite3.Row
        g.db_type = 'sqlite'
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'success': False, 'message': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'message': f'Server internal error: {str(error)}'}), 500

# --- Admin Authentication Middleware Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            if request.path.startswith('/api/') or request.path.startswith('/admin/api/'):
                return jsonify({'success': False, 'message': 'Unauthorized admin access denied'}), 401
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    # 1. Supabase / PostgreSQL Tables & Seed Data (if configured)
    if POSTGRES_URL:
        try:
            pg = get_postgres_connection()
            if pg:
                cur = pg.cursor()
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        category VARCHAR(100) NOT NULL,
                        price DECIMAL(10,2) NOT NULL,
                        original_price DECIMAL(10,2) NOT NULL,
                        discount_percent INT NOT NULL,
                        rating DECIMAL(3,2) DEFAULT 4.8,
                        review_count INT DEFAULT 12,
                        image TEXT NOT NULL,
                        hover_image TEXT NOT NULL,
                        description TEXT NOT NULL,
                        specs TEXT NOT NULL,
                        is_best_seller INT DEFAULT 0,
                        is_new_arrival INT DEFAULT 0,
                        is_bridal INT DEFAULT 0,
                        color VARCHAR(50) NOT NULL,
                        material VARCHAR(50) NOT NULL,
                        occasion VARCHAR(50) NOT NULL,
                        stock INT DEFAULT 25
                    );

                    CREATE TABLE IF NOT EXISTS categories (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        slug VARCHAR(100) UNIQUE NOT NULL,
                        image TEXT NOT NULL,
                        description TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS reviews (
                        id SERIAL PRIMARY KEY,
                        product_id INT NOT NULL,
                        user_name VARCHAR(100) NOT NULL,
                        rating INT NOT NULL,
                        comment TEXT NOT NULL,
                        date VARCHAR(50) NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS orders (
                        id SERIAL PRIMARY KEY,
                        order_code VARCHAR(50) UNIQUE NOT NULL,
                        customer_name VARCHAR(100) NOT NULL,
                        customer_email VARCHAR(100) NOT NULL,
                        customer_phone VARCHAR(50) NOT NULL,
                        shipping_address TEXT NOT NULL,
                        items_json TEXT NOT NULL,
                        subtotal DECIMAL(10,2) NOT NULL,
                        tax DECIMAL(10,2) NOT NULL,
                        shipping DECIMAL(10,2) NOT NULL,
                        discount DECIMAL(10,2) DEFAULT 0,
                        total DECIMAL(10,2) NOT NULL,
                        payment_method VARCHAR(50) NOT NULL,
                        payment_status VARCHAR(50) NOT NULL,
                        order_status VARCHAR(50) DEFAULT 'Placed',
                        created_at VARCHAR(50) NOT NULL,
                        email_notification_sent INT DEFAULT 0,
                        whatsapp_notification_sent INT DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS coupons (
                        code VARCHAR(50) PRIMARY KEY,
                        discount_type VARCHAR(20) NOT NULL,
                        discount_value DECIMAL(10,2) NOT NULL,
                        min_order DECIMAL(10,2) DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(150) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NULL,
                        name VARCHAR(100),
                        created_at VARCHAR(50) NOT NULL,
                        last_login VARCHAR(50) NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS password_resets (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(150) NOT NULL,
                        token VARCHAR(100) NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        is_used INT DEFAULT 0
                    );
                ''')

                # Categories
                cur.execute("SELECT COUNT(*) AS total FROM categories")
                cnt_row = cur.fetchone()
                cnt = cnt_row['total'] if isinstance(cnt_row, dict) else (cnt_row[0] if cnt_row else 0)
                if cnt == 0:
                    categories = [
                        ("Necklaces", "necklaces", "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80", "Statement, Kundan & Choker Necklaces"),
                        ("Earrings", "earrings", "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80", "Jhumkas, Chandbalis & Studs"),
                        ("Pendants", "pendants", "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=600&q=80", "Minimal & Zircon Pendant Sets"),
                        ("Bracelets", "bracelets", "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=600&q=80", "Antique Gold Cuffs & Bangles"),
                        ("Rings", "rings", "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=600&q=80", "Solitaire & Cocktail Statement Rings"),
                        ("Bridal Sets", "bridal-sets", "/static/images/bridal_spotlight.jpg", "Grand Maharani Bridal Kundan Sets"),
                        ("Clutchers", "clutchers", "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=600&q=80", "Embellished Hair Accessories & Clutchers"),
                        ("Scrunchies & Garters", "scrunchies-garters", "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=600&q=80", "Luxury Satin Silk Scrunchies & Hair Garters")
                    ]
                    cur.executemany("INSERT INTO categories (name, slug, image, description) VALUES (%s, %s, %s, %s)", categories)

                # Coupons
                cur.execute("SELECT COUNT(*) AS total FROM coupons")
                cnt_row = cur.fetchone()
                cnt = cnt_row['total'] if isinstance(cnt_row, dict) else (cnt_row[0] if cnt_row else 0)
                if cnt == 0:
                    coupons = [
                        ("HEENA10", "percentage", 10.0, 499.0),
                        ("BRIDAL15", "percentage", 15.0, 1999.0),
                        ("FESTIVE200", "flat", 200.0, 999.0),
                        ("WELCOME500", "flat", 500.0, 2499.0)
                    ]
                    cur.executemany("INSERT INTO coupons (code, discount_type, discount_value, min_order) VALUES (%s, %s, %s, %s)", coupons)

                # Products
                cur.execute("SELECT COUNT(*) AS total FROM products")
                cnt_row = cur.fetchone()
                cnt = cnt_row['total'] if isinstance(cnt_row, dict) else (cnt_row[0] if cnt_row else 0)
                if cnt == 0:
                    from_default_products = [
                        ("Royal Emerald Kundan Choker Set", "Necklaces", 1899, 2999, 36, 4.9, 42,
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                         "Exquisite antique gold finish choker necklace studded with vibrant green emerald style Kundan stones and shell pearl drop beads. Comes with matching earrings.",
                         json.dumps({"Material": "Brass Alloy", "Plating": "22k Antique Gold", "Stone": "Kundan & Faux Emerald", "Occasion": "Festive / Wedding", "Care": "Avoid direct spray of perfume or water"}),
                         1, 1, 0, "Green", "Brass", "Festive", 18),
                        ("Heritage Temple Gold Necklace", "Necklaces", 2499, 3999, 37, 4.8, 28,
                         "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "Traditional South Indian temple design necklace featuring intricate Goddess motif carving and antique champagne gold polish.",
                         json.dumps({"Material": "High Grade Copper Alloy", "Plating": "Matt Antique Gold", "Stone": "Ruby Red CZ", "Occasion": "Festive / Pooja", "Care": "Store in airtight velvet pouch"}),
                         1, 0, 0, "Gold", "Alloy", "Festive", 12),
                        ("Maharani Oversized Chandbali", "Earrings", 1199, 1799, 33, 4.8, 31,
                         "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                         "Crescent-shaped Chandbali earrings adorned with Kundan work and maroon bead droppings. Perfect pair for ethnic silk sarees.",
                         json.dumps({"Material": "Brass", "Plating": "Gold Plated", "Stone": "Kundan & Maroon Beads", "Occasion": "Festive / Wedding", "Care": "Store in soft cotton pouch"}),
                         1, 1, 0, "Maroon", "Kundan", "Festive", 15),
                        ("Rose Gold Zircon Huggie Studs", "Earrings", 499, 799, 37, 4.6, 22,
                         "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                         "Sparkling rose gold polished zircon stud earrings designed for office wear and everyday casual sophistication.",
                         json.dumps({"Material": "Copper", "Plating": "Rose Gold", "Stone": "American Diamond", "Occasion": "Daily Wear", "Care": "Clean gently with dry cloth"}),
                         0, 0, 0, "Rose Gold", "Zircon", "Daily", 30),
                        ("Royal Solitaire Zircon Pendant Set", "Pendants", 799, 1299, 38, 4.9, 39,
                         "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "Classic heart solitaire cubic zirconia pendant chain set in 18k champagne gold plating with matching stud earrings.",
                         json.dumps({"Material": "Brass", "Plating": "18k Champagne Gold", "Stone": "CZ Diamond", "Occasion": "Daily / Gifting", "Care": "Keep in airtight box"}),
                         1, 0, 0, "Gold", "Zircon", "Daily", 20),
                        ("Floral Enamel Kundan Pendant", "Pendants", 699, 1099, 36, 4.7, 18,
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                         "Hand painted Meenakari enamel floral pendant with delicate Kundan center and gold beaded chain.",
                         json.dumps({"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Meenakari & Kundan", "Occasion": "Festive", "Care": "Avoid chemical exposure"}),
                         0, 1, 0, "Maroon", "Alloy", "Festive", 16),
                        ("Antique Gold Royal Bangle Set", "Bracelets", 1299, 1999, 35, 4.8, 27,
                         "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                         "Set of 4 intricate antique gold bangles embossed with floral motifs and ruby CZ accents.",
                         json.dumps({"Material": "Brass", "Plating": "Antique Gold", "Stone": "CZ Stones", "Occasion": "Festive / Wedding", "Care": "Wipe after wear"}),
                         1, 0, 0, "Gold", "Brass", "Festive", 22),
                        ("Rose Gold CZ Crystal Cuff", "Bracelets", 899, 1399, 35, 4.9, 14,
                         "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                         "Flexible openable wrist cuff with pavé set AAA cubic zirconia stones in radiant rose gold shine.",
                         json.dumps({"Material": "Alloy", "Plating": "Rose Gold", "Stone": "Cubic Zirconia", "Occasion": "Daily / Party", "Care": "Do not submerge in water"}),
                         0, 1, 0, "Rose Gold", "Zircon", "Daily", 19),
                        ("Solitaire Crown Adjustable Ring", "Rings", 399, 699, 42, 4.8, 64,
                         "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                         "Stunning crown design solitaire ring with adjustable band, suitable for all finger sizes.",
                         json.dumps({"Material": "Brass", "Plating": "Rhodium Gold", "Stone": "American Diamond", "Occasion": "Daily / Gifting", "Care": "Keep dry"}),
                         1, 1, 0, "Silver", "Zircon", "Daily", 50),
                        ("Traditional Kundan Cocktail Ring", "Rings", 599, 999, 40, 4.7, 33,
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                         "Statement oversized circular Kundan ring with pearl cluster border and adjustable ring base.",
                         json.dumps({"Material": "Alloy", "Plating": "Antique Gold", "Stone": "Kundan & Pearls", "Occasion": "Festive / Wedding", "Care": "Store in soft box"}),
                         0, 0, 0, "Gold", "Kundan", "Festive", 28),
                        ("Maharani Heritage Kundan Bridal Set", "Bridal Sets", 4999, 7999, 37, 5.0, 48,
                         "/static/images/bridal_spotlight.jpg",
                         "/static/images/hero_banner.jpg",
                         "Complete 7-Piece Luxury Royal Bridal Jewellery Set: Heavy Choker, Long Haar Necklace, Matching Chandbalis, Maang Tikka, Hathphool Bangles, and Nose Ring in 24k Gold Polish & Maroon Gemstones.",
                         json.dumps({"Material": "Premium Brass Alloy", "Plating": "24k Matt Antique Gold", "Stone": "Heritage Kundan & Maroon Gemstones", "Occasion": "Bridal", "Care": "Store in padded velvet bridal box"}),
                         1, 1, 1, "Maroon", "Kundan", "Bridal", 10),
                        ("Royal Velvet Ruby Kundan Bridal Set", "Bridal Sets", 5499, 8999, 38, 4.9, 35,
                         "/static/images/hero_banner.jpg",
                         "/static/images/bridal_spotlight.jpg",
                         "Opulent Rajputana style full bridal necklace set with cascading ruby drops, pearl clusters and matching heavy ear cuff jhumkas.",
                         json.dumps({"Material": "Heavy Brass Alloy", "Plating": "Antique Champagne Gold", "Stone": "Ruby & Kundan Glass", "Occasion": "Bridal", "Care": "Keep dry and store safely"}),
                         1, 0, 1, "Maroon", "Kundan", "Bridal", 8),
                        ("Royal Pearl Embellished Clutcher", "Clutchers", 349, 599, 41, 4.6, 21,
                         "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                         "Heavy gold metal hair clutcher encrusted with lustrous faux pearls and shiny zircons.",
                         json.dumps({"Material": "Metal Alloy", "Plating": "Gold Plated", "Stone": "Faux Pearl", "Occasion": "Daily / Festive", "Care": "Handle gently"}),
                         1, 0, 0, "Gold", "Pearl", "Daily", 45),
                        ("Golden Crystal Butterfly Hair Clip", "Clutchers", 299, 499, 40, 4.5, 18,
                         "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                         "Elegant butterfly shape hair pin with crystal rhinestones for hairstyles at parties and weddings.",
                         json.dumps({"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Rhinestone", "Occasion": "Festive / Party", "Care": "Avoid bending"}),
                         0, 1, 0, "Gold", "Alloy", "Festive", 35),
                        ("Handcrafted Silk Satin Pearl Scrunchie", "Scrunchies & Garters", 499, 799, 37, 4.9, 44,
                         "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                         "Premium silk satin hair scrunchie with faux pearl accents and comfortable elastic band.",
                         json.dumps({"Material": "Fabric & Faux Pearls", "Plating": "N/A", "Stone": "Pearl Drops", "Occasion": "Festive / Bridal", "Care": "Store in soft box"}),
                         1, 1, 1, "Gold", "Pearl", "Bridal", 50),
                        ("Antique Gold Floral Hair Garter", "Scrunchies & Garters", 699, 1099, 36, 4.8, 29,
                         "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                         "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                         "Traditional South Indian bun decoration hair garter with golden flower links and ruby accents.",
                         json.dumps({"Material": "Brass", "Plating": "Antique Gold", "Stone": "Ruby CZ", "Occasion": "Bridal / Festive", "Care": "Wipe dry after use"}),
                         0, 0, 1, "Maroon", "Brass", "Bridal", 22)
                    ]
                    cur.executemany('''
                        INSERT INTO products (
                            name, category, price, original_price, discount_percent, rating, review_count,
                            image, hover_image, description, specs, is_best_seller, is_new_arrival,
                            is_bridal, color, material, occasion, stock
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', from_default_products)

                pg.close()
                print("Supabase / PostgreSQL initialized successfully.")
        except Exception as pg_init_err:
            print("PostgreSQL/Supabase init note:", pg_init_err)

    try:
        conn = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, port=MYSQL_PORT, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.close()

        conn = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DB, port=MYSQL_PORT, autocommit=True)
        cursor = conn.cursor()

        # Products
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                category VARCHAR(100) NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                original_price DECIMAL(10,2) NOT NULL,
                discount_percent INT NOT NULL,
                rating DECIMAL(3,2) DEFAULT 4.8,
                review_count INT DEFAULT 12,
                image TEXT NOT NULL,
                hover_image TEXT NOT NULL,
                description TEXT NOT NULL,
                specs TEXT NOT NULL,
                is_best_seller INT DEFAULT 0,
                is_new_arrival INT DEFAULT 0,
                is_bridal INT DEFAULT 0,
                color VARCHAR(50) NOT NULL,
                material VARCHAR(50) NOT NULL,
                occasion VARCHAR(50) NOT NULL,
                stock INT DEFAULT 25
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')

        # Categories
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                image TEXT NOT NULL,
                description TEXT NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')

        # Reviews
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT NOT NULL,
                user_name VARCHAR(100) NOT NULL,
                rating INT NOT NULL,
                comment TEXT NOT NULL,
                date VARCHAR(50) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')

        # Orders
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_code VARCHAR(50) UNIQUE NOT NULL,
                customer_name VARCHAR(100) NOT NULL,
                customer_email VARCHAR(100) NOT NULL,
                customer_phone VARCHAR(50) NOT NULL,
                shipping_address TEXT NOT NULL,
                items_json LONGTEXT NOT NULL,
                subtotal DECIMAL(10,2) NOT NULL,
                tax DECIMAL(10,2) NOT NULL,
                shipping DECIMAL(10,2) NOT NULL,
                discount DECIMAL(10,2) DEFAULT 0,
                total DECIMAL(10,2) NOT NULL,
                payment_method VARCHAR(50) NOT NULL,
                payment_status VARCHAR(50) NOT NULL,
                order_status VARCHAR(50) DEFAULT 'Placed',
                created_at VARCHAR(50) NOT NULL,
                email_notification_sent INT DEFAULT 0,
                whatsapp_notification_sent INT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
        try:
            cursor.execute("SHOW COLUMNS FROM orders LIKE 'email_notification_sent'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE orders ADD COLUMN email_notification_sent INT DEFAULT 0")
            cursor.execute("SHOW COLUMNS FROM orders LIKE 'whatsapp_notification_sent'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE orders ADD COLUMN whatsapp_notification_sent INT DEFAULT 0")
        except Exception as e:
            print("Orders notification columns migration note:", e)

        # Coupons
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS coupons (
                code VARCHAR(50) PRIMARY KEY,
                discount_type VARCHAR(20) NOT NULL,
                discount_value DECIMAL(10,2) NOT NULL,
                min_order DECIMAL(10,2) DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')

        # Customer Users (Email + Password + Google)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(150) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NULL,
                name VARCHAR(100),
                created_at VARCHAR(50) NOT NULL,
                last_login VARCHAR(50) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
        try:
            cursor.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL")
            cursor.execute("SHOW COLUMNS FROM users LIKE 'created_at'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE users ADD COLUMN created_at VARCHAR(50) NULL")
            else:
                cursor.execute("ALTER TABLE users MODIFY COLUMN created_at VARCHAR(50) NULL")
            cursor.execute("SHOW COLUMNS FROM users LIKE 'last_login'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE users ADD COLUMN last_login VARCHAR(50) NULL")
            else:
                cursor.execute("ALTER TABLE users MODIFY COLUMN last_login VARCHAR(50) NULL")
            cursor.execute("SHOW COLUMNS FROM users LIKE 'name'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE users ADD COLUMN name VARCHAR(100) NULL")
            cursor.execute("SHOW COLUMNS FROM users LIKE 'identifier'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE users MODIFY COLUMN identifier VARCHAR(150) NULL")
            cursor.execute("SHOW COLUMNS FROM users LIKE 'phone'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE users MODIFY COLUMN phone VARCHAR(50) NULL")
        except Exception as e:
            print("Users migration note:", e)

        # Password Resets Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(150) NOT NULL,
                token VARCHAR(100) NOT NULL,
                expires_at DATETIME NOT NULL,
                is_used INT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')

        # Category migration Gajra -> Scrunchies & Garters
        try:
            cursor.execute("UPDATE products SET category = 'Scrunchies & Garters' WHERE category = 'Gajra/Garder' OR category LIKE '%Gajra%'")
            cursor.execute("UPDATE categories SET name = 'Scrunchies & Garters', slug = 'scrunchies-garters', description = 'Luxury Satin Silk Scrunchies & Hair Garters' WHERE name = 'Gajra/Garder' OR slug = 'gajra-garder' OR name LIKE '%Gajra%'")
            cursor.execute("UPDATE products SET name = 'Handcrafted Silk Satin Pearl Scrunchie', description = 'Premium silk satin hair scrunchie with faux pearl accents and comfortable elastic band.' WHERE name LIKE '%Gajra%'")
        except Exception as e:
            print("Category migration note:", e)

        cursor.execute("SELECT COUNT(*) FROM categories")
        if cursor.fetchone()[0] == 0:
            categories = [
                ("Necklaces", "necklaces", "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80", "Statement, Kundan & Choker Necklaces"),
                ("Earrings", "earrings", "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80", "Jhumkas, Chandbalis & Studs"),
                ("Pendants", "pendants", "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=600&q=80", "Minimal & Zircon Pendant Sets"),
                ("Bracelets", "bracelets", "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=600&q=80", "Antique Gold Cuffs & Bangles"),
                ("Rings", "rings", "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=600&q=80", "Solitaire & Cocktail Statement Rings"),
                ("Bridal Sets", "bridal-sets", "/static/images/bridal_spotlight.jpg", "Grand Maharani Bridal Kundan Sets"),
                ("Clutchers", "clutchers", "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=600&q=80", "Embellished Hair Accessories & Clutchers"),
                ("Scrunchies & Garters", "scrunchies-garters", "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=600&q=80", "Luxury Satin Silk Scrunchies & Hair Garters")
            ]
            cursor.executemany("INSERT INTO categories (name, slug, image, description) VALUES (%s, %s, %s, %s)", categories)

        cursor.execute("SELECT COUNT(*) FROM coupons")
        if cursor.fetchone()[0] == 0:
            coupons = [
                ("HEENA10", "percentage", 10.0, 499.0),
                ("BRIDAL15", "percentage", 15.0, 1999.0),
                ("FESTIVE200", "flat", 200.0, 999.0),
                ("WELCOME500", "flat", 500.0, 2499.0)
            ]
            cursor.executemany("INSERT INTO coupons (code, discount_type, discount_value, min_order) VALUES (%s, %s, %s, %s)", coupons)

        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            products = [
                ("Royal Emerald Kundan Choker Set", "Necklaces", 1899, 2999, 36, 4.9, 42,
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                 "Exquisite antique gold finish choker necklace studded with vibrant green emerald style Kundan stones and shell pearl drop beads. Comes with matching earrings.",
                 json.dumps({"Material": "Brass Alloy", "Plating": "22k Antique Gold", "Stone": "Kundan & Faux Emerald", "Occasion": "Festive / Wedding", "Care": "Avoid direct spray of perfume or water"}),
                 1, 1, 0, "Green", "Brass", "Festive", 18),

                ("Heritage Temple Gold Necklace", "Necklaces", 2499, 3999, 37, 4.8, 28,
                 "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "Traditional South Indian temple design necklace featuring intricate Goddess motif carving and antique champagne gold polish.",
                 json.dumps({"Material": "High Grade Copper Alloy", "Plating": "Matt Antique Gold", "Stone": "Ruby Red CZ", "Occasion": "Festive / Pooja", "Care": "Store in airtight velvet pouch"}),
                 1, 0, 0, "Gold", "Alloy", "Festive", 12),

                ("Maharani Oversized Chandbali", "Earrings", 1199, 1799, 33, 4.8, 31,
                 "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                 "Crescent-shaped Chandbali earrings adorned with Kundan work and maroon bead droppings. Perfect pair for ethnic silk sarees.",
                 json.dumps({"Material": "Brass", "Plating": "Gold Plated", "Stone": "Kundan & Maroon Beads", "Occasion": "Festive / Wedding", "Care": "Store in soft cotton pouch"}),
                 1, 1, 0, "Maroon", "Kundan", "Festive", 15),

                ("Rose Gold Zircon Huggie Studs", "Earrings", 499, 799, 37, 4.6, 22,
                 "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                 "Sparkling rose gold polished zircon stud earrings designed for office wear and everyday casual sophistication.",
                 json.dumps({"Material": "Copper", "Plating": "Rose Gold", "Stone": "American Diamond", "Occasion": "Daily Wear", "Care": "Clean gently with dry cloth"}),
                 0, 0, 0, "Rose Gold", "Zircon", "Daily", 30),

                ("Royal Solitaire Zircon Pendant Set", "Pendants", 799, 1299, 38, 4.9, 39,
                 "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "Classic heart solitaire cubic zirconia pendant chain set in 18k champagne gold plating with matching stud earrings.",
                 json.dumps({"Material": "Brass", "Plating": "18k Champagne Gold", "Stone": "CZ Diamond", "Occasion": "Daily / Gifting", "Care": "Keep in airtight box"}),
                 1, 0, 0, "Gold", "Zircon", "Daily", 20),

                ("Floral Enamel Kundan Pendant", "Pendants", 699, 1099, 36, 4.7, 18,
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                 "Hand painted Meenakari enamel floral pendant with delicate Kundan center and gold beaded chain.",
                 json.dumps({"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Meenakari & Kundan", "Occasion": "Festive", "Care": "Avoid chemical exposure"}),
                 0, 1, 0, "Maroon", "Alloy", "Festive", 16),

                ("Antique Gold Royal Bangle Set", "Bracelets", 1299, 1999, 35, 4.8, 27,
                 "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                 "Set of 4 intricate antique gold bangles embossed with floral motifs and ruby CZ accents.",
                 json.dumps({"Material": "Brass", "Plating": "Antique Gold", "Stone": "CZ Stones", "Occasion": "Festive / Wedding", "Care": "Wipe after wear"}),
                 1, 0, 0, "Gold", "Brass", "Festive", 22),

                ("Rose Gold CZ Crystal Cuff", "Bracelets", 899, 1399, 35, 4.9, 14,
                 "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                 "Flexible openable wrist cuff with pavé set AAA cubic zirconia stones in radiant rose gold shine.",
                 json.dumps({"Material": "Alloy", "Plating": "Rose Gold", "Stone": "Cubic Zirconia", "Occasion": "Daily / Party", "Care": "Do not submerge in water"}),
                 0, 1, 0, "Rose Gold", "Zircon", "Daily", 19),

                ("Solitaire Crown Adjustable Ring", "Rings", 399, 699, 42, 4.8, 64,
                 "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                 "Stunning crown design solitaire ring with adjustable band, suitable for all finger sizes.",
                 json.dumps({"Material": "Brass", "Plating": "Rhodium Gold", "Stone": "American Diamond", "Occasion": "Daily / Gifting", "Care": "Keep dry"}),
                 1, 1, 0, "Silver", "Zircon", "Daily", 50),

                ("Traditional Kundan Cocktail Ring", "Rings", 599, 999, 40, 4.7, 33,
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                 "Statement oversized circular Kundan ring with pearl cluster border and adjustable ring base.",
                 json.dumps({"Material": "Alloy", "Plating": "Antique Gold", "Stone": "Kundan & Pearls", "Occasion": "Festive / Wedding", "Care": "Store in soft box"}),
                 0, 0, 0, "Gold", "Kundan", "Festive", 28),

                ("Maharani Heritage Kundan Bridal Set", "Bridal Sets", 4999, 7999, 37, 5.0, 48,
                 "/static/images/bridal_spotlight.jpg",
                 "/static/images/hero_banner.jpg",
                 "Complete 7-Piece Luxury Royal Bridal Jewellery Set: Heavy Choker, Long Haar Necklace, Matching Chandbalis, Maang Tikka, Hathphool Bangles, and Nose Ring in 24k Gold Polish & Maroon Gemstones.",
                 json.dumps({"Material": "Premium Brass Alloy", "Plating": "24k Matt Antique Gold", "Stone": "Heritage Kundan & Maroon Gemstones", "Occasion": "Bridal", "Care": "Store in padded velvet bridal box"}),
                 1, 1, 1, "Maroon", "Kundan", "Bridal", 10),

                ("Royal Velvet Ruby Kundan Bridal Set", "Bridal Sets", 5499, 8999, 38, 4.9, 35,
                 "/static/images/hero_banner.jpg",
                 "/static/images/bridal_spotlight.jpg",
                 "Opulent Rajputana style full bridal necklace set with cascading ruby drops, pearl clusters and matching heavy ear cuff jhumkas.",
                 json.dumps({"Material": "Heavy Brass Alloy", "Plating": "Antique Champagne Gold", "Stone": "Ruby & Kundan Glass", "Occasion": "Bridal", "Care": "Keep dry and store safely"}),
                 1, 0, 1, "Maroon", "Kundan", "Bridal", 8),

                ("Royal Pearl Embellished Clutcher", "Clutchers", 349, 599, 41, 4.6, 21,
                 "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80",
                 "Heavy gold metal hair clutcher encrusted with lustrous faux pearls and shiny zircons.",
                 json.dumps({"Material": "Metal Alloy", "Plating": "Gold Plated", "Stone": "Faux Pearl", "Occasion": "Daily / Festive", "Care": "Handle gently"}),
                 1, 0, 0, "Gold", "Pearl", "Daily", 45),

                ("Golden Crystal Butterfly Hair Clip", "Clutchers", 299, 499, 40, 4.5, 18,
                 "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",
                 "Elegant butterfly shape hair pin with crystal rhinestones for hairstyles at parties and weddings.",
                 json.dumps({"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Rhinestone", "Occasion": "Festive / Party", "Care": "Avoid bending"}),
                 0, 1, 0, "Gold", "Alloy", "Festive", 35),

                ("Handcrafted Silk Satin Pearl Scrunchie", "Scrunchies & Garters", 499, 799, 37, 4.9, 44,
                 "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                 "Premium silk satin hair scrunchie with faux pearl accents and comfortable elastic band.",
                 json.dumps({"Material": "Fabric & Faux Pearls", "Plating": "N/A", "Stone": "Pearl Drops", "Occasion": "Festive / Bridal", "Care": "Store in soft box"}),
                 1, 1, 1, "Gold", "Pearl", "Bridal", 50),

                ("Antique Gold Floral Hair Garter", "Scrunchies & Garters", 699, 1099, 36, 4.8, 29,
                 "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                 "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80",
                 "Traditional South Indian bun decoration hair garter with golden flower links and ruby accents.",
                 json.dumps({"Material": "Brass", "Plating": "Antique Gold", "Stone": "Ruby CZ", "Occasion": "Bridal / Festive", "Care": "Wipe dry after use"}),
                 0, 0, 1, "Maroon", "Brass", "Bridal", 22)
            ]
            cursor.executemany('''
                INSERT INTO products (
                    name, category, price, original_price, discount_percent, rating, review_count,
                    image, hover_image, description, specs, is_best_seller, is_new_arrival,
                    is_bridal, color, material, occasion, stock
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', products)

        conn.close()

    except Exception as e:
        print("MySQL init note:", e)

    # Always ensure SQLite fallback tables exist and are up to date
    try:
        s_conn = sqlite3.connect(SQLITE_DB)
        s_cursor = s_conn.cursor()

        # Users table
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                name TEXT,
                created_at TEXT,
                last_login TEXT
            )
        ''')

        # Password resets table
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                token TEXT NOT NULL,
                expires_at DATETIME NOT NULL,
                is_used INTEGER DEFAULT 0
            )
        ''')

        # Orders table notification columns
        cols = [col[1] for col in s_cursor.execute("PRAGMA table_info(orders)").fetchall()]
        if cols:
            if 'email_notification_sent' not in cols:
                s_cursor.execute("ALTER TABLE orders ADD COLUMN email_notification_sent INTEGER DEFAULT 0")
            if 'whatsapp_notification_sent' not in cols:
                s_cursor.execute("ALTER TABLE orders ADD COLUMN whatsapp_notification_sent INTEGER DEFAULT 0")

        # Migrate Gajra -> Scrunchies & Garters in SQLite
        s_cursor.execute("UPDATE products SET category = 'Scrunchies & Garters' WHERE category = 'Gajra/Garder' OR category LIKE '%Gajra%'")
        s_cursor.execute("UPDATE categories SET name = 'Scrunchies & Garters', slug = 'scrunchies-garters', description = 'Luxury Satin Silk Scrunchies & Hair Garters' WHERE name = 'Gajra/Garder' OR slug = 'gajra-garder' OR name LIKE '%Gajra%'")
        s_cursor.execute("UPDATE products SET name = 'Handcrafted Silk Satin Pearl Scrunchie', description = 'Premium silk satin hair scrunchie with faux pearl accents and comfortable elastic band.' WHERE name LIKE '%Gajra%'")

        s_conn.commit()
        s_conn.close()
    except Exception as se:
        print("SQLite init note:", se)

# Initialize DB
init_db()

# --- CUSTOMER ROUTES ---
@app.route('/')
def home():
    return render_template('index.html', google_client_id=GOOGLE_CLIENT_ID)

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    data = request.json or {}
    credential = data.get('credential')
    if not credential:
        return jsonify({'success': False, 'message': 'Google authentication credential is required.'}), 400

    try:
        req = urllib.request.Request(f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}")
        with urllib.request.urlopen(req) as resp:
            info = json.loads(resp.read().decode('utf-8'))
        
        email = (info.get('email') or '').strip().lower()
        name = info.get('name') or email.split('@')[0].capitalize()
        
        if not email:
            return jsonify({'success': False, 'message': 'Could not verify email from Google account.'}), 400

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db = get_db()

        if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
            cursor = db.cursor()
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            u = cursor.fetchone()
            if not u:
                cursor.execute("INSERT INTO users (email, name, created_at, last_login) VALUES (%s, %s, %s, %s)",
                               (email, name, now_str, now_str))
            else:
                cursor.execute("UPDATE users SET name = %s, last_login = %s WHERE email = %s", (name, now_str, email))
        else:
            cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
            u = cursor.fetchone()
            if not u:
                db.execute("INSERT INTO users (email, name, created_at, last_login) VALUES (?, ?, ?, ?)",
                           (email, name, now_str, now_str))
            else:
                db.execute("UPDATE users SET name = ?, last_login = ? WHERE email = ?", (name, now_str, email))
            db.commit()

        session['user_email'] = email
        session['user_name'] = name

        return jsonify({
            'success': True,
            'user': {
                'email': email,
                'name': name,
                'is_logged_in': True
            },
            'message': f"Welcome {name}! Signed in with Google."
        })
    except Exception as e:
        print("Google Auth Token Verification Error:", e)
        return jsonify({'success': False, 'message': f'Google Sign-In failed: {str(e)}'}), 400

# --- CUSTOMER EMAIL & PASSWORD AUTHENTICATION (NO OTP REQUIRED) ---

@app.route('/api/auth/register', methods=['POST'])
def register_customer():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()
    name = (data.get('name') or '').strip()

    if not email or '@' not in email or '.' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    if not password or len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters long.'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Password and Confirm Password do not match.'}), 400

    if not name:
        name = email.split('@')[0].capitalize()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p_hash = generate_password_hash(password)
    db = get_db()

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        u = cursor.fetchone()
        if u and u.get('password_hash'):
            return jsonify({'success': False, 'message': 'An account with this email already exists. Please log in.'}), 400
        elif u:
            cursor.execute("UPDATE users SET password_hash = %s, name = %s, last_login = %s WHERE email = %s",
                           (p_hash, name, now_str, email))
        else:
            cursor.execute("INSERT INTO users (email, password_hash, name, created_at, last_login) VALUES (%s, %s, %s, %s, %s)",
                           (email, p_hash, name, now_str, now_str))
    else:
        cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        r = cursor.fetchone()
        u = dict(r) if r else None
        if u and u.get('password_hash'):
            return jsonify({'success': False, 'message': 'An account with this email already exists. Please log in.'}), 400
        elif u:
            db.execute("UPDATE users SET password_hash = ?, name = ?, last_login = ? WHERE email = ?",
                       (p_hash, name, now_str, email))
        else:
            db.execute("INSERT INTO users (email, password_hash, name, created_at, last_login) VALUES (?, ?, ?, ?, ?)",
                       (email, p_hash, name, now_str, now_str))
        db.commit()

    # Automatically log customer in after successful registration (no OTP step)
    session['user_email'] = email
    session['user_name'] = name

    return jsonify({
        'success': True,
        'user': {
            'email': email,
            'name': name,
            'is_logged_in': True
        },
        'message': f"Account created successfully! Welcome, {name}."
    })

@app.route('/api/auth/login', methods=['POST'])
def login_customer():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()

    if not email or not password:
        return jsonify({'success': False, 'message': 'Please enter both email and password.'}), 400

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        u = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        r = cursor.fetchone()
        u = dict(r) if r else None

    if not u or not u.get('password_hash'):
        return jsonify({'success': False, 'message': 'Invalid email or password. If you signed up with Google, please use Continue with Google.'}), 401

    if not check_password_hash(u['password_hash'], password):
        return jsonify({'success': False, 'message': 'Invalid email or password.'}), 401

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_name = u.get('name') or email.split('@')[0].capitalize()

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor.execute("UPDATE users SET last_login = %s WHERE email = %s", (now_str, email))
    else:
        db.execute("UPDATE users SET last_login = ? WHERE email = ?", (now_str, email))
        db.commit()

    session['user_email'] = email
    session['user_name'] = user_name

    return jsonify({
        'success': True,
        'user': {
            'email': email,
            'name': user_name,
            'is_logged_in': True
        },
        'message': f"Welcome back, {user_name}!"
    })

def send_password_reset_email(to_email, reset_token):
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASSWORD', '')

    reset_link = f"http://127.0.0.1:5000/?reset_token={reset_token}"
    body = f"Hello,\n\nYou requested a password reset for your Heena Imitation Jewellery account.\n\nPlease click the link below to reset your password:\n{reset_link}\n\nThis link is valid for 30 minutes. If you did not request this, please ignore this email."
    
    msg = MIMEText(body)
    msg['Subject'] = 'Password Reset Request — Heena Imitation Jewellery'
    msg['From'] = f"Heena Imitation Jewellery <{smtp_user or 'noreply@heenajewellery.com'}>"
    msg['To'] = to_email

    if smtp_user and smtp_pass:
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(msg['From'], [to_email], msg.as_string())
            return True
        except Exception as e:
            print("Password Reset SMTP Error:", e)
            return False
    else:
        print(f"==================================================")
        print(f"[PASSWORD RESET EMAIL] TO: {to_email}")
        print(f"[PASSWORD RESET EMAIL] LINK: {reset_link}")
        print(f"==================================================")
        return True

@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()

    if not email or '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        u = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        r = cursor.fetchone()
        u = dict(r) if r else None

    if u:
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
            cursor.execute("INSERT INTO password_resets (email, token, expires_at, is_used) VALUES (%s, %s, %s, 0)",
                           (email, token, expires_at))
        else:
            db.execute("INSERT INTO password_resets (email, token, expires_at, is_used) VALUES (?, ?, ?, 0)",
                       (email, token, expires_at))
            db.commit()
        send_password_reset_email(email, token)

    return jsonify({
        'success': True,
        'message': 'If an account exists for this email, a password reset link has been sent.'
    })

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.json or {}
    token = (data.get('token') or '').strip()
    new_password = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not token:
        return jsonify({'success': False, 'message': 'Invalid password reset token.'}), 400

    if not new_password or len(new_password) < 6:
        return jsonify({'success': False, 'message': 'New password must be at least 6 characters.'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match.'}), 400

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM password_resets WHERE token = %s AND is_used = 0 ORDER BY id DESC LIMIT 1", (token,))
        record = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM password_resets WHERE token = ? AND is_used = 0 ORDER BY id DESC LIMIT 1", (token,))
        r = cursor.fetchone()
        record = dict(r) if r else None

    if not record:
        return jsonify({'success': False, 'message': 'Invalid or expired password reset link.'}), 400

    expires_at = datetime.strptime(str(record['expires_at']), '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expires_at:
        return jsonify({'success': False, 'message': 'Password reset link has expired. Please request a new one.'}), 400

    email = record['email']
    p_hash = generate_password_hash(new_password)

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (p_hash, email))
        cursor.execute("UPDATE password_resets SET is_used = 1 WHERE id = %s", (record['id'],))
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE email = ?", (p_hash, email))
        db.execute("UPDATE password_resets SET is_used = 1 WHERE id = ?", (record['id'],))
        db.commit()

    return jsonify({'success': True, 'message': 'Password reset successfully! Please log in with your new password.'})

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    if session.get('user_email'):
        return jsonify({
            'success': True,
            'user': {
                'email': session['user_email'],
                'name': session.get('user_name', session['user_email'].split('@')[0]),
                'is_logged_in': True
            }
        })
    return jsonify({'success': False, 'user': None})

@app.route('/api/auth/logout', methods=['POST'])
def customer_logout():
    session.pop('user_email', None)
    session.pop('user_name', None)
    return jsonify({'success': True, 'message': 'Customer logged out successfully.'})

# --- COMPLETELY SEPARATE ADMIN AUTHENTICATION & DASHBOARD ---

@app.route('/admin')
def admin_root():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard_page'))
    return redirect(url_for('admin_login_page'))

@app.route('/admin/login', methods=['GET'])
def admin_login_page():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard_page'))
    return render_template('admin_login.html', google_client_id=GOOGLE_CLIENT_ID)

@app.route('/admin/api/login', methods=['POST'])
def admin_login_api():
    data = request.json or {}
    admin_id = (data.get('admin_id') or '').strip()
    password = (data.get('password') or '').strip()

    # Server-side validation against environment secrets (case-insensitive for Admin ID)
    if admin_id.lower() == ADMIN_ID.lower() and password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        session['admin_id'] = ADMIN_ID
        return jsonify({'success': True, 'message': 'Admin authenticated successfully.'})
    
    return jsonify({'success': False, 'message': 'Invalid Admin ID or Password.'}), 401

@app.route('/admin/dashboard', methods=['GET'])
@admin_required
def admin_dashboard_page():
    return render_template('admin_dashboard.html', admin_id=session.get('admin_id', ADMIN_ID))

@app.route('/admin/api/logout', methods=['POST'])
def admin_logout_api():
    session.pop('admin_logged_in', None)
    session.pop('admin_id', None)
    return jsonify({'success': True, 'message': 'Admin logged out successfully.'})

# --- PRODUCTS & CATALOG APIS ---

@app.route('/api/products', methods=['GET'])
def get_products():
    db = get_db()
    category = request.args.get('category')
    occasion = request.args.get('occasion')
    color = request.args.get('color')
    material = request.args.get('material')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    search = request.args.get('search')
    sort = request.args.get('sort', 'popularity')
    best_seller = request.args.get('best_seller')
    new_arrival = request.args.get('new_arrival')
    bridal = request.args.get('bridal')

    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if category and category != 'all':
        query += " AND (LOWER(category) = LOWER(%s) OR LOWER(category) = LOWER(%s))" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND (LOWER(category) = LOWER(?) OR LOWER(category) = LOWER(?))"
        params.extend([category, category.replace('-', ' ')])
    if occasion and occasion != 'all':
        query += " AND LOWER(occasion) = LOWER(%s)" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND LOWER(occasion) = LOWER(?)"
        params.append(occasion)
    if color and color != 'all':
        query += " AND LOWER(color) = LOWER(%s)" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND LOWER(color) = LOWER(?)"
        params.append(color)
    if material and material != 'all':
        query += " AND LOWER(material) = LOWER(%s)" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND LOWER(material) = LOWER(?)"
        params.append(material)
    if min_price is not None:
        query += " AND price >= %s" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND price >= ?"
        params.append(min_price)
    if max_price is not None:
        query += " AND price <= %s" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND price <= ?"
        params.append(max_price)
    if search:
        query += " AND (name LIKE %s OR description LIKE %s OR category LIKE %s)" if getattr(g, 'db_type', '') in ('mysql', 'postgres') else " AND (name LIKE ? OR description LIKE ? OR category LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
    if best_seller:
        query += " AND is_best_seller = 1"
    if new_arrival:
        query += " AND is_new_arrival = 1"
    if bridal:
        query += " AND is_bridal = 1"

    if sort == 'price-low':
        query += " ORDER BY price ASC"
    elif sort == 'price-high':
        query += " ORDER BY price DESC"
    elif sort == 'newest':
        query += " ORDER BY is_new_arrival DESC, id DESC"
    elif sort == 'rating':
        query += " ORDER BY rating DESC"
    else:
        query += " ORDER BY is_best_seller DESC, rating DESC"

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
    else:
        cursor = db.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]

    products_list = []
    for r in rows:
        item = dict(r)
        item['price'] = float(item['price'])
        item['original_price'] = float(item['original_price'])
        item['rating'] = float(item['rating'])
        try:
            item['specs'] = json.loads(item['specs']) if item['specs'] else {}
        except Exception:
            item['specs'] = {}
        products_list.append(item)

    return jsonify({'success': True, 'count': len(products_list), 'products': products_list})

@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product_detail(product_id):
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        p = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        r = cursor.fetchone()
        p = dict(r) if r else None

    if not p:
        return jsonify({'success': False, 'message': 'Product not found'}), 404

    product = dict(p)
    product['price'] = float(product['price'])
    product['original_price'] = float(product['original_price'])
    try:
        product['specs'] = json.loads(product['specs']) if product['specs'] else {}
    except Exception:
        product['specs'] = {}

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor.execute("SELECT * FROM reviews WHERE product_id = %s ORDER BY id DESC", (product_id,))
        reviews = cursor.fetchall()
        cursor.execute("SELECT * FROM products WHERE category = %s AND id != %s LIMIT 4", (product['category'], product_id))
        rel_rows = cursor.fetchall()
    else:
        cursor = db.execute("SELECT * FROM reviews WHERE product_id = ? ORDER BY id DESC", (product_id,))
        reviews = [dict(r) for r in cursor.fetchall()]
        cursor = db.execute("SELECT * FROM products WHERE category = ? AND id != ? LIMIT 4", (product['category'], product_id))
        rel_rows = [dict(r) for r in cursor.fetchall()]

    related = []
    for r in rel_rows:
        item = dict(r)
        item['price'] = float(item['price'])
        item['original_price'] = float(item['original_price'])
        related.append(item)

    return jsonify({'success': True, 'product': product, 'reviews': reviews, 'related': related})

# --- PROTECTED ADMIN API ENDPOINTS ---

@app.route('/api/admin/upload-image', methods=['POST'])
@admin_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        saved_filename = timestamp + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        file.save(filepath)
        
        image_url = f"/static/uploads/{saved_filename}"
        return jsonify({'success': True, 'image_url': image_url})

    return jsonify({'success': False, 'message': 'Invalid image format.'}), 400

@app.route('/api/products', methods=['POST'])
@admin_required
def add_product():
    data = request.json or {}
    name = data.get('name')
    category = data.get('category')
    price = float(data.get('price', 0))
    original_price = float(data.get('original_price', price * 1.4))
    discount_percent = int(((original_price - price) / original_price) * 100) if original_price > 0 else 0
    image = data.get('image', 'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80')
    hover_image = data.get('hover_image', image)
    description = data.get('description', '')
    specs = json.dumps(data.get('specs', {"Material": "Alloy", "Occasion": "Festive"}))
    color = data.get('color', 'Gold')
    material = data.get('material', 'Brass')
    occasion = data.get('occasion', 'Festive')
    stock = int(data.get('stock', 25))
    is_bridal = 1 if category == 'Bridal Sets' or data.get('is_bridal') else 0

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO products (
                name, category, price, original_price, discount_percent, rating, review_count,
                image, hover_image, description, specs, is_best_seller, is_new_arrival,
                is_bridal, color, material, occasion, stock
            ) VALUES (%s, %s, %s, %s, %s, 5.0, 1, %s, %s, %s, %s, 1, 1, %s, %s, %s, %s, %s)
        ''', (name, category, price, original_price, discount_percent, image, hover_image, description, specs, is_bridal, color, material, occasion, stock))
        last_id = cursor.lastrowid
    else:
        cursor = db.execute('''
            INSERT INTO products (
                name, category, price, original_price, discount_percent, rating, review_count,
                image, hover_image, description, specs, is_best_seller, is_new_arrival,
                is_bridal, color, material, occasion, stock
            ) VALUES (?, ?, ?, ?, ?, 5.0, 1, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
        ''', (name, category, price, original_price, discount_percent, image, hover_image, description, specs, is_bridal, color, material, occasion, stock))
        db.commit()
        last_id = cursor.lastrowid

    return jsonify({'success': True, 'product_id': last_id, 'message': f"Product '{name}' added successfully!"})

@app.route('/api/products/<int:product_id>/stock', methods=['PUT'])
@admin_required
def update_product_stock(product_id):
    data = request.json or {}
    new_stock = int(data.get('stock', 0))

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("UPDATE products SET stock = %s WHERE id = %s", (new_stock, product_id))
    else:
        db.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product_id))
        db.commit()

    return jsonify({'success': True, 'message': f'Stock updated to {new_stock} pcs'})

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
    else:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        db.commit()
    return jsonify({'success': True, 'message': 'Product deleted successfully!'})

@app.route('/api/categories', methods=['GET'])
def get_categories():
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM categories ORDER BY id ASC")
        categories = cursor.fetchall()
    else:
        cursor = db.execute("SELECT * FROM categories ORDER BY id ASC")
        categories = [dict(r) for r in cursor.fetchall()]
    return jsonify({'success': True, 'categories': categories})

@app.route('/api/coupons/validate', methods=['POST'])
def validate_coupon():
    data = request.json or {}
    code = (data.get('code') or '').strip().upper()
    subtotal = float(data.get('subtotal', 0))

    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM coupons WHERE UPPER(code) = %s", (code,))
        c = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM coupons WHERE UPPER(code) = ?", (code,))
        r = cursor.fetchone()
        c = dict(r) if r else None

    if not c:
        return jsonify({'success': False, 'message': 'Invalid coupon code'}), 400
    
    coupon = dict(c)
    min_ord = float(coupon['min_order'])
    if subtotal < min_ord:
        return jsonify({'success': False, 'message': f"Minimum order amount ₹{min_ord} required for code {code}"}), 400

    disc_val = float(coupon['discount_value'])
    discount_amount = (subtotal * disc_val) / 100.0 if coupon['discount_type'] == 'percentage' else disc_val

    return jsonify({
        'success': True,
        'code': code,
        'discount_amount': round(discount_amount, 2),
        'message': f"Coupon '{code}' applied successfully!"
    })

def send_admin_order_email(order):
    order_id = order.get('order_id')
    db = get_db()
    if order_id:
        if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
            cursor = db.cursor()
            cursor.execute("SELECT email_notification_sent FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
        else:
            cursor = db.execute("SELECT email_notification_sent FROM orders WHERE id = ?", (order_id,))
            r = cursor.fetchone()
            row = dict(r) if r else None
        
        if row and row.get('email_notification_sent') == 1:
            print(f"[DUPLICATE PREVENTED] Email notification already sent for order #{order.get('order_code')}")
            return True

    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = (os.environ.get('SMTP_USER') or '').strip() or ADMIN_EMAIL
    smtp_pass = (os.environ.get('SMTP_PASSWORD') or '').strip()

    items = order.get('items', [])
    items_rows_text = []
    items_rows_html = []
    for item in items:
        name = item.get('name', 'Product')
        qty = item.get('qty', 1)
        price = float(item.get('price', 0))
        sub = price * qty
        items_rows_text.append(f"• {name} x {qty} — Rs. {price:,.2f} (Subtotal: Rs. {sub:,.2f})")
        items_rows_html.append(f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{name}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{qty}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">Rs. {price:,.2f}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right; font-weight: bold; color: #b8860b;">Rs. {sub:,.2f}</td>
            </tr>
        """)

    items_list_str = "\n".join(items_rows_text)
    items_table_html = "".join(items_rows_html)

    body_text = f"""NEW ORDER RECEIVED — HEENA IMITATION JEWELLERS

Order ID: #{order.get('order_code')}
Date: {order.get('created_at')}

--- CUSTOMER DETAILS ---
Name: {order.get('customer_name')}
Email: {order.get('customer_email')}
Phone: {order.get('customer_phone')}
Shipping Address: {order.get('shipping_address')}

--- ORDER ITEMS ---
{items_list_str}

Subtotal: Rs. {order.get('subtotal')}
Shipping: Rs. {order.get('shipping')}
Discount: Rs. {order.get('discount')}
TOTAL: Rs. {order.get('total')}

--- PAYMENT DETAILS ---
Payment Method: {order.get('payment_method')}
Payment Status: {order.get('payment_status')}
"""

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background-color: #faf8f5; margin: 0; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d4af37; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06);">
            <div style="background: linear-gradient(135deg, #1f1a17, #2c241e); color: #d4af37; padding: 22px; text-align: center;">
                <h1 style="margin: 0; font-size: 22px; letter-spacing: 2px;">HEENA IMITATION JEWELLERS</h1>
                <p style="margin: 6px 0 0 0; color: #f0e6d2; font-size: 14px;">🔔 New Order Received</p>
            </div>
            
            <div style="padding: 22px;">
                <div style="background: #fdfaf3; border-left: 4px solid #d4af37; padding: 12px 16px; margin-bottom: 20px;">
                    <strong style="font-size: 16px; color: #1f1a17;">Order #{order.get('order_code')}</strong><br>
                    <span style="color: #666; font-size: 13px;">Placed on: {order.get('created_at')}</span>
                </div>

                <h3 style="color: #1f1a17; border-bottom: 2px solid #f0e6d2; padding-bottom: 6px; margin-top: 18px; font-size: 15px;">Customer Details</h3>
                <p style="margin: 4px 0; font-size: 14px;"><strong>Name:</strong> {order.get('customer_name')}</p>
                <p style="margin: 4px 0; font-size: 14px;"><strong>Email:</strong> {order.get('customer_email')}</p>
                <p style="margin: 4px 0; font-size: 14px;"><strong>Phone:</strong> {order.get('customer_phone')}</p>
                <p style="margin: 4px 0; font-size: 14px;"><strong>Delivery Address:</strong> {order.get('shipping_address')}</p>

                <h3 style="color: #1f1a17; border-bottom: 2px solid #f0e6d2; padding-bottom: 6px; margin-top: 22px; font-size: 15px;">Order Items</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 15px;">
                    <thead>
                        <tr style="background: #fdfaf3; color: #5a4b41;">
                            <th style="padding: 8px 10px; text-align: left;">Item</th>
                            <th style="padding: 8px 10px; text-align: center;">Qty</th>
                            <th style="padding: 8px 10px; text-align: right;">Price</th>
                            <th style="padding: 8px 10px; text-align: right;">Subtotal</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_table_html}
                    </tbody>
                </table>

                <div style="text-align: right; font-size: 14px; line-height: 1.8; border-top: 2px solid #f0e6d2; padding-top: 10px;">
                    <div>Subtotal: Rs. {order.get('subtotal')}</div>
                    <div>Shipping: Rs. {order.get('shipping')}</div>
                    <div>Discount: -Rs. {order.get('discount')}</div>
                    <div style="font-size: 18px; font-weight: bold; color: #b8860b; margin-top: 4px;">Total Amount: Rs. {order.get('total')}</div>
                </div>

                <div style="margin-top: 18px; padding: 12px; background: #fdfaf3; border-radius: 4px; font-size: 13px;">
                    <strong>Payment Method:</strong> {order.get('payment_method')}<br>
                    <strong>Payment Status:</strong> <span style="color: {'#28a745' if 'Paid' in str(order.get('payment_status')) else '#e67e22'}; font-weight: bold;">{order.get('payment_status')}</span>
                </div>
            </div>

            <div style="background: #f5f2eb; color: #888; padding: 12px; text-align: center; font-size: 12px; border-top: 1px solid #e8e2d5;">
                Heena Imitation Jewellery Order Management System
            </div>
        </div>
    </body>
    </html>
    """

    subject = f"🔔 New Order #{order.get('order_code')} — Rs. {order.get('total')} — Heena Imitation Jewellery"
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"Heena Orders <{smtp_user}>"
    msg['To'] = ADMIN_EMAIL
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    sent_success = False
    if smtp_user and smtp_pass:
        # Try TLS (587) first with timeout
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                server.starttls()
            with server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [ADMIN_EMAIL], msg.as_string())
            print(f"[ADMIN ORDER EMAIL SENT] to {ADMIN_EMAIL} for Order #{order.get('order_code')}")
            sent_success = True
        except Exception as e1:
            # Fallback to SSL (port 465) if TLS failed
            try:
                with smtplib.SMTP_SSL(smtp_server, 465, timeout=10) as ssl_server:
                    ssl_server.login(smtp_user, smtp_pass)
                    ssl_server.sendmail(smtp_user, [ADMIN_EMAIL], msg.as_string())
                print(f"[ADMIN ORDER EMAIL SENT (SSL 465)] to {ADMIN_EMAIL} for Order #{order.get('order_code')}")
                sent_success = True
            except Exception as e2:
                print(f"Admin Order Email SMTP Error: TLS={e1}, SSL={e2}")
                sent_success = False
    else:
        print(f"==================================================")
        print(f"[ADMIN ORDER EMAIL NOTIFICATION] TO: {ADMIN_EMAIL}")
        print(f"SUBJECT: {subject}")
        print(body_text)
        print(f"==================================================")
        sent_success = True

    if sent_success and order_id:
        try:
            if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
                cursor = db.cursor()
                cursor.execute("UPDATE orders SET email_notification_sent = 1 WHERE id = %s", (order_id,))
            else:
                db.execute("UPDATE orders SET email_notification_sent = 1 WHERE id = ?", (order_id,))
                db.commit()
        except Exception as e:
            print("Error updating email_notification_sent:", e)

    return sent_success


def send_admin_order_whatsapp(order):
    """WhatsApp order alerts removed as requested. Email notifications used exclusively."""
    return True


@app.route('/api/orders', methods=['POST'])
def create_order():
    if not session.get('user_email'):
        return jsonify({'success': False, 'message': 'Please log in to place an order.'}), 401

    data = request.json or {}
    items = data.get('items', [])
    customer = data.get('customer', {})
    subtotal = float(data.get('subtotal', 0))
    discount = float(data.get('discount', 0))
    tax = round((subtotal - discount) * 0.03, 2)
    shipping = 0 if subtotal >= 999 else 99
    total = round(subtotal - discount + tax + shipping, 2)
    payment_method = data.get('payment_method', 'Razorpay / UPI')
    is_cod = 'COD' in payment_method.upper() or 'CASH ON DELIVERY' in payment_method.upper()
    payment_status = 'Pending (COD)' if is_cod else 'Paid'
    
    order_code = f"HJM-{secrets.randbelow(90000) + 10000}"
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    customer_name = customer.get('name', session.get('user_name', 'Customer'))
    customer_email = session['user_email']
    customer_phone = customer.get('phone', '9777166165')
    shipping_address = f"{customer.get('address', '')}, {customer.get('city', '')}, {customer.get('state', '')} - {customer.get('pincode', '')}"

    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO orders (
                order_code, customer_name, customer_email, customer_phone,
                shipping_address, items_json, subtotal, tax, shipping, discount,
                total, payment_method, payment_status, order_status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Placed', %s)
        ''', (
            order_code, customer_name, customer_email, customer_phone,
            shipping_address, json.dumps(items), subtotal, tax, shipping, discount,
            total, payment_method, payment_status, created_at
        ))
        last_id = cursor.lastrowid
        for item in items:
            cursor.execute("UPDATE products SET stock = GREATEST(0, stock - %s) WHERE id = %s", (item.get('qty', 1), item.get('id')))
    else:
        cursor = db.execute('''
            INSERT INTO orders (
                order_code, customer_name, customer_email, customer_phone,
                shipping_address, items_json, subtotal, tax, shipping, discount,
                total, payment_method, payment_status, order_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Placed', ?)
        ''', (
            order_code, customer_name, customer_email, customer_phone,
            shipping_address, json.dumps(items), subtotal, tax, shipping, discount,
            total, payment_method, payment_status, created_at
        ))
        db.commit()
        last_id = cursor.lastrowid

    order_dict = {
        'order_id': last_id,
        'order_code': order_code,
        'customer_name': customer_name,
        'customer_email': customer_email,
        'customer_phone': customer_phone,
        'shipping_address': shipping_address,
        'items': items,
        'subtotal': subtotal,
        'discount': discount,
        'tax': tax,
        'shipping': shipping,
        'total': total,
        'payment_method': payment_method,
        'payment_status': payment_status,
        'order_status': 'Placed',
        'created_at': created_at
    }

    # Trigger admin email notification for EVERY order
    send_admin_order_email(order_dict)

    return jsonify({
        'success': True,
        'order_id': last_id,
        'order_code': order_code,
        'total': total,
        'payment_status': payment_status,
        'message': 'Order placed successfully!'
    })

@app.route('/api/orders', methods=['GET'])
def get_orders():
    email = session.get('user_email')
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        if session.get('admin_logged_in'):
            cursor.execute("SELECT * FROM orders ORDER BY id DESC")
        elif email:
            cursor.execute("SELECT * FROM orders WHERE customer_email = %s ORDER BY id DESC", (email,))
        else:
            return jsonify({'success': True, 'orders': []})
        rows = cursor.fetchall()
    else:
        if session.get('admin_logged_in'):
            cursor = db.execute("SELECT * FROM orders ORDER BY id DESC")
        elif email:
            cursor = db.execute("SELECT * FROM orders WHERE customer_email = ? ORDER BY id DESC", (email,))
        else:
            return jsonify({'success': True, 'orders': []})
        rows = [dict(r) for r in cursor.fetchall()]

    orders = []
    for r in rows:
        item = dict(r)
        item['total'] = float(item['total'])
        try:
            item['items'] = json.loads(item['items_json'])
        except Exception:
            item['items'] = []
        orders.append(item)

    return jsonify({'success': True, 'orders': orders})

@app.route('/api/orders/code/<order_code>/invoice', methods=['GET'])
def get_order_invoice(order_code):
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_code = %s", (order_code,))
        r = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,))
        row = cursor.fetchone()
        r = dict(row) if row else None

    if not r:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    order = dict(r)
    order['subtotal'] = float(order['subtotal'])
    order['tax'] = float(order['tax'])
    order['shipping'] = float(order['shipping'])
    order['discount'] = float(order['discount'])
    order['total'] = float(order['total'])
    try:
        order['items'] = json.loads(order['items_json'])
    except Exception:
        order['items'] = []

    gst_info = {
        'business_name': 'Heena Imitation Jewellery',
        'gstin': os.environ.get('BUSINESS_GSTIN', 'GST Document Pending Upload'),
        'support_email': 'heenaimitationjewellery06@gmail.com',
        'support_phone': '+91 9777166165'
    }

    return jsonify({
        'success': True,
        'order': order,
        'gst_info': gst_info
    })

@app.route('/api/orders/<int:order_id>/status', methods=['PUT'])
@admin_required
def update_order_status(order_id):
    data = request.json or {}
    new_status = data.get('status', 'Shipped')
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("UPDATE orders SET order_status = %s WHERE id = %s", (new_status, order_id))
    else:
        db.execute("UPDATE orders SET order_status = ? WHERE id = ?", (new_status, order_id))
        db.commit()
    return jsonify({'success': True, 'message': f'Order status updated to {new_status}'})

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_admin_stats():
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT SUM(total) as revenue, COUNT(*) as count FROM orders WHERE payment_status = 'Paid'")
        rev_row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) as count FROM products")
        prod_row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) as count FROM products WHERE stock <= 5")
        low_stock_row = cursor.fetchone()
    else:
        cursor = db.execute("SELECT SUM(total) as revenue, COUNT(*) as count FROM orders WHERE payment_status = 'Paid'")
        rev_row = dict(cursor.fetchone())
        cursor = db.execute("SELECT COUNT(*) as count FROM products")
        prod_row = dict(cursor.fetchone())
        cursor = db.execute("SELECT COUNT(*) as count FROM products WHERE stock <= 5")
        low_stock_row = dict(cursor.fetchone())

    total_revenue = float(rev_row['revenue'] or 0) if rev_row else 0
    total_orders = int(rev_row['count'] or 0) if rev_row else 0
    total_products = int(prod_row['count'] or 0) if prod_row else 0
    low_stock_count = int(low_stock_row['count'] or 0) if low_stock_row else 0
    avg_order = round(total_revenue / total_orders, 2) if total_orders > 0 else 0

    return jsonify({
        'success': True,
        'stats': {
            'total_revenue': total_revenue,
            'total_orders': total_orders,
            'total_products': total_products,
            'low_stock_count': low_stock_count,
            'avg_order_value': avg_order,
            'db_engine': getattr(g, 'db_type', 'mysql').upper()
        }
    })

# --- Database Inspector API (Admin Protected) ---
@app.route('/api/db/info', methods=['GET'])
@admin_required
def get_db_info():
    db = get_db()
    db_engine = getattr(g, 'db_type', 'mysql')

    if db_engine == 'postgres':
        cursor = db.cursor()
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name ASC")
        table_rows = cursor.fetchall()
        tables = []
        for r in table_rows:
            tname = r.get('table_name') if isinstance(r, dict) else r[0]
            cursor.execute(f'SELECT COUNT(*) as c FROM "{tname}"')
            cnt_row = cursor.fetchone()
            cnt = cnt_row.get('c') if isinstance(cnt_row, dict) else (cnt_row[0] if cnt_row else 0)
            tables.append({'name': tname, 'sql': f'PostgreSQL table: {tname}', 'row_count': cnt})

        return jsonify({
            'success': True,
            'db_engine': 'Supabase PostgreSQL',
            'db_name': 'Supabase Database',
            'db_host': 'Supabase Cloud / Netlify Extension',
            'tables': tables
        })
    elif db_engine == 'mysql':
        cursor = db.cursor()
        cursor.execute("SHOW TABLES")
        table_rows = cursor.fetchall()
        tables = []
        for r in table_rows:
            tname = list(r.values())[0]
            cursor.execute(f"SHOW CREATE TABLE `{tname}`")
            create_sql = list(cursor.fetchone().values())[1]
            cursor.execute(f"SELECT COUNT(*) as c FROM `{tname}`")
            cnt = cursor.fetchone()['c']
            tables.append({'name': tname, 'sql': create_sql, 'row_count': cnt})
        
        return jsonify({
            'success': True,
            'db_engine': 'Laragon MySQL / MariaDB',
            'db_name': MYSQL_DB,
            'db_host': f"{MYSQL_HOST}:{MYSQL_PORT}",
            'tables': tables
        })
    else:
        cursor = db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
        tables = []
        for r in cursor.fetchall():
            tname = r['name']
            sql = r['sql']
            cnt_cursor = db.execute(f"SELECT COUNT(*) as c FROM [{tname}]")
            cnt = cnt_cursor.fetchone()['c']
            tables.append({'name': tname, 'sql': sql, 'row_count': cnt})
        
        return jsonify({
            'success': True,
            'db_engine': 'SQLite Fallback',
            'db_name': SQLITE_DB,
            'tables': tables
        })

@app.route('/api/db/table/<table_name>', methods=['GET'])
@admin_required
def get_db_table_data(table_name):
    safe_table = re.sub(r'[^a-zA-Z0-9_]', '', table_name)
    db = get_db()
    db_engine = getattr(g, 'db_type', 'mysql')

    if db_engine == 'postgres':
        cursor = db.cursor()
        cursor.execute(f'SELECT * FROM "{safe_table}" LIMIT 100')
        rows = cursor.fetchall()
        clean_rows = []
        for r in rows:
            item = dict(r)
            for k, v in item.items():
                if isinstance(v, (datetime, timedelta)):
                    item[k] = str(v)
                elif hasattr(v, 'quantize'):
                    item[k] = float(v)
            clean_rows.append(item)
        return jsonify({'success': True, 'table': safe_table, 'count': len(clean_rows), 'rows': clean_rows})
    elif db_engine == 'mysql':
        cursor = db.cursor()
        cursor.execute(f"SELECT * FROM `{safe_table}` LIMIT 100")
        rows = cursor.fetchall()
        for r in rows:
            for k, v in r.items():
                if isinstance(v, (datetime, timedelta)):
                    r[k] = str(v)
                elif hasattr(v, 'quantize'):
                    r[k] = float(v)
        return jsonify({'success': True, 'table': safe_table, 'count': len(rows), 'rows': rows})
    else:
        rows_cursor = db.execute(f"SELECT * FROM [{safe_table}] LIMIT 100")
        rows = [dict(r) for r in rows_cursor.fetchall()]
        return jsonify({'success': True, 'table': safe_table, 'count': len(rows), 'rows': rows})

if __name__ == '__main__':
    print(f"Heena Imitation Jewellery Server starting on http://127.0.0.1:5000 ...")
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
