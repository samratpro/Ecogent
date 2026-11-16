// Test shop server: serves the built React app (dist/) and the shop API on one port (default 3010).
//
//   node server.js [--port 3010]
//
// Shop API  (/api/...)   what the web page itself uses: products, cart, wishlist, login, orders.
// Lab API   (/__lab/...) site version (drift), reset, ground truth and recorded state for the oracles.
//                         Needs the lab key (header x-lab-key or ?key=), written to .lab_key on start,
//                         so no agent under test can read the answers or change the site version.
//                         robots.txt disallows it; nothing in the shop links to it.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { buildCatalog, reviewsFor, CATEGORIES, COUPONS, SHIPPING, TEST_CARD } from "./shared/catalog.js";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(ROOT, "dist");
const argPort = process.argv.indexOf("--port");
const PORT = Number(argPort > 0 ? process.argv[argPort + 1] : process.env.PORT || 3010);
const LAB_KEY = process.env.LAB_KEY || crypto.randomBytes(12).toString("hex");
fs.writeFileSync(path.join(ROOT, ".lab_key"), LAB_KEY);

export const AXES = {                                   // see README.md: "Site versions"
  markup: [0, 1, 2, 3],          // same look, different code: 0 base, 1 rebuild, 2 refactor, 3 per-load names
  layout: [0, 1, 2],             // visible redesign: 0 base, 1 navigation/filters moved, 2 full redesign
  copy: [0, 1],                  // wording: 0 base, 1 rewritten labels
  interruptions: [0, 1, 2],      // 0 none, 1 cookie banner, 2 + newsletter popup
};
const USERS = [{ email: "ada.tester@example.com", password: "Shop!2026", name: "Ada Tester" }];

let config, catalog, byId, sessions, orders, events, seq;
function reset(keepConfig = true) {
  config = keepConfig && config ? config : { markup: 0, layout: 0, copy: 0, content: 0, interruptions: 0, seed: 1 };
  catalog = buildCatalog(config.content);
  byId = new Map(catalog.map((p) => [p.id, p]));
  sessions = new Map();
  orders = [];
  events = [];
  seq = 0;
}
reset(false);

// ------------------------------------------------------------------ helpers
const json = (res, code, body, headers = {}) => {
  res.writeHead(code, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers });
  res.end(JSON.stringify(body));
};
const readBody = (req) => new Promise((resolve) => {
  let data = "";
  req.on("data", (c) => { data += c; if (data.length > 65536) req.destroy(); });
  req.on("end", () => { try { resolve(data ? JSON.parse(data) : {}); } catch { resolve({}); } });
});
const cookies = (req) => Object.fromEntries((req.headers.cookie || "").split(";").map((c) => c.trim().split("=")).filter((x) => x[0]));
const money = (v) => Math.round(v * 100) / 100;
const log = (type, sid, data) => events.push({ n: ++seq, t: new Date().toISOString(), type, sid, ...data });

function session(req, res) {
  let sid = cookies(req).sid;
  if (!sid || !sessions.has(sid)) {
    sid = crypto.randomBytes(9).toString("hex");
    sessions.set(sid, { cart: [], coupon: null, wishlist: [], user: null });
    res.setHeader("set-cookie", `sid=${sid}; Path=/; HttpOnly; SameSite=Lax`);
  }
  return [sid, sessions.get(sid)];
}

function cartView(s) {
  const lines = s.cart.map((l) => {
    const p = byId.get(l.productId);
    return p ? { lineId: l.lineId, productId: p.id, name: p.name, price: p.price, qty: l.qty, color: l.color, size: l.size,
      lineTotal: money(p.price * l.qty), stock: p.stock, hue: p.hue } : null;
  }).filter(Boolean);
  const subtotal = money(lines.reduce((a, l) => a + l.lineTotal, 0));
  const c = s.coupon && COUPONS[s.coupon];
  const discount = c && c.type === "percent" ? money(subtotal * c.value / 100) : 0;
  return { lines, count: lines.reduce((a, l) => a + l.qty, 0), subtotal, coupon: s.coupon, discount, total: money(subtotal - discount) };
}

