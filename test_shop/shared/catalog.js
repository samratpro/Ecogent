// Deterministic product catalog for the test shop.
// buildCatalog(0) is the base catalog; buildCatalog(k > 0) applies "content change" k to it:
// prices move, stock changes, ratings drift, some products are replaced by new ones, best-seller
// order changes - the kind of change a real shop's data goes through between two visits.
// Everything is seeded, so the same content number always gives the same catalog (ground truth).

export const BASE_SEED = 2026;

export function rng(seed) {                      // mulberry32
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
const price99 = (v) => Math.max(0.99, Math.round(v) - 0.01);
const slugify = (s) => s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

export const CATEGORIES = [
  { slug: "electronics", name: "Electronics" },
  { slug: "home-kitchen", name: "Home & Kitchen" },
  { slug: "sports-outdoors", name: "Sports & Outdoors" },
  { slug: "books", name: "Books" },
  { slug: "toys-games", name: "Toys & Games" },
  { slug: "beauty", name: "Beauty" },
  { slug: "fashion", name: "Fashion" },
  { slug: "pet-supplies", name: "Pet Supplies" },
];

const SPEC = {
  electronics: {
    brands: ["Voltix", "Aurion", "Kestrel", "Nimbus Audio", "Pixelon"],
    items: [["Wireless Earbuds", 59], ["Noise-Cancelling Headphones", 189], ["Bluetooth Speaker", 79], ["Smartwatch", 229],
      ["Power Bank 20000mAh", 39], ["USB-C Hub 7-in-1", 45], ["Mechanical Keyboard", 119], ["Wireless Mouse", 29],
      ["4K Webcam", 99], ["Portable SSD 1TB", 129], ["Fitness Tracker", 69], ["Smart Plug 2-Pack", 25]],
    colors: ["Black", "White", "Midnight Blue"],
  },
  "home-kitchen": {
    brands: ["Hearthly", "Copperline", "Nordform", "Casa Verde"],
    items: [["Air Fryer 5L", 99], ["Ceramic Cookware Set", 149], ["Electric Kettle 1.7L", 45], ["Chef's Knife 8\"", 69],
      ["French Press 1L", 35], ["Stand Mixer", 279], ["Bamboo Cutting Board", 29], ["Vacuum Flask 1L", 32],
      ["Linen Duvet Cover", 119], ["Scented Candle Trio", 38], ["Cast Iron Skillet 26cm", 55], ["Burr Coffee Grinder", 89]],
    colors: ["Stone", "Sage", "Charcoal"],
  },
  "sports-outdoors": {
    brands: ["Trailpeak", "Stridewell", "Apex Motion", "Riverstone"],
    items: [["Yoga Mat 6mm", 39], ["Running Shoes", 129], ["Adjustable Dumbbells", 199], ["Resistance Bands Set", 29],
      ["Hiking Backpack 30L", 89], ["Cycling Gloves", 25], ["Speed Jump Rope", 15], ["Foam Roller", 27],
      ["Insulated Water Bottle", 33], ["Trail Running Jacket", 149], ["Tennis Racket", 119], ["Camping Lantern", 42]],
    colors: ["Black", "Ocean", "Forest"],
    sized: ["Running Shoes", "Cycling Gloves", "Trail Running Jacket"],
  },
  books: {
    brands: ["Lantern Press", "Northbound Books", "Quill & Ink"],
    items: [["The Quiet Algorithm", 18], ["Gardens of Glass", 16], ["A Field Guide to Clouds", 24], ["The Last Cartographer", 17],
      ["Cooking with Fire", 29], ["Small Habits, Big Days", 21], ["The Salt Road", 15], ["Learning Python Slowly", 39],
      ["Midnight at the Archive", 14], ["The Bicycle Atlas", 27], ["Letters from the Coast", 13], ["Thinking in Systems Today", 25]],
    authors: ["Mara Ellison", "Tomas Reyes", "Ingrid Haas", "Kofi Mensah", "Lena Park", "Ravi Anand"],
  },
  "toys-games": {
    brands: ["Brickwell", "Tinker Tots", "Galaxy Play"],
    items: [["Building Blocks Set 500pcs", 49], ["Remote Control Car", 59], ["Wooden Puzzle Map", 25], ["Plush Bear", 19],
      ["Junior Science Kit", 35], ["Family Board Game", 32], ["Art Easel", 69], ["Toy Kitchen Set", 89],
      ["Stunt Kite", 22], ["Marble Run", 45], ["Magnetic Tiles 60pcs", 55], ["Card Game Classics", 12]],
    colors: ["Red", "Blue", "Yellow"],
  },
  beauty: {
    brands: ["Lumea", "Pure Botanica", "Velvetine"],
    items: [["Vitamin C Serum", 34], ["Hydrating Moisturizer", 28], ["Clay Face Mask", 22], ["SPF 50 Sunscreen", 19],
      ["Hair Repair Oil", 26], ["Lip Balm Set", 12], ["Retinol Night Cream", 39], ["Micellar Water", 14],
      ["Bamboo Hair Brush", 18], ["Body Butter", 21], ["Eye Cream", 31], ["Gentle Cleanser", 17]],
  },
  fashion: {
    brands: ["Northloom", "Urban Thread", "Maris & Co"],
    items: [["Organic Cotton T-Shirt", 25], ["Denim Jacket", 89], ["Merino Wool Scarf", 45], ["Slim Chino Trousers", 59],
      ["Hooded Sweatshirt", 55], ["Leather Belt", 39], ["Packable Rain Jacket", 99], ["Linen Shirt", 65],
      ["Knit Beanie", 22], ["Canvas Sneakers", 69], ["Wool Socks 3-Pack", 24], ["Quilted Vest", 79]],
    colors: ["Navy", "Olive", "Sand", "Black"],
    sized: "all",
  },
  "pet-supplies": {
    brands: ["Pawsome", "Whiskerly", "Tailwise"],
    items: [["Orthopedic Dog Bed", 79], ["Cat Scratching Post", 45], ["Pet Water Fountain", 39], ["Chew Toy Set", 18],
      ["No-Pull Dog Harness", 29], ["Covered Litter Box", 49], ["Slow Feeder Bowl", 15], ["Grooming Brush", 16],
      ["Travel Pet Carrier", 59], ["Catnip Mice 6-Pack", 9], ["Dog Rain Coat", 34], ["Automatic Feeder", 89]],
    colors: ["Grey", "Teal", "Brown"],
  },
};

const ADJ = ["Pro", "Lite", "Plus", "Max", "Mini", "Classic", "Air", "Edge"];
const MATERIALS = ["recycled aluminium", "BPA-free plastic", "stainless steel", "organic cotton", "FSC-certified wood", "silicone"];
const FEATURES = ["easy to clean", "two-year warranty", "travel friendly", "designed for daily use", "low-noise operation",
  "gift-ready packaging", "tested by independent labs", "repairable parts available"];

function makeProduct(r, id, cat, idx, extraAdj = "") {
  const spec = SPEC[cat.slug];
  const [noun, basePrice] = spec.items[idx % spec.items.length];
  const brand = pick(r, spec.brands);
  const round = Math.floor(idx / spec.items.length);
  const adj = extraAdj || (round > 0 ? ADJ[(idx + round) % ADJ.length] : "");
  const name = cat.slug === "books" ? `${noun}${adj ? ` (${adj} Edition)` : ""}` : `${brand} ${noun}${adj ? ` ${adj}` : ""}`;
  const price = price99(basePrice * (0.8 + r() * 0.5));
  const onSale = r() < 0.22;
  const sized = spec.sized === "all" || (Array.isArray(spec.sized) && spec.sized.includes(noun));
  const p = {
    id, slug: slugify(name), name, brand, category: cat.slug, price,
    compareAt: onSale ? price99(price * (1.15 + r() * 0.25)) : null,
    rating: Math.round((3 + r() * 2) * 10) / 10,
    reviewCount: Math.floor(4 + r() * 380),
    stock: r() < 0.12 ? 0 : Math.floor(1 + r() * 60),
    sales: Math.floor(r() * 5000),
    added: new Date(Date.UTC(2026, 0, 1) + Math.floor(r() * 300) * 86400000).toISOString().slice(0, 10),
    colors: spec.colors ? spec.colors.filter(() => r() < 0.75).slice(0, 3) : [],
    sizes: sized ? (noun.includes("Shoes") || noun.includes("Sneakers") ? ["40", "41", "42", "43", "44"] : ["S", "M", "L", "XL"]) : [],
    hue: Math.floor(r() * 360),
  };
  if (p.colors.length === 0 && spec.colors) p.colors = [spec.colors[0]];
  if (cat.slug === "books") {
    p.author = pick(r, spec.authors);
    p.brand = brand;
    p.specs = { Author: p.author, Publisher: brand, Pages: String(180 + Math.floor(r() * 400)), Format: pick(r, ["Paperback", "Hardcover"]) };
  } else {
    p.specs = { Brand: brand, Material: pick(r, MATERIALS), Weight: `${(0.1 + r() * 4).toFixed(1)} kg`, Warranty: `${1 + Math.floor(r() * 3)} years` };
  }
  const f = [...FEATURES].sort(() => r() - 0.5).slice(0, 3);
  p.description = `${name} from ${brand}. ${f[0][0].toUpperCase() + f[0].slice(1)}, ${f[1]} and ${f[2]}.` +
    (cat.slug === "books" ? ` Written by ${p.author}.` : ` Made with ${p.specs.Material}.`);
  return p;
}

function baseCatalog() {
  const r = rng(BASE_SEED);
  const products = [];
  let id = 1001;
  for (const cat of CATEGORIES) {
    for (let i = 0; i < 18; i++) products.push(makeProduct(r, id++, cat, i));
  }
  return products;
}

// Content change k: applied to the base catalog, deterministic per k.
export function buildCatalog(content = 0) {
  const products = baseCatalog();
  if (!content) return products;
  const r = rng(BASE_SEED * 31 + content * 7919);
  let newId = 5001 + (content - 1) * 100;
  return products.map((p) => {
    if (r() < 0.1) {                                     // discontinued, replaced by a new product
      const cat = CATEGORIES.find((c) => c.slug === p.category);
      const q = makeProduct(r, newId++, cat, Math.floor(r() * 12), pick(r, ["2026", "Gen 2", "Studio", "Sport"]));
      q.added = "2026-11-01";
      return q;
    }
    const q = { ...p, specs: { ...p.specs } };
    q.price = price99(p.price * (1 + (r() - 0.5) * 0.4));
    if (r() < 0.3) q.compareAt = r() < 0.5 ? null : price99(q.price * (1.15 + r() * 0.2));
    if (q.compareAt && q.compareAt <= q.price) q.compareAt = null;
    if (r() < 0.35) q.stock = r() < 0.2 ? 0 : Math.floor(1 + r() * 60);
    q.rating = Math.min(5, Math.max(2.5, Math.round((p.rating + (r() - 0.5) * 0.6) * 10) / 10));
    q.reviewCount = p.reviewCount + Math.floor(r() * 40);
    q.sales = Math.floor(p.sales * (0.6 + r() * 0.8));
    return q;
  });
}

const REVIEWERS = ["Sam K.", "Priya D.", "Jonas W.", "Amara O.", "Chen L.", "Rosa M.", "Ethan B.", "Yuki T.", "Nadia F.", "Leo G."];
const GOOD = ["Exactly as described.", "Great value for the price.", "Arrived quickly and well packed.", "Using it every day, very happy.",
  "Better quality than I expected."];
const MEH = ["Does the job, nothing special.", "Good, but a bit smaller than I thought.", "Fine overall; the instructions could be clearer."];
const BAD = ["Stopped working after two weeks.", "Not worth the price.", "The colour was different from the photos."];

export function reviewsFor(p) {
  const r = rng(p.id * 13 + 7);
  const n = Math.min(p.reviewCount, 6 + Math.floor(r() * 18));
  const out = [];
  for (let i = 0; i < n; i++) {
    const stars = Math.max(1, Math.min(5, Math.round(p.rating + (r() - 0.55) * 2.4)));
    const text = stars >= 4 ? pick(r, GOOD) : stars === 3 ? pick(r, MEH) : pick(r, BAD);
    out.push({ id: `${p.id}-${i}`, author: pick(r, REVIEWERS), stars, text,
      date: new Date(Date.UTC(2026, 2, 1) + Math.floor(r() * 240) * 86400000).toISOString().slice(0, 10) });
  }
  return out;
}

export const COUPONS = { SAVE10: { type: "percent", value: 10, label: "10% off your order" },
  FREESHIP: { type: "shipping", value: 0, label: "Free standard shipping" } };
export const SHIPPING = { standard: { label: "Standard (3-5 business days)", price: 4.99, freeOver: 50 },
  express: { label: "Express (1-2 business days)", price: 14.99, freeOver: null } };
export const TEST_CARD = "4242424242424242";
