import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "./api.js";
import { money, useSite } from "./site.js";
import { Alert, Btn, Price, ProductGrid, ProductImage, Stars, Stock, Wrap, productUrl, useShop } from "./components.jsx";

function useTitle(t) { useEffect(() => { document.title = t ? `${t} | Northwind Market` : "Northwind Market"; }, [t]); }

// ------------------------------------------------------------------ home
export function Home() {
  const s = useSite();
  const { categories } = useShop();
  const [f, setF] = useState(null);
  useTitle("");
  useEffect(() => { api("/featured").then(setF).catch(() => {}); }, []);
  const view = s.layout === 2 ? "grid4" : "grid";
  const sections = [
    <section key="best" className={s.cx("section")}><h2 className={s.cx("section-title")}>{s.t("bestsellers")}</h2>
      {f ? <ProductGrid items={s.layout === 2 ? f.bestsellers : f.bestsellers.slice(0, 6)} view={view} quickAdd={s.layout === 2} /> : null}</section>,
    <section key="deals" className={s.cx("section")}><h2 className={s.cx("section-title")}>{s.t("deals")}</h2>
      {f ? <ProductGrid items={s.layout === 2 ? f.deals : f.deals.slice(0, 6)} view={view} quickAdd={s.layout === 2} /> : null}</section>,
  ];
  return (
    <div className={s.cx("container")}>
      <div className={s.cx("hero")}>
        <div>
          <h1 className={s.cx("hero-title")}>New season, new essentials</h1>
          <p className={s.cx("hero-sub")}>Electronics, home, outdoor gear and more - with free standard shipping on orders over $50.</p>
          <Link to="/search?q=" className={s.cx("btn", "btn-primary")}>{s.t("all_products")}</Link>
        </div>
        <div className={s.cx("hero-art")} />
      </div>
      <div className={s.cx("promo-strip")}>Use code <strong>SAVE10</strong> at checkout for 10% off. <Link to="/help">{s.t("help")}</Link></div>
      {s.layout === 2 ? sections.reverse() : sections.slice(0, 1)}
      <section className={s.cx("section")}>
        <h2 className={s.cx("section-title")}>{s.t("shop_by_category")}</h2>
        <div className={s.cx("cat-grid")}>
          {categories.map((c) => <Wrap key={c.slug}><Link to={`/c/${c.slug}`} className={s.cx("cat-tile")}>{c.name}<div className={s.cx("muted")}>{c.count} items</div></Link></Wrap>)}
        </div>
      </section>
      {s.layout !== 2 ? sections[1] : null}
    </div>
  );
}

// ------------------------------------------------------------------ listing (category + search)
const SORT_OPTIONS = [["relevance", "Featured"], ["price-asc", "Price: low to high"], ["price-desc", "Price: high to low"],
  ["rating", "Customer rating"], ["newest", "Newest"], ["bestselling", "Best selling"]];

function Filters({ data, params, set, compact }) {
  const s = useSite();
  const brands = (params.get("brand") || "").split(",").filter(Boolean);
  const [min, setMin] = useState(params.get("min") || "");
  const [max, setMax] = useState(params.get("max") || "");
  useEffect(() => { setMin(params.get("min") || ""); setMax(params.get("max") || ""); }, [params]);
  const toggleBrand = (b) => set({ brand: (brands.includes(b) ? brands.filter((x) => x !== b) : [...brands, b]).join(",") || null });
  const groups = [
    <div key="brand" className={s.cx("filter-group")}><div className={s.cx("filter-title")}>{s.t("brand_f")}</div>
      {data.brands.map((b) => (
        <label key={b.name} className={s.cx("check-row")}>
          <input type="checkbox" name="brand" value={b.name} checked={brands.includes(b.name)} onChange={() => toggleBrand(b.name)} />
          {b.name} <span className={s.cx("muted")}>({b.count})</span>
        </label>))}
    </div>,
    <form key="price" className={s.cx("filter-group")} onSubmit={(e) => { e.preventDefault(); set({ min: min || null, max: max || null }); }}>
      <div className={s.cx("filter-title")}>{s.t("price_f")}</div>
      <div className={s.cx("price-row")}>
        <input className={s.cx("input", "input-sm")} name="min" inputMode="decimal" placeholder={s.t("min")} value={min} onChange={(e) => setMin(e.target.value)} aria-label={`${s.t("price_f")} ${s.t("min")}`} />
        <span>-</span>
        <input className={s.cx("input", "input-sm")} name="max" inputMode="decimal" placeholder={s.t("max")} value={max} onChange={(e) => setMax(e.target.value)} aria-label={`${s.t("price_f")} ${s.t("max")}`} />
        <button type="submit" className={s.cx("btn", "btn-secondary")}>{s.t("apply")}</button>
      </div>
    </form>,
    <div key="rating" className={s.cx("filter-group")}><div className={s.cx("filter-title")}>{s.t("rating_f")}</div>
      {[4, 3].map((n) => (
        <label key={n} className={s.cx("check-row")}>
          <input type="radio" name="rating" value={n} checked={params.get("rating") === String(n)} onChange={() => set({ rating: String(n) })} />
          {s.t("stars_up", n)}
        </label>))}
    </div>,
    <div key="stock" className={s.cx("filter-group")}>
      <label className={s.cx("check-row")}>
        <input type="checkbox" name="instock" checked={params.get("instock") === "1"} onChange={(e) => set({ instock: e.target.checked ? "1" : null })} />
        {s.t("in_stock_only")}
      </label>
      <Btn kind="link" onClick={() => set({ brand: null, min: null, max: null, rating: null, instock: null })}>{s.t("clear")}</Btn>
    </div>,
  ];
  return compact ? <div className={s.cx("filter-panel")}>{groups}</div> : <aside aria-label={s.t("filters")}><Wrap>{groups}</Wrap></aside>;
}

