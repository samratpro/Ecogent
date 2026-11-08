# Plan — Test Site for Self-Healing and Complex Websites

> **Goal.** Show, with numbers, how Ecogent finds the same element again when the website's code changes
> (self-healing), and how it handles hard website features (popups, shadow DOM, iframes, infinite scroll,
> JavaScript-built pages).
> **Idea.** One test site with the same data, the same look, and a different inside: ids, classes, tags,
> nesting (the "path" to an element) and URLs change. One click (or one URL parameter) switches the version.
> Hosted on our VPS, so anyone can repeat the test.

---

## 1. Why we build it

| Problem today | What the new site fixes |
|---|---|
| Our drift levels 1–4 change **code and look together** (banner, new wording, redesign). When Ecogent fails, we cannot say whether the code change or the look change caused it. | A **"same look" track**: only the code changes, and the screenshot stays the same. Any failure is caused by the code change alone. |
| Level 1 has a bug: classes are renamed in the HTML but **not in the `<style>` block**, so `.wrap` loses its width and the page looks slightly different. | Renames are applied to the HTML **and** the CSS. A screenshot check proves the look did not change. |
| A real website changes when it wants. We cannot repeat a real run, and we do not know the right answer. | A fixed site with fixed data: the ground truth is known exactly and every run can be repeated (seeded). |
| Agents that pick elements by screenshot or by text, and agents that pick by selector, break in different ways. We want to show this difference. | Same look + new code is easy for "looks like" methods and hard for "selector replay" methods. That is exactly where Ecogent's ladder should help. |
| The paper says "handles complex websites", but the lab covers only some features. | A **"complex features"** track: one page per hard feature, each with a task and an oracle. |

**The research question this answers:**
*When a website's code changes but its look and meaning stay the same, how often does Ecogent recover,
at which step of its lookup ladder, and at what LLM cost, compared to agents with no repair or with an
LLM call every run?*

---

## 2. What Ecogent does when an element is gone (what we are testing)

`Executor.resolve` tries the cheapest way first (details in the ecogent skill):

| Rung | Method | LLM cost |
|---|---|---|
| R1 | Cached selector, accepted only if the element is still the same (tag + stable attributes + text) | 0 |
| R2 | Stored alternates (id, test-id, name, aria-label, placeholder, `tag:text-is()`) | 0 |
| R3 | Local re-find: score the page's elements against the remembered one, accept only a clear winner | 0 |
| R4 | Obvious choice: the only element that fits | 0 |
| R5 | LLM pick: 15 → 60 candidates → focused outline → full outline | small → large |
| R6 | Heal / rescue (ReAct turns) | largest |

Each code change below is built to **break specific rungs**. This lets the results show *which rung saved
the run*. The benchmark CSV already records `cache_hits`, `local_heals`, `local_picks`, `llm_lookups`,
`healed` and `rescued`, and the ablations (`no_identity`, `no_alternates`, `no_refind`, `no_obvious`,
`no_graded`, `no_repair`) switch single rungs off.

---

## 3. Track S — "same look, new code"

Cumulative steps, like the current levels, seeded and reproducible. Every page at every step must give
**the same screenshot** as S0 (checked automatically, see §5).

| Step | What changes in the code | How the look stays the same | Rung it should break | Rung expected to recover |
|---|---|---|---|---|
| **S0** | Nothing (base) | – | – | R1 |
| **S1** | Ids, classes and `data-testid` renamed | The same renames are applied inside the `<style>` rules | R1 when the selector uses a class or id; R2 for id / test-id | R2 (aria-label, name, text) |
| **S2** | + extra wrapper `<div>`s around elements and groups | `display: contents` on each wrapper: it takes no space | Every nested path (`main > div > a`, `nth-child`) | R1 / R2 if the selector was not a path, else R3 |
| **S3** | + tags swapped: `<button>` → `<a role="button">`, `<ul>/<li>` → `<div>`, `<h3>` → `<div role="heading">` | CSS styles both forms the same way | The identity check (the tag changed) and `tag:text-is()` | R3 (text + attributes still match) |
| **S4** | + elements in a different order in the code (product card fields, menu, table columns) | Flexbox / grid `order` puts them back on screen | `nth-child`, "the 2nd link in the card" | R3 / R4 |
| **S5** | + accessible names moved: `aria-label` → `aria-labelledby`, label `for` → wrapping `<label>`, `placeholder` kept | The text on screen is the same | R2 for aria-label | R3 / R5 |
| **S6** | + URL paths renamed: `/shop/p/101` → `/store/item/101` (the old URLs give a 301 redirect) | The pages are identical | Saved `link_hrefs`, a URL-based `goto` | Redirect + link signature; re-pick if needed |
| **S7 (per load)** | S1–S5, but with **new random names on every page load** (seed = time) | Same | Everything cached | Tests that healing does not loop or "thrash" and that the cost per run stays bounded |

