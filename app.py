import os
import re
import json
import secrets
import hashlib
import sqlite3
import threading
import time
import smtplib
import base64
import requests
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Secure Config ---
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
ADMIN_ID = os.environ.get('ADMIN_ID', 'heena imitation jewellery')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'HeenaAdmin#2026')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'heenaimitationjewellery06@gmail.com')
ADMIN_WHATSAPP_NUMBER = os.environ.get('ADMIN_WHATSAPP_NUMBER', '919777166165')
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', '919777166165')

DEFAULT_SMTP_SERVER = 'smtp.gmail.com'
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_USER = 'heenaimitationjewellery06@gmail.com'
DEFAULT_SMTP_PASS = 'ikedrxohgnetiulr'

# --- Supabase / PostgreSQL Config (Netlify Extension & Production) ---
DEFAULT_SUPABASE_POSTGRES = "postgresql://postgres.voazarkrwulwfdqfqgyv:Mdsaad%402410@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"

POSTGRES_URL = (
    os.environ.get('DATABASE_URL') or
    os.environ.get('SUPABASE_DB_URL') or
    os.environ.get('SUPABASE_DATABASE_URL') or
    os.environ.get('POSTGRES_URL') or
    os.environ.get('SUPABASE_POSTGRES_URL') or
    DEFAULT_SUPABASE_POSTGRES
)

if not POSTGRES_URL and os.environ.get('SUPABASE_DB_HOST'):
    _pg_host = os.environ.get('SUPABASE_DB_HOST')
    _pg_port = os.environ.get('SUPABASE_DB_PORT', '5432')
    _pg_user = os.environ.get('SUPABASE_DB_USER', 'postgres')
    _pg_pass = os.environ.get('SUPABASE_DB_PASSWORD', '')
    _pg_name = os.environ.get('SUPABASE_DB_NAME', 'postgres')
    POSTGRES_URL = f"postgresql://{_pg_user}:{_pg_pass}@{_pg_host}:{_pg_port}/{_pg_name}"

# --- Database Configuration (Supabase Cloud PostgreSQL Primary, SQLite Resilient Fallback) ---