function SortSelect({ params, set }) {
  const s = useSite();
  return (
    <label className={s.cx("check-row")}>{s.t("sort_by")}
      <select className={s.cx("select")} name="sort" value={params.get("sort") || "relevance"} onChange={(e) => set({ sort: e.target.value })} data-testid={s.tid("sort-select")}>
        {SORT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function Pagination({ data, set }) {
  const s = useSite();
  if (data.pages <= 1) return null;
  const pages = Array.from({ length: data.pages }, (_, i) => i + 1);
  return (
    <nav className={s.cx("pagination")} aria-label={s.t("page")}>
      {s.layout === 2 && data.page > 1 ? <button type="button" className={s.cx("page-btn")} onClick={() => set({ page: String(data.page - 1) })}>{s.t("prev")}</button> : null}
      {pages.map((n) => (
        <button key={n} type="button" className={s.cx("page-btn", n === data.page && "page-btn-on")} aria-current={n === data.page ? "page" : undefined}
          onClick={() => set({ page: String(n) })}>{n}</button>))}
      {s.layout === 2 && data.page < data.pages ? <button type="button" className={s.cx("page-btn")} onClick={() => set({ page: String(data.page + 1) })}>{s.t("next")}</button> : null}
    </nav>
  );
}

export function Listing({ mode }) {
  const s = useSite();
  const { slug } = useParams();
  const { categories } = useShop();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [shown, setShown] = useState(1);                     // layout 1: "Load more" pages
  const [dialog, setDialog] = useState(false);
  const cat = categories.find((c) => c.slug === slug);
  const title = mode === "search" ? (params.get("q") ? `"${params.get("q")}"` : s.t("all_products")) : cat?.name || "";
  useTitle(title);
  const key = `${slug}|${params.toString()}`;
  useEffect(() => { setShown(1); }, [slug, params.get("q"), params.get("brand"), params.get("min"), params.get("max"), params.get("rating"), params.get("instock"), params.get("sort")]);
  useEffect(() => {
    const q = new URLSearchParams(params);
    if (mode === "category") q.set("category", slug);
    if (s.layout === 1) { q.set("page", "1"); q.set("per", String(12 * shown)); }
    api(`/products?${q}`).then((d) => { setData(d); setErr(""); }).catch((e) => setErr(e.message));
  }, [key, shown, s.layout]);
  const set = (changes) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v === null || v === "" ? next.delete(k) : next.set(k, v)));
    if (!("page" in changes)) next.delete("page");
    setParams(next);
    setDialog(false);
  };
  if (mode === "category" && categories.length && !cat) return <NotFound />;
  const head = (
    <>
      <div className={s.cx("crumbs")}><Link to="/">{s.t("home")}</Link> / {mode === "search" ? "Search" : cat?.name}</div>
      <h1 className={s.cx("section-title")}>{title}</h1>
    </>
  );
  if (!data) return <div className={s.cx("container")}>{head}<Alert>{err}</Alert></div>;
  const count = <span className={s.cx("muted")}>{s.t("results", data.total)}</span>;
  const empty = data.total === 0 ? <div className={s.cx("empty")}>No products match. <Btn kind="link" onClick={() => setParams(params.get("q") ? { q: params.get("q") } : {})}>{s.t("clear")}</Btn></div> : null;

  if (s.layout === 1) {
    return (
      <div className={s.cx("container")}>
        {head}
        <div className={s.cx("filter-bar")}>
          <Btn kind="secondary" onClick={() => setDialog(!dialog)} aria-expanded={dialog}>{s.t("filters")}</Btn>
          <SortSelect params={params} set={set} /> {count}
        </div>
        {dialog ? <Filters data={data} params={params} set={set} compact /> : null}
        {empty || <ProductGrid items={data.items} view="list" />}
        {data.items.length < data.total ? <div className={s.cx("load-more")}><Btn kind="secondary" onClick={() => setShown(shown + 1)}>{s.t("load_more")}</Btn></div> : null}
      </div>
    );
  }
  if (s.layout === 2) {
    return (
      <div className={s.cx("container")}>
        {head}
        <div className={s.cx("toolbar")}>{count}<Btn kind="secondary" onClick={() => setDialog(true)}>{s.t("filter_sort")}</Btn></div>
        {empty || <ProductGrid items={data.items} view="grid4" quickAdd />}
        <Pagination data={data} set={set} />
        {dialog ? (
          <div className={s.cx("modal-backdrop")} onClick={(e) => e.target === e.currentTarget && setDialog(false)}>
            <div className={s.cx("modal-panel")} role="dialog" aria-modal="true" aria-label={s.t("filter_sort")}>
              <div className={s.cx("modal-head")}><h2 className={s.cx("modal-title")}>{s.t("filter_sort")}</h2>
                <Btn kind="link" onClick={() => setDialog(false)} label={s.t("close")}>✕</Btn></div>
              <SortSelect params={params} set={set} />
              <Filters data={data} params={params} set={set} />
              <Btn onClick={() => setDialog(false)}>{s.t("show_results")}</Btn>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className={s.cx("container")}>
      {head}
      <div className={s.cx("listing")}>
        <Filters data={data} params={params} set={set} />
        <div>
          <div className={s.cx("toolbar")}>{count}<SortSelect params={params} set={set} /></div>
          {empty || <ProductGrid items={data.items} />}
          <Pagination data={data} set={set} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ product page
function Reviews({ p }) {
  const s = useSite();
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  useEffect(() => { api(`/products/${p.id}/reviews?page=${page}`).then(setData).catch(() => {}); }, [p.id, page]);
  if (!data) return null;
  return (
    <div>
      <p><Stars value={p.rating} /> <strong>{p.rating}</strong> {s.t("reviews_count", p.reviewCount)}</p>
      {data.items.map((r) => (
        <div key={r.id} className={s.cx("review")}>
          <div className={s.cx("review-head")}><Stars value={r.stars} /><strong>{r.author}</strong><span className={s.cx("muted")}>{r.date}</span></div>
          <div>{r.text}</div>
        </div>))}
      {data.pages > 1 ? (
        <div className={s.cx("pagination")}>
          {Array.from({ length: data.pages }, (_, i) => i + 1).map((n) => (
            <button key={n} type="button" className={s.cx("page-btn", n === data.page && "page-btn-on")} onClick={() => setPage(n)}>{n}</button>))}
        </div>) : null}
    </div>
  );
}

function Specs({ p }) {
  const s = useSite();
  return <table className={s.cx("specs")}><tbody>{Object.entries(p.specs).map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}</tbody></table>;
}

function Variant({ label, name, options, value, onChange }) {
  const s = useSite();
  if (!options.length) return null;
  if (s.layout === 2) {
    return (
      <div className={s.cx("variant")} role="radiogroup" aria-label={label}>
        <span className={s.cx("variant-label")}>{label}: {value || ""}</span>
        <div className={s.cx("swatches")}>
          {options.map((o) => <button key={o} type="button" role="radio" aria-checked={value === o} className={s.cx("swatch", value === o && "swatch-on")} onClick={() => onChange(o)}>{o}</button>)}
        </div>
      </div>
    );
  }
  return (
    <label className={s.cx("variant")}>
      <span className={s.cx("variant-label")}>{label}</span>
      <select className={s.cx("select")} name={name} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{s.t("choose")}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

export function ProductPage() {
  const s = useSite();
  const { id } = useParams();
  const { setCart, refresh } = useShop();
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [color, setColor] = useState("");
  const [size, setSize] = useState("");
  const [qty, setQty] = useState(1);
  const [msg, setMsg] = useState({});
  const [tab, setTab] = useState("description");
  const [open, setOpen] = useState({ description: true });
  const [showReviews, setShowReviews] = useState(false);
  const [saved, setSaved] = useState(false);
  useTitle(p?.name);
  useEffect(() => {
    setP(null); setErr(""); setQty(1); setMsg({}); setShowReviews(false);
    api(`/products/${id}`).then((d) => { setP(d); setColor(d.colors.length === 1 ? d.colors[0] : ""); setSize(""); }).catch((e) => setErr(e.message));
  }, [id]);
  if (err) return <NotFound text={err} />;
  if (!p) return <div className={s.cx("container")} />;
  const add = async () => {
    try {
      setCart(await api("/cart", { method: "POST", body: { productId: p.id, qty, color: color || null, size: size || null } }));
      setMsg({ ok: s.t("added") });
    } catch (e) { setMsg({ error: e.message }); refresh(); }
  };
  const save = async () => { await api("/wishlist", { method: "POST", body: { productId: p.id } }); setSaved(true); };
  const sections = [["description", s.t("description"), <p key="d">{p.description}</p>], ["specs", s.t("specifications"), <Specs key="s" p={p} />],
    ["reviews", `${s.t("reviews")} (${p.reviewCount})`, <Reviews key="r" p={p} />]];
  const buy = (
    <div className={s.cx("pdp-info", s.layout === 2 && "pdp-sticky")}>
      <Link to={`/search?q=${encodeURIComponent(p.brand)}`} className={s.cx("pdp-brand")}>{p.brand}</Link>
      <h1 className={s.cx("pdp-title")}>{p.name}</h1>
      <div><Stars value={p.rating} /> {p.rating} · {s.t("reviews_count", p.reviewCount)}</div>
      <div><Price p={p} /></div>
      <div><Stock p={p} /></div>
      <Variant label={s.t("color")} name="color" options={p.colors.length > 1 ? p.colors : []} value={color} onChange={setColor} />
      <Variant label={s.t("size")} name="size" options={p.sizes} value={size} onChange={setSize} />
      <div className={s.cx("buy-row")}>
        <div className={s.cx("qty")}>
          <button type="button" className={s.cx("qty-btn")} onClick={() => setQty(Math.max(1, qty - 1))} aria-label={s.t("decrease")}>−</button>
          <input className={s.cx("qty-input")} name="quantity" type="number" min="1" value={qty} onChange={(e) => setQty(Math.max(1, parseInt(e.target.value || "1", 10)))}
            aria-label={s.t("quantity")} />
          <button type="button" className={s.cx("qty-btn")} onClick={() => setQty(qty + 1)} aria-label={s.t("increase")}>+</button>
        </div>
        <Btn onClick={add} disabled={p.stock <= 0} testid="add-to-cart">{s.t("add_to_cart")}</Btn>
        <Btn kind="secondary" onClick={save} testid="wishlist-button" label={saved ? s.t("in_wishlist") : s.t("add_wishlist")}>{saved ? "♥" : "♡"}</Btn>
      </div>
      <Alert kind="ok">{msg.ok ? <>{msg.ok} · <Link to="/cart">{s.t("view_cart")}</Link></> : null}</Alert>
      <Alert>{msg.error}</Alert>
    </div>
  );
  const crumbs = <div className={s.cx("crumbs")}><Link to="/">{s.t("home")}</Link> / <Link to={`/c/${p.category}`}>{p.category.replace(/-/g, " ")}</Link> / {p.name}</div>;
  return (
    <div className={s.cx("container")}>
      {crumbs}
      <div className={s.cx("pdp")}>
        <div className={s.cx("pdp-gallery")}><ProductImage p={p} size={600} /></div>
        <Wrap>{buy}</Wrap>
      </div>
      {s.layout === 0 ? (
        <>
          <div className={s.cx("tabs")} role="tablist">
            {sections.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={s.cx("tab", tab === k && "tab-on")} onClick={() => setTab(k)}>{label}</button>)}
          </div>
          <div className={s.cx("tab-panel")} role="tabpanel">{sections.find(([k]) => k === tab)[2]}</div>
        </>
      ) : s.layout === 1 ? (
        sections.map(([k, label, body]) => (
          <div key={k} className={s.cx("acc-item")}>
            <button type="button" className={s.cx("acc-head")} aria-expanded={!!open[k]} onClick={() => setOpen({ ...open, [k]: !open[k] })}>{label}<span>{open[k] ? "−" : "+"}</span></button>
            {open[k] ? <div className={s.cx("acc-body")}>{body}</div> : null}
          </div>))
      ) : (
        <>
          <div className={s.cx("panel")} style={{ marginTop: 24 }}><h2 className={s.cx("panel-title")}>{s.t("description")}</h2>{sections[0][2]}<Specs p={p} /></div>
          <div className={s.cx("panel")}>
            <h2 className={s.cx("panel-title")}>{s.t("reviews")}</h2>
            {showReviews ? <Reviews p={p} /> : <Btn kind="secondary" onClick={() => setShowReviews(true)}>{s.t("show_reviews")} ({p.reviewCount})</Btn>}
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ cart
function Summary({ cart, shipping, children }) {
  const s = useSite();
  return (
    <aside className={s.cx("summary")}>
      <div className={s.cx("summary-row")}><span>{s.t("subtotal")}</span><span>{money(cart.subtotal)}</span></div>
      {cart.discount ? <div className={s.cx("summary-row")}><span>{s.t("discount")} ({cart.coupon})</span><span>−{money(cart.discount)}</span></div> : null}
      {shipping !== undefined ? <div className={s.cx("summary-row")}><span>{s.t("shipping")}</span><span>{shipping === 0 ? s.t("free") : money(shipping)}</span></div> : null}
      <div className={s.cx("summary-row", "summary-total")}><span>{s.t("total")}</span><span>{money(cart.total + (shipping || 0))}</span></div>
      {children}
    </aside>
  );
}

function CartLine({ l }) {
  const s = useSite();
  const { setCart } = useShop();
  const [qty, setQty] = useState(l.qty);
  const [err, setErr] = useState("");
  useEffect(() => setQty(l.qty), [l.qty]);
  const update = async (q) => {
    try { setCart(await api(`/cart/${l.lineId}`, { method: "PATCH", body: { qty: q } })); setErr(""); } catch (e) { setErr(e.message); setQty(l.qty); }
  };
  const remove = async () => setCart(await api(`/cart/${l.lineId}`, { method: "DELETE" }));
  const meta = [l.color, l.size].filter(Boolean).join(" · ");
  return (
    <div className={s.cx("cart-line")}>
      <Link to={`/p/${l.productId}/x`} className={s.cx("line-img")} tabIndex={-1} aria-hidden="true"><ProductImage p={{ name: l.name, hue: l.hue }} size={90} /></Link>
      <div>
        <Link to={`/p/${l.productId}/x`} className={s.cx("line-name")}>{l.name}</Link>
        <div className={s.cx("line-meta")}>{meta ? `${meta} · ` : ""}{money(l.price)} each</div>
        <Btn kind="link" onClick={remove} label={`${s.t("remove")} ${l.name}`}>{s.t("remove")}</Btn>
        <Alert>{err}</Alert>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); update(qty); }} className={s.cx("price-row")}>
        <input className={s.cx("input", "input-sm")} name="qty" type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)}
          aria-label={`${s.t("quantity")}: ${l.name}`} data-testid={s.tid("qty-input")} />
        <button type="submit" className={s.cx("btn", "btn-secondary")}>{s.t("update")}</button>
      </form>
      <div className={s.cx("line-total")}>{money(l.lineTotal)}</div>
    </div>
  );
}

export function CartPage() {
  const s = useSite();
  const { cart, setCart, refresh } = useShop();
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  useTitle(s.t("cart"));
  useEffect(() => { refresh(); }, []);
  const apply = async (e) => {
    e.preventDefault();
    try { setCart(await api("/cart/coupon", { method: "POST", body: { code } })); setErr(""); } catch (x) { setErr(x.message); }
  };
  if (!cart.lines.length) {
    return <div className={s.cx("container")}><h1 className={s.cx("section-title")}>{s.t("cart")}</h1>
      <div className={s.cx("empty")}>{s.t("cart_empty")} <Link to="/">{s.t("continue_shopping")}</Link></div></div>;
  }
  return (
    <div className={s.cx("container")}>
      <h1 className={s.cx("section-title")}>{s.t("cart")} ({cart.count})</h1>
      <div className={s.cx("cart")}>
        <div><Wrap>{cart.lines.map((l) => <CartLine key={l.lineId} l={l} />)}</Wrap></div>
        <Summary cart={cart}>
          <form className={s.cx("coupon-row")} onSubmit={apply}>
            <input className={s.cx("input")} name="coupon" placeholder={s.t("coupon")} value={code} onChange={(e) => setCode(e.target.value)}
              aria-label={s.t("coupon")} data-testid={s.tid("coupon-input")} />
            <button type="submit" className={s.cx("btn", "btn-secondary")}>{s.t("apply")}</button>
          </form>
          <Alert>{err}</Alert>
          <p className={s.cx("muted")}>Shipping is calculated at checkout.</p>
          <Btn onClick={() => navigate("/checkout")} testid="checkout-button">{s.t("checkout")}</Btn>
          <Link to="/" className={s.cx("btn", "btn-link")}>{s.t("continue_shopping")}</Link>
        </Summary>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ checkout
const COUNTRIES = ["United States", "United Kingdom", "Germany", "Bangladesh", "India", "Canada", "Australia"];

function Field({ label, name, value, onChange, type = "text", wide, required = true, autoComplete }) {
  const s = useSite();
  return (
    <label className={s.cx("field", wide && "field-wide")}>
      <span>{label}{required ? " *" : ""}</span>
      <input className={s.cx("input")} name={name} type={type} value={value} onChange={(e) => onChange(e.target.value)} required={required} autoComplete={autoComplete} />
    </label>
  );
}

export function CheckoutPage() {
  const s = useSite();
  const { cart, setCart, user, refresh } = useShop();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [f, setF] = useState({ email: "", name: "", phone: "", line1: "", city: "", postcode: "", country: "", shipping: "standard", card: "", exp: "", cvc: "" });
  const [rates, setRates] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useTitle(s.t("checkout"));
  useEffect(() => { refresh(); api("/shipping").then(setRates).catch(() => {}); }, []);
  useEffect(() => { if (user && !f.email) setF((x) => ({ ...x, email: user.email, name: user.name })); }, [user]);
  const up = (k) => (v) => setF({ ...f, [k]: v });
  const shipCost = useMemo(() => {
    if (!rates) return undefined;
    const r = rates[f.shipping];
    return f.shipping === "standard" && (cart.coupon === "FREESHIP" || cart.subtotal >= r.freeOver) ? 0 : r.price;
  }, [rates, f.shipping, cart]);
  if (!cart.lines.length) return <div className={s.cx("container")}><div className={s.cx("empty")}>{s.t("cart_empty")} <Link to="/">{s.t("continue_shopping")}</Link></div></div>;

  const place = async () => {
    setBusy(true); setErr("");
    try {
      const order = await api("/orders", { method: "POST", body: { contact: { email: f.email, name: f.name, phone: f.phone },
        address: { line1: f.line1, city: f.city, postcode: f.postcode, country: f.country }, shipping: f.shipping, payment: { card: f.card } } });
      setCart({ lines: [], count: 0, subtotal: 0, discount: 0, total: 0 });
      navigate(`/order/${order.id}`);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const contact = (
    <div className={s.cx("panel")} key="c">
      <h2 className={s.cx("panel-title")}>{s.t("contact")}</h2>
      <div className={s.cx("form-grid")}>
        <Field label={s.t("email")} name="email" type="email" value={f.email} onChange={up("email")} autoComplete="email" />
        <Field label={s.t("full_name")} name="name" value={f.name} onChange={up("name")} autoComplete="name" />
        <Field label={s.t("phone")} name="phone" value={f.phone} onChange={up("phone")} required={false} autoComplete="tel" />
      </div>
      <h2 className={s.cx("panel-title")} style={{ marginTop: 16 }}>{s.t("address")}</h2>
      <div className={s.cx("form-grid")}>
        <Field label={s.t("line1")} name="line1" value={f.line1} onChange={up("line1")} wide autoComplete="address-line1" />
        <Field label={s.t("city")} name="city" value={f.city} onChange={up("city")} autoComplete="address-level2" />
        <Field label={s.t("postcode")} name="postcode" value={f.postcode} onChange={up("postcode")} autoComplete="postal-code" />
        <label className={s.cx("field")}><span>{s.t("country")} *</span>
          <select className={s.cx("select")} name="country" value={f.country} onChange={(e) => up("country")(e.target.value)} required>
            <option value="">{s.t("choose")}</option>{COUNTRIES.map((c) => <option key={c}>{c}</option>)}
          </select></label>
      </div>
    </div>
  );
  const shipping = (
    <div className={s.cx("panel")} key="s">
      <h2 className={s.cx("panel-title")}>{s.t("shipping_method")}</h2>
      {rates ? Object.entries(rates).map(([k, r]) => {
        const cost = k === "standard" && (cart.coupon === "FREESHIP" || cart.subtotal >= r.freeOver) ? 0 : r.price;
        return (
          <label key={k} className={s.cx("radio-card", f.shipping === k && "radio-card-on")}>
            <input type="radio" name="shipping" value={k} checked={f.shipping === k} onChange={() => up("shipping")(k)} />
            <span style={{ flex: 1 }}>{r.label}</span><strong>{cost === 0 ? s.t("free") : money(cost)}</strong>
          </label>);
      }) : null}
    </div>
  );
  const payment = (
    <div className={s.cx("panel")} key="p">
      <h2 className={s.cx("panel-title")}>{s.t("payment")}</h2>
      <p className={s.cx("muted")}>Test shop: use card number 4242 4242 4242 4242, any future date and any CVC.</p>
      <div className={s.cx("form-grid")}>
        <Field label={s.t("card")} name="card" value={f.card} onChange={up("card")} wide autoComplete="cc-number" />
        <Field label="Expiry (MM/YY)" name="exp" value={f.exp} onChange={up("exp")} autoComplete="cc-exp" />
        <Field label="CVC" name="cvc" value={f.cvc} onChange={up("cvc")} autoComplete="cc-csc" />
      </div>
    </div>
  );
  const placeBtn = <Btn type="submit" testid="place-order" disabled={busy}>{s.t("place_order")} · {money(cart.total + (shipCost || 0))}</Btn>;
  const summary = (
    <Summary cart={cart} shipping={shipCost}>
      {cart.lines.map((l) => <div key={l.lineId} className={s.cx("summary-row")}><span>{l.qty} × {l.name}</span><span>{money(l.lineTotal)}</span></div>)}
    </Summary>
  );
  if (s.layout === 2) {                                         // redesign: one-page checkout
    return (
      <div className={s.cx("container")}>
        <h1 className={s.cx("section-title")}>{s.t("checkout")}</h1>
        <form className={s.cx("checkout")} onSubmit={(e) => { e.preventDefault(); place(); }}>
          <div>{contact}{shipping}{payment}<Alert>{err}</Alert>{placeBtn}</div>{summary}
        </form>
      </div>
    );
  }
  const names = [s.t("contact"), s.t("shipping_method"), s.t("payment")];
  const next = (e) => {
    e.preventDefault();
    if (step === 1 && !(f.email && f.name && f.line1 && f.city && f.postcode && f.country)) return setErr("Please fill in all required fields.");
    setErr("");
    if (step < 3) setStep(step + 1); else place();
  };
  return (
    <div className={s.cx("container")}>
      <h1 className={s.cx("section-title")}>{s.t("checkout")}</h1>
      <div className={s.cx("steps")}>
        {names.map((n, i) => <span key={n} className={s.cx("step", step === i + 1 && "step-on", step > i + 1 && "step-done")} aria-current={step === i + 1 ? "step" : undefined}>{i + 1}. {n}</span>)}
      </div>
      <form className={s.cx("checkout")} onSubmit={next}>
        <div>
          {[contact, shipping, payment][step - 1]}
          <Alert>{err}</Alert>
          <div className={s.cx("buy-row")}>
            {step > 1 ? <Btn kind="secondary" onClick={() => setStep(step - 1)}>{s.t("back")}</Btn> : null}
            {step < 3 ? <Btn type="submit">{s.t("continue")}</Btn> : placeBtn}
          </div>
        </div>
        {summary}
      </form>
    </div>
  );
}

export function OrderPage() {
  const s = useSite();
  const { id } = useParams();
  const [o, setO] = useState(null);
  const [err, setErr] = useState("");
  useTitle(s.t("order_confirmed"));
  useEffect(() => { api(`/orders/${id}`).then(setO).catch((e) => setErr(e.message)); }, [id]);
  if (err) return <NotFound text={err} />;
  if (!o) return <div className={s.cx("container")} />;
  return (
    <div className={s.cx("container")}>
      <div className={s.cx("confirm-box")}>
        <h1 className={s.cx("section-title")}>{s.t("order_confirmed")}</h1>
        <p>{s.t("order_number")}: <strong data-testid="order-number">{o.id}</strong></p>
        <p className={s.cx("muted")}>A confirmation was sent to {o.contact.email}.</p>
        <table className={s.cx("specs")}><tbody>
          {o.lines.map((l, i) => <tr key={i}><th>{l.qty} × {l.name}{l.color ? ` (${[l.color, l.size].filter(Boolean).join(", ")})` : ""}</th><td>{money(l.price * l.qty)}</td></tr>)}
          {o.discount ? <tr><th>{s.t("discount")} ({o.coupon})</th><td>−{money(o.discount)}</td></tr> : null}
          <tr><th>{s.t("shipping")}</th><td>{o.shippingCost === 0 ? s.t("free") : money(o.shippingCost)}</td></tr>
          <tr><th><strong>{s.t("total")}</strong></th><td><strong>{money(o.total)}</strong></td></tr>
        </tbody></table>
        <p><Link to="/" className={s.cx("btn", "btn-primary")}>{s.t("continue_shopping")}</Link></p>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ account
export function LoginPage() {
  const s = useSite();
  const { setUser, refresh } = useShop();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  useTitle(s.t("sign_in"));
  const submit = async (e) => {
    e.preventDefault();
    try { setUser(await api("/login", { method: "POST", body: { email, password } })); refresh(); navigate("/account/orders"); }
    catch (x) { setErr(x.message); }
  };
  return (
    <div className={s.cx("container")}>
      <form className={s.cx("auth-box")} onSubmit={submit}>
        <h1 className={s.cx("section-title")}>{s.t("sign_in")}</h1>
        <label className={s.cx("field")}><span>{s.t("email")}</span>
          <input className={s.cx("input")} name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
        <label className={s.cx("field")}><span>{s.t("password")}</span>
          <input className={s.cx("input")} name="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        <Alert>{err}</Alert>
        <Btn type="submit" testid="login-submit">{s.t("sign_in")}</Btn>
      </form>
    </div>
  );
}

export function OrdersPage() {
  const s = useSite();
  const { user, setUser } = useShop();
  const navigate = useNavigate();
  const [orders, setOrders] = useState(null);
  useTitle(s.t("orders"));
  useEffect(() => { api("/orders").then(setOrders).catch(() => setOrders([])); }, [user]);
  const logout = async () => { await api("/logout", { method: "POST" }); setUser(null); navigate("/"); };
  return (
    <div className={s.cx("container")}>
      <div className={s.cx("toolbar")}>
        <h1 className={s.cx("section-title")}>{s.t("orders")}</h1>
        {user ? <span>{user.name} · <Btn kind="link" onClick={logout}>{s.t("sign_out")}</Btn></span> : <Link to="/account/login">{s.t("sign_in")}</Link>}
      </div>
      {orders && !orders.length ? <div className={s.cx("empty")}>No orders yet.</div> : null}
      {(orders || []).map((o) => (
        <div key={o.id} className={s.cx("panel")}>
          <div className={s.cx("toolbar")}><Link to={`/order/${o.id}`}><strong>{o.id}</strong></Link><span>{o.created.slice(0, 10)} · {o.status} · {money(o.total)}</span></div>
          <div className={s.cx("muted")}>{o.lines.map((l) => `${l.qty} × ${l.name}`).join(", ")}</div>
        </div>))}
    </div>
  );
}

export function WishlistPage() {
  const s = useSite();
  const [items, setItems] = useState(null);
  useTitle(s.t("wishlist"));
  useEffect(() => { api("/wishlist").then(setItems).catch(() => setItems([])); }, []);
  const remove = async (id) => setItems(await api(`/wishlist/${id}`, { method: "DELETE" }));
  return (
    <div className={s.cx("container")}>
      <h1 className={s.cx("section-title")}>{s.t("wishlist")}</h1>
      {items && !items.length ? <div className={s.cx("empty")}>Nothing saved yet.</div> : null}
      {(items || []).map((p) => (
        <div key={p.id} className={s.cx("panel")}>
          <div className={s.cx("toolbar")}><Link to={productUrl(p)}><strong>{p.name}</strong></Link><span><Price p={p} /> · <Stock p={p} /></span>
            <Btn kind="link" onClick={() => remove(p.id)} label={`${s.t("remove")} ${p.name}`}>{s.t("remove")}</Btn></div>
        </div>))}
    </div>
  );
}

export function HelpPage() {
  const s = useSite();
  const [open, setOpen] = useState(null);
  useTitle(s.t("help"));
  const faq = [
    ["How much does shipping cost?", "Standard shipping (3-5 business days) costs $4.99 and is free when your items subtotal (before discount codes) is $50 or more. Express shipping (1-2 business days) costs $14.99."],
    ["What is your return policy?", "You can return most items within 30 days of delivery for a full refund. Items must be unused and in their original packaging. Beauty products can only be returned unopened. Refunds are issued to the original payment method within 5 business days after we receive the return."],
    ["Do you have discount codes?", "Yes. SAVE10 gives 10% off the items in your cart. FREESHIP gives free standard shipping. Only one code can be used per order."],
    ["Which payment methods do you accept?", "Visa, Mastercard and American Express. This is a test shop: use card number 4242 4242 4242 4242."],
    ["Can I change my order?", "Orders can be changed or cancelled within 1 hour of being placed. After that, please wait for delivery and start a return."],
    ["Do you ship internationally?", "We ship to the United States, United Kingdom, Germany, Bangladesh, India, Canada and Australia. International delivery takes 7-14 business days."],
  ];
  return (
    <div className={s.cx("container")}>
      <h1 className={s.cx("section-title")}>{s.t("help")}</h1>
      {faq.map(([q, a], i) => (
        <div key={i} className={s.cx("acc-item")}>
          <button type="button" className={s.cx("acc-head")} aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>{q}<span>{open === i ? "−" : "+"}</span></button>
          {open === i ? <div className={s.cx("acc-body")}>{a}</div> : null}
        </div>))}
    </div>
  );
}

export function NotFound({ text }) {
  const s = useSite();
  useTitle("Page not found");
  return <div className={s.cx("container")}><div className={s.cx("empty")}><h1 className={s.cx("section-title")}>Page not found</h1><p>{text || "We couldn't find that page."}</p><Link to="/">{s.t("home")}</Link></div></div>;
}