S0–S5 never change the visible text, the data, the form field names, the form actions or the link targets
(the same rules `selftest.py` checks for the current levels). S6 changes URLs only, with redirects.

**Why build it this way:**
- One change is added per step, so a drop in success points to a single cause.
- "Same look" removes the visual confound, so a vision-based agent should score ~100% on every step.
  If a selector-replay agent fails at S1–S4 and Ecogent does not, that is the claim of the paper, isolated.
- S7 is the worst case real websites create (React/CSS-in-JS class hashes that change on every build).

---

## 4. Track C — "complex features"

One page (or small flow) per feature, each with its own task and oracle in `bench/lab/tasks.py`. These do
not drift by themselves; they can be combined with any S step.

| Feature | Why it is hard for an agent | Task idea |
|---|---|---|
| Shadow DOM (open) product cards | The page HTML (and so BeautifulSoup / `page_reader`) does not contain it; Playwright selectors can reach open shadow roots | Scrape name + price of all cards |
| iframe checkout form | Element is in another document | Fill and submit the form in the iframe |
| Infinite scroll (no "Load more" button) | Content appears only after scrolling | Collect all 30 items |
| Lazy content (rendered 1–3 s after load) | Agent may read the page too early | Read the price that appears late |
| JavaScript-built page (page arrives as JSON, JS draws it) | Raw HTML is empty; timing matters | Same shop task, `?lab_render=js` |
| Virtualized list (only ~10 rows in the DOM at a time) | Rows exist only while visible | Find one contact far down the list |
| Hover menu | The link is hidden until the mouse is over the menu | Open "Toys → Outdoor" |
| Custom dropdown (div-based, not `<select>`) | `select_option` does not work | Pick a stage in the deal wizard |
| Toast / delayed second popup | Blocks a click only sometimes | Add to cart while the popup appears |
| Tabs + accordion | Content is in the DOM but hidden | Read the spec in the closed "Details" tab |
| Same-text decoys ("Add to cart" ×12, a hidden honeypot button) | Text-only matching picks the wrong one | Add the 3rd product, not the first |

**Why:** the paper should say which hard features Ecogent handles, which it handles only with LLM help, and
which it fails. A clear "fails" row is honest and useful; we keep it in the table.

---

## 5. How we check the site is right (before any LLM money)

1. **Look check (new):** Playwright screenshots every page at S0 and at S1–S5 (2 seeds) and compares the
   pixels. Allowed difference: 0.1% of pixels (anti-aliasing). Any page above that fails the build.
2. **Invariant check (extend `selftest.py`):** data, visible text, form fields and actions are identical
   at every S step; every old URL still works at S6 (redirect).
3. **Break check (new):** for each S step, confirm the intended rungs really break: replay the S0 selectors
   with no healing (`compile_only` / `no_repair`) and require that they fail on the pages listed in §3.
   If the old selectors still work, the step tests nothing.
4. **Fake run:** `python -m bench.lab.fake_run` on S1–S7 must still print `FAKE RUN OK`.

---

## 6. How we run the experiment

- `drift_bench.py` gets level names `S0`…`S7` next to `0`…`4`, e.g.
  `--levels S0,S1,S2,S3,S4,S5,S6,S7`.
- **Variants:** `ecogent`, `compile_only`, `nocache`, plus single-rung ablations
  (`no_alternates`, `no_refind`, `no_obvious`, `no_identity`).
- **Protocol:** the same as today: cold at S0 → `rerun` at each S step → `rerun2` (was the repair saved?).
  3 seeds.
- **Public site:** `bench/lab/public.py` gets `?lab_mode=S3` (and `?lab_render=js`) next to `?lab_level=`,
  and the switch bar shows both tracks. Hand-driven agents (Claude in Chrome, Comet, browser-use) are
  tested there with `benchmark_manual_testing.md`.