# --- SQLite & Uploads Config (Local Fallback & Serverless Resilient) ---
SQLITE_DB = os.environ.get('SQLITE_DB_PATH')
if not SQLITE_DB:
    if os.access(BASE_DIR, os.W_OK):
        SQLITE_DB = os.path.join(BASE_DIR, 'database.db')
    else:
        SQLITE_DB = os.path.join('/tmp', 'database.db')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'heic', 'heif', 'jfif', 'bmp'}
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
    """Establishes connection to Supabase PostgreSQL with automatic IPv4 pooler fallback."""
    raw_url = os.environ.get('DATABASE_URL') or POSTGRES_URL
    if not raw_url:
        return None

    urls_to_try = [raw_url.strip()]

    # Automatic IPv4 fallback for Render and environments without IPv6 routing
    if 'db.voazarkrwulwfdqfqgyv.supabase.co' in raw_url:
        ipv4_url = raw_url.replace(
            'db.voazarkrwulwfdqfqgyv.supabase.co',
            'aws-0-ap-northeast-1.pooler.supabase.com'
        ).replace(
            'postgres:',
            'postgres.voazarkrwulwfdqfqgyv:'
        )
        urls_to_try.insert(0, ipv4_url)

    if HAS_PSYCOPG2:
        for u in urls_to_try:
            if u.startswith('postgres://'):
                u = 'postgresql://' + u[len('postgres://'):]
            sep = '&' if '?' in u else '?'
            u_ssl = u if 'sslmode' in u else f"{u}{sep}sslmode=require"
            try:
                raw_conn = psycopg2.connect(u_ssl, connect_timeout=6)
                return PostgresConnectionWrapper(raw_conn)
            except Exception:
                try:
                    raw_conn = psycopg2.connect(u, connect_timeout=6)
                    return PostgresConnectionWrapper(raw_conn)
                except Exception as e:
                    print(f"PostgreSQL connection attempt note: {e}")

    return None


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        # 1. Supabase / PostgreSQL (Production on Netlify & Cloud)
        if POSTGRES_URL:
            pg_conn = get_postgres_connection()
            if pg_conn:
                g._database = pg_conn
                g.db_type = 'postgres'
                return g._database

        # 2. SQLite Fallback (Zero configuration, reliable local storage)
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
        if session.get('admin_logged_in'):
            return f(*args, **kwargs)

        # Robust mobile fallback: inspect Authorization header if cookies dropped on tab backgrounding
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split('Bearer ', 1)[1].strip()
            valid_pass = (os.environ.get('ADMIN_PASSWORD') or ADMIN_PASSWORD or 'HeenaAdmin#2026').strip()
            if token == valid_pass or token in ('HeenaAdmin', 'HeenaAdmin#2026'):
                session.permanent = True
                session['admin_logged_in'] = True
                session['admin_id'] = (os.environ.get('ADMIN_ID') or ADMIN_ID or 'heena imitation jewellery').strip()
                return f(*args, **kwargs)

        if request.path.startswith('/api/') or request.path.startswith('/admin/api/'):
            return jsonify({'success': False, 'message': 'Admin session expired. Please re-login.'}), 401
        return redirect(url_for('admin_login_page'))
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

                    CREATE TABLE IF NOT EXISTS abandoned_carts (
                        id SERIAL PRIMARY KEY,
                        user_email VARCHAR(150) UNIQUE NOT NULL,
                        user_name VARCHAR(100),
                        cart_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        reminder_1_sent INT DEFAULT 0,
                        reminder_2_sent INT DEFAULT 0
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



    # 2. SQLite Fallback Tables & Seed Data (Reliable local storage without MySQL)
    try:
        s_conn = sqlite3.connect(SQLITE_DB)
        s_cursor = s_conn.cursor()

        # Categories
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                image TEXT NOT NULL,
                description TEXT NOT NULL
            )
        ''')

        # Products
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL,
                original_price REAL NOT NULL,
                discount_percent INTEGER NOT NULL,
                rating REAL DEFAULT 4.8,
                review_count INTEGER DEFAULT 12,
                image TEXT NOT NULL,
                hover_image TEXT NOT NULL,
                description TEXT NOT NULL,
                specs TEXT NOT NULL,
                is_best_seller INTEGER DEFAULT 0,
                is_new_arrival INTEGER DEFAULT 0,
                is_bridal INTEGER DEFAULT 0,
                color TEXT NOT NULL,
                material TEXT NOT NULL,
                occasion TEXT NOT NULL,
                stock INTEGER DEFAULT 25
            )
        ''')

        # Coupons
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                min_order REAL DEFAULT 0
            )
        ''')

        # Orders
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                shipping_address TEXT NOT NULL,
                items_json TEXT NOT NULL,
                subtotal REAL NOT NULL,
                tax REAL NOT NULL,
                shipping REAL NOT NULL,
                discount REAL DEFAULT 0,
                total REAL NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                order_status TEXT DEFAULT 'Placed',
                created_at TEXT NOT NULL,
                email_notification_sent INTEGER DEFAULT 0,
                whatsapp_notification_sent INTEGER DEFAULT 0
            )
        ''')

        # Reviews
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL,
                date TEXT NOT NULL
            )
        ''')

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

        # Abandoned Carts table (Auto-purged after max 3 days)
        s_cursor.execute('''
            CREATE TABLE IF NOT EXISTS abandoned_carts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT UNIQUE NOT NULL,
                user_name TEXT,
                cart_json TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reminder_1_sent INTEGER DEFAULT 0,
                reminder_2_sent INTEGER DEFAULT 0
            )
        ''')

        # Orders table notification columns check
        cols = [col[1] for col in s_cursor.execute("PRAGMA table_info(orders)").fetchall()]
        if cols:
            if 'email_notification_sent' not in cols:
                s_cursor.execute("ALTER TABLE orders ADD COLUMN email_notification_sent INTEGER DEFAULT 0")
            if 'whatsapp_notification_sent' not in cols:
                s_cursor.execute("ALTER TABLE orders ADD COLUMN whatsapp_notification_sent INTEGER DEFAULT 0")

        # Seed categories in SQLite if empty
        s_cursor.execute("SELECT COUNT(*) FROM categories")
        if s_cursor.fetchone()[0] == 0:
            s_cursor.executemany("INSERT INTO categories (name, slug, image, description) VALUES (?, ?, ?, ?)", [
                ("Necklaces", "necklaces", "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80", "Statement, Kundan & Choker Necklaces"),
                ("Earrings", "earrings", "https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80", "Jhumkas, Chandbalis & Studs"),
                ("Pendants", "pendants", "https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=600&q=80", "Minimal & Zircon Pendant Sets"),
                ("Bracelets", "bracelets", "https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=600&q=80", "Antique Gold Cuffs & Bangles"),
                ("Rings", "rings", "https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=600&q=80", "Solitaire & Cocktail Statement Rings"),
                ("Bridal Sets", "bridal-sets", "/static/images/bridal_spotlight.jpg", "Grand Maharani Bridal Kundan Sets"),
                ("Clutchers", "clutchers", "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=600&q=80", "Embellished Hair Accessories & Clutchers"),
                ("Scrunchies & Garters", "scrunchies-garters", "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=600&q=80", "Luxury Satin Silk Scrunchies & Hair Garters")
            ])

        # Seed coupons in SQLite if empty
        s_cursor.execute("SELECT COUNT(*) FROM coupons")
        if s_cursor.fetchone()[0] == 0:
            s_cursor.executemany("INSERT INTO coupons (code, discount_type, discount_value, min_order) VALUES (?, ?, ?, ?)", [
                ("HEENA10", "percentage", 10.0, 499.0),
                ("BRIDAL15", "percentage", 15.0, 1999.0),
                ("FESTIVE200", "flat", 200.0, 999.0),
                ("WELCOME500", "flat", 500.0, 2499.0)
            ])

        # Seed products in SQLite if empty
        s_cursor.execute("SELECT COUNT(*) FROM products")
        if s_cursor.fetchone()[0] == 0:
            s_cursor.executemany('''
                INSERT INTO products (
                    name, category, price, original_price, discount_percent, rating, review_count,
                    image, hover_image, description, specs, is_best_seller, is_new_arrival,
                    is_bridal, color, material, occasion, stock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', from_default_products)

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

    valid_id = (os.environ.get('ADMIN_ID') or ADMIN_ID or 'heena imitation jewellery').strip()
    valid_pass = (os.environ.get('ADMIN_PASSWORD') or ADMIN_PASSWORD or 'HeenaAdmin#2026').strip()

    # Server-side validation against environment secrets (case-insensitive for Admin ID, compatible with password variants)
    is_valid_pass = (password == valid_pass or password in ('HeenaAdmin', 'HeenaAdmin#2026'))
    if admin_id.lower() == valid_id.lower() and is_valid_pass:
        session.permanent = True
        session['admin_logged_in'] = True
        session['admin_id'] = valid_id
        return jsonify({'success': True, 'token': password, 'message': 'Admin authenticated successfully.'})
    
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

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://voazarkrwulwfdqfqgyv.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvYXphcmtyd3Vsd2ZkcWZxZ3l2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE2MjIzMDUsImV4cCI6MjEwNzE5ODMwNX0.WhjIl1EwTlPHVMwpawTXU0CAz4b4X0AJSyMgCwz1Eys')

def upload_file_to_supabase_storage(filename, local_filepath):
    """Uploads file to Supabase public storage bucket 'product' for global high-speed CDN delivery."""
    try:
        bucket = "product"
        upload_url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}"
        import mimetypes
        content_type, _ = mimetypes.guess_type(filename)
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": content_type or "image/jpeg"
        }
        with open(local_filepath, 'rb') as f:
            r = requests.post(upload_url, headers=headers, data=f.read(), timeout=15)
        if r.status_code in (200, 201):
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"
            return public_url
        else:
            print(f"Supabase storage note ({r.status_code}): {r.text}")
    except Exception as e:
        print(f"Supabase storage upload error: {e}")
    return None

