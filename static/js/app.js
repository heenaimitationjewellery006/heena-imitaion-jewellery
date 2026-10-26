/*
  Heena Imitation Jewellery - Customer Frontend Logic
  Passwordless Email-Only OTP Authentication (NO PHONE LOGIN), WhatsApp: 1234567890
*/

// --- Global State ---
const state = {
  shopName: 'Heena Imitation Jewellery',
  whatsappNumber: '919777166165',
  cart: JSON.parse(localStorage.getItem('hjm_cart') || '[]'),
  wishlist: JSON.parse(localStorage.getItem('hjm_wishlist') || '[]'),
  user: null,
  activeCoupon: JSON.parse(localStorage.getItem('hjm_coupon') || 'null'),
  theme: localStorage.getItem('hjm_theme') || 'light',
  productsCache: [],
  selectedPayMethod: 'upi'
};

// --- Supabase Cloud Database Configuration (Shared with Render Backend) ---
const SUPABASE_CONFIG = {
  url: 'https://voazarkrwulwfdqfqgyv.supabase.co',
  anonKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvYXphcmtyd3Vsd2ZkcWZxZ3l2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE2MjIzMDUsImV4cCI6MjEwNzE5ODMwNX0.WhjIl1EwTlPHVMwpawTXU0CAz4b4X0AJSyMgCwz1Eys'
};

function normalizeProduct(p) {
  if (!p) return null;
  let specs = p.specs;
  if (typeof specs === 'string') {
    try { specs = JSON.parse(specs); } catch (e) { specs = {}; }
  }
  return {
    ...p,
    id: Number(p.id),
    price: Number(p.price || 0),
    original_price: Number(p.original_price || p.price || 0),
    discount_percent: Number(p.discount_percent || 0),
    rating: Number(p.rating || 4.8),
    review_count: Number(p.review_count || 12),
    stock: Number(p.stock !== undefined ? p.stock : 25),
    is_best_seller: Number(p.is_best_seller || 0),
    is_new_arrival: Number(p.is_new_arrival || 0),
    is_bridal: Number(p.is_bridal || 0),
    specs: specs || {}
  };
}

let catalogFetchPromise = null;

async function getLiveCatalogProducts(forceRefresh = false) {
  if (!forceRefresh && state.productsCache && state.productsCache.length > 0) {
    return state.productsCache;
  }
  if (catalogFetchPromise && !forceRefresh) {
    return catalogFetchPromise;
  }

  catalogFetchPromise = (async () => {
    // 1. Try Live Supabase Cloud Database (Direct Global Edge CDN)
    try {
      const resp = await fetch(`${SUPABASE_CONFIG.url}/rest/v1/products?select=*&order=id.asc`, {
        headers: {
          'apikey': SUPABASE_CONFIG.anonKey,
          'Authorization': `Bearer ${SUPABASE_CONFIG.anonKey}`
        }
      });
      if (resp.ok) {
        const rows = await resp.json();
        if (Array.isArray(rows) && rows.length > 0) {
          const list = rows.map(normalizeProduct);
          state.productsCache = list;
          return list;
        }
      }
    } catch (err) {
      console.warn('Supabase cloud fetch notice, falling back:', err);
    }

    // 2. Try Backend API
    try {
      const res = await fetch('/api/products');
      const data = await res.json();
      const rawList = Array.isArray(data) ? data : (data.products || []);
      if (rawList.length > 0) {
        const list = rawList.map(normalizeProduct);
        state.productsCache = list;
        return list;
      }
    } catch (e) {}

    // 3. Resilient Static JSON Cache
    try {
      const res = await fetch('/static/data/products.json');
      const data = await res.json();
      const rawList = Array.isArray(data) ? data : (data.products || []);
      if (rawList.length > 0) {
        const list = rawList.map(normalizeProduct);
        state.productsCache = list;
        return list;
      }
    } catch (e) {}

    return state.productsCache || [];
  })();

  try {
    const res = await catalogFetchPromise;
    return res;
  } finally {
    catalogFetchPromise = null;
  }
}

async function getLiveCategories() {
  // 1. Live Supabase Cloud Categories
  try {
    const resp = await fetch(`${SUPABASE_CONFIG.url}/rest/v1/categories?select=*&order=id.asc`, {
      headers: {
        'apikey': SUPABASE_CONFIG.anonKey,
        'Authorization': `Bearer ${SUPABASE_CONFIG.anonKey}`
      }
    });
    if (resp.ok) {
      const rows = await resp.json();
      if (Array.isArray(rows) && rows.length > 0) return rows;
    }
  } catch (err) {
    console.warn('Supabase categories fetch notice:', err);
  }

  // 2. Try Backend API
  try {
    const res = await fetch('/api/categories');
    const data = await res.json();
    const list = Array.isArray(data) ? data : (data.categories || []);
    if (list.length > 0) return list;
  } catch (e) {}

  // 3. Fallback to static JSON
  try {
    const res = await fetch('/static/data/categories.json');
    const data = await res.json();
    const list = Array.isArray(data) ? data : (data.categories || []);
    if (list.length > 0) return list;
  } catch (e) {}

  return [];
}

// --- Initializer ---
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initHeroCarousel();

  try {
    checkCurrentCustomerUser();
    updateBadges();
    loadCategories();
    loadFeaturedProducts('newarrivals');
    fetchFilteredProducts();
  } catch (err) {
    console.error('App init warning:', err);
  }

  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get('reset_token');
  if (resetToken) {
    setTimeout(() => {
      openAuthModal();
      renderAuthResetView(resetToken);
    }, 300);
  }
});

async function checkCurrentCustomerUser() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    if (data.success && data.user) {
      state.user = data.user;
      updateBadges();
    }
  } catch (err) {
    console.error(err);
  }
}

// --- HERO CAROUSEL CONTROLLER ---
let currentHeroIndex = 0;
let heroTimer = null;

function initHeroCarousel() {
  const slides = document.querySelectorAll('.hero-slide');
  if (!slides.length) return;

  goToHeroSlide(currentHeroIndex || 0);
  startHeroTimer();

  const container = document.getElementById('heroSliderContainer');
  let touchStartX = 0;
  let touchEndX = 0;

  if (container && !container.dataset.carouselInit) {
    container.dataset.carouselInit = "true";
    container.addEventListener('mouseenter', () => {
      if (heroTimer) clearInterval(heroTimer);
    });
    container.addEventListener('mouseleave', () => startHeroTimer());
    container.addEventListener('touchstart', (e) => {
      if (heroTimer) clearInterval(heroTimer);
      if (e.changedTouches && e.changedTouches[0]) {
        touchStartX = e.changedTouches[0].screenX;
      }
    }, { passive: true });
    container.addEventListener('touchend', (e) => {
      if (e.changedTouches && e.changedTouches[0]) {
        touchEndX = e.changedTouches[0].screenX;
        if (touchStartX - touchEndX > 40) {
          moveHeroSlide(1);
        } else if (touchEndX - touchStartX > 40) {
          moveHeroSlide(-1);
        } else {
          startHeroTimer();
        }
      } else {
        startHeroTimer();
      }
    }, { passive: true });
  }
}

function startHeroTimer() {
  if (heroTimer) clearInterval(heroTimer);
  heroTimer = setInterval(() => {
    moveHeroSlide(1);
  }, 3000); // 3 seconds slideshow interval
}

function goToHeroSlide(index) {
  const slides = document.querySelectorAll('.hero-slide');
  const dots = document.querySelectorAll('.hero-dot');
  if (!slides.length) return;

  currentHeroIndex = (index + slides.length) % slides.length;
  slides.forEach((s, i) => {
    if (i === currentHeroIndex) {
      s.classList.add('active');
      s.style.opacity = '1';
      s.style.visibility = 'visible';
      s.style.zIndex = '2';
    } else {
      s.classList.remove('active');
      s.style.opacity = '0';
      s.style.visibility = 'hidden';
      s.style.zIndex = '1';
    }
  });

  dots.forEach((d, i) => {
    if (i === currentHeroIndex) {
      d.classList.add('active');
    } else {
      d.classList.remove('active');
    }
  });
}

