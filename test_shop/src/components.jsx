import { createContext, useContext, useEffect, useId, useState } from "react";
import { Link, NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "./api.js";
import { money, useSite } from "./site.js";

// ------------------------------------------------------------------ cart / user state
export const ShopCtx = createContext(null);
export const useShop = () => useContext(ShopCtx);

export function ShopProvider({ children }) {
  const [cart, setCart] = useState({ lines: [], count: 0, subtotal: 0, discount: 0, total: 0 });
  const [user, setUser] = useState(null);
  const [categories, setCategories] = useState([]);
  const refresh = () => api("/cart").then(setCart).catch(() => {});
  useEffect(() => {
    refresh();
    api("/me").then(setUser).catch(() => {});
    api("/categories").then(setCategories).catch(() => {});
  }, []);
  return <ShopCtx.Provider value={{ cart, setCart, refresh, user, setUser, categories }}>{children}</ShopCtx.Provider>;
}

// ------------------------------------------------------------------ markup primitives
// Wrap: in a refactored build, an extra element appears around a block (display: contents keeps the look).
export function Wrap({ children }) {
  const s = useSite();
  return s.refactor ? <div className={s.cx("dc")}>{children}</div> : children;
}

// Btn: a <button>; in a refactored build, actions outside forms become div[role=button] (component-library migration).
export function Btn({ kind = "primary", className, onClick, disabled, type, children, testid, label, ...rest }) {
  const s = useSite();
  const id = useId();
  const cls = s.cx("btn", `btn-${kind}`, className);
  const aria = label ? (s.refactor ? { "aria-labelledby": `${id}-l` } : { "aria-label": label }) : {};
  const hidden = label && s.refactor ? <span id={`${id}-l`} className={s.cx("sr-only")}>{label}</span> : null;
  if (s.refactor && type !== "submit") {
    const act = (e) => { if (!disabled && onClick) onClick(e); };
    return (
      <div role="button" tabIndex={0} className={cls} aria-disabled={disabled ? "true" : undefined} data-testid={testid ? s.tid(testid) : undefined}
        onClick={act} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(e); } }} {...aria} {...rest}>
        {children}{hidden}
      </div>
    );
  }
  return (
    <button type={type || "button"} className={cls} onClick={onClick} disabled={disabled} data-testid={testid ? s.tid(testid) : undefined} {...aria} {...rest}>
      {children}{hidden}
    </button>
  );
}

export function Stars({ value }) {
  const s = useSite();
  const full = Math.round(value);
  return (
    <span className={s.cx("stars")} title={`${value} out of 5`}>
      {"★".repeat(full)}<span className={s.cx("stars-off")}>{"★".repeat(5 - full)}</span>
      <span className={s.cx("sr-only")}>{value} out of 5 stars</span>
    </span>
  );
}

export function Price({ p }) {
  const s = useSite();
  return (
    <span>
      <span className={s.cx("price-now")}>{money(p.price)}</span>
      {p.compareAt ? <span className={s.cx("price-was")}>{money(p.compareAt)}</span> : null}
    </span>
  );
}

export function ProductImage({ p, size = 400 }) {
  const initials = p.name.split(" ").filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join("");
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300'><rect width='400' height='300' fill='hsl(${p.hue},45%,86%)'/>` +
    `<circle cx='200' cy='150' r='78' fill='hsl(${p.hue},40%,72%)'/><text x='200' y='170' font-family='Segoe UI,Arial' font-size='56' ` +
    `font-weight='700' text-anchor='middle' fill='hsl(${p.hue},35%,30%)'>${initials}</text></svg>`;
  return <img src={`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`} alt={p.name} width={size} height={size * 0.75} loading="lazy" />;
}

export function Stock({ p }) {
  const s = useSite();
  if (p.stock <= 0) return <span className={s.cx("stock-out")}>{s.t("out_of_stock")}</span>;
  if (p.stock <= 5) return <span className={s.cx("stock-low")}>{s.t("low_stock", p.stock)}</span>;
  return <span className={s.cx("stock-ok")}>{s.t("in_stock")}</span>;
}

export const productUrl = (p) => `/p/${p.id}/${p.slug}`;