**What we expect (written down before running, so the paper is honest):**

| # | Hypothesis | Shown by |
|---|---|---|
| H1 | Ecogent success at S1–S5 stays within 5 points of S0 | success column |
| H2 | Most S1–S5 recoveries use R2–R4 (0 LLM calls) | `local_heals` + `local_picks` vs `llm_lookups` |
| H3 | `compile_only` drops sharply from S1 (and almost to 0 at S3) | success column |
| H4 | Ecogent's repair cost at S1–S5 is far below `nocache` cost per run | `cost_usd` |
| H5 | `rerun2` ≈ 0 calls: one repair is enough | `rerun2` rows |
| H6 | S7 (new names per load) costs LLM calls every run, but bounded, and never loops | calls per run, `max_heals_per_run` hits |
| H7 | `no_refind` hurts most at S3 (tag swap); `no_alternates` hurts most at S1 | ablation figure |

If a hypothesis is false, we report it and look at the step that cost (`by_purpose`), not hide it.

---

## 7. Build order

| Phase | Work | Output | Done when |
|---|---|---|---|
| 1 | Fix level 1: rename classes / ids in `<style>` too. Keep the old behaviour behind a flag so earlier pilot numbers stay comparable | `drift.py` | Look check passes for level 1 |
| 2 | Track S1–S5 in a new module `bench/lab/same_look.py`, wired into `drift.apply` as levels `S1`…`S5` | module + CSS rules | Look, invariant and break checks pass |
| 3 | Screenshot look check | `bench/lab/look_check.py` | Prints `LOOK OK` |
| 4 | S6 (URL renames + redirects) and S7 (per-load names) | `sites.route` + drift | `selftest` + fake run pass |
| 5 | Track C pages + tasks + oracles (start with shadow DOM, iframe, infinite scroll, custom dropdown, decoys) | `sites.py`, `tasks.py` | Each task solvable by hand; oracle gives 1.0 for the right answer |
| 6 | `?lab_render=js` mode | `sites.py` + a small JS renderer | Same oracle results as server-rendered |
| 7 | Public server: `lab_mode`, switch bar for both tracks, redeploy on VPS | `public.py` | Live at the lab subdomain |
| 8 | Pilot (4 tasks × S0–S7 × 2 seeds), then the full run | CSV + summary | Hypotheses table filled in |
| 9 | Figures: success and cost vs S step; "which rung recovered" stacked bars; Track C table | `bench/plot.py` | Figures in the paper |

Phases 1–3 come first: without the look check, "same look" is only a promise.

---

## 8. Risks and how we handle them

| Risk | Handling |
|---|---|
| The look is "almost" the same (font rendering, sub-pixel shifts) | Fixed browser, fixed window size, fonts bundled; small pixel threshold; fail the build otherwise |
| `display: contents` changes accessibility trees in some browsers | Note it; the accessibility-tree agents are tested in the manual study, not hidden |
| We design the changes to suit Ecogent | The changes come from real-site patterns (CSS-module hashes, wrapper components, tag swaps in redesigns); the break check proves each one breaks plain selector replay; hypotheses are written before running |
| Public site gets abused or crawled | noindex, robots.txt, nginx rate limit, 64 KB body limit, per-visitor state with expiry (already in `public.py`) |
| Changing level 1 makes old pilot numbers incomparable | The fix is a new level name / flag; old results keep `level=1` meaning the old behaviour |
| JS mode results depend on timing | Fixed delays from the seed; report waits separately |

---

## 9. What goes into the paper

- A table of the S steps (§3) with a screenshot pair (S0 vs S4) and the code diff of one element, to show
  that the look is the same and the code is different.
- Success and LLM cost vs S step for each system.
- "Which rung recovered": stacked bars per S step. This is the main new evidence for *how* self-healing
  works, not only *that* it works.
- The Track C feature table: handled locally / handled with LLM / failed.
- The public URL and the git tag of the site build, so others can repeat the run.

---

## 10. Open decisions

1. Shadow DOM: open only, or closed too? (Closed shadow roots are unreachable for most agents, including
   Playwright's normal selectors.)
2. Should S7 be in the main results or only in a "stress" appendix?
3. Should Track C tasks count in the 24-task total, or be a separate set?
