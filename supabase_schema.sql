-- ==============================================================================
-- HEENA IMITATION JEWELLERS - SUPABASE POSTGRESQL DATABASE SCHEMA
-- ==============================================================================
-- Instructions:
-- 1. Open your Supabase project dashboard (https://supabase.com/dashboard)
-- 2. Go to the "SQL Editor" tab on the left sidebar
-- 3. Click "New Query"
-- 4. Paste this entire file and click "Run"
-- 5. In Netlify -> Site Settings -> Environment Variables, ensure DATABASE_URL
--    is set (either manually or automatically via the Netlify Supabase Integration).
-- ==============================================================================

-- 1. CATEGORIES TABLE
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    image TEXT NOT NULL,
    description TEXT NOT NULL
);

-- 2. PRODUCTS TABLE
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

-- 3. REVIEWS TABLE
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    rating INT NOT NULL,
    comment TEXT NOT NULL,
    date VARCHAR(50) NOT NULL
);

-- 4. ORDERS TABLE
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

-- 5. COUPONS TABLE
CREATE TABLE IF NOT EXISTS coupons (
    code VARCHAR(50) PRIMARY KEY,
    discount_type VARCHAR(20) NOT NULL,
    discount_value DECIMAL(10,2) NOT NULL,
    min_order DECIMAL(10,2) DEFAULT 0
);

-- 6. USERS TABLE (Email + Password + Google Auth)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NULL,
    name VARCHAR(100),
    created_at VARCHAR(50) NOT NULL,
    last_login VARCHAR(50) NOT NULL
);

-- 7. PASSWORD RESETS TABLE
CREATE TABLE IF NOT EXISTS password_resets (
    id SERIAL PRIMARY KEY,
    email VARCHAR(150) NOT NULL,
    token VARCHAR(100) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    is_used INT DEFAULT 0
);

-- ==============================================================================
-- INITIAL SEED DATA
-- ==============================================================================