export function ProductCard({ p, quickAdd }) {
  const s = useSite();
  const { setCart } = useShop();
  const navigate = useNavigate();
  const [msg, setMsg] = useState("");
  const needsChoice = p.colors.length > 1 || p.sizes.length > 0;
  const add = async () => {
    if (needsChoice) return navigate(productUrl(p));
    try {
      setCart(await api("/cart", { method: "POST", body: { productId: p.id, qty: 1, color: p.colors[0] || null } }));
      setMsg(s.t("added"));
    } catch (e) { setMsg(e.message); }
  };
  const parts = {
    brand: <div key="b" className={s.cx("card-brand")}>{p.brand}</div>,
    title: <Link key="t" to={productUrl(p)} className={s.cx("card-title")}>{p.name}</Link>,
    rating: <div key="r" className={s.cx("card-rating")}><Stars value={p.rating} /> {p.rating} ({s.t("reviews_count", p.reviewCount)})</div>,
    price: <div key="p" className={s.cx("card-price")}><Price p={p} /></div>,
    stock: <div key="s" className={s.cx("card-stock")}><Stock p={p} /></div>,
  };
  // Refactored build: the fields come in a different order in the code; CSS "order" keeps the visual order.
  const order = s.refactor ? ["price", "title", "stock", "brand", "rating"] : ["brand", "title", "rating", "price", "stock"];
  return (
    <article className={s.cx("card")} data-testid={s.tid("product-card")}>
      <Link to={productUrl(p)} className={s.cx("card-img")} tabIndex={-1} aria-hidden="true">
        <ProductImage p={p} />
        {p.compareAt ? <span className={s.cx("sale-badge")}>{s.t("sale")}</span> : null}
      </Link>
      <div className={s.cx("card-body")}>
        <Wrap>{order.map((k) => parts[k])}</Wrap>
        {quickAdd ? (
          <div className={s.cx("card-actions")}>
            <Btn kind="secondary" onClick={add} disabled={p.stock <= 0} label={`${s.t("quick_add")}: ${p.name}`}>{s.t("quick_add")}</Btn>
          </div>
        ) : null}
        {msg ? <div className={s.cx("muted")} role="status">{msg}</div> : null}
      </div>
    </article>
  );
}

export function ProductGrid({ items, view = "grid", quickAdd }) {
  const s = useSite();
  const cls = view === "list" ? "product-list" : view === "grid4" ? "product-grid-4" : "product-grid";
  return <div className={s.cx(cls)}>{items.map((p) => <Wrap key={p.id}><ProductCard p={p} quickAdd={quickAdd} /></Wrap>)}</div>;
}

// ------------------------------------------------------------------ header / footer
function SearchBox() {
  const s = useSite();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  return (
    <form className={s.cx("search")} role="search" onSubmit={(e) => { e.preventDefault(); navigate(`/search?q=${encodeURIComponent(q.trim())}`); }}>
      <input className={s.cx("search-input")} name="q" type="search" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={s.t("search_placeholder")} aria-label={s.refactor ? undefined : s.t("search_placeholder")} data-testid={s.tid("search-input")} />
      <button type="submit" className={s.cx("search-btn")} data-testid={s.tid("search-submit")}>{s.t("search_btn")}</button>
    </form>
  );
}

export function Header() {
  const s = useSite();
  const { cart, user, categories } = useShop();
  const [open, setOpen] = useState(false);
  const cartLabel = `${s.t("cart")} (${cart.count})`;
  const actions = (
    <div className={s.cx("header-actions")}>
      <Link to={user ? "/account/orders" : "/account/login"} className={s.cx("icon-btn")}>{user ? s.t("account") : s.t("sign_in")}</Link>
      <Link to="/wishlist" className={s.cx("icon-btn")}>{s.t("wishlist")}</Link>
      <Link to="/cart" className={s.cx("icon-btn")} data-testid={s.tid("cart-link")} aria-label={s.refactor ? undefined : cartLabel}>
        {s.layout === 2 ? "🛒" : s.t("cart")} <span className={s.cx("badge")}>{cart.count}</span>
      </Link>
    </div>
  );
  return (
    <>
      <div className={s.cx("topbar")}>Free standard shipping on orders over $50 · Use code SAVE10 for 10% off</div>
      <header className={s.cx("header")}>
        <div className={s.cx("container", "header-inner")}>
          {s.layout >= 1 ? <button type="button" className={s.cx("menu-btn")} onClick={() => setOpen(true)} aria-expanded={open}>☰ {s.t("menu")}</button> : null}
          <Link to="/" className={s.cx("logo")}>{s.t("brand")}</Link>
          <Wrap><SearchBox /></Wrap>
          {actions}
        </div>
      </header>
      {s.layout === 0 ? (
        <nav className={s.cx("nav")} aria-label="Categories">
          <div className={s.cx("container", "nav-inner")}>
            <Wrap>
              {categories.map((c) => <NavLink key={c.slug} to={`/c/${c.slug}`} className={s.cx("nav-link")}>{c.name}</NavLink>)}
              <NavLink to="/help" className={s.cx("nav-link")}>{s.t("help")}</NavLink>
            </Wrap>
          </div>
        </nav>
      ) : null}
      {open ? (
        <>
          <div className={s.cx("drawer-backdrop")} onClick={() => setOpen(false)} />
          <nav className={s.cx("drawer-panel")} aria-label="Categories">
            <div className={s.cx("modal-head")}>
              <strong>{s.t("menu")}</strong>
              <Btn kind="link" onClick={() => setOpen(false)} label={s.t("close")}>✕</Btn>
            </div>
            <Link to="/search?q=" className={s.cx("drawer-link")} onClick={() => setOpen(false)}>{s.t("all_products")}</Link>
            {categories.map((c) => <Link key={c.slug} to={`/c/${c.slug}`} className={s.cx("drawer-link")} onClick={() => setOpen(false)}>{c.name}</Link>)}
            <Link to="/help" className={s.cx("drawer-link")} onClick={() => setOpen(false)}>{s.t("help")}</Link>
          </nav>
        </>
      ) : null}
    </>
  );
}

