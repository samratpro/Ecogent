// Site version helpers. The server says which version to render (GET /api/site):
//   markup  0 base | 1 rebuild: hashed class names (CSS-modules style), renamed test ids
//           2 refactor: + wrapper elements, non-form buttons become div[role=button], DOM order differs
//             from the visual order, accessible names moved to aria-labelledby, half the test ids removed
//           3 like 2, but class names change on every page load (dev builds / CSS-in-JS)
//   layout  0 base | 1 navigation in a menu drawer, filters in a top bar, "Load more", accordion
//           2 full redesign: filter dialog, quick add, swatches, one-page checkout
//   copy    0 base | 1 rewritten labels ("Add to bag", "Check out", ...)
// Markup changes never change the look: the CSS is rewritten with the same class names (styles.js).

import { createContext, useContext } from "react";

export const SiteCtx = createContext(null);
export const useSite = () => useContext(SiteCtx);

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36).slice(0, 5);
}
const pascal = (n) => n.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join("");

// Renamed test ids, as when a team changes its test-id convention during a rebuild.
const TID_RENAMED = {
  "search-input": "site-search-field", "search-submit": "site-search-go", "cart-link": "header-bag",
  "product-card": "plp-tile", "add-to-cart": "pdp-add-button", "checkout-button": "cart-checkout-cta",
  "place-order": "checkout-submit", "qty-input": "cart-line-qty", "coupon-input": "promo-field",
  "sort-select": "plp-sort", "login-submit": "auth-submit", "wishlist-button": "save-for-later",
};
const TID_KEPT_IN_REFACTOR = new Set(["search-input", "add-to-cart", "place-order", "product-card", "login-submit", "qty-input"]);

export const COPY = [{
  brand: "Northwind Market", search_placeholder: "Search products", search_btn: "Search", add_to_cart: "Add to cart",
  added: "Added to cart", out_of_stock: "Out of stock", in_stock: "In stock", low_stock: "Only {n} left", cart: "Cart",
  checkout: "Checkout", view_cart: "View cart", continue_shopping: "Continue shopping", wishlist: "Wishlist",
  add_wishlist: "Add to wishlist", in_wishlist: "In your wishlist", remove: "Remove", apply: "Apply", coupon: "Coupon code",
  sort_by: "Sort by", filters: "Filters", brand_f: "Brand", price_f: "Price", min: "Min", max: "Max", rating_f: "Customer rating",
  stars_up: "{n} stars & up", in_stock_only: "In stock only", clear: "Clear all", results: "{n} results", load_more: "Load more",
  next: "Next", prev: "Previous", page: "Page", place_order: "Place order", shipping_method: "Shipping method",
  contact: "Contact information", address: "Shipping address", payment: "Payment", card: "Card number",
  continue: "Continue", back: "Back", sign_in: "Sign in", sign_out: "Sign out", account: "Account", orders: "My orders",
  email: "Email", password: "Password", full_name: "Full name", phone: "Phone (optional)", line1: "Street address",
  city: "City", postcode: "Postcode", country: "Country", subtotal: "Subtotal", discount: "Discount", shipping: "Shipping",
  total: "Total", quantity: "Quantity", color: "Colour", size: "Size", description: "Description",
  specifications: "Specifications", reviews: "Reviews", show_reviews: "Show reviews", menu: "Menu", home: "Home",
  deals: "Today's deals", bestsellers: "Best sellers", shop_by_category: "Shop by category", newsletter: "Get 10% off your first order",
  newsletter_text: "Join our newsletter for new arrivals and member-only offers.", subscribe: "Subscribe", no_thanks: "No thanks",
  close: "Close", cookies: "We use cookies to improve your experience and to analyse traffic.", accept: "Accept all",
  reject: "Reject non-essential", help: "Help & returns", order_confirmed: "Thank you! Your order is confirmed.",
  order_number: "Order number", cart_empty: "Your cart is empty.", free: "Free", choose: "Choose...", update: "Update",
  increase: "Increase quantity", decrease: "Decrease quantity", reviews_count: "{n} reviews", sale: "Sale",
  quick_add: "Quick add", filter_sort: "Filter & sort", show_results: "Show results", all_products: "All products",
}, {
  brand: "Northwind Market", search_placeholder: "What are you looking for?", search_btn: "Find", add_to_cart: "Add to bag",
  added: "Added to your bag", out_of_stock: "Sold out", in_stock: "Available", low_stock: "Hurry, {n} remaining", cart: "Bag",
  checkout: "Check out", view_cart: "Go to bag", continue_shopping: "Keep browsing", wishlist: "Saved items",
  add_wishlist: "Save for later", in_wishlist: "Saved", remove: "Delete", apply: "Redeem", coupon: "Promo code",
  sort_by: "Order by", filters: "Refine", brand_f: "Brands", price_f: "Price range", min: "From", max: "To", rating_f: "Rating",
  stars_up: "{n}+ stars", in_stock_only: "Hide sold-out items", clear: "Reset", results: "{n} products", load_more: "Show more",
  next: "Next page", prev: "Previous page", page: "Page", place_order: "Complete purchase", shipping_method: "Delivery options",
  contact: "Your details", address: "Delivery address", payment: "Payment details", card: "Card no.",
  continue: "Next step", back: "Go back", sign_in: "Log in", sign_out: "Log out", account: "My account", orders: "Order history",
  email: "Email address", password: "Password", full_name: "Name", phone: "Mobile (optional)", line1: "Address line",
  city: "Town / city", postcode: "ZIP / postcode", country: "Country / region", subtotal: "Items", discount: "Savings",
  shipping: "Delivery", total: "Order total", quantity: "Qty", color: "Color", size: "Size", description: "About this item",
  specifications: "Details", reviews: "Ratings & reviews", show_reviews: "Read reviews", menu: "Browse", home: "Home",
  deals: "Hot offers", bestsellers: "Most popular", shop_by_category: "Departments", newsletter: "Unlock 10% off",
  newsletter_text: "Sign up for emails and be first to hear about drops and offers.", subscribe: "Sign me up",
  no_thanks: "Maybe later", close: "Dismiss", cookies: "This site uses cookies. See our policy for details.",
  accept: "Allow cookies", reject: "Only necessary", help: "Customer service", order_confirmed: "Order received - thanks for shopping with us!",
  order_number: "Order reference", cart_empty: "There is nothing in your bag yet.", free: "FREE", choose: "Select",
  update: "Save", increase: "Add one", decrease: "Remove one", reviews_count: "{n} ratings", sale: "Offer",
  quick_add: "Add", filter_sort: "Sort & refine", show_results: "View products", all_products: "Shop all",
}];

export function makeSite(cfg) {
  const m = cfg.markup;
  const cx = (...names) => names.filter(Boolean).map((n) => (m === 0 ? n : `${pascal(n)}_${hash(`${n}|${cfg.salt}`)}`)).join(" ");
  const tid = (n) => (m === 0 ? n : m === 1 ? TID_RENAMED[n] || n : TID_KEPT_IN_REFACTOR.has(n) ? TID_RENAMED[n] || n : undefined);
  const words = COPY[cfg.copy] || COPY[0];
  const t = (k, n) => String(words[k] ?? COPY[0][k] ?? k).replace("{n}", n);
  return { ...cfg, cx, tid, t, refactor: m >= 2 };
}

export const money = (v) => `$${Number(v).toFixed(2)}`;