-- Seed Categories
INSERT INTO categories (name, slug, image, description)
VALUES 
    ('Necklaces', 'necklaces', 'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80', 'Statement, Kundan & Choker Necklaces'),
    ('Earrings', 'earrings', 'https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80', 'Jhumkas, Chandbalis & Studs'),
    ('Pendants', 'pendants', 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=600&q=80', 'Minimal & Zircon Pendant Sets'),
    ('Bracelets', 'bracelets', 'https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=600&q=80', 'Antique Gold Cuffs & Bangles'),
    ('Rings', 'rings', 'https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=600&q=80', 'Solitaire & Cocktail Statement Rings'),
    ('Bridal Sets', 'bridal-sets', '/static/images/bridal_spotlight.jpg', 'Grand Maharani Bridal Kundan Sets'),
    ('Clutchers', 'clutchers', 'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=600&q=80', 'Embellished Hair Accessories & Clutchers'),
    ('Scrunchies & Garters', 'scrunchies-garters', 'https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=600&q=80', 'Luxury Satin Silk Scrunchies & Hair Garters')
ON CONFLICT (slug) DO NOTHING;

-- Seed Coupons
INSERT INTO coupons (code, discount_type, discount_value, min_order)
VALUES
    ('HEENA10', 'percentage', 10.0, 499.0),
    ('BRIDAL15', 'percentage', 15.0, 1999.0),
    ('FESTIVE200', 'flat', 200.0, 999.0),
    ('WELCOME500', 'flat', 500.0, 2499.0)
ON CONFLICT (code) DO NOTHING;

-- Seed Products
INSERT INTO products (
    name, category, price, original_price, discount_percent, rating, review_count,
    image, hover_image, description, specs, is_best_seller, is_new_arrival,
    is_bridal, color, material, occasion, stock
)
VALUES
    ('Royal Emerald Kundan Choker Set', 'Necklaces', 1899, 2999, 36, 4.9, 42,
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80',
     'Exquisite antique gold finish choker necklace studded with vibrant green emerald style Kundan stones and shell pearl drop beads. Comes with matching earrings.',
     '{"Material": "Brass Alloy", "Plating": "22k Antique Gold", "Stone": "Kundan & Faux Emerald", "Occasion": "Festive / Wedding", "Care": "Avoid direct spray of perfume or water"}',
     1, 1, 0, 'Green', 'Brass', 'Festive', 18),

    ('Heritage Temple Gold Necklace', 'Necklaces', 2499, 3999, 37, 4.8, 28,
     'https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'Traditional South Indian temple design necklace featuring intricate Goddess motif carving and antique champagne gold polish.',
     '{"Material": "High Grade Copper Alloy", "Plating": "Matt Antique Gold", "Stone": "Ruby Red CZ", "Occasion": "Festive / Pooja", "Care": "Store in airtight velvet pouch"}',
     1, 0, 0, 'Gold', 'Alloy', 'Festive', 12),

    ('Maharani Oversized Chandbali', 'Earrings', 1199, 1799, 33, 4.8, 31,
     'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80',
     'Crescent-shaped Chandbali earrings adorned with Kundan work and maroon bead droppings. Perfect pair for ethnic silk sarees.',
     '{"Material": "Brass", "Plating": "Gold Plated", "Stone": "Kundan & Maroon Beads", "Occasion": "Festive / Wedding", "Care": "Store in soft cotton pouch"}',
     1, 1, 0, 'Maroon', 'Kundan', 'Festive', 15),

    ('Rose Gold Zircon Huggie Studs', 'Earrings', 499, 799, 37, 4.6, 22,
     'https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80',
     'Sparkling rose gold polished zircon stud earrings designed for office wear and everyday casual sophistication.',
     '{"Material": "Copper", "Plating": "Rose Gold", "Stone": "American Diamond", "Occasion": "Daily Wear", "Care": "Clean gently with dry cloth"}',
     0, 0, 0, 'Rose Gold', 'Zircon', 'Daily', 30),

    ('Royal Solitaire Zircon Pendant Set', 'Pendants', 799, 1299, 38, 4.9, 39,
     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'Classic heart solitaire cubic zirconia pendant chain set in 18k champagne gold plating with matching stud earrings.',
     '{"Material": "Brass", "Plating": "18k Champagne Gold", "Stone": "CZ Diamond", "Occasion": "Daily / Gifting", "Care": "Keep in airtight box"}',
     1, 0, 0, 'Gold', 'Zircon', 'Daily', 20),

    ('Floral Enamel Kundan Pendant', 'Pendants', 699, 1099, 36, 4.7, 18,
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80',
     'Hand painted Meenakari enamel floral pendant with delicate Kundan center and gold beaded chain.',
     '{"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Meenakari & Kundan", "Occasion": "Festive", "Care": "Avoid chemical exposure"}',
     0, 1, 0, 'Maroon', 'Alloy', 'Festive', 16),

    ('Antique Gold Royal Bangle Set', 'Bracelets', 1299, 1999, 35, 4.8, 27,
     'https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80',
     'Set of 4 intricate antique gold bangles embossed with floral motifs and ruby CZ accents.',
     '{"Material": "Brass", "Plating": "Antique Gold", "Stone": "CZ Stones", "Occasion": "Festive / Wedding", "Care": "Wipe after wear"}',
     1, 0, 0, 'Gold', 'Brass', 'Festive', 22),

    ('Rose Gold CZ Crystal Cuff', 'Bracelets', 899, 1399, 35, 4.9, 14,
     'https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80',
     'Flexible openable wrist cuff with pavé set AAA cubic zirconia stones in radiant rose gold shine.',
     '{"Material": "Alloy", "Plating": "Rose Gold", "Stone": "Cubic Zirconia", "Occasion": "Daily / Party", "Care": "Do not submerge in water"}',
     0, 1, 0, 'Rose Gold', 'Zircon', 'Daily', 19),

    ('Solitaire Crown Adjustable Ring', 'Rings', 399, 699, 42, 4.8, 64,
     'https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80',
     'Stunning crown design solitaire ring with adjustable band, suitable for all finger sizes.',
     '{"Material": "Brass", "Plating": "Rhodium Gold", "Stone": "American Diamond", "Occasion": "Daily / Gifting", "Care": "Keep dry"}',
     1, 1, 0, 'Silver', 'Zircon', 'Daily', 50),

    ('Traditional Kundan Cocktail Ring', 'Rings', 599, 999, 40, 4.7, 33,
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80',
     'Statement oversized circular Kundan ring with pearl cluster border and adjustable ring base.',
     '{"Material": "Alloy", "Plating": "Antique Gold", "Stone": "Kundan & Pearls", "Occasion": "Festive / Wedding", "Care": "Store in soft box"}',
     0, 0, 0, 'Gold', 'Kundan', 'Festive', 28),

    ('Maharani Heritage Kundan Bridal Set', 'Bridal Sets', 4999, 7999, 37, 5.0, 48,
     '/static/images/bridal_spotlight.jpg',
     '/static/images/hero_banner.jpg',
     'Complete 7-Piece Luxury Royal Bridal Jewellery Set: Heavy Choker, Long Haar Necklace, Matching Chandbalis, Maang Tikka, Hathphool Bangles, and Nose Ring in 24k Gold Polish & Maroon Gemstones.',
     '{"Material": "Premium Brass Alloy", "Plating": "24k Matt Antique Gold", "Stone": "Heritage Kundan & Maroon Gemstones", "Occasion": "Bridal", "Care": "Store in padded velvet bridal box"}',
     1, 1, 1, 'Maroon', 'Kundan', 'Bridal', 10),

    ('Royal Velvet Ruby Kundan Bridal Set', 'Bridal Sets', 5499, 8999, 38, 4.9, 35,
     '/static/images/hero_banner.jpg',
     '/static/images/bridal_spotlight.jpg',
     'Opulent Rajputana style full bridal necklace set with cascading ruby drops, pearl clusters and matching heavy ear cuff jhumkas.',
     '{"Material": "Heavy Brass Alloy", "Plating": "Antique Champagne Gold", "Stone": "Ruby & Kundan Glass", "Occasion": "Bridal", "Care": "Keep dry and store safely"}',
     1, 0, 1, 'Maroon', 'Kundan', 'Bridal', 8),

    ('Royal Pearl Embellished Clutcher', 'Clutchers', 349, 599, 41, 4.6, 21,
     'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=800&q=80',
     'Heavy gold metal hair clutcher encrusted with lustrous faux pearls and shiny zircons.',
     '{"Material": "Metal Alloy", "Plating": "Gold Plated", "Stone": "Faux Pearl", "Occasion": "Daily / Festive", "Care": "Handle gently"}',
     1, 0, 0, 'Gold', 'Pearl', 'Daily', 45),

    ('Golden Crystal Butterfly Hair Clip', 'Clutchers', 299, 499, 40, 4.5, 18,
     'https://images.unsplash.com/photo-1603561591411-07134e71a2a9?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80',
     'Elegant butterfly shape hair pin with crystal rhinestones for hairstyles at parties and weddings.',
     '{"Material": "Alloy", "Plating": "Gold Finish", "Stone": "Rhinestone", "Occasion": "Festive / Party", "Care": "Avoid bending"}',
     0, 1, 0, 'Gold', 'Alloy', 'Festive', 35),

    ('Handcrafted Silk Satin Pearl Scrunchie', 'Scrunchies & Garters', 499, 799, 37, 4.9, 44,
     'https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80',
     'Premium silk satin hair scrunchie with faux pearl accents and comfortable elastic band.',
     '{"Material": "Fabric & Faux Pearls", "Plating": "N/A", "Stone": "Pearl Drops", "Occasion": "Festive / Bridal", "Care": "Store in soft box"}',
     1, 1, 1, 'Gold', 'Pearl', 'Bridal', 50),

    ('Antique Gold Floral Hair Garter', 'Scrunchies & Garters', 699, 1099, 36, 4.8, 29,
     'https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80',
     'https://images.unsplash.com/photo-1611591475140-be38b638edec?auto=format&fit=crop&w=800&q=80',
     'Traditional South Indian bun decoration hair garter with golden flower links and ruby accents.',
     '{"Material": "Brass", "Plating": "Antique Gold", "Stone": "Ruby CZ", "Occasion": "Bridal / Festive", "Care": "Wipe dry after use"}',
     0, 0, 1, 'Maroon', 'Brass', 'Bridal', 22);
