// One stylesheet for every site version. buildCss() renames the class selectors with the same
// function the components use (site.cx), so a markup change renames classes in the HTML *and*
// the CSS: the code changes, the look does not.

const CSS = String.raw`
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;color:#1f2933;background:#f6f7f9}
a{color:inherit}
img{display:block;max-width:100%}
.dc{display:contents}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}
.container{max-width:1200px;margin:0 auto;padding:0 20px}
.topbar{background:#12355b;color:#e8eef5;font-size:13px;text-align:center;padding:6px 12px}
.header{background:#fff;border-bottom:1px solid #e3e7ec;position:sticky;top:0;z-index:20}
.header-inner{display:flex;align-items:center;gap:18px;height:68px}
.logo{font-weight:700;font-size:20px;text-decoration:none;color:#12355b;white-space:nowrap}
.search{flex:1;display:flex;max-width:560px}
.search-input{flex:1;border:1px solid #c9d1da;border-right:0;border-radius:8px 0 0 8px;padding:9px 12px;font:inherit}
.search-btn{border:0;background:#12355b;color:#fff;padding:0 16px;border-radius:0 8px 8px 0;font:inherit;cursor:pointer}
.header-actions{display:flex;align-items:center;gap:6px;margin-left:auto}
.icon-btn{display:inline-flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;text-decoration:none;color:#1f2933;cursor:pointer;background:none;border:0;font:inherit}
.icon-btn:hover{background:#eef1f5}
.badge{background:#e4572e;color:#fff;border-radius:999px;font-size:12px;min-width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;padding:0 6px}
.nav{background:#fff;border-bottom:1px solid #e3e7ec}
.nav-inner{display:flex;gap:4px;overflow-x:auto}
.nav-link{padding:10px 12px;text-decoration:none;font-size:14px;color:#3e4c59;white-space:nowrap}
.nav-link:hover{color:#12355b;background:#f1f4f8}
.menu-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid #c9d1da;background:#fff;border-radius:8px;padding:8px 12px;font:inherit;cursor:pointer}
.drawer-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:40}
.drawer-panel{position:fixed;top:0;left:0;bottom:0;width:300px;background:#fff;z-index:41;padding:18px;overflow:auto;box-shadow:4px 0 24px rgba(0,0,0,.15)}
.drawer-link{display:block;padding:10px 6px;border-bottom:1px solid #eef1f5;text-decoration:none}
.main{min-height:70vh;padding:24px 0 48px}
.footer{background:#0f2440;color:#c6d2df;padding:36px 0 20px;font-size:14px}
.footer-cols{display:grid;grid-template-columns:repeat(4,1fr);gap:24px}
.footer-col a{display:block;color:#c6d2df;text-decoration:none;padding:3px 0}
.footer-title{color:#fff;font-weight:600;margin-bottom:8px}
.footer-bottom{border-top:1px solid #23395a;margin-top:24px;padding-top:14px;font-size:13px;color:#8fa3ba}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:8px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer;border:1px solid transparent;text-decoration:none;user-select:none}
.btn-primary{background:#e4572e;color:#fff}
.btn-primary:hover{background:#cf4a23}
.btn-secondary{background:#fff;color:#12355b;border-color:#c9d1da}
.btn-secondary:hover{background:#f1f4f8}
.btn-link{background:none;border:0;color:#1d5fa8;padding:4px 0;font-weight:500;text-decoration:underline}
.btn[aria-disabled=true],.btn:disabled{opacity:.5;cursor:not-allowed}
.muted{color:#66788a}
.alert{padding:10px 14px;border-radius:8px;margin:10px 0;font-size:14px}
.alert-error{background:#fdecea;color:#9b1c1c}
.alert-ok{background:#e7f6ec;color:#1e6b3a}
.stars{color:#f5a524;letter-spacing:1px;font-size:14px}
.stars-off{color:#cfd6de}
.price-now{font-weight:700;font-size:18px;color:#1f2933}
.price-was{text-decoration:line-through;color:#8795a1;margin-left:8px;font-size:14px}
.sale-badge{position:absolute;top:10px;left:10px;background:#e4572e;color:#fff;font-size:12px;font-weight:700;padding:2px 8px;border-radius:6px}
.hero{background:linear-gradient(120deg,#12355b,#1d5fa8);color:#fff;border-radius:16px;padding:44px;display:flex;justify-content:space-between;align-items:center;gap:24px}
.hero-title{font-size:34px;font-weight:700;margin:0 0 8px}
.hero-sub{margin:0 0 18px;color:#d7e4f3;max-width:520px}
.hero-art{width:220px;height:160px;border-radius:12px;background:rgba(255,255,255,.12)}
.section{margin-top:36px}
.section-title{font-size:22px;font-weight:700;margin:0 0 14px}
.cat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.cat-tile{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:18px;text-decoration:none;font-weight:600}
.cat-tile:hover{border-color:#1d5fa8}
.promo-strip{margin-top:28px;background:#fff4e5;border:1px dashed #f0b866;border-radius:12px;padding:14px 18px}
.product-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.product-grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.product-list{display:flex;flex-direction:column;gap:12px}
.card{background:#fff;border:1px solid #e3e7ec;border-radius:12px;overflow:hidden;display:flex;flex-direction:column;position:relative}
.product-list .card{flex-direction:row}
.card-img{position:relative;aspect-ratio:4/3;background:#eef1f5;display:block}
.card-img img,.pdp-gallery img,.line-img img{width:100%;height:100%;object-fit:cover}
.product-list .card-img{width:200px;flex:none}
.card-body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:4px;flex:1}
.card-brand{order:1;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#66788a}
.card-title{order:2;font-weight:600;text-decoration:none;line-height:1.3}
.card-title:hover{text-decoration:underline}
.card-rating{order:3;font-size:13px;color:#66788a}
.card-price{order:4}
.card-stock{order:5;font-size:13px}
.card-actions{order:6;margin-top:auto;padding-top:8px;display:flex;gap:8px}
.stock-ok{color:#1e6b3a}
.stock-low{color:#b45309}
.stock-out{color:#9b1c1c}
.crumbs{font-size:13px;color:#66788a;margin-bottom:10px}
.crumbs a{text-decoration:none}
.listing{display:grid;grid-template-columns:240px 1fr;gap:24px}
.listing-full{display:block}
.filter-group{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:12px 14px;margin-bottom:12px}
.filter-title{font-weight:600;margin-bottom:6px}
.check-row{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:14px;cursor:pointer}
.price-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.input{border:1px solid #c9d1da;border-radius:8px;padding:9px 12px;font:inherit;width:100%;background:#fff}
.input-sm{width:72px}
.select{border:1px solid #c9d1da;border-radius:8px;padding:8px 10px;font:inherit;background:#fff}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.filter-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:10px 12px;margin-bottom:14px}
.filter-panel{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.pagination{display:flex;gap:6px;justify-content:center;margin-top:24px;flex-wrap:wrap}
.page-btn{min-width:38px;padding:8px 10px;border:1px solid #c9d1da;background:#fff;border-radius:8px;cursor:pointer;font:inherit;text-decoration:none;text-align:center}
.page-btn-on{background:#12355b;color:#fff;border-color:#12355b}
.load-more{display:flex;justify-content:center;margin-top:24px}
.modal-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:50;display:flex;align-items:center;justify-content:center;padding:16px}
.modal-panel{background:#fff;border-radius:14px;max-width:560px;width:100%;max-height:85vh;overflow:auto;padding:20px;position:relative}
.modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.modal-title{font-size:20px;font-weight:700;margin:0}
.pdp{display:grid;grid-template-columns:1fr 1fr;gap:32px}
.pdp-gallery{background:#fff;border:1px solid #e3e7ec;border-radius:14px;overflow:hidden;align-self:start}
.pdp-info{display:flex;flex-direction:column;gap:10px}
.pdp-sticky{position:sticky;top:90px;align-self:start}
.pdp-brand{color:#1d5fa8;font-weight:600;text-decoration:none}
.pdp-title{font-size:28px;font-weight:700;margin:0;line-height:1.25}
.variant{display:flex;flex-direction:column;gap:6px}
.variant-label{font-weight:600;font-size:14px}
.swatches{display:flex;gap:8px;flex-wrap:wrap}
.swatch{border:1px solid #c9d1da;background:#fff;border-radius:8px;padding:7px 12px;cursor:pointer;font:inherit}
.swatch-on{border-color:#12355b;box-shadow:0 0 0 2px #12355b inset}
.qty{display:inline-flex;align-items:center;border:1px solid #c9d1da;border-radius:8px;overflow:hidden;background:#fff}
.qty-btn{width:36px;height:38px;border:0;background:#f1f4f8;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center}
.qty-input{width:52px;height:38px;border:0;text-align:center;font:inherit}
.buy-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.tabs{display:flex;gap:4px;border-bottom:1px solid #e3e7ec;margin-top:32px}
.tab{padding:10px 16px;border:0;background:none;cursor:pointer;font:inherit;font-weight:600;color:#66788a;border-bottom:2px solid transparent}
.tab-on{color:#12355b;border-bottom-color:#12355b}
.tab-panel{background:#fff;border:1px solid #e3e7ec;border-top:0;border-radius:0 0 12px 12px;padding:18px}
.acc-item{background:#fff;border:1px solid #e3e7ec;border-radius:12px;margin-top:10px}
.acc-head{width:100%;text-align:left;padding:14px 16px;background:none;border:0;font:inherit;font-weight:600;cursor:pointer;display:flex;justify-content:space-between}
.acc-body{padding:0 16px 16px}
.specs{border-collapse:collapse;width:100%}
.specs th,.specs td{text-align:left;padding:8px;border-bottom:1px solid #eef1f5;font-size:14px}
.specs th{width:40%;color:#66788a;font-weight:500}
.review{border-bottom:1px solid #eef1f5;padding:10px 0}
.review-head{display:flex;gap:10px;align-items:center;font-size:14px}
.cart{display:grid;grid-template-columns:1fr 340px;gap:24px}
.cart-line{display:grid;grid-template-columns:90px 1fr auto auto;gap:14px;align-items:center;background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:12px;margin-bottom:10px}
.line-img{width:90px;border-radius:8px;overflow:hidden}
.line-name{font-weight:600;text-decoration:none}
.line-meta{font-size:13px;color:#66788a}
.line-total{font-weight:700;min-width:80px;text-align:right}
.summary{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:16px;align-self:start;display:flex;flex-direction:column;gap:8px}
.summary-row{display:flex;justify-content:space-between;font-size:14px}
.summary-total{font-weight:700;font-size:17px;border-top:1px solid #e3e7ec;padding-top:8px}
.coupon-row{display:flex;gap:8px}
.checkout{display:grid;grid-template-columns:1fr 340px;gap:24px}
.steps{display:flex;gap:8px;margin-bottom:16px}
.step{padding:6px 12px;border-radius:999px;background:#e9edf2;color:#66788a;font-size:13px;font-weight:600}
.step-on{background:#12355b;color:#fff}
.step-done{background:#d6eadb;color:#1e6b3a}
.panel{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:18px;margin-bottom:14px}
.panel-title{font-size:18px;font-weight:700;margin:0 0 12px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.field{display:flex;flex-direction:column;gap:4px;font-size:14px}
.field-wide{grid-column:1/-1}
.radio-card{display:flex;align-items:center;gap:10px;border:1px solid #c9d1da;border-radius:10px;padding:12px;margin-bottom:8px;cursor:pointer;background:#fff}
.radio-card-on{border-color:#12355b;box-shadow:0 0 0 1px #12355b inset}
.confirm-box{background:#fff;border:1px solid #e3e7ec;border-radius:14px;padding:28px;max-width:680px;margin:0 auto}
.auth-box{background:#fff;border:1px solid #e3e7ec;border-radius:14px;padding:28px;max-width:420px;margin:0 auto;display:flex;flex-direction:column;gap:12px}
.cookie-banner{position:fixed;left:0;right:0;bottom:0;background:#1f2933;color:#e5e9ee;z-index:60;padding:16px 20px;display:flex;gap:16px;align-items:center;justify-content:center;flex-wrap:wrap}
.cookie-actions{display:flex;gap:8px}
.nl-modal{text-align:center}
.nl-close{position:absolute;top:10px;right:10px;border:0;background:none;font-size:22px;cursor:pointer;line-height:1;padding:6px}
.empty{background:#fff;border:1px solid #e3e7ec;border-radius:12px;padding:28px;text-align:center}
@media (max-width:900px){.listing,.pdp,.cart,.checkout{grid-template-columns:1fr}.product-grid,.product-grid-4,.cat-grid,.filter-panel{grid-template-columns:repeat(2,1fr)}.footer-cols{grid-template-columns:repeat(2,1fr)}.hero-art{display:none}}
`;

export function buildCss(site) {
  // Rename class selectors only (the part before "{"), never property values like "0.5em".
  return CSS.replace(/([^{}]+)\{/g, (whole, selector) =>
    selector.trim().startsWith("@") ? whole
      : selector.replace(/\.([a-zA-Z][\w-]*)/g, (_, name) => `.${site.cx(name)}`) + "{");
}