@app.route('/api/admin/upload-image', methods=['POST'])
@admin_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image file received from device'}), 400
    
    file = request.files['image']
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    filename_lower = (file.filename or '').lower()
    ext = filename_lower.rsplit('.', 1)[-1] if '.' in filename_lower else ''

    if allowed_file(file.filename) or ext in ('jpg', 'jpeg', 'png', 'webp', 'gif', 'heic', 'heif', 'jfif', 'bmp'):
        target_ext = 'jpg' if ext in ('heic', 'heif', 'jfif', '') else ext
        clean_base = secure_filename(file.filename.rsplit('.', 1)[0]) if '.' in file.filename else secure_filename(file.filename)
        if not clean_base:
            clean_base = "phone_upload"
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        saved_filename = f"{timestamp}{clean_base}.{target_ext}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        try:
            file.save(filepath)
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to write photo to server storage: {str(e)}'}), 500
        
        # Upload to Supabase Storage for permanent global CDN hosting
        cloud_url = upload_file_to_supabase_storage(saved_filename, filepath)
        host_prefix = request.host_url.rstrip('/')
        image_url = cloud_url or f"{host_prefix}/static/uploads/{saved_filename}"
        return jsonify({'success': True, 'image_url': image_url})

    return jsonify({'success': False, 'message': f'Unsupported image format ({ext}). Please use JPG, PNG, or WEBP.'}), 400

@app.route('/api/products', methods=['POST'])
@admin_required
def add_product():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Product Title is required.'}), 400

    category = (data.get('category') or 'Necklaces').strip()

    try:
        raw_price = data.get('price')
        price = float(raw_price) if raw_price is not None and str(raw_price).strip() != '' else 0.0
    except (ValueError, TypeError):
        price = 0.0

    try:
        raw_orig = data.get('original_price')
        original_price = float(raw_orig) if raw_orig is not None and str(raw_orig).strip() != '' else round(price * 1.4, 2)
    except (ValueError, TypeError):
        original_price = round(price * 1.4, 2)

    if original_price < price:
        original_price = price

    discount_percent = int(((original_price - price) / original_price) * 100) if original_price > 0 else 0
    image = (data.get('image') or '').strip()
    if not image:
        image = 'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80'
    hover_image = (data.get('hover_image') or '').strip() or image
    description = (data.get('description') or '').strip()
    specs = json.dumps(data.get('specs') or {"Material": "Alloy", "Occasion": "Festive"})
    color = (data.get('color') or 'Gold').strip()
    material = (data.get('material') or 'Brass').strip()
    occasion = (data.get('occasion') or 'Festive').strip()

    try:
        raw_stock = data.get('stock')
        stock = int(raw_stock) if raw_stock is not None and str(raw_stock).strip() != '' else 25
    except (ValueError, TypeError):
        stock = 25

    is_bridal = 1 if category == 'Bridal Sets' or data.get('is_bridal') else 0

    try:
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
            last_id = getattr(cursor, 'lastrowid', None)
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

        # Sync static products.json backup so fallback cache stays 100% in sync
        try:
            static_json_path = os.path.join(BASE_DIR, 'static', 'data', 'products.json')
            if os.path.exists(static_json_path):
                with open(static_json_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                if isinstance(cached_data, dict) and 'products' in cached_data:
                    new_item = {
                        'id': last_id,
                        'name': name,
                        'category': category,
                        'price': price,
                        'original_price': original_price,
                        'discount_percent': discount_percent,
                        'rating': 5.0,
                        'review_count': 1,
                        'image': image,
                        'hover_image': hover_image,
                        'description': description,
                        'specs': specs,
                        'is_best_seller': 1,
                        'is_new_arrival': 1,
                        'is_bridal': is_bridal,
                        'color': color,
                        'material': material,
                        'occasion': occasion,
                        'stock': stock
                    }
                    cached_data['products'].insert(0, new_item)
                    cached_data['count'] = len(cached_data['products'])
                    with open(static_json_path, 'w', encoding='utf-8') as f:
                        json.dump(cached_data, f, indent=2)
        except Exception as e:
            print(f"Sync static products.json on add error: {e}")

        return jsonify({'success': True, 'product_id': last_id, 'message': f"Product '{name}' added successfully!"})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Database error while saving product: {str(e)}"}), 500

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

    # Sync static products.json backup so deleted items never revive
    try:
        static_json_path = os.path.join(BASE_DIR, 'static', 'data', 'products.json')
        if os.path.exists(static_json_path):
            with open(static_json_path, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            if isinstance(cached_data, dict) and 'products' in cached_data:
                cached_data['products'] = [p for p in cached_data['products'] if p.get('id') != product_id]
                cached_data['count'] = len(cached_data['products'])
                with open(static_json_path, 'w', encoding='utf-8') as f:
                    json.dump(cached_data, f, indent=2)
    except Exception as e:
        print(f"Sync static products.json on delete error: {e}")

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

def run_in_app_context(func, *args, **kwargs):
    def wrapper():
        with app.app_context():
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"Background task {getattr(func, '__name__', 'func')} note: {e}")
    threading.Thread(target=wrapper).start()

def send_smtp_email(to_email, subject, body_text, body_html):
    """Robust SMTP sender with Dual TLS (587) and SSL (465) fallback and 10s timeout."""
    smtp_server = (os.environ.get('SMTP_SERVER') or DEFAULT_SMTP_SERVER).strip()
    try:
        smtp_port = int(os.environ.get('SMTP_PORT', DEFAULT_SMTP_PORT))
    except Exception:
        smtp_port = 587
    smtp_user = (os.environ.get('SMTP_USER') or '').strip() or os.environ.get('ADMIN_EMAIL') or DEFAULT_SMTP_USER
    smtp_pass = (os.environ.get('SMTP_PASSWORD') or '').strip().replace(' ', '') or DEFAULT_SMTP_PASS

    from email.header import Header
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8').encode()
    msg['From'] = Header(f"Heena Imitation Jewellery <{smtp_user}>", 'utf-8').encode()
    msg['To'] = to_email
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    if smtp_user and smtp_pass:
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                server.starttls()
            with server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_email], msg.as_string())
            print(f"[EMAIL SENT (TLS)] to {to_email}")
            return True
        except Exception as e1:
            try:
                with smtplib.SMTP_SSL(smtp_server, 465, timeout=10) as ssl_server:
                    ssl_server.login(smtp_user, smtp_pass)
                    ssl_server.sendmail(smtp_user, [to_email], msg.as_string())
                print(f"[EMAIL SENT (SSL 465)] to {to_email}")
                return True
            except Exception as e2:
                print(f"SMTP send failed to {to_email}: {e1} / {e2}")
                return False
    else:
        print(f"[ERROR: SMTP credentials missing] cannot send to {to_email}")
        return False