function shippingCost(method, subtotal, coupon) {
  const m = SHIPPING[method];
  if (!m) return null;
  if (method === "standard" && (coupon === "FREESHIP" || (m.freeOver && subtotal >= m.freeOver))) return 0;
  return m.price;
}

const SORTS = {
  relevance: null,
  "price-asc": (a, b) => a.price - b.price || a.id - b.id,
  "price-desc": (a, b) => b.price - a.price || a.id - b.id,
  rating: (a, b) => b.rating - a.rating || b.reviewCount - a.reviewCount,
  newest: (a, b) => b.added.localeCompare(a.added) || b.id - a.id,
  bestselling: (a, b) => b.sales - a.sales,
};

function search(q) {
  const cat = q.get("category");
  const text = (q.get("q") || "").toLowerCase().trim();
  const brands = (q.get("brand") || "").split(",").filter(Boolean);
  const min = parseFloat(q.get("min")), max = parseFloat(q.get("max")), rating = parseFloat(q.get("rating"));
  let items = catalog.filter((p) => !cat || p.category === cat);
  if (text) {
    const words = text.split(/\s+/);
    items = items.filter((p) => words.every((w) => `${p.name} ${p.brand} ${p.category} ${p.author || ""}`.toLowerCase().includes(w)));
  }
  const facetBase = items;
  if (brands.length) items = items.filter((p) => brands.includes(p.brand));
  if (!isNaN(min)) items = items.filter((p) => p.price >= min);
  if (!isNaN(max)) items = items.filter((p) => p.price <= max);
  if (!isNaN(rating)) items = items.filter((p) => p.rating >= rating);
  if (q.get("instock") === "1") items = items.filter((p) => p.stock > 0);
  const sort = SORTS[q.get("sort") || "relevance"];
  if (sort) items = [...items].sort(sort);
  const per = Math.min(48, Math.max(1, parseInt(q.get("per") || "12", 10)));
  const pages = Math.max(1, Math.ceil(items.length / per));
  const page = Math.min(pages, Math.max(1, parseInt(q.get("page") || "1", 10)));
  const counts = {};
  facetBase.forEach((p) => { counts[p.brand] = (counts[p.brand] || 0) + 1; });
  return { items: items.slice((page - 1) * per, page * per), total: items.length, page, pages, per,
    brands: Object.entries(counts).sort().map(([name, count]) => ({ name, count })) };
}

