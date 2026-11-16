# Northwind Market: Neutral Test Shop

A realistic e-commerce site for testing browser agents (Ecogent and the baselines) when a website **changes**:
its code, its layout, its wording, its popups, or its data. Built with React (Vite), served by a small Node server
on **port 3010**. It has no connection to Ecogent's code. Any agent, scripted or manual, uses it the same way.

## Run it

- **From Ecogent:** sidebar → **Benchmark** → **Test shop** → **Start**. The first start installs packages and builds,
  which takes about a minute. The same tab switches the site version.
- **By hand:** `npm install`, `npm run build`, `node server.js --port 3010`, then open http://localhost:3010.

Needs Node 18+.

## What is in the shop

144 products in 8 categories (seeded, the same on every machine). Pages: home, category and search listings with
filters (brand, price, rating, in stock), sorting and pagination, product pages (colour / size variants, quantity,
tabs with specs and paginated reviews), cart (quantity, remove, coupon codes), a 3-step checkout with validation and
a test card, order confirmation, login + order history, wishlist, help / FAQ.
Test account: `ada.tester@example.com` / `Shop!2026`. Test card: `4242 4242 4242 4242`. Codes: `SAVE10`, `FREESHIP`.

## Site versions

Five independent settings, changed for every visitor at once:

| Setting | Values | What changes | Real-world source of this change |
|---|---|---|---|
| **markup** (code, same look) | 0 base · 1 rebuild · 2 refactor · 3 new names every load | 1: class names become hashes, test ids renamed. 2: + wrapper elements, buttons outside forms become `div[role=button]`, card fields in a different code order, accessible names moved to `aria-labelledby`, half the test ids removed. 3: like 2, class names change on every page load | CSS-modules / CSS-in-JS builds, component-library migrations, refactors |
| **layout** (visible) | 0 base · 1 · 2 | 1: categories move into a menu drawer, filters into a top bar, "Load more", accordions instead of tabs. 2: full redesign: 4-column grid, "Filter & sort" dialog, quick-add buttons, colour swatches, reviews behind a button, one-page checkout | Site redesigns, A/B tests |
| **copy** (wording) | 0 · 1 | "Add to cart" → "Add to bag", "Checkout" → "Check out", "Sign in" → "Log in", "Coupon code" → "Promo code", ... | Copywriting / localisation updates |
| **interruptions** | 0 · 1 · 2 | 1: cookie banner. 2: + newsletter popup after 1.5 s | Consent banners, marketing popups |
| **content** (data) | 0, 1, 2, ... | Prices move (±20%), stock changes, about 10% of products are replaced by new ones, ratings and best-seller order change. The **layout stays the same**. This tests whether an agent notices new data or returns an old cached answer | Normal shop data changing between visits |

Markup 1–3 change the code **and** the CSS together, so the page looks identical. `check_look.py` proves this.

## Fairness rules (why this site does not favour Ecogent)

1. **Changes come from real-world patterns** (table above), defined without looking at any agent. No setting was
   designed around Ecogent's element-lookup steps.
2. **Some changes are expected to hurt Ecogent**: wording (its identity check uses text), the redesign (its saved
   plan no longer fits), new names on every load (its cache never hits), new data (cached answers become wrong).
3. **The same version for everyone**: the version is server-wide, set before a run, and recorded with the results.
4. **No answers for agents**: ground truth, recorded orders and the version controls are under `/__lab`, protected by
   a random key (`.lab_key`, created on every start), disallowed in `robots.txt` and never linked from the shop.
5. **Every version can be finished**: `check_flows.py` buys a product in every version using only what a person
   sees (roles, labels, text), never the version-specific class names.
6. **Frozen before testing**: build the site, then freeze it (git tag) before the first agent run. Don't change the
   site or Ecogent's prompts after seeing results on it, or re-run everything.
7. **Realistic, not adversarial**: no hidden traps, honeypots or impossible flows that a normal shop would not have.

## Lab API (for oracles and the Ecogent app; header `x-lab-key: <.lab_key>`)

| Call | What it does |
|---|---|
| `GET /__lab/state` | Current version, all orders, carts, wishlists and an event log (add_to_cart, coupon_applied, order_placed, login, ...) |
| `GET /__lab/truth` | Full catalog for the current data version, coupons, shipping rules, test card, users: the ground truth |
| `POST /__lab/config` `{markup, layout, copy, interruptions, content, seed}` | Change the version (changing `content` also clears carts and orders) |
| `POST /__lab/reset` | Clear carts, orders and events; keep the version |
| `GET /__lab?key=...` | A small control page for manual testing |

## Checks (free, the shop must be running)

```bash
python test_shop/check_look.py     # markup 1-3: identical pixels and words, new class names   -> LOOK OK
python test_shop/check_flows.py    # a scripted user completes a purchase in 18 versions        -> FLOWS OK
```
Both also run from the app (Benchmark → Test shop).

## Not done yet

Benchmark tasks + oracles on this shop (in `bench/lab/tasks.py` style), and `drift_bench.py` support for setting the
shop version per level. See `Ecogent_Works_Doc/self_healing_test_site_plan.md`.