function moveHeroSlide(direction) {
  goToHeroSlide(currentHeroIndex + direction);
  startHeroTimer(); // Reset 3s timer on manual slide click
}

// --- Router ---
function showPage(pageId) {
  document.querySelectorAll('.page-view').forEach(view => view.style.display = 'none');
  const target = document.getElementById(pageId);
  if (target) {
    target.style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.querySelectorAll('.nav-item a').forEach(a => a.classList.remove('active'));
  const activeNav = document.getElementById('nav-' + pageId.replace('-view', ''));
  if (activeNav) activeNav.classList.add('active');

  document.querySelectorAll('.mobile-nav-item').forEach(el => el.classList.remove('active'));
  const mNavId = pageId === 'home-view' ? 'mNavHome' : pageId === 'shop-view' ? 'mNavShop' : pageId === 'account-view' ? 'mNavAccount' : '';
  if (mNavId) {
    const mEl = document.getElementById(mNavId);
    if (mEl) mEl.classList.add('active');
  }

  if (pageId === 'home-view') initHeroCarousel();
  if (pageId === 'cart-view') renderFullCartPage();
  if (pageId === 'checkout-view') checkCheckoutAuth();
  if (pageId === 'account-view') renderAccountPortal();
}

// --- Theme ---
function initTheme() {
  document.documentElement.setAttribute('data-theme', state.theme);
  const icon = document.getElementById('themeIcon');
  if (icon) icon.className = state.theme === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
}

function toggleTheme() {
  state.theme = state.theme === 'light' ? 'dark' : 'light';
  localStorage.setItem('hjm_theme', state.theme);
  initTheme();
  showToast(`Switched to ${state.theme.toUpperCase()} mode`, 'info');
}

// --- Toast Notifications ---
function showToast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  let iconClass = 'fa-solid fa-circle-check';
  if (type === 'info') iconClass = 'fa-solid fa-circle-info';
  if (type === 'warning') iconClass = 'fa-solid fa-triangle-exclamation';
  if (type === 'error') iconClass = 'fa-solid fa-circle-xmark';

  toast.innerHTML = `<i class="${iconClass}" style="color: var(--accent-gold); font-size: 1.2rem;"></i> <span>${msg}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// --- Server Cart Sync (Debounced for Abandoned Cart Reminders) ---
let cartSyncTimeout = null;
function syncCartWithServer() {
  if (cartSyncTimeout) clearTimeout(cartSyncTimeout);
  cartSyncTimeout = setTimeout(async () => {
    try {
      if (state.user && state.user.is_logged_in) {
        await fetch('/api/cart/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cart: state.cart })
        });
      }
    } catch (e) {
      // Non-blocking background sync
    }
  }, 1200);
}

// --- Badges & Sync ---
function updateBadges() {
  localStorage.setItem('hjm_cart', JSON.stringify(state.cart));
  localStorage.setItem('hjm_wishlist', JSON.stringify(state.wishlist));

  const totalCartCount = state.cart.reduce((sum, item) => sum + item.qty, 0);
  const cartBadge = document.getElementById('cartBadge') || document.getElementById('cartCount');
  if (cartBadge) cartBadge.textContent = totalCartCount;
  const mobileCartBadge = document.getElementById('mobileCartBadge');
  if (mobileCartBadge) mobileCartBadge.textContent = totalCartCount;

  const wishlistBadge = document.getElementById('wishlistBadge') || document.getElementById('wishlistCount');
  if (wishlistBadge) wishlistBadge.textContent = state.wishlist.length;

  syncCartWithServer();
}

// --- Category Grid ---
async function loadCategories() {
  try {
    const categories = await getLiveCategories();
    if (categories && categories.length > 0) {
      const container = document.getElementById('categoryGridContainer');
      if (container) {
        container.innerHTML = categories.map(c => `
          <div class="category-card" onclick="filterByCategory('${c.name}')">
            <div class="category-thumb-wrapper">
              <img src="${c.image}" class="category-thumb-img" alt="${c.name}">
            </div>
            <div class="category-name">${c.name}</div>
          </div>
        `).join('');
      }
    }
  } catch (err) {
    console.error(err);
  }
}

// --- Featured Products ---
async function loadFeaturedProducts(tab) {
  const btnBest = document.getElementById('btn-tab-bestsellers');
  const btnNew = document.getElementById('btn-tab-newarrivals');
  if (btnBest && btnNew) {
    btnBest.style.backgroundColor = tab === 'bestsellers' ? 'var(--accent-gold)' : 'transparent';
    btnBest.style.color = tab === 'bestsellers' ? '#FFF' : 'var(--accent-gold)';
    btnNew.style.backgroundColor = tab === 'newarrivals' ? 'var(--accent-gold)' : 'transparent';
    btnNew.style.color = tab === 'newarrivals' ? '#FFF' : 'var(--accent-gold)';
  }

  try {
    const allProducts = await getLiveCatalogProducts();
    let prods = allProducts.slice();
    if (tab === 'bestsellers') {
      const filtered = prods.filter(p => p.is_best_seller);
      if (filtered.length > 0) prods = filtered;
      prods.sort((a, b) => b.id - a.id);
    } else if (tab === 'newarrivals') {
      const filtered = prods.filter(p => p.is_new_arrival);
      if (filtered.length > 0) prods = filtered;
      prods.sort((a, b) => b.id - a.id);
    }
    const container = document.getElementById('featuredProductsContainer');
    if (container) {
      container.innerHTML = prods.slice(0, 12).map(p => renderProductCardHTML(p)).join('');
    }
  } catch (err) {
    console.error(err);
  }
}

function renderProductCardHTML(p) {
  const isWishlisted = state.wishlist.includes(p.id);
  const starsHTML = Array(5).fill(0).map((_, i) => `<i class="fa-solid fa-star${i < Math.floor(p.rating) ? '' : '-half-stroke'}"></i>`).join('');
  const isNew = Boolean(p.is_new_arrival);

  return `
    <div class="product-card">
      ${isNew ? '<span style="position: absolute; top: 12px; left: 12px; background: #C9A15C; color: #161618; font-size: 0.72rem; font-weight: 800; padding: 3px 8px; border-radius: 4px; z-index: 2; letter-spacing: 0.05em; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">NEW</span>' : ''}
      <span class="badge-discount" style="${isNew ? 'top: 38px;' : ''}">-${p.discount_percent}% OFF</span>
      <button class="wishlist-toggle-btn ${isWishlisted ? 'active' : ''}" onclick="toggleWishlist(${p.id}, event)">
        <i class="fa-${isWishlisted ? 'solid' : 'regular'} fa-heart"></i>
      </button>

      <div class="product-img-box" onclick="showPDP(${p.id})">
        <img src="${p.image}" class="product-img" alt="${p.name}">
        <div class="quick-view-overlay">
          <button class="quick-btn" title="Quick View" onclick="event.stopPropagation(); openQuickView(${p.id})">
            <i class="fa-regular fa-eye"></i>
          </button>
          <button class="quick-btn" title="Add to Cart" onclick="event.stopPropagation(); addToCart(${p.id})">
            <i class="fa-solid fa-bag-shopping"></i>
          </button>
        </div>
      </div>

      <div class="product-info">
        <span class="product-category-tag">${p.category}</span>
        <h3 class="product-title" title="${p.name}" onclick="showPDP(${p.id})" style="cursor: pointer;">${p.name}</h3>
        
        <div class="rating-box">
          ${starsHTML}
          <span class="rating-count">(${p.review_count})</span>
        </div>

        <div class="price-box">
          <span class="current-price">₹${p.price.toLocaleString('en-IN')}</span>
          <span class="original-price">₹${p.original_price.toLocaleString('en-IN')}</span>
        </div>
      </div>
    </div>
  `;
}

// --- Filter Engine ---
function updatePriceSlider(val) {
  const lbl = document.getElementById('priceMaxLabel');
  if (lbl) lbl.textContent = `Up to ₹${parseInt(val).toLocaleString('en-IN')}`;
}

function filterByCategory(categoryName) {
  showPage('shop-view');
  const rads = document.querySelectorAll('input[name="filterCategory"]');
  rads.forEach(r => {
    r.checked = (r.value.toLowerCase() === categoryName.toLowerCase());
  });
  fetchFilteredProducts();
}

function resetFilters() {
  document.querySelectorAll('input[name="filterCategory"]')[0].checked = true;
  const slider = document.getElementById('priceRange');
  if (slider) slider.value = 6000;
  updatePriceSlider(6000);
  fetchFilteredProducts();
}

async function fetchFilteredProducts() {
  const cat = document.querySelector('input[name="filterCategory"]:checked')?.value || 'all';
  const maxPrice = parseFloat(document.getElementById('priceRange')?.value || 6000);
  const sort = document.getElementById('sortSelect')?.value || 'popularity';

  try {
    const allProducts = await getLiveCatalogProducts();
    let prods = allProducts.slice();
    if (cat !== 'all') {
      prods = prods.filter(p => p.category && p.category.toLowerCase() === cat.toLowerCase());
    }
    prods = prods.filter(p => p.price <= maxPrice);

    if (sort === 'price_asc' || sort === 'price-low') prods.sort((a,b) => a.price - b.price);
    else if (sort === 'price_desc' || sort === 'price-high') prods.sort((a,b) => b.price - a.price);
    else if (sort === 'rating') prods.sort((a,b) => b.rating - a.rating);
    else if (sort === 'newest') prods.sort((a,b) => (b.is_new_arrival - a.is_new_arrival) || (b.id - a.id));
    else prods.sort((a,b) => (b.is_best_seller - a.is_best_seller) || (b.rating - a.rating));

    state.productsCache = allProducts;
    const grid = document.getElementById('shopProductsGrid');
    const title = document.getElementById('shopCategoryTitle');
    const count = document.getElementById('shopProductsCount');

    if (title) title.textContent = cat === 'all' ? 'All Imitation Jewellery' : cat;
    if (count) count.textContent = `Showing ${prods.length} products`;

    if (grid) {
      if (prods.length === 0) {
        grid.innerHTML = `
          <div style="grid-column: 1/-1; text-align: center; padding: 60px 0;">
            <i class="fa-solid fa-gem" style="font-size: 3rem; color: var(--border-color); margin-bottom: 16px;"></i>
            <h3 style="font-size: 1.4rem;">No matching jewellery found</h3>
            <button class="btn-gold" onclick="resetFilters()">Reset Filters</button>
          </div>
        `;
      } else {
        grid.innerHTML = prods.map(p => renderProductCardHTML(p)).join('');
      }
    }
  } catch (err) {
    console.error(err);
  }
}

// --- Live Search ---
let searchDebounceTimer;
function handleLiveSearch(e) {
  const query = e.target.value.trim();
  const dropdown = document.getElementById('searchResultsDropdown');
  if (!dropdown) return;

  clearTimeout(searchDebounceTimer);
  if (query.length < 2) {
    dropdown.classList.remove('active');
    return;
  }

  searchDebounceTimer = setTimeout(async () => {
    try {
      const allProducts = await getLiveCatalogProducts();
      const term = query.toLowerCase();
      const matches = allProducts.filter(p =>
        (p.name && p.name.toLowerCase().includes(term)) ||
        (p.category && p.category.toLowerCase().includes(term)) ||
        (p.description && p.description.toLowerCase().includes(term))
      );
      if (matches.length > 0) {
        dropdown.innerHTML = matches.slice(0, 5).map(p => `
          <div class="search-item" onclick="showPDP(${p.id}); document.getElementById('searchResultsDropdown').classList.remove('active');">
            <img src="${p.image}" alt="${p.name}">
            <div>
              <div style="font-weight: 600; font-size: 0.9rem;">${p.name}</div>
              <div style="font-size: 0.8rem; color: var(--accent-gold); font-weight: 700;">₹${p.price.toLocaleString('en-IN')}</div>
            </div>
          </div>
        `).join('');
        dropdown.classList.add('active');
      } else {
        dropdown.innerHTML = `<div style="padding: 14px; text-align: center; color: var(--text-muted); font-size: 0.9rem;">No matching jewellery found</div>`;
        dropdown.classList.add('active');
      }
    } catch (err) {
      console.error(err);
    }
  }, 250);
}

// --- PDP & Quick View ---
async function getProductById(productId) {
  const allProducts = await getLiveCatalogProducts();
  const match = allProducts.find(item => item.id == productId);
  if (match) return { product: match, reviews: [] };
  try {
    const res = await fetch(`/api/products/${productId}`);
    const data = await res.json();
    if (data.product) return { product: normalizeProduct(data.product), reviews: data.reviews || [] };
    if (data.products) {
      const p = data.products.find(item => item.id == productId);
      if (p) return { product: normalizeProduct(p), reviews: [] };
    }
  } catch (e) {}
  return { product: null, reviews: [] };
}

async function openQuickView(productId) {
  try {
    const data = await getProductById(productId);
    if (data.product) {
      const content = document.getElementById('quickViewContent');
      if (content) {
        content.innerHTML = renderPDPContentHTML(data.product, data.reviews);
        openModal('quickViewModal');
      }
    }
  } catch (err) {
    console.error(err);
  }
}

async function showPDP(productId) {
  closeModal('quickViewModal');
  showPage('pdp-view');
  try {
    const data = await getProductById(productId);
    if (data.product) {
      const container = document.getElementById('pdpContentContainer');
      if (container) {
        container.innerHTML = renderPDPContentHTML(data.product, data.reviews);
      }
    }
  } catch (err) {
    console.error(err);
  }
}

function renderPDPContentHTML(p, reviews = []) {
  const isWishlisted = state.wishlist.includes(p.id);
  const specs = p.specs || {};

  return `
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 36px; align-items: start;">
      <div>
        <div style="width: 100%; height: 380px; border-radius: var(--radius-md); overflow: hidden; border: 1px solid var(--border-color); margin-bottom: 14px; background-color: var(--bg-secondary);">
          <img id="mainPdpImage" src="${p.image}" style="width: 100%; height: 100%; object-fit: cover;" alt="${p.name}">
        </div>
        <div style="display: flex; gap: 10px;">
          <img src="${p.image}" onclick="document.getElementById('mainPdpImage').src='${p.image}'" style="width: 70px; height: 70px; object-fit: cover; border-radius: var(--radius-sm); border: 2px solid var(--accent-gold); cursor: pointer;">
          <img src="${p.hover_image}" onclick="document.getElementById('mainPdpImage').src='${p.hover_image}'" style="width: 70px; height: 70px; object-fit: cover; border-radius: var(--radius-sm); border: 1px solid var(--border-color); cursor: pointer;">
        </div>
      </div>

      <div>
        <span style="font-size: 0.8rem; text-transform: uppercase; color: var(--accent-gold); font-weight: 700; letter-spacing: 0.1em;">${p.category} • ${p.occasion}</span>
        <h1 class="serif-font" style="font-size: 2rem; margin: 8px 0; color: var(--text-main);">${p.name}</h1>
        
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
          <div style="color: #F1C40F; font-size: 0.95rem;"><i class="fa-solid fa-star"></i> <strong>${p.rating}</strong></div>
          <span style="color: var(--text-muted); font-size: 0.9rem;">(${p.review_count} Customer Reviews)</span>
          <span style="background-color: #27AE60; color: white; font-size: 0.75rem; font-weight: 700; padding: 2px 8px; border-radius: var(--radius-sm);">In Stock</span>
        </div>

        <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 20px;">
          <span style="font-size: 2rem; font-weight: 700; color: var(--brand-maroon);">₹${p.price.toLocaleString('en-IN')}</span>
          <span style="font-size: 1.1rem; color: var(--text-muted); text-decoration: line-through;">₹${p.original_price.toLocaleString('en-IN')}</span>
          <span style="background-color: var(--brand-maroon); color: white; font-size: 0.85rem; font-weight: 700; padding: 4px 10px; border-radius: var(--radius-sm);">${p.discount_percent}% OFF</span>
        </div>

        <p style="color: var(--text-muted); line-height: 1.7; margin-bottom: 24px;">${p.description}</p>

        <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 16px;">
          <div class="cart-qty-ctrl" style="padding: 6px;">
            <button class="cart-qty-btn" onclick="adjustPdpQty(-1)">-</button>
            <span class="cart-qty-val" id="pdpQtyVal" style="font-weight: 700;">1</span>
            <button class="cart-qty-btn" onclick="adjustPdpQty(1)">+</button>
          </div>

          <button class="btn-gold" style="flex-grow: 1;" onclick="addToCart(${p.id}, parseInt(document.getElementById('pdpQtyVal').textContent))">
            Add To Cart <i class="fa-solid fa-bag-shopping"></i>
          </button>
          
          <button class="wishlist-toggle-btn ${isWishlisted ? 'active' : ''}" style="position: static; width: 48px; height: 48px;" onclick="toggleWishlist(${p.id}, event)">
            <i class="fa-${isWishlisted ? 'solid' : 'regular'} fa-heart"></i>
          </button>
        </div>

        <button class="btn-gold btn-maroon" style="width: 100%; margin-bottom: 10px;" onclick="addToCart(${p.id}, 1); showPage('checkout-view');">
          Buy Now Instant Checkout <i class="fa-solid fa-bolt"></i>
        </button>

        <button class="btn-gold" style="width: 100%; background-color: #25D366; color: white;" onclick="orderProductOnWhatsApp('${p.name.replace(/'/g, "\\'")}', ${p.price})">
          Order via WhatsApp (1234567890) <i class="fa-brands fa-whatsapp"></i>
        </button>
      </div>
    </div>
  `;
}

function adjustPdpQty(delta) {
  const el = document.getElementById('pdpQtyVal');
  if (el) {
    let current = parseInt(el.textContent) || 1;
    el.textContent = Math.max(1, current + delta);
  }
}

// --- Cart Engine ---
async function addToCart(productId, qty = 1) {
  let product = (state.productsCache || []).find(p => p.id === productId);
  if (!product) {
    const data = await getProductById(productId);
    product = data?.product;
  }
  if (!product) return;

  const existing = state.cart.find(item => item.id === productId);
  if (existing) existing.qty += qty;
  else state.cart.push({ id: product.id, name: product.name, price: product.price, original_price: product.original_price, image: product.image, qty: qty });

  updateBadges();
  showToast(`Added '${product.name}' to Cart!`);
  openCartDrawer();
}

function toggleCartDrawer() {
  const drawer = document.getElementById('cartDrawer');
  if (drawer) {
    drawer.classList.toggle('active');
    if (drawer.classList.contains('active')) renderCartDrawer();
  }
}

function openCartDrawer() {
  const drawer = document.getElementById('cartDrawer');
  if (drawer) {
    drawer.classList.add('active');
    renderCartDrawer();
  }
}

function updateCartQty(index, delta) {
  if (state.cart[index]) {
    state.cart[index].qty += delta;
    if (state.cart[index].qty <= 0) state.cart.splice(index, 1);
    updateBadges();
    renderCartDrawer();
    renderFullCartPage();
  }
}

function renderCartDrawer() {
  const body = document.getElementById('cartDrawerBody');
  const footer = document.getElementById('cartDrawerFooter');

  if (!body || !footer) return;

  if (state.cart.length === 0) {
    body.innerHTML = `
      <div style="text-align: center; padding: 60px 0;">
        <i class="fa-solid fa-bag-shopping" style="font-size: 3rem; color: var(--border-color); margin-bottom: 16px;"></i>
        <p style="color: var(--text-muted); font-size: 1.1rem;">Your bag is empty.</p>
        <button class="btn-gold" style="margin-top: 18px;" onclick="toggleCartDrawer(); showPage('shop-view');">Explore Jewellery</button>
      </div>
    `;
    footer.innerHTML = '';
    return;
  }

  body.innerHTML = state.cart.map((item, idx) => `
    <div class="cart-item">
      <img src="${item.image}" class="cart-item-img" alt="${item.name}">
      <div class="cart-item-info">
        <div style="font-weight: 600; font-size: 0.95rem; line-height: 1.3;">${item.name}</div>
        <div style="color: var(--brand-maroon); font-weight: 700; margin-top: 4px;">₹${item.price.toLocaleString('en-IN')}</div>
        <div class="cart-qty-ctrl">
          <button class="cart-qty-btn" onclick="updateCartQty(${idx}, -1)">-</button>
          <span class="cart-qty-val">${item.qty}</span>
          <button class="cart-qty-btn" onclick="updateCartQty(${idx}, 1)">+</button>
        </div>
      </div>
      <button style="color: var(--text-muted); font-size: 1rem; align-self: flex-start;" onclick="updateCartQty(${idx}, -${item.qty})"><i class="fa-solid fa-trash-can"></i></button>
    </div>
  `).join('');

  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
  const freeShipGap = Math.max(0, 500 - subtotal);

  footer.innerHTML = `
    ${freeShipGap > 0 ? `<p style="font-size: 0.8rem; color: var(--brand-maroon); font-weight: 600; text-align: center; margin-bottom: 10px;">Add ₹${freeShipGap} more for FREE Delivery!</p>` : `<p style="font-size: 0.8rem; color: #27AE60; font-weight: 700; text-align: center; margin-bottom: 10px;">🎉 FREE Delivery Unlocked!</p>`}
    <div class="cart-summary-row"><span>Subtotal</span><span>₹${subtotal.toLocaleString('en-IN')}</span></div>
    <button class="btn-gold" style="width: 100%; margin-top: 14px;" onclick="toggleCartDrawer(); showPage('checkout-view');">
      Proceed to Checkout <i class="fa-solid fa-arrow-right"></i>
    </button>
  `;
}

function renderFullCartPage() {
  const container = document.getElementById('fullCartContainer');
  if (!container) return;

  if (state.cart.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 60px 0;">
        <p style="font-size: 1.2rem; color: var(--text-muted);">Your cart is currently empty.</p>
        <button class="btn-gold" style="margin-top: 16px;" onclick="showPage('shop-view')">Shop Now</button>
      </div>
    `;
    return;
  }

  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);

  container.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 360px; gap: 40px;">
      <div>
        ${state.cart.map((item, idx) => `
          <div style="display: flex; gap: 20px; align-items: center; padding: 20px; background-color: var(--bg-card); border-radius: var(--radius-md); border: 1px solid var(--border-color); margin-bottom: 14px;">
            <img src="${item.image}" style="width: 90px; height: 90px; object-fit: cover; border-radius: var(--radius-sm);" alt="${item.name}">
            <div style="flex-grow: 1;">
              <h3 style="font-size: 1.1rem; font-weight: 600;">${item.name}</h3>
              <div style="color: var(--brand-maroon); font-weight: 700; margin-top: 4px;">₹${item.price.toLocaleString('en-IN')}</div>
            </div>
            <div class="cart-qty-ctrl">
              <button class="cart-qty-btn" onclick="updateCartQty(${idx}, -1)">-</button>
              <span class="cart-qty-val" style="font-weight: 700;">${item.qty}</span>
              <button class="cart-qty-btn" onclick="updateCartQty(${idx}, 1)">+</button>
            </div>
            <div style="font-weight: 700; width: 100px; text-align: right;">₹${(item.price * item.qty).toLocaleString('en-IN')}</div>
          </div>
        `).join('')}
      </div>

      <div style="background-color: var(--bg-card); padding: 24px; border-radius: var(--radius-md); border: 1px solid var(--border-color); height: fit-content;">
        <h3 style="font-size: 1.2rem; margin-bottom: 16px;">Order Summary</h3>
        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;"><span>Subtotal</span><span>₹${subtotal.toLocaleString('en-IN')}</span></div>
        <div style="margin: 16px 0;">
          <label style="font-size: 0.85rem; font-weight: 600;">Promo Code</label>
          <div style="display: flex; gap: 8px; margin-top: 6px;">
            <input type="text" id="couponInput" placeholder="HEENA10" style="padding: 8px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); width: 100%; text-transform: uppercase;">
            <button class="btn-gold btn-outline-gold" onclick="applyPromoCode()">Apply</button>
          </div>
        </div>
        <button class="btn-gold" style="width: 100%;" onclick="showPage('checkout-view')">Proceed to Checkout</button>
      </div>
    </div>
  `;
}

async function applyPromoCode() {
  const code = document.getElementById('couponInput')?.value || '';
  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
  try {
    const res = await fetch('/api/coupons/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code, subtotal: subtotal })
    });
    const data = await res.json();
    if (data.success) {
      state.activeCoupon = data;
      localStorage.setItem('hjm_coupon', JSON.stringify(data));
      showToast(data.message);
      renderFullCartPage();
    } else showToast(data.message, 'error');
  } catch (err) {
    showToast('Failed to validate coupon', 'error');
  }
}

// --- Customer Checkout Authorization ---
function checkCheckoutAuth() {
  if (!state.user || !state.user.is_logged_in) {
    showToast('Please log in with passwordless Email OTP before placing an order', 'warning');
    openAuthModal();
    return;
  }
  renderCheckoutPage();
}

function renderCheckoutPage() {
  const itemsContainer = document.getElementById('checkoutSummaryItems');
  const totalsContainer = document.getElementById('checkoutSummaryTotals');
  if (!itemsContainer || !totalsContainer) return;

  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
  const discount = state.activeCoupon ? state.activeCoupon.discount_amount : 0;
  const netSubtotal = Math.max(0, subtotal - discount);
  const shipping = netSubtotal < 500 ? 40 : 0;
  const tax = 0; // Prices inclusive of all taxes
  const total = roundVal(netSubtotal + tax + shipping);

  if (state.user) {
    const emailEl = document.getElementById('chkEmail');
    const nameEl = document.getElementById('chkName');
    if (emailEl) emailEl.value = state.user.email || '';
    if (nameEl && !nameEl.value) nameEl.value = state.user.name || '';
  }

  itemsContainer.innerHTML = state.cart.map(item => `
    <div style="display: flex; justify-content: space-between; font-size: 0.9rem; margin-bottom: 8px;">
      <span>${item.name} (x${item.qty})</span>
      <span>₹${(item.price * item.qty).toLocaleString('en-IN')}</span>
    </div>
  `).join('');

  totalsContainer.innerHTML = `
    <div style="display: flex; justify-content: space-between; font-size: 0.9rem; margin-bottom: 6px;"><span>Subtotal</span><span>₹${subtotal.toLocaleString('en-IN')}</span></div>
    ${discount > 0 ? `<div style="display: flex; justify-content: space-between; font-size: 0.9rem; color: #27AE60; margin-bottom: 6px;"><span>Coupon Discount</span><span>-₹${discount}</span></div>` : ''}
    <div style="display: flex; justify-content: space-between; font-size: 0.9rem; margin-bottom: 6px;"><span>Delivery Charge</span><span>${shipping === 0 ? '<strong style="color: #27AE60;">FREE</strong>' : '₹' + shipping}</span></div>
    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #64748B; margin-bottom: 6px;"><span>GST / Taxes</span><span>Included in Price</span></div>
    <div class="cart-total-row" style="display: flex; justify-content: space-between;"><span>Total Payable</span><span>₹${total.toLocaleString('en-IN')}</span></div>
  `;
}

function handleProceedToPayment(event) {
  event.preventDefault();

  if (!state.user || !state.user.is_logged_in) {
    showToast('Please sign in to your account to proceed to payment!', 'warning');
    openAuthModal();
    return;
  }

  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
  const discount = state.activeCoupon ? state.activeCoupon.discount_amount : 0;
  const netSubtotal = Math.max(0, subtotal - discount);
  const shipping = netSubtotal < 500 ? 40 : 0;
  const tax = 0;
  const total = roundVal(netSubtotal + tax + shipping);

  document.getElementById('rzpTotalAmount').textContent = `₹${total.toLocaleString('en-IN')}`;
  
  const upiPa = '9777166165@ybl';
  const upiPn = encodeURIComponent('Heena Imitation Jewellery');
  const upiQrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=upi://pay?pa=${upiPa}%26pn=${upiPn}%26am=${total}%26cu=INR`;
  const qrImg = document.getElementById('upiQrCodeImg');
  if (qrImg) qrImg.src = upiQrUrl;

  openModal('razorpayModal');
}