// ------------------------------------------------------------------ shop API
async function api(req, res, url) {
  const [sid, s] = session(req, res);
  const p = url.pathname.replace(/^\/api/, "");
  const m = req.method;
  let mm;
  if (p === "/site" && m === "GET") {
    // What the page needs to render this site version. The per-load salt makes markup 3 change on every load.
    const salt = config.markup === 3 ? crypto.randomBytes(3).toString("hex") : String(config.seed);
    return json(res, 200, { markup: config.markup, layout: config.layout, copy: config.copy,
      interruptions: config.interruptions, salt });
  }
  if (p === "/categories") return json(res, 200, CATEGORIES.map((c) => ({ ...c, count: catalog.filter((x) => x.category === c.slug).length })));
  if (p === "/featured") {
    const best = [...catalog].sort(SORTS.bestselling).slice(0, 8);
    const deals = catalog.filter((x) => x.compareAt && x.stock > 0).sort((a, b) => (b.compareAt - b.price) / b.compareAt - (a.compareAt - a.price) / a.compareAt).slice(0, 8);
    return json(res, 200, { bestsellers: best, deals });
  }
  if (p === "/products" && m === "GET") return json(res, 200, search(url.searchParams));
  if ((mm = p.match(/^\/products\/(\d+)$/))) {
    const prod = byId.get(+mm[1]);
    return prod ? json(res, 200, prod) : json(res, 404, { error: "Product not found" });
  }
  if ((mm = p.match(/^\/products\/(\d+)\/reviews$/))) {
    const prod = byId.get(+mm[1]);
    if (!prod) return json(res, 404, { error: "Product not found" });
    const all = reviewsFor(prod), per = 5, pages = Math.max(1, Math.ceil(all.length / per));
    const page = Math.min(pages, Math.max(1, parseInt(url.searchParams.get("page") || "1", 10)));
    return json(res, 200, { items: all.slice((page - 1) * per, page * per), total: all.length, page, pages });
  }
  if (p === "/cart" && m === "GET") return json(res, 200, cartView(s));
  if (p === "/cart" && m === "POST") {
    const b = await readBody(req);
    const prod = byId.get(+b.productId);
    const qty = Math.max(1, parseInt(b.qty || 1, 10));
    if (!prod) return json(res, 404, { error: "Product not found" });
    if (prod.colors.length && !prod.colors.includes(b.color)) return json(res, 400, { error: "Please choose a colour" });
    if (prod.sizes.length && !prod.sizes.includes(b.size)) return json(res, 400, { error: "Please choose a size" });
    const line = s.cart.find((l) => l.productId === prod.id && l.color === (b.color || null) && l.size === (b.size || null));
    const want = (line ? line.qty : 0) + qty;
    if (want > prod.stock) return json(res, 409, { error: prod.stock ? `Only ${prod.stock} left in stock` : "Out of stock" });
    if (line) line.qty = want;
    else s.cart.push({ lineId: crypto.randomBytes(4).toString("hex"), productId: prod.id, qty, color: b.color || null, size: b.size || null });
    log("add_to_cart", sid, { productId: prod.id, qty, color: b.color || null, size: b.size || null });
    return json(res, 200, cartView(s));
  }
  if ((mm = p.match(/^\/cart\/(\w+)$/)) && mm[1] !== "coupon") {
    const line = s.cart.find((l) => l.lineId === mm[1]);
    if (!line) return json(res, 404, { error: "Line not found" });
    if (m === "DELETE") {
      s.cart = s.cart.filter((l) => l !== line);
      log("remove_from_cart", sid, { productId: line.productId });
    } else if (m === "PATCH") {
      const b = await readBody(req);
      const qty = parseInt(b.qty, 10);
      const prod = byId.get(line.productId);
      if (!(qty >= 1)) return json(res, 400, { error: "Quantity must be at least 1" });
      if (prod && qty > prod.stock) return json(res, 409, { error: `Only ${prod.stock} left in stock` });
      line.qty = qty;
      log("update_quantity", sid, { productId: line.productId, qty });
    }
    return json(res, 200, cartView(s));
  }
  if (p === "/cart/coupon") {
    if (m === "DELETE") { s.coupon = null; return json(res, 200, cartView(s)); }
    const code = String((await readBody(req)).code || "").trim().toUpperCase();
    if (!COUPONS[code]) return json(res, 400, { error: "This code is not valid" });
    s.coupon = code;
    log("coupon_applied", sid, { code });
    return json(res, 200, cartView(s));
  }
  if (p === "/wishlist") {
    if (m === "POST") {
      const id = +(await readBody(req)).productId;
      if (byId.has(id) && !s.wishlist.includes(id)) { s.wishlist.push(id); log("wishlist_add", sid, { productId: id }); }
    }
    return json(res, 200, s.wishlist.map((id) => byId.get(id)).filter(Boolean));
  }
  if ((mm = p.match(/^\/wishlist\/(\d+)$/)) && m === "DELETE") {
    s.wishlist = s.wishlist.filter((id) => id !== +mm[1]);
    log("wishlist_remove", sid, { productId: +mm[1] });
    return json(res, 200, s.wishlist.map((id) => byId.get(id)).filter(Boolean));
  }
  if (p === "/login" && m === "POST") {
    const b = await readBody(req);
    const u = USERS.find((x) => x.email === String(b.email || "").trim().toLowerCase() && x.password === b.password);
    if (!u) return json(res, 401, { error: "Email or password is incorrect" });
    s.user = u.email;
    log("login", sid, { email: u.email });
    return json(res, 200, { email: u.email, name: u.name });
  }
  if (p === "/logout" && m === "POST") { s.user = null; return json(res, 200, { ok: true }); }
  if (p === "/me") {
    const u = USERS.find((x) => x.email === s.user);
    return json(res, 200, u ? { email: u.email, name: u.name } : null);
  }
  if (p === "/shipping") return json(res, 200, SHIPPING);
  if (p === "/orders" && m === "POST") {
    const b = await readBody(req);
    const cart = cartView(s);
    if (!cart.lines.length) return json(res, 400, { error: "Your cart is empty" });
    const c = b.contact || {}, a = b.address || {};
    const missing = [["email", c.email], ["full name", c.name], ["address", a.line1], ["city", a.city], ["postcode", a.postcode],
      ["country", a.country]].filter(([, v]) => !String(v || "").trim()).map(([k]) => k);
    if (missing.length) return json(res, 400, { error: `Please fill in: ${missing.join(", ")}` });
    if (!/^\S+@\S+\.\S+$/.test(c.email)) return json(res, 400, { error: "Please enter a valid email address" });
    const ship = shippingCost(b.shipping, cart.subtotal, cart.coupon);
    if (ship === null) return json(res, 400, { error: "Please choose a shipping method" });
    if (String(b.payment?.card || "").replace(/\s+/g, "") !== TEST_CARD) return json(res, 402, { error: "Your card was declined" });
    for (const l of cart.lines) {
      const prod = byId.get(l.productId);
      if (!prod || prod.stock < l.qty) return json(res, 409, { error: `${l.name} is no longer available in that quantity` });
    }
    cart.lines.forEach((l) => { byId.get(l.productId).stock -= l.qty; });
    const order = { id: `ORD-${String(100000 + orders.length * 7919 % 900000).slice(0, 6)}`, created: new Date().toISOString(),
      sid, user: s.user, contact: { email: c.email, name: c.name, phone: c.phone || "" },
      address: { line1: a.line1, city: a.city, postcode: a.postcode, country: a.country }, shipping: b.shipping,
      lines: cart.lines.map(({ productId, name, price, qty, color, size }) => ({ productId, name, price, qty, color, size })),
      subtotal: cart.subtotal, discount: cart.discount, coupon: cart.coupon, shippingCost: ship,
      total: money(cart.total + ship), status: "Processing" };
    orders.push(order);
    s.cart = []; s.coupon = null;
    log("order_placed", sid, { orderId: order.id, total: order.total });
    const { sid: _hidden, ...publicOrder } = order;
    return json(res, 200, publicOrder);
  }
  if (p === "/orders" && m === "GET") {
    return json(res, 200, orders.filter((o) => (s.user && o.user === s.user) || o.sid === sid).map(({ sid: _s, ...o }) => o).reverse());
  }
  if ((mm = p.match(/^\/orders\/([\w-]+)$/))) {
    const o = orders.find((x) => x.id === mm[1] && (x.sid === sid || (s.user && x.user === s.user)));
    if (!o) return json(res, 404, { error: "Order not found" });
    const { sid: _s, ...rest } = o;
    return json(res, 200, rest);
  }
  return json(res, 404, { error: "Not found" });
}