export function Footer() {
  const s = useSite();
  const { categories } = useShop();
  return (
    <footer className={s.cx("footer")}>
      <div className={s.cx("container")}>
        <div className={s.cx("footer-cols")}>
          <div className={s.cx("footer-col")}><div className={s.cx("footer-title")}>{s.t("brand")}</div>
            <p>Everyday products, honest prices. Demo shop for testing - no real orders are shipped.</p></div>
          <div className={s.cx("footer-col")}><div className={s.cx("footer-title")}>{s.t("shop_by_category")}</div>
            {categories.slice(0, 4).map((c) => <Link key={c.slug} to={`/c/${c.slug}`}>{c.name}</Link>)}</div>
          <div className={s.cx("footer-col")}><div className={s.cx("footer-title")}>&nbsp;</div>
            {categories.slice(4).map((c) => <Link key={c.slug} to={`/c/${c.slug}`}>{c.name}</Link>)}</div>
          <div className={s.cx("footer-col")}><div className={s.cx("footer-title")}>{s.t("help")}</div>
            <Link to="/help">Shipping</Link><Link to="/help">Returns</Link><Link to="/help">Payment</Link><Link to="/account/orders">{s.t("orders")}</Link></div>
        </div>
        <div className={s.cx("footer-bottom")}>© 2026 Northwind Market (test site)</div>
      </div>
    </footer>
  );
}

// ------------------------------------------------------------------ interruptions
export function Interruptions() {
  const s = useSite();
  const read = (k) => { try { return sessionStorage.getItem(k); } catch { return null; } };
  const write = (k) => { try { sessionStorage.setItem(k, "1"); } catch { /* storage blocked: show again */ } };
  const [cookie, setCookie] = useState(s.interruptions >= 1 && !read("nw_cookie"));
  const [news, setNews] = useState(false);
  useEffect(() => {
    if (s.interruptions < 2 || read("nw_news")) return undefined;
    const t = setTimeout(() => setNews(true), 1500);
    return () => clearTimeout(t);
  }, [s.interruptions]);
  const closeCookie = () => { write("nw_cookie"); setCookie(false); };
  const closeNews = () => { write("nw_news"); setNews(false); };
  return (
    <>
      {cookie ? (
        <div className={s.cx("cookie-banner")} role="region" aria-label="Cookie consent">
          <span>{s.t("cookies")}</span>
          <div className={s.cx("cookie-actions")}>
            <Btn kind="secondary" onClick={closeCookie}>{s.t("reject")}</Btn>
            <Btn onClick={closeCookie}>{s.t("accept")}</Btn>
          </div>
        </div>
      ) : null}
      {news ? (
        <div className={s.cx("modal-backdrop")}>
          <div className={s.cx("modal-panel", "nl-modal")} role="dialog" aria-modal="true" aria-label={s.t("newsletter")}>
            <button type="button" className={s.cx("nl-close")} onClick={closeNews} aria-label={s.t("close")}>×</button>
            <h2 className={s.cx("modal-title")}>{s.t("newsletter")}</h2>
            <p className={s.cx("muted")}>{s.t("newsletter_text")}</p>
            <form onSubmit={(e) => { e.preventDefault(); closeNews(); }} className={s.cx("coupon-row")}>
              <input className={s.cx("input")} type="email" name="newsletter_email" placeholder={s.t("email")} aria-label={s.t("email")} />
              <button type="submit" className={s.cx("btn", "btn-primary")}>{s.t("subscribe")}</button>
            </form>
            <p><Btn kind="link" onClick={closeNews}>{s.t("no_thanks")}</Btn></p>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function Alert({ kind = "error", children }) {
  const s = useSite();
  return children ? <div className={s.cx("alert", `alert-${kind}`)} role={kind === "error" ? "alert" : "status"}>{children}</div> : null;
}