function selectPayOption(method) {
  state.selectedPayMethod = method;
  document.querySelectorAll('.payment-option-card').forEach(c => c.classList.remove('selected'));
  const target = document.getElementById('opt-' + method);
  if (target) target.classList.add('selected');

  const upiBox = document.getElementById('directUpiContainer');
  if (upiBox) upiBox.style.display = (method === 'upi') ? 'block' : 'none';
}

async function executeRazorpayPayment() {
  const phoneEl = document.getElementById('chkPhone');
  const customer = {
    name: document.getElementById('chkName').value,
    email: document.getElementById('chkEmail').value,
    phone: phoneEl ? phoneEl.value.trim() : '9777166165',
    address: document.getElementById('chkAddress').value,
    city: document.getElementById('chkCity').value,
    state: document.getElementById('chkState').value,
    pincode: document.getElementById('chkPincode').value
  };

  const subtotal = state.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
  const discount = state.activeCoupon ? state.activeCoupon.discount_amount : 0;

  try {
    const res = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer: customer,
        items: state.cart,
        subtotal: subtotal,
        discount: discount,
        payment_method: state.selectedPayMethod.toUpperCase()
      })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('razorpayModal');
      state.cart = [];
      state.activeCoupon = null;
      localStorage.removeItem('hjm_coupon');
      updateBadges();

      renderOrderConfirmation(data);
      showPage('order-success-view');
      showToast('Order Placed Successfully!', 'success');
    } else {
      showToast(data.message, 'error');
    }
  } catch (err) {
    showToast('Order creation failed', 'error');
  }
}

