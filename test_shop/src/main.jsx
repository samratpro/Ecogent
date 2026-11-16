import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { SiteCtx, makeSite } from "./site.js";
import { buildCss } from "./styles.js";
import { Footer, Header, Interruptions, ShopProvider } from "./components.jsx";
import { CartPage, CheckoutPage, HelpPage, Home, Listing, LoginPage, NotFound, OrderPage, OrdersPage, ProductPage, WishlistPage } from "./pages.jsx";

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function App({ site }) {
  return (
    <SiteCtx.Provider value={site}>
      <ShopProvider>
        <BrowserRouter>
          <ScrollTop />
          <Header />
          <main className={site.cx("main")}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/c/:slug" element={<Listing mode="category" />} />
              <Route path="/search" element={<Listing mode="search" />} />
              <Route path="/p/:id/:slug?" element={<ProductPage />} />
              <Route path="/cart" element={<CartPage />} />
              <Route path="/checkout" element={<CheckoutPage />} />
              <Route path="/order/:id" element={<OrderPage />} />
              <Route path="/account/login" element={<LoginPage />} />
              <Route path="/account/orders" element={<OrdersPage />} />
              <Route path="/wishlist" element={<WishlistPage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </main>
          <Footer />
          <Interruptions />
        </BrowserRouter>
      </ShopProvider>
    </SiteCtx.Provider>
  );
}

async function boot() {
  let cfg = { markup: 0, layout: 0, copy: 0, interruptions: 0, salt: "1" };
  try { cfg = await (await fetch("/api/site", { cache: "no-store" })).json(); } catch { /* server down: base version */ }
  const site = makeSite(cfg);
  const style = document.createElement("style");
  style.textContent = buildCss(site);
  document.head.appendChild(style);
  createRoot(document.getElementById("root")).render(<StrictMode><App site={site} /></StrictMode>);
}
boot();