// ------------------------------------------------------------------ lab API
async function lab(req, res, url) {
  const key = req.headers["x-lab-key"] || url.searchParams.get("key");
  if (key !== LAB_KEY) return json(res, 403, { error: "lab key required" });
  const p = url.pathname.replace(/^\/__lab/, "") || "/";
  if (p === "/" ) {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
    return res.end(labPage(key));
  }
  if (p === "/config" && req.method === "POST") {
    const b = await readBody(req);
    const next = { ...config };
    for (const k of Object.keys(AXES)) if (b[k] !== undefined) {
      const v = parseInt(b[k], 10);
      if (!AXES[k].includes(v)) return json(res, 400, { error: `${k} must be one of ${AXES[k].join(", ")}` });
      next[k] = v;
    }
    for (const k of ["content", "seed"]) if (b[k] !== undefined) {
      const v = parseInt(b[k], 10);
      if (!(v >= 0 && v <= 999)) return json(res, 400, { error: `${k} must be 0-999` });
      next[k] = k === "seed" ? Math.max(1, v) : v;
    }
    const contentChanged = next.content !== config.content;
    config = next;
    if (contentChanged || b.reset) reset(true);           // new data: carts / orders from the old data are cleared
    return json(res, 200, { config, reset: contentChanged || !!b.reset });
  }
  if (p === "/reset" && req.method === "POST") { reset(true); return json(res, 200, { config }); }
  if (p === "/state") {
    return json(res, 200, { config, orders, events,
      sessions: [...sessions].map(([sid, s]) => ({ sid, user: s.user, cart: s.cart, coupon: s.coupon, wishlist: s.wishlist })) });
  }
  if (p === "/truth") {
    return json(res, 200, { config, categories: CATEGORIES, products: catalog, coupons: COUPONS, shipping: SHIPPING,
      testCard: TEST_CARD, users: USERS.map(({ email, name }) => ({ email, name })) });
  }
  return json(res, 404, { error: "Not found" });
}