function renderOrderConfirmation(data) {
  const container = document.getElementById('orderSuccessContainer');
  if (!container) return;

  container.innerHTML = `
    <i class="fa-solid fa-circle-check" style="font-size: 4rem; color: #27AE60; margin-bottom: 16px;"></i>
    <h2 class="serif-font" style="font-size: 2.2rem; color: var(--brand-maroon);">Order Confirmed!</h2>
    <p style="color: var(--text-muted); font-size: 1.05rem; margin-bottom: 24px;">Thank you for shopping with ${state.shopName}.</p>

    <div style="background-color: var(--bg-secondary); padding: 20px; border-radius: var(--radius-md); text-align: left; margin-bottom: 24px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px;"><strong>Order ID:</strong><span style="font-weight: 700; color: var(--accent-gold);">${data.order_code}</span></div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px;"><strong>Total Amount:</strong><span>₹${data.total.toLocaleString('en-IN')} (${data.payment_status || 'Paid'})</span></div>
      <div style="display: flex; justify-content: space-between;"><strong>Estimated Delivery:</strong><span>3-5 Business Days</span></div>
    </div>

    <div style="display: flex; justify-content: space-between; position: relative; margin-bottom: 32px; padding: 0 10px;">
      <div style="text-align: center;"><div style="width: 36px; height: 36px; background-color: var(--brand-maroon); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;"><i class="fa-solid fa-check"></i></div><span style="font-size: 0.8rem; font-weight: 600;">Placed</span></div>
      <div style="text-align: center;"><div style="width: 36px; height: 36px; background-color: var(--accent-gold); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;"><i class="fa-solid fa-box-open"></i></div><span style="font-size: 0.8rem; font-weight: 600;">Processing</span></div>
      <div style="text-align: center;"><div style="width: 36px; height: 36px; background-color: var(--border-color); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;"><i class="fa-solid fa-truck"></i></div><span style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">Shipped</span></div>
      <div style="text-align: center;"><div style="width: 36px; height: 36px; background-color: var(--border-color); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 6px auto;"><i class="fa-solid fa-house"></i></div><span style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">Delivered</span></div>
    </div>

    <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
      <button class="btn-gold" onclick="showPage('shop-view')">Continue Shopping</button>
      <button class="btn-gold btn-outline-gold" onclick="viewOrderInvoice('${data.order_code}')"><i class="fa-solid fa-file-invoice"></i> View / Print Invoice</button>
      <button class="btn-gold" style="background-color: #25D366; color: white;" onclick="shareOrderOnWhatsApp('${data.order_code}', ${data.total})"><i class="fa-brands fa-whatsapp"></i> Share on WhatsApp</button>
    </div>
  `;
}