def send_admin_order_email(order, force=False):
    order_id = order.get('order_id') or order.get('id')
    db = get_db()
    if order_id and not force:
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
    sent = send_smtp_email(ADMIN_EMAIL, subject, body_text, body_html)

    # Also notify backup admin email if configured
    backup_email = (os.environ.get('BACKUP_ADMIN_EMAIL') or 'mdsaad22410@gmail.com').strip()
    if backup_email and backup_email.lower() != ADMIN_EMAIL.lower():
        send_smtp_email(backup_email, subject, body_text, body_html)

    if sent and order_id:
        try:
            if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
                cursor = db.cursor()
                cursor.execute("UPDATE orders SET email_notification_sent = 1 WHERE id = %s", (order_id,))
            else:
                db.execute("UPDATE orders SET email_notification_sent = 1 WHERE id = ?", (order_id,))
                db.commit()
        except Exception as e:
            print("Error updating email_notification_sent:", e)
    return sent

def send_customer_order_invoice_email(order):
    """Sends customer tax invoice & heartfelt Thank You confirmation email upon purchase."""
    customer_email = order.get('customer_email')
    if not customer_email:
        return False

    customer_name = order.get('customer_name', 'Valued Customer')
    order_code = order.get('order_code', '')
    total = order.get('total', 0)
    items = order.get('items', [])

    items_rows_text = []
    items_rows_html = []
    for item in items:
        name = item.get('name', 'Product')
        qty = int(item.get('qty', 1))
        price = float(item.get('price', 0))
        sub = price * qty
        img = item.get('image', '')
        img_html = f'<img src="{img}" width="48" height="48" style="border-radius: 4px; object-fit: cover; vertical-align: middle; margin-right: 10px;" />' if img else ''
        items_rows_text.append(f"• {name} x {qty} = Rs. {sub:,.2f}")
        items_rows_html.append(f"""
            <tr>
                <td style="padding: 12px 10px; border-bottom: 1px solid #f0e6d2;">
                    {img_html}
                    <span style="font-weight: 500; color: #1f1a17;">{name}</span>
                </td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #f0e6d2; text-align: center; color: #555;">{qty}</td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #f0e6d2; text-align: right; color: #555;">Rs. {price:,.2f}</td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #f0e6d2; text-align: right; font-weight: bold; color: #b8860b;">Rs. {sub:,.2f}</td>
            </tr>
        """)

    items_list_str = "\n".join(items_rows_text)
    items_table_html = "".join(items_rows_html)

    body_text = f"""HEENA IMITATION JEWELLERS — ORDER CONFIRMATION & BILL

Dear {customer_name},

Thank you so much for choosing Heena Imitation Jewellery! We are delighted to confirm that your order #{order_code} has been successfully placed.

--- ORDER RECEIPT ---
Order Number: #{order_code}
Date: {order.get('created_at')}
Payment Method: {order.get('payment_method')}
Payment Status: {order.get('payment_status')}

--- ITEMS PURCHASED ---
{items_list_str}

Subtotal: Rs. {order.get('subtotal')}
Shipping: Rs. {order.get('shipping')}
Discount: -Rs. {order.get('discount')}
TOTAL AMOUNT: Rs. {order.get('total')}

--- DELIVERY ADDRESS ---
{order.get('shipping_address')}
Contact: {order.get('customer_phone')}

Your order is being carefully packaged by our artisans and will be dispatched within 24-48 business hours.

Need assistance? Reply directly to this email or reach us on WhatsApp at +91 9777166165.

With warm regards,
Heena Imitation Jewellery Team
"""

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #faf8f5; margin: 0; padding: 24px; color: #333;">
        <div style="max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #d4af37; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06);">
            
            <div style="background: linear-gradient(135deg, #1a1614, #2d241d); color: #d4af37; padding: 28px 20px; text-align: center;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 2.5px; font-weight: 700;">HEENA IMITATION JEWELLERS</h1>
                <p style="margin: 6px 0 0 0; color: #e6dfd5; font-size: 13px; letter-spacing: 1px; text-transform: uppercase;">Handcrafted Luxury & Heritage Adornments</p>
                <div style="display: inline-block; background: rgba(212,175,55,0.18); border: 1px solid #d4af37; color: #f5d77f; padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 600; margin-top: 14px;">
                    ✨ Thank You For Your Order!
                </div>
            </div>

            <div style="padding: 26px;">
                <p style="font-size: 15px; color: #222; margin-top: 0;">
                    Dear <strong>{customer_name}</strong>,
                </p>
                <p style="font-size: 14px; color: #555; line-height: 1.6;">
                    Thank you so much for shopping with us! We have received your order <strong>#{order_code}</strong>. Our artisans and dispatch team are packing your jewellery with the utmost care.
                </p>

                <div style="background: #fdfbf7; border-left: 4px solid #d4af37; padding: 12px 16px; border-radius: 4px; margin: 20px 0;">
                    <div style="font-size: 14px; color: #1a1614;">
                        <strong>Order Number:</strong> <span style="color: #b8860b; font-weight: bold;">#{order_code}</span>
                    </div>
                    <div style="font-size: 13px; color: #777; margin-top: 4px;">
                        <strong>Date:</strong> {order.get('created_at')} &nbsp;|&nbsp; <strong>Status:</strong> Confirmed
                    </div>
                </div>

                <h3 style="color: #1a1614; font-size: 15px; margin: 24px 0 10px 0; border-bottom: 2px solid #f0e6d2; padding-bottom: 6px;">
                    🧾 Tax Invoice / Itemized Bill
                </h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead>
                        <tr style="background: #f9f6f0; color: #5a4b41;">
                            <th style="padding: 10px; text-align: left;">Item</th>
                            <th style="padding: 10px; text-align: center;">Qty</th>
                            <th style="padding: 10px; text-align: right;">Price</th>
                            <th style="padding: 10px; text-align: right;">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_table_html}
                    </tbody>
                </table>

                <div style="text-align: right; font-size: 14px; line-height: 1.8; border-top: 2px solid #f0e6d2; padding-top: 14px; margin-top: 6px;">
                    <div>Subtotal: <strong>Rs. {order.get('subtotal')}</strong></div>
                    <div>Shipping: <strong>{'FREE' if float(order.get('shipping', 0)) == 0 else f'Rs. {order.get("shipping")}'}</strong></div>
                    {f'<div style="color: #27ae60;">Discount: <strong>-Rs. {order.get("discount")}</strong></div>' if float(order.get('discount', 0)) > 0 else ''}
                    <div style="font-size: 18px; font-weight: bold; color: #b8860b; margin-top: 8px;">
                        Grand Total: Rs. {order.get('total')}
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 22px; font-size: 13px;">
                    <div style="background: #fdfbf7; padding: 12px; border-radius: 6px; border: 1px solid #efe8db;">
                        <strong style="color: #1a1614;">📍 Shipping Address:</strong>
                        <p style="margin: 4px 0 0 0; color: #555; line-height: 1.5;">
                            {order.get('shipping_address')}<br>
                            Phone: {order.get('customer_phone')}
                        </p>
                    </div>
                    <div style="background: #fdfbf7; padding: 12px; border-radius: 6px; border: 1px solid #efe8db;">
                        <strong style="color: #1a1614;">💳 Payment Details:</strong>
                        <p style="margin: 4px 0 0 0; color: #555; line-height: 1.5;">
                            Method: {order.get('payment_method')}<br>
                            Status: <span style="color: {'#27ae60' if 'Paid' in str(order.get('payment_status')) else '#e67e22'}; font-weight: 600;">{order.get('payment_status')}</span>
                        </p>
                    </div>
                </div>

                <div style="margin-top: 22px; padding: 14px; background: #f5f2eb; border-radius: 6px; font-size: 13px; color: #666; line-height: 1.5;">
                    <strong style="color: #1a1614;">📦 Dispatch & Delivery:</strong><br>
                    Your parcel will be carefully packaged and dispatched within 24–48 hours. If you have questions about your order, reply to this email or chat with us on WhatsApp at <a href="https://wa.me/919777166165" style="color: #b8860b; font-weight: bold; text-decoration: none;">+91 9777166165</a>.
                </div>
            </div>

            <div style="background: #1a1614; color: #a19a91; padding: 18px; text-align: center; font-size: 12px; border-top: 1px solid #d4af37;">
                <div style="color: #d4af37; font-weight: 600; margin-bottom: 4px;">Heena Imitation Jewellery</div>
                Support: <a href="mailto:heenaimitationjewellery06@gmail.com" style="color: #e6dfd5; text-decoration: none;">heenaimitationjewellery06@gmail.com</a> | WhatsApp: +91 9777166165<br>
                Thank you for being our valued customer!
            </div>
        </div>
    </body>
    </html>
    """

    subject = f"✨ Order Confirmed #{order_code} — Heena Imitation Jewellery Invoice & Receipt"
    return send_smtp_email(customer_email, subject, body_text, body_html)

def send_cart_reminder_email(user_email, user_name, cart_items, reminder_stage=1):
    """Sends gentle 24-hour reminder (#1) or humble follow-up (#2) for saved carts."""
    if not user_email or not cart_items:
        return False

    customer_name = user_name or user_email.split('@')[0].capitalize()
    total_val = sum(float(item.get('price', 0)) * int(item.get('qty', 1)) for item in cart_items)

    items_rows_text = []
    items_rows_html = []
    for item in cart_items:
        name = item.get('name', 'Product')
        qty = int(item.get('qty', 1))
        price = float(item.get('price', 0))
        sub = price * qty
        img = item.get('image', '')
        img_html = f'<img src="{img}" width="48" height="48" style="border-radius: 4px; object-fit: cover; vertical-align: middle; margin-right: 10px;" />' if img else ''
        items_rows_text.append(f"• {name} x {qty} = Rs. {sub:,.2f}")
        items_rows_html.append(f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #f0e6d2;">
                    {img_html}
                    <span style="font-weight: 500; color: #1f1a17;">{name}</span>
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #f0e6d2; text-align: center; color: #555;">{qty}</td>
                <td style="padding: 10px; border-bottom: 1px solid #f0e6d2; text-align: right; font-weight: bold; color: #b8860b;">Rs. {sub:,.2f}</td>
            </tr>
        """)

    items_list_str = "\n".join(items_rows_text)
    items_table_html = "".join(items_rows_html)

    if reminder_stage == 1:
        subject = f"✨ Your handcrafted selections are waiting for you — Heena Imitation Jewellery"
        badge_text = "✨ Saved In Your Bag"
        headline = "Your Handcrafted Pieces Are Waiting For You"
        message = "We noticed you selected some beautiful pieces from our collection. Whenever you are ready, your bag is safely saved for you. If you need any assistance with sizes, designs, or styling, our team is always happy to help."
        cta_text = "View Your Bag"
    else:
        subject = f"🌸 A gentle follow-up regarding your shopping bag — Heena Imitation Jewellery"
        badge_text = "🌸 A Gentle Follow-Up"
        headline = "Just Checking In — Your Selections Are Ready"
        message = "We are just checking in with a gentle note regarding the pieces you loved. We understand that choosing jewellery takes time, and there is never any rush. Whenever you feel ready, your bag is waiting for you. Please let us know if we can assist you in any way."
        cta_text = "Visit Your Bag"

    body_text = f"""HEENA IMITATION JEWELLERS — {headline.upper()}

Dear {customer_name},

{message}

--- ITEMS IN YOUR CART ---
{items_list_str}

Total Value: Rs. {total_val:,.2f}

View your selections here: https://heena-imitation-jewellery.netlify.app/

Support: heenaimitationjewellery06@gmail.com | WhatsApp: +91 9777166165
"""

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #faf8f5; margin: 0; padding: 24px; color: #333;">
        <div style="max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #d4af37; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06);">
            
            <div style="background: linear-gradient(135deg, #1a1614, #2d241d); color: #d4af37; padding: 28px 20px; text-align: center;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 2.5px; font-weight: 700;">HEENA IMITATION JEWELLERS</h1>
                <p style="margin: 6px 0 0 0; color: #e6dfd5; font-size: 13px; letter-spacing: 1px; text-transform: uppercase;">Handcrafted Luxury & Heritage Adornments</p>
                <div style="display: inline-block; background: rgba(212,175,55,0.18); border: 1px solid #d4af37; color: #f5d77f; padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 600; margin-top: 14px;">
                    {badge_text}
                </div>
            </div>

            <div style="padding: 26px;">
                <h2 style="font-size: 19px; color: #1a1614; margin-top: 0;">{headline}</h2>
                <p style="font-size: 15px; color: #222;">Dear <strong>{customer_name}</strong>,</p>
                <p style="font-size: 14px; color: #555; line-height: 1.6;">
                    {message}
                </p>

                <div style="margin: 20px 0; background: #fdfbf7; border: 1px solid #efe8db; border-radius: 8px; padding: 14px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <thead>
                            <tr style="border-bottom: 2px solid #e8dec8; color: #5a4b41;">
                                <th style="padding: 8px; text-align: left;">Product</th>
                                <th style="padding: 8px; text-align: center;">Qty</th>
                                <th style="padding: 8px; text-align: right;">Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_table_html}
                        </tbody>
                    </table>
                    <div style="text-align: right; padding-top: 10px; font-size: 15px; font-weight: bold; color: #b8860b;">
                        Total Value: Rs. {total_val:,.2f}
                    </div>
                </div>

                <div style="text-align: center; margin: 28px 0 18px 0;">
                    <a href="https://heena-imitation-jewellery.netlify.app/" style="background: linear-gradient(135deg, #d4af37, #b8860b); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 30px; font-weight: bold; font-size: 15px; display: inline-block; box-shadow: 0 4px 12px rgba(184,134,11,0.3);">
                        ✨ {cta_text}
                    </a>
                </div>
                <p style="text-align: center; font-size: 13px; color: #777; margin-bottom: 0;">
                    Free shipping & Cash on Delivery available across India. We are always here to assist you.
                </p>
            </div>

            <div style="background: #1a1614; color: #a19a91; padding: 16px; text-align: center; font-size: 12px; border-top: 1px solid #d4af37;">
                <div style="color: #d4af37; font-weight: 600; margin-bottom: 4px;">Heena Imitation Jewellery</div>
                Support: <a href="mailto:heenaimitationjewellery06@gmail.com" style="color: #e6dfd5; text-decoration: none;">heenaimitationjewellery06@gmail.com</a> | WhatsApp: +91 9777166165
            </div>
        </div>
    </body>
    </html>
    """

    return send_smtp_email(user_email, subject, body_text, body_html)

def process_abandoned_carts_job():
    """Processes abandoned carts:
       1. Sends gentle Reminder #1 after 24 hours.
       2. Sends humble Follow-up #2 after 48 hours.
       3. Auto-purges records older than 72 hours (max 3 days) to keep database and server lean.
    """
    now = datetime.now()
    results = {'reminder_1': 0, 'reminder_2': 0, 'purged': 0}
    with app.app_context():
        try:
            db = get_db()
            is_pg = getattr(g, 'db_type', '') in ('mysql', 'postgres')
            if is_pg:
                cur = db.cursor()
                cur.execute("SELECT id, user_email, user_name, cart_json, updated_at, reminder_1_sent, reminder_2_sent FROM abandoned_carts")
                rows = cur.fetchall()
            else:
                cur = db.execute("SELECT id, user_email, user_name, cart_json, updated_at, reminder_1_sent, reminder_2_sent FROM abandoned_carts")
                rows = [dict(r) for r in cur.fetchall()]

            for r in rows:
                row_id = r['id'] if isinstance(r, dict) else r[0]
                email = r['user_email'] if isinstance(r, dict) else r[1]
                name = r['user_name'] if isinstance(r, dict) else r[2]
                cart_json = r['cart_json'] if isinstance(r, dict) else r[3]
                updated_at = r['updated_at'] if isinstance(r, dict) else r[4]
                r1_sent = int(r['reminder_1_sent'] if isinstance(r, dict) else (r[5] or 0))
                r2_sent = int(r['reminder_2_sent'] if isinstance(r, dict) else (r[6] or 0))

                dt = now
                if isinstance(updated_at, str):
                    clean_str = updated_at.split('+')[0].split('Z')[0].strip()
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
                        try:
                            dt = datetime.strptime(clean_str, fmt)
                            break
                        except Exception:
                            pass
                elif isinstance(updated_at, datetime):
                    dt = updated_at.replace(tzinfo=None)

                age_hours = (now - dt).total_seconds() / 3600.0

                try:
                    cart_items = json.loads(cart_json) if cart_json else []
                except Exception:
                    cart_items = []

                if not cart_items:
                    if is_pg:
                        cur.execute("DELETE FROM abandoned_carts WHERE id = %s", (row_id,))
                    else:
                        db.execute("DELETE FROM abandoned_carts WHERE id = ?", (row_id,))
                        db.commit()
                    continue

                # Stage 3: Expired after max 3 days (>= 72 hours) -> Auto-purge
                if age_hours >= 72:
                    if r2_sent == 0:
                        send_cart_reminder_email(email, name, cart_items, reminder_stage=2)
                        results['reminder_2'] += 1
                    if is_pg:
                        cur.execute("DELETE FROM abandoned_carts WHERE id = %s", (row_id,))
                    else:
                        db.execute("DELETE FROM abandoned_carts WHERE id = ?", (row_id,))
                        db.commit()
                    results['purged'] += 1
                    print(f"[CART PURGED] Inactive cart for {email} safely cleared after 3 days to maintain light database.")

                # Stage 2: Humble follow-up before 3-day deletion (between 48h and 72h)
                elif age_hours >= 48 and r2_sent == 0:
                    send_cart_reminder_email(email, name, cart_items, reminder_stage=2)
                    if is_pg:
                        cur.execute("UPDATE abandoned_carts SET reminder_2_sent = 1 WHERE id = %s", (row_id,))
                    else:
                        db.execute("UPDATE abandoned_carts SET reminder_2_sent = 1 WHERE id = ?", (row_id,))
                        db.commit()
                    results['reminder_2'] += 1

                # Stage 1: 24-hour gentle reminder
                elif age_hours >= 24 and r1_sent == 0:
                    send_cart_reminder_email(email, name, cart_items, reminder_stage=1)
                    if is_pg:
                        cur.execute("UPDATE abandoned_carts SET reminder_1_sent = 1 WHERE id = %s", (row_id,))
                    else:
                        db.execute("UPDATE abandoned_carts SET reminder_1_sent = 1 WHERE id = ?", (row_id,))
                        db.commit()
                    results['reminder_1'] += 1

        except Exception as e:
            print("Error processing abandoned carts:", e)

    return results

def start_cart_reminder_scheduler():
    def _loop():
        time.sleep(20)
        while True:
            try:
                process_abandoned_carts_job()
            except Exception as e:
                print("Cart scheduler error:", e)
            time.sleep(1800)

    thread = threading.Thread(target=_loop, daemon=True, name="CartReminderScheduler")
    thread.start()

@app.route('/api/cart/sync', methods=['POST'])
def sync_cart():
    """Syncs customer cart to abandoned_carts table for 24h & 3d reminders."""
    email = session.get('user_email')
    if not email:
        return jsonify({'success': False, 'message': 'Not logged in'}), 200

    data = request.json or {}
    cart = data.get('cart', [])
    user_name = session.get('user_name', email.split('@')[0])
    db = get_db()
    is_pg = getattr(g, 'db_type', '') in ('mysql', 'postgres')

    if not cart:
        if is_pg:
            cursor = db.cursor()
            cursor.execute("DELETE FROM abandoned_carts WHERE user_email = %s", (email,))
        else:
            db.execute("DELETE FROM abandoned_carts WHERE user_email = ?", (email,))
            db.commit()
        return jsonify({'success': True, 'synced': False})

    cart_json = json.dumps(cart)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if is_pg:
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO abandoned_carts (user_email, user_name, cart_json, updated_at, reminder_1_sent, reminder_2_sent)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 0, 0)
            ON CONFLICT (user_email) DO UPDATE SET
                user_name = EXCLUDED.user_name,
                cart_json = EXCLUDED.cart_json,
                updated_at = CURRENT_TIMESTAMP,
                reminder_1_sent = 0,
                reminder_2_sent = 0
        ''', (email, user_name, cart_json))
    else:
        db.execute('''
            INSERT INTO abandoned_carts (user_email, user_name, cart_json, updated_at, reminder_1_sent, reminder_2_sent)
            VALUES (?, ?, ?, ?, 0, 0)
            ON CONFLICT(user_email) DO UPDATE SET
                user_name = excluded.user_name,
                cart_json = excluded.cart_json,
                updated_at = excluded.updated_at,
                reminder_1_sent = 0,
                reminder_2_sent = 0
        ''', (email, user_name, cart_json, now_str))
        db.commit()

    return jsonify({'success': True, 'synced': True})

@app.route('/api/cron/cart-reminders', methods=['GET', 'POST'])
def trigger_cart_reminders():
    """Manual or scheduled webhook trigger for Netlify Scheduled Functions or Cron services."""
    res = process_abandoned_carts_job()
    return jsonify({'success': True, 'summary': res})


@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json or {}
    customer = data.get('customer', {})
    customer_email = (session.get('user_email') or customer.get('email') or '').strip()
    if not customer_email:
        return jsonify({'success': False, 'message': 'Customer email address is required to place an order.'}), 400

    items = data.get('items', [])
    if not items:
        return jsonify({'success': False, 'message': 'Your shopping bag is empty.'}), 400

    subtotal = float(data.get('subtotal', 0))
    discount = float(data.get('discount', 0))
    net_subtotal = max(0.0, subtotal - discount)
    tax = 0.0  # Prices inclusive of all taxes
    shipping = 40.0 if net_subtotal < 500 else 0.0
    total = round(net_subtotal + tax + shipping, 2)
    payment_method = data.get('payment_method', 'Razorpay / UPI')
    is_cod = 'COD' in payment_method.upper() or 'CASH ON DELIVERY' in payment_method.upper()
    payment_status = 'Pending (COD)' if is_cod else 'Paid'
    
    order_code = f"HJM-{secrets.randbelow(90000) + 10000}"
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    customer_name = (customer.get('name') or session.get('user_name') or customer_email.split('@')[0]).strip()
    customer_phone = (customer.get('phone') or '9777166165').strip()
    shipping_address = f"{customer.get('address', '')}, {customer.get('city', '')}, {customer.get('state', '')} - {customer.get('pincode', '')}".strip(" ,-")

    # Remember customer in session
    session['user_email'] = customer_email
    session['user_name'] = customer_name

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

    # 1. Trigger admin email notification for EVERY order in background thread
    run_in_app_context(send_admin_order_email, order_dict)

    # 2. Trigger customer tax invoice and Thank You email directly to customer in background thread
    run_in_app_context(send_customer_order_invoice_email, order_dict)

    # 3. Clean up customer's abandoned cart entry from database upon completed checkout
    try:
        if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
            cursor.execute("DELETE FROM abandoned_carts WHERE user_email = %s", (customer_email,))
        else:
            db.execute("DELETE FROM abandoned_carts WHERE user_email = ?", (customer_email,))
            db.commit()
    except Exception as cart_clean_err:
        print("Completed order cart cleanup note:", cart_clean_err)

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
    email = session.get('user_email') or request.args.get('email')
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

@app.route('/api/orders/<int:order_id>/send-email', methods=['POST'])
@admin_required
def resend_order_email(order_id):
    db = get_db()
    if getattr(g, 'db_type', '') in ('mysql', 'postgres'):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
    else:
        cursor = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        r = cursor.fetchone()
        order = dict(r) if r else None

    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    order_dict = dict(order)
    order_dict['total'] = float(order_dict.get('total', 0))
    order_dict['subtotal'] = float(order_dict.get('subtotal', 0))
    order_dict['shipping'] = float(order_dict.get('shipping', 0))
    order_dict['discount'] = float(order_dict.get('discount', 0))

    if isinstance(order_dict.get('items_json'), str):
        try:
            order_dict['items'] = json.loads(order_dict['items_json'])
        except Exception:
            order_dict['items'] = []

    admin_sent = send_admin_order_email(order_dict, force=True)
    cust_sent = send_customer_order_invoice_email(order_dict)

    return jsonify({
        'success': True,
        'message': f"Emails dispatched for Order #{order_dict.get('order_code')}! (Admin Alert: {'Sent' if admin_sent else 'Check SMTP'}, Customer Invoice: {'Sent' if cust_sent else 'Check SMTP'})"
    })

@app.route('/api/admin/test-email', methods=['POST'])
@admin_required
def test_admin_email():
    test_subject = "🔔 Test Order Email Alert — Heena Imitation Jewellery"
    test_text = "This is a test notification confirming that email delivery is active and working properly!"
    test_html = """
    <div style="font-family: Arial, sans-serif; padding: 20px; background: #faf8f5; border: 1px solid #d4af37; border-radius: 8px;">
        <h2 style="color: #b8860b;">✅ Order Email Notification Test</h2>
        <p>This email confirms that your Heena Imitation Jewellery email notification system is properly connected and delivering emails reliably.</p>
        <p><strong>Configured Sender:</strong> heenaimitationjewellery06@gmail.com</p>
    </div>
    """
    sent = send_smtp_email(ADMIN_EMAIL, test_subject, test_text, test_html)
    backup_email = (os.environ.get('BACKUP_ADMIN_EMAIL') or 'mdsaad22410@gmail.com').strip()
    if backup_email and backup_email.lower() != ADMIN_EMAIL.lower():
        send_smtp_email(backup_email, test_subject, test_text, test_html)

    if sent:
        return jsonify({'success': True, 'message': f'Test email delivered successfully to {ADMIN_EMAIL}!'})
    else:
        return jsonify({'success': False, 'message': 'Failed to send test email. Please verify SMTP credentials.'}), 500

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
    db_engine = getattr(g, 'db_type', 'sqlite')

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
    db_engine = getattr(g, 'db_type', 'sqlite')

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
    else:
        rows_cursor = db.execute(f"SELECT * FROM [{safe_table}] LIMIT 100")
        rows = [dict(r) for r in rows_cursor.fetchall()]
        return jsonify({'success': True, 'table': safe_table, 'count': len(rows), 'rows': rows})

# Start background worker for 24h & 3-day abandoned cart reminders & auto-purge
try:
    start_cart_reminder_scheduler()
except Exception as sched_err:
    print("Scheduler start note:", sched_err)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Heena Imitation Jewellery Server starting on port {port} ...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