function labPage(key) {
  const row = (k, labels) => `<p><b>${k}</b> ${labels.map((l, i) => `<label><input type=radio name=${k} value=${i}> ${i} ${l}</label>`).join(" ")}</p>`;
  return `<!doctype html><meta charset=utf-8><title>Test shop lab</title><meta name=robots content=noindex>
<style>body{font:14px system-ui;margin:24px;max-width:860px}label{margin-right:12px}pre{background:#f4f4f5;padding:8px}</style>
<h2>Test shop - site version</h2>
${row("markup", ["base", "rebuild (hashed names)", "refactor (wrappers, tags)", "new names every load"])}
${row("layout", ["base", "nav + filters moved", "full redesign"])}
${row("copy", ["base", "rewritten labels"])}
${row("interruptions", ["none", "cookie banner", "+ newsletter popup"])}
<p><b>content</b> <input id=content type=number min=0 max=999 style=width:70px> (0 = base data; 1, 2, ... = changed prices, stock, products)</p>
<p><button onclick=apply()>Apply</button> <button onclick=resetAll()>Reset carts and orders</button></p><pre id=out></pre>
<script>
const K=${JSON.stringify(key)},H={"content-type":"application/json","x-lab-key":K};
async function load(){const s=await (await fetch("/__lab/state",{headers:H})).json();for(const[k,v]of Object.entries(s.config)){
document.querySelectorAll("input[name="+k+"]").forEach(e=>e.checked=+e.value===v)}document.getElementById("content").value=s.config.content;
document.getElementById("out").textContent=JSON.stringify(s.config)+"\\n"+s.orders.length+" orders, "+s.events.length+" events"}
async function apply(){const b={};for(const k of ["markup","layout","copy","interruptions"]){const e=document.querySelector("input[name="+k+"]:checked");if(e)b[k]=+e.value}
b.content=+document.getElementById("content").value||0;await fetch("/__lab/config",{method:"POST",headers:H,body:JSON.stringify(b)});load()}
async function resetAll(){await fetch("/__lab/reset",{method:"POST",headers:H});load()}
load()</script>`;
}

// ------------------------------------------------------------------ static files
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
  ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json", ".woff2": "font/woff2" };
function serveStatic(req, res, url) {
  if (url.pathname === "/robots.txt") {
    res.writeHead(200, { "content-type": "text/plain" });
    return res.end("User-agent: *\nDisallow: /__lab\n");
  }
  if (!fs.existsSync(DIST)) {
    res.writeHead(503, { "content-type": "text/plain" });
    return res.end("The shop is not built yet: run `npm run build` in test_shop/.");
  }
  let file = path.normalize(path.join(DIST, decodeURIComponent(url.pathname)));
  if (!file.startsWith(DIST) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, "index.html");
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream",
    "cache-control": file.endsWith("index.html") ? "no-store" : "public, max-age=3600" });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  try {
    if (url.pathname.startsWith("/api/")) return await api(req, res, url);
    if (url.pathname.startsWith("/__lab")) return await lab(req, res, url);
    return serveStatic(req, res, url);
  } catch (e) {
    console.error(e);
    return json(res, 500, { error: "Server error" });
  }
});
server.listen(PORT, "127.0.0.1", () => console.log(`Test shop ready on http://localhost:${PORT}`));