async function viewOrderInvoice(orderCode) {
  try {
    const res = await fetch('/api/orders/code/' + orderCode + '/invoice');
    const data = await res.json();
    if (data.success && data.order) {
      const o = data.order;
      const g = data.gst_info;
      const invoiceWin = window.open('', '_blank');
      const itemsHtml = o.items.map(i => `
        <tr>
          <td style="padding: 10px; border-bottom: 1px solid #EEE;">${i.name}</td>
          <td style="padding: 10px; border-bottom: 1px solid #EEE; text-align: center;">${i.qty}</td>
          <td style="padding: 10px; border-bottom: 1px solid #EEE; text-align: right;">₹${i.price}</td>
          <td style="padding: 10px; border-bottom: 1px solid #EEE; text-align: right;">₹${i.price * i.qty}</td>
        </tr>
      `).join('');

      invoiceWin.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Order Invoice #${o.order_code} - Heena Imitation Jewellery</title>
          <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; padding: 40px; color: #333; max-width: 800px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; border-bottom: 2px solid #C9A15C; padding-bottom: 20px; margin-bottom: 30px; }
            .brand-name { font-size: 24px; font-weight: bold; color: #6B1E2E; }
            .invoice-title { font-size: 20px; font-weight: bold; color: #C9A15C; }
            .details-grid { display: flex; justify-content: space-between; margin-bottom: 30px; font-size: 14px; }
            table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
            th { background-color: #6B1E2E; color: white; padding: 10px; text-align: left; }
            .summary { float: right; width: 300px; font-size: 14px; }
            .summary-row { display: flex; justify-content: space-between; padding: 6px 0; }
            .total-row { font-weight: bold; font-size: 16px; border-top: 2px solid #6B1E2E; padding-top: 10px; }
          </style>
        </head>
        <body>
          <div class="header">
            <div>
              <div class="brand-name">${g.business_name}</div>
              <div style="font-size: 13px; color: #666; margin-top: 4px;">GSTIN: ${g.gstin}</div>
              <div style="font-size: 13px; color: #666;">Support: ${g.support_email} | ${g.support_phone}</div>
            </div>
            <div style="text-align: right;">
              <div class="invoice-title">OFFICIAL INVOICE</div>
              <div style="margin-top: 6px; font-size: 14px;"><strong>Order ID:</strong> #${o.order_code}</div>
              <div style="font-size: 13px; color: #666;"><strong>Date:</strong> ${o.created_at}</div>
            </div>
          </div>

          <div class="details-grid">
            <div>
              <strong>Billed To:</strong><br>
              ${o.customer_name}<br>
              Email: ${o.customer_email}<br>
              Phone: ${o.customer_phone}
            </div>
            <div>
              <strong>Delivery Address:</strong><br>
              ${o.shipping_address}<br>
              <strong>Payment Method:</strong> ${o.payment_method}<br>
              <strong>Payment Status:</strong> ${o.payment_status}
            </div>
          </div>

          <table>
            <thead>
              <tr>
                <th>Item Description</th>
                <th style="text-align: center;">Qty</th>
                <th style="text-align: right;">Unit Price</th>
                <th style="text-align: right;">Total</th>
              </tr>
            </thead>
            <tbody>
              ${itemsHtml}
            </tbody>
          </table>

          <div class="summary">
            <div class="summary-row"><span>Subtotal:</span><span>₹${o.subtotal}</span></div>
            <div class="summary-row"><span>Discount:</span><span>-₹${o.discount}</span></div>
            <div class="summary-row"><span>Shipping:</span><span>₹${o.shipping}</span></div>
            <div class="summary-row total-row"><span>Total Amount:</span><span>₹${o.total}</span></div>
          </div>

          <div style="clear: both; margin-top: 60px; text-align: center; font-size: 12px; color: #888;">
            Thank you for shopping with Heena Imitation Jewellery!
          </div>
          <script>window.print();</script>
        </body>
        </html>
      `);
      invoiceWin.document.close();
    } else {
      showToast('Could not load invoice data.', 'error');
    }
  } catch (err) {
    showToast('Failed to generate invoice.', 'error');
  }
}

// --- Wishlist ---
function toggleWishlist(productId, event) {
  if (event) event.stopPropagation();
  const idx = state.wishlist.indexOf(productId);
  if (idx > -1) {
    state.wishlist.splice(idx, 1);
    showToast('Removed from Wishlist', 'info');
  } else {
    state.wishlist.push(productId);
    showToast('Saved to Wishlist!', 'success');
  }
  updateBadges();
  fetchFilteredProducts();
}

// --- CUSTOMER AUTHENTICATION SYSTEM (GOOGLE SIGN-IN & EMAIL + PASSWORD) ---

function openAuthModal() {
  const content = document.getElementById('authModalContent');
  if (!content) return;

  if (state.user && state.user.is_logged_in) {
    content.innerHTML = `
      <h2 class="serif-font" style="color: var(--brand-maroon); margin-bottom: 12px;">Customer Account</h2>
      <p style="color: var(--text-muted); margin-bottom: 16px;">Logged in as <strong>${state.user.email}</strong></p>
      <button class="btn-gold" onclick="closeModal('authModal'); showPage('account-view');">My Account Dashboard</button>
      <button class="btn-gold btn-maroon" style="margin-top: 10px; width: 100%;" onclick="handleCustomerLogout()">Logout Session</button>
    `;
  } else {
    renderAuthLoginView();
  }
  openModal('authModal');
}

window.handleGoogleSignInCallback = async function(response) {
  if (!response || !response.credential) return;
  showToast('Authenticating with Google...', 'info');

  try {
    const res = await fetch('/api/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential: response.credential })
    });
    const data = await res.json();
    if (data.success) {
      state.user = data.user;
      updateBadges();
      closeModal('authModal');
      showToast(data.message);
      showPage('account-view');
    } else {
      showToast(data.message || 'Google Sign-In failed', 'error');
    }
  } catch (err) {
    showToast('Google Sign-In server error', 'error');
  }
};

function renderAuthLoginView() {
  const content = document.getElementById('authModalContent');
  if (!content) return;

  content.innerHTML = `
    <h2 class="serif-font" style="color: var(--brand-maroon); margin-bottom: 8px;">Customer Sign In</h2>
    <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 18px;">Sign in with Google or enter your Email and Password below.</p>
    
    <!-- Option 1: Official Google Sign-In Container -->
    <div style="margin-bottom: 18px; display: flex; justify-content: center;">
      <div id="googleBtnContainer" class="g_id_signin"></div>
    </div>

    <div style="display: flex; align-items: center; margin: 16px 0; color: var(--text-muted); font-size: 0.75rem;">
      <div style="flex: 1; height: 1px; background: var(--border-color);"></div>
      <span style="padding: 0 10px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em;">OR EMAIL & PASSWORD</span>
      <div style="flex: 1; height: 1px; background: var(--border-color);"></div>
    </div>

    <!-- Option 2: Email + Password Form -->
    <form onsubmit="handleCustomerLoginSubmit(event)">
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Email Address *</label>
        <input type="email" id="loginEmail" required placeholder="name@example.com" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>
      <div style="margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <label style="font-size: 0.85rem; font-weight: 600;">Password *</label>
          <a href="#" onclick="event.preventDefault(); renderAuthForgotView();" style="font-size: 0.8rem; color: var(--accent-gold); font-weight: 600;">Forgot Password?</a>
        </div>
        <input type="password" id="loginPassword" required placeholder="••••••••" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>

      <button type="submit" class="btn-gold" id="btnLoginSubmit" style="width: 100%;">
        Sign In <i class="fa-solid fa-right-to-bracket"></i>
      </button>

      <div style="text-align: center; margin-top: 16px; font-size: 0.85rem; color: var(--text-muted);">
        Don't have an account? <a href="#" onclick="event.preventDefault(); renderAuthRegisterView();" style="color: var(--accent-gold); font-weight: 700;">Create Account</a>
      </div>
    </form>
  `;

  // Render Google Sign-In Button dynamically via Google SDK
  setTimeout(() => {
    if (window.google && window.google.accounts && window.google.accounts.id) {
      try {
        const metaGoogleClient = document.querySelector('meta[name="google-signin-client_id"]')?.getAttribute('content') || window.GOOGLE_CLIENT_ID || '';
        if (metaGoogleClient) {
          window.google.accounts.id.initialize({
            client_id: metaGoogleClient,
            callback: window.handleGoogleSignInCallback
          });
        }
        const container = document.getElementById('googleBtnContainer');
        if (container) {
          window.google.accounts.id.renderButton(container, {
            type: 'standard',
            size: 'large',
            theme: 'outline',
            text: 'sign_in_with',
            shape: 'rectangular',
            logo_alignment: 'left',
            width: 320
          });
        }
      } catch (err) {
        console.error('Google Button render error:', err);
      }
    }
  }, 100);
}

function renderAuthRegisterView() {
  const content = document.getElementById('authModalContent');
  if (!content) return;

  content.innerHTML = `
    <h2 class="serif-font" style="color: var(--brand-maroon); margin-bottom: 8px;">Create Customer Account</h2>
    <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 18px;">Register with your email and password to shop & track orders.</p>

    <form onsubmit="handleCustomerRegisterSubmit(event)">
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Full Name</label>
        <input type="text" id="regName" placeholder="Ananya Sharma" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Email Address *</label>
        <input type="email" id="regEmail" required placeholder="ananya@example.com" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Password (Min. 6 chars) *</label>
        <input type="password" id="regPassword" required placeholder="••••••••" minlength="6" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>
      <div style="margin-bottom: 18px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Confirm Password *</label>
        <input type="password" id="regConfirmPassword" required placeholder="••••••••" minlength="6" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>

      <button type="submit" class="btn-gold" id="btnRegisterSubmit" style="width: 100%;">
        Create Account <i class="fa-solid fa-user-plus"></i>
      </button>

      <div style="text-align: center; margin-top: 16px; font-size: 0.85rem; color: var(--text-muted);">
        Already have an account? <a href="#" onclick="event.preventDefault(); renderAuthLoginView();" style="color: var(--accent-gold); font-weight: 700;">Sign In</a>
      </div>
    </form>
  `;
}

function renderAuthForgotView() {
  const content = document.getElementById('authModalContent');
  if (!content) return;

  content.innerHTML = `
    <h2 class="serif-font" style="color: var(--brand-maroon); margin-bottom: 8px;">Forgot Password</h2>
    <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 18px;">Enter your account email to receive a password reset link.</p>

    <form onsubmit="handleForgotPasswordSubmit(event)">
      <div style="margin-bottom: 18px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Email Address *</label>
        <input type="email" id="forgotEmail" required placeholder="ananya@example.com" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>

      <button type="submit" class="btn-gold" id="btnForgotSubmit" style="width: 100%;">
        Send Password Reset Link <i class="fa-solid fa-paper-plane"></i>
      </button>

      <div style="text-align: center; margin-top: 16px; font-size: 0.85rem;">
        <a href="#" onclick="event.preventDefault(); renderAuthLoginView();" style="color: var(--accent-gold); font-weight: 600;"><i class="fa-solid fa-arrow-left"></i> Back to Sign In</a>
      </div>
    </form>
  `;
}

function renderAuthResetView(token) {
  const content = document.getElementById('authModalContent');
  if (!content) return;

  content.innerHTML = `
    <h2 class="serif-font" style="color: var(--brand-maroon); margin-bottom: 8px;">Reset Password</h2>
    <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 18px;">Enter your new password below.</p>

    <form onsubmit="handleResetPasswordSubmit(event)">
      <input type="hidden" id="resetToken" value="${token}">
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.85rem; font-weight: 600;">New Password *</label>
        <input type="password" id="resetNewPassword" required placeholder="••••••••" minlength="6" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>
      <div style="margin-bottom: 18px;">
        <label style="font-size: 0.85rem; font-weight: 600;">Confirm New Password *</label>
        <input type="password" id="resetConfirmPassword" required placeholder="••••••••" minlength="6" style="width: 100%; padding: 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-color); margin-top: 4px;">
      </div>

      <button type="submit" class="btn-gold" id="btnResetSubmit" style="width: 100%;">
        Update Password <i class="fa-solid fa-key"></i>
      </button>
    </form>
  `;
}

async function handleCustomerLoginSubmit(event) {
  event.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  const btn = document.getElementById('btnLoginSubmit');

  if (!email || !password) {
    showToast('Please enter both email and password.', 'error');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Signing In...`;
  }

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (data.success) {
      state.user = data.user;
      updateBadges();
      closeModal('authModal');
      showToast(data.message);
      showPage('account-view');
    } else {
      showToast(data.message, 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `Sign In <i class="fa-solid fa-right-to-bracket"></i>`;
      }
    }
  } catch (err) {
    showToast('Login server error.', 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `Sign In <i class="fa-solid fa-right-to-bracket"></i>`;
    }
  }
}

async function handleCustomerRegisterSubmit(event) {
  event.preventDefault();
  const name = document.getElementById('regName').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const password = document.getElementById('regPassword').value.trim();
  const confirmPassword = document.getElementById('regConfirmPassword').value.trim();
  const btn = document.getElementById('btnRegisterSubmit');

  if (!email || !password || !confirmPassword) {
    showToast('Please complete all required fields.', 'error');
    return;
  }

  if (password !== confirmPassword) {
    showToast('Password and Confirm Password do not match.', 'error');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Creating Account...`;
  }

  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password, confirm_password: confirmPassword })
    });
    const data = await res.json();
    if (data.success) {
      state.user = data.user;
      updateBadges();
      closeModal('authModal');
      showToast(data.message);
      showPage('account-view');
    } else {
      showToast(data.message, 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `Create Account <i class="fa-solid fa-user-plus"></i>`;
      }
    }
  } catch (err) {
    showToast('Registration failed.', 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `Create Account <i class="fa-solid fa-user-plus"></i>`;
    }
  }
}

async function handleForgotPasswordSubmit(event) {
  event.preventDefault();
  const email = document.getElementById('forgotEmail').value.trim();
  const btn = document.getElementById('btnForgotSubmit');

  if (!email) {
    showToast('Please enter your email address.', 'error');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Sending Link...`;
  }

  try {
    const res = await fetch('/api/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    const data = await res.json();
    showToast(data.message);
    renderAuthLoginView();
  } catch (err) {
    showToast('Failed to send reset link.', 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `Send Password Reset Link <i class="fa-solid fa-paper-plane"></i>`;
    }
  }
}

async function handleResetPasswordSubmit(event) {
  event.preventDefault();
  const token = document.getElementById('resetToken').value;
  const newPassword = document.getElementById('resetNewPassword').value.trim();
  const confirmPassword = document.getElementById('resetConfirmPassword').value.trim();
  const btn = document.getElementById('btnResetSubmit');

  if (newPassword !== confirmPassword) {
    showToast('Passwords do not match.', 'error');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Updating...`;
  }

  try {
    const res = await fetch('/api/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword, confirm_password: confirmPassword })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message);
      renderAuthLoginView();
    } else {
      showToast(data.message, 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `Update Password <i class="fa-solid fa-key"></i>`;
      }
    }
  } catch (err) {
    showToast('Password reset failed.', 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `Update Password <i class="fa-solid fa-key"></i>`;
    }
  }
}

async function handleCustomerLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {}
  state.user = null;
  updateBadges();
  showToast('Logged out');
  showPage('home-view');
}

function renderAccountPortal() {
  const nameEl = document.getElementById('accWelcomeName');
  if (nameEl) nameEl.textContent = state.user ? `Hello, ${state.user.name}` : 'My Account';

  if (!state.user || !state.user.is_logged_in) {
    const content = document.getElementById('accountTabContent');
    if (content) {
      content.innerHTML = `
        <div style="text-align: center; padding: 40px 0;">
          <i class="fa-solid fa-user-lock" style="font-size: 3rem; color: var(--brand-maroon); margin-bottom: 16px;"></i>
          <h3 style="font-size: 1.4rem;">Customer Sign In Required</h3>
          <p style="color: var(--text-muted); margin-bottom: 20px;">Please sign in to view your order history and saved wishlist items.</p>
          <button class="btn-gold" onclick="openAuthModal()">Sign In / Create Account</button>
        </div>
      `;
    }
    return;
  }

  switchAccountTab('orders');
}

async function switchAccountTab(tab) {
  const content = document.getElementById('accountTabContent');
  if (!content) return;

  if (tab === 'orders') {
    try {
      const res = await fetch('/api/orders');
      const data = await res.json();
      if (data.success && data.orders.length > 0) {
        content.innerHTML = `
          <h3 style="font-size: 1.3rem; margin-bottom: 20px; color: var(--brand-maroon);">Your Order History</h3>
          ${data.orders.map(o => `
            <div style="border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 18px; margin-bottom: 16px;">
              <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                <span style="font-weight: 700; color: var(--accent-gold);">${o.order_code}</span>
                <span style="background-color: var(--brand-maroon); color: white; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 0.8rem;">${o.order_status}</span>
              </div>
              <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 10px;">Date: ${o.created_at} | Total: ₹${o.total.toLocaleString('en-IN')}</div>
              <div style="font-size: 0.85rem;">Items: ${o.items.map(i => i.name).join(', ')}</div>
            </div>
          `).join('')}
        `;
      } else {
        content.innerHTML = `<p style="color: var(--text-muted);">No past orders found for ${state.user.email}.</p>`;
      }
    } catch (err) {
      console.error(err);
    }
  } else if (tab === 'wishlist') {
    content.innerHTML = `<h3 style="font-size: 1.3rem; margin-bottom: 20px; color: var(--brand-maroon);">Saved Wishlist (${state.wishlist.length})</h3><p style="color: var(--text-muted);">Click heart icons on products to save them for later.</p>`;
  }
}

// --- WhatsApp Helpers ---
function orderProductOnWhatsApp(productName, price) {
  const msg = encodeURIComponent(`Hello Heena Imitation Jewellery! I would like to order: ${productName} (Price: ₹${price.toLocaleString('en-IN')}). Please process my order.`);
  window.open(`https://wa.me/${state.whatsappNumber}?text=${msg}`, '_blank');
}

function shareOrderOnWhatsApp(orderCode, total) {
  const msg = encodeURIComponent(`Hello Heena Imitation Jewellery! I placed Order ${orderCode} for ₹${total.toLocaleString('en-IN')}. Please confirm delivery status.`);
  window.open(`https://wa.me/${state.whatsappNumber}?text=${msg}`, '_blank');
}

// --- Helpers ---
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

function roundVal(num) {
  return Math.round((num + Number.EPSILON) * 100) / 100;
}

function openPolicyModal(type) {
  const titleEl = document.getElementById('policyModalTitle');
  const bodyEl = document.getElementById('policyModalBody');
  if (!titleEl || !bodyEl) return;

  const policies = {
    shipping: {
      title: 'Shipping & Delivery Policy',
      content: `
        <h4 style="color: var(--brand-maroon); margin-top: 0;">1. Delivery Charges</h4>
        <p>• <strong>Orders of ₹500 and above:</strong> 100% FREE Express Delivery across India.</p>
        <p>• <strong>Orders below ₹500:</strong> A standard delivery charge of ₹40 applies per order.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">2. Dispatch & Delivery Timelines</h4>
        <p>All handcrafted jewellery orders are packaged securely with bubble protection and dispatched within <strong>24 to 48 business hours</strong>. Delivery typically takes <strong>3 to 7 business days</strong> depending on your destination city/state across India.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">3. Order Tracking</h4>
        <p>Once your order is handed over to our courier partner (Delhivery / Blue Dart / India Post), you will receive automated shipping and tracking updates via email and WhatsApp.</p>
      `
    },
    refund: {
      title: 'Returns & Refund Policy',
      content: `
        <h4 style="color: var(--brand-maroon); margin-top: 0;">1. 7-Day Hassle-Free Replacement / Return</h4>
        <p>At Heena Imitation Jewellery, customer satisfaction is our prime commitment. If you receive an item that is defective, transit-damaged, or incorrect, you can request a return or replacement within <strong>7 days</strong> of delivery.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">2. Reporting Damaged Items</h4>
        <p>Please share a brief unboxing video or photographs of the damaged product with your Order ID via WhatsApp at <strong>+91 9777166165</strong> or email us at <strong>heenaimitationjewellery06@gmail.com</strong>.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">3. Refund Process & Timelines</h4>
        <p>Once your return is inspected and approved, refunds are credited back to the original payment source (Bank / UPI / Card) within <strong>3 to 5 business days</strong>. For COD orders, refund is issued directly via UPI/Bank transfer.</p>
      `
    },
    terms: {
      title: 'Terms & Conditions',
      content: `
        <h4 style="color: var(--brand-maroon); margin-top: 0;">1. Introduction & Ownership</h4>
        <p>Welcome to Heena Imitation Jewellery. By browsing our website and placing orders, you agree to comply with our terms and conditions.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">2. Pricing & Product Descriptions</h4>
        <p>All prices are listed in Indian Rupees (INR) and are inclusive of all applicable taxes. We strive to provide accurate photographs of handcrafted imitation jewellery; subtle color tone variations may occur due to photographic lighting.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">3. Secure Orders & Payments</h4>
        <p>Payments on our store are secured via 256-bit SSL encryption. We reserve the right to cancel orders in unforeseen circumstances such as stock discrepancies or inaccurate shipping addresses, with immediate full refund.</p>
      `
    },
    privacy: {
      title: 'Privacy Policy',
      content: `
        <h4 style="color: var(--brand-maroon); margin-top: 0;">1. Customer Data Protection</h4>
        <p>Heena Imitation Jewellery respects your privacy. We only collect essential customer information (Name, Email, Delivery Address, Phone Number) strictly necessary for order delivery and customer support.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">2. Non-Disclosure & Security</h4>
        <p>We do not sell, rent, or trade your personal information to any third parties. All sensitive transaction data is encrypted and handled securely through RBI-compliant payment processing partners.</p>

        <h4 style="color: var(--brand-maroon); margin-top: 16px;">3. Contact Support</h4>
        <p>If you have any questions about your data, feel free to contact us at <strong>heenaimitationjewellery06@gmail.com</strong>.</p>
      `
    }
  };

  const selected = policies[type] || policies.shipping;
  titleEl.textContent = selected.title;
  bodyEl.innerHTML = selected.content;
  openModal('policyModal');
}
