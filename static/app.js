/* Shared storefront components. Business rules and authorization live on the server. */
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (n) =>
  new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN" }).format(
    n / 100,
  );
let store,
  session,
  products = [],
  categories = [],
  cart = [],
  revision = 0;
const isOwner = () => session?.role === "superadmin";
const cartKey = () => `growthly-${store.storeId}-cart`;
const orderKey = () => `growthly-${store.storeId}-checkout`;
function restored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}
function persist() {
  localStorage.setItem(cartKey(), JSON.stringify(cart));
  sessionStorage.removeItem(orderKey());
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  clearTimeout(window.toastTimeout);
  window.toastTimeout = setTimeout(
    () => $("#toast").classList.remove("visible"),
    4500,
  );
}
async function api(url, body) {
  const res = await fetch("/api/" + url, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body instanceof FormData
        ? { "X-CSRF-Token": session?.csrf }
        : { "Content-Type": "application/json", "X-CSRF-Token": session?.csrf },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw Error("The store could not respond. Please try again.");
  }
  if (!res.ok) {
    const e = Error(data.error || "Please try again.");
    e.status = res.status;
    throw e;
  }
  return data;
}
async function go(url) {
  history.pushState({}, "", url);
  window.scrollTo(0, 0);
  await render();
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (a && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    e.preventDefault();
    go(a.getAttribute("href"));
  }
});
window.onpopstate = () => render();
const link = (url, text, cls = "") =>
  `<a data-link href="${esc(url)}" class="${cls}">${esc(text)}</a>`;
function shell(body) {
  const count = cart.reduce((n, i) => n + i.qty, 0);
  return `<div class="announcement">${esc(store.tagline)}</div><header><div class="nav wrap"><a data-link href="/" class="brand">${store.logo ? `<img src="${esc(store.logo)}" alt="" width="40" height="40">` : ""}${esc(store.businessName)}</a><nav aria-label="Main navigation">${link("/shop", "Shop")}${link("/about", "About")}${link("/contact", "Contact")}</nav>${link("/cart", `Bag (${count})`, "bag")}</div></header><main id="main" class="wrap" tabindex="-1">${body}</main><footer class="wrap"><div><strong>${esc(store.businessName)}</strong><p>${esc(store.tagline)}</p></div><nav aria-label="Store policies">${link("/privacy", "Privacy")}${link("/returns", "Returns & warranty")}${link("/delivery", "Delivery")}${link("/contact", "Contact")}</nav><p>© ${new Date().getFullYear()} ${esc(store.businessName)} · NGN · Nigeria</p></footer>`;
}
const pageTitle = (title, text = "") =>
  `<div class="page-title"><p class="eyebrow">${esc(store.businessName)}</p><h1>${esc(title)}</h1>${text ? `<p>${esc(text)}</p>` : ""}</div>`;
function card(p) {
  return `<article class="product"><a data-link href="/product/${encodeURIComponent(p.id)}" class="product-image"><img src="${esc(p.images[0])}" alt="${esc(p.name)}" width="600" height="600" loading="lazy"><span class="badge">${p.sample ? "DEMONSTRATION" : p.variants.every((v) => !v.available) ? "SOLD OUT" : p.featured ? "FEATURED" : "THE COLLECTION"}</span></a><div class="product-copy"><p class="eyebrow">${esc(p.category)}</p><h3>${link("/product/" + encodeURIComponent(p.id), p.name)}</h3><p>${money(p.price)}</p></div></article>`;
}
function grid(items) {
  return items.length
    ? `<div class="product-grid">${items.map(card).join("")}</div>`
    : `<section class="empty"><h2>No products here yet</h2><p>Try another search or check back for the next collection.</p>${link("/shop", "Explore the store", "button secondary")}</section>`;
}
function home() {
  const electronic = store.layout === "electronics";
  return shell(
    `<section class="hero ${electronic ? "tech" : "editorial"}"><div><p class="eyebrow">${electronic ? "CONNECTED TO WHAT’S NEXT" : "THE EVERYDAY COLLECTION"}</p><h1>${electronic ? "Your next<br>great upgrade." : "Everyday finds.<br>Extraordinary feeling."}</h1><p>${esc(store.tagline)}</p>${link("/shop", electronic ? "Explore the gadgets →" : "Discover the collection →", "button")}<div class="hero-notes"><span>₦ Prices in naira</span><span>Personal service</span><span>${esc(store.address || "Independent retail")}</span></div></div><div class="hero-art"><img src="${electronic ? "/static/demo-gadget.svg" : "/static/demo-object.svg"}" alt="${electronic ? "Illustrative smartphone" : "Illustrative everyday bag"} — demonstration artwork" width="800" height="800"></div></section><section class="category-strip" aria-label="Browse categories">${categories.map((c) => link("/shop?category=" + encodeURIComponent(c), c, "chip")).join("")}</section><section><div class="section-heading"><div><p class="eyebrow">${electronic ? "THE UPGRADE EDIT" : "SELECTED FOR YOU"}</p><h2>${electronic ? "Better tech. More possibility." : "Meet your next favourites."}</h2></div>${link("/shop", "View all →")}</div>${grid([...products].sort((a, b) => Number(b.featured) - Number(a.featured)).slice(0, 4))}</section><section class="story"><p class="eyebrow">A STORE WITH A PERSONAL TOUCH</p><h2>${electronic ? "Find the right fit<br>for your digital life." : "A little care in every order."}</h2><p>Explore the collection, ask a question, and confirm the details before you buy.</p>${link("/contact", "Talk to the store", "button secondary")}</section>`,
  );
}
function catalogue() {
  const q = new URLSearchParams(location.search);
  return shell(
    `${pageTitle("The collection", "Find what works for you.")}<form id="filters" class="filters"><label>Search<input name="q" placeholder="Search products…" value="${esc(q.get("q") || "")}"></label><label>Category<select name="category"><option value="">All categories</option>${categories.map((c) => `<option ${q.get("category") === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label><label>Sort<select name="sort"><option value="featured">Featured first</option><option value="low" ${q.get("sort") === "low" ? "selected" : ""}>Price: low to high</option><option value="high" ${q.get("sort") === "high" ? "selected" : ""}>Price: high to low</option></select></label><button class="button">Apply</button></form><div id="results"></div>`,
  );
}
function filtered() {
  const q = new URLSearchParams(location.search),
    term = (q.get("q") || "").toLowerCase();
  let items = products.filter(
    (p) =>
      (!q.get("category") || p.category === q.get("category")) &&
      (!term ||
        (p.name + " " + p.description + " " + p.category)
          .toLowerCase()
          .includes(term)),
  );
  items.sort(
    q.get("sort") === "low"
      ? (a, b) => a.price - b.price
      : q.get("sort") === "high"
        ? (a, b) => b.price - a.price
        : (a, b) => Number(b.featured) - Number(a.featured),
  );
  $("#results").innerHTML =
    `<p role="status">${items.length} products</p>` + grid(items);
}
function detail(p) {
  return shell(
    `<div class="breadcrumbs">${link("/shop", "Shop")} / ${esc(p.category)}</div><section class="detail"><div><img id="main-photo" class="detail-image" src="${esc(p.images[0])}" alt="${esc(p.name)}"><div class="thumbnails">${p.images.map((im, i) => `<button data-photo="${esc(im)}" aria-label="View image ${i + 1}"><img src="${esc(im)}" alt=""></button>`).join("")}</div></div><div><p class="eyebrow">${esc(p.category)}</p><h1>${esc(p.name)}</h1><p class="detail-price">${money(p.price)}</p>${p.sample ? '<p class="notice">Demonstration product. Illustrative image and price; not actual inventory.</p>' : ""}<p class="prose">${esc(p.description)}</p><dl>${Object.entries(
      p.specifications || {},
    )
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
      .join(
        "",
      )}</dl><form id="add-cart"><label>Choose an option<select name="variant">${p.variants.map((v) => `<option value="${esc(v.id)}" ${!v.available ? "disabled" : ""}>${esc(v.size)} / ${esc(v.colour)} — ${v.available} available</option>`).join("")}</select></label><label>Quantity<input name="qty" type="number" min="1" max="99" value="1" required></label><button class="button" ${p.variants.every((v) => !v.available) ? "disabled" : ""}>Add to bag</button></form>${store.features.instalments ? '<p class="notice">Ask the store about an instalment agreement before paying.</p>' : ""}<p class="muted">Delivery fees and fulfilment are confirmed separately.</p>${link("/returns", "Returns & warranty")}</div></section>`,
  );
}
function cartPage() {
  const total = cart.reduce((s, i) => s + i.qty * i.price, 0);
  return shell(
    `${pageTitle("Your bag", "Review your products before placing an order.")}<div class="cart-layout"><div>${cart.length ? cart.map((i, n) => `<article class="cart-line"><img src="${esc(i.image)}" alt=""><div><h2>${esc(i.name)}</h2><p>${esc(i.option)}</p><label>Quantity<input type="number" min="1" max="99" value="${i.qty}" data-quantity="${n}" aria-label="Quantity for ${esc(i.name)}"></label><button class="text-button" data-remove="${n}">Remove</button></div><strong>${money(i.price * i.qty)}</strong></article>`).join("") : '<div class="empty"><h2>Your bag is waiting</h2><p>Add something you like from the collection.</p></div>'}</div><aside class="panel"><h2>Order summary</h2><p class="total">${money(total)}</p><p>Product subtotal. Delivery fees confirmed separately.</p><form id="checkout"><label>Fulfilment<select name="fulfilment">${store.features.pickup ? "<option>Pickup</option>" : ""}${store.features.delivery ? "<option>Request delivery</option>" : ""}</select></label><button class="button" ${!cart.length || (!store.features.pickup && !store.features.delivery) ? "disabled" : ""}>Continue to checkout</button></form><p class="muted">An order is only marked paid after verification.</p></aside></div>`,
  );
}
let handoff;
function checkoutPage() {
  if (!handoff)
    return shell(
      `${pageTitle("No checkout in progress")}${link("/cart", "Return to your bag", "button")}`,
    );
  return shell(
    `${pageTitle("Your order request is saved", handoff.reference)}<section class="panel checkout-panel"><p>Payment is awaiting verification. Stock and any delivery fee will be confirmed by the store.</p>${store.features.whatsappCheckout && handoff.url ? `<a class="button" href="${esc(handoff.url)}" target="_blank" rel="noopener">Send order on WhatsApp ↗</a><pre>${esc(handoff.message)}</pre><button id="copy-message" class="text-button">Copy order message</button>` : ""}${store.features.bankTransfer ? `<h2>Bank transfer</h2><p>${esc(store.bank.name)} · ${esc(store.bank.accountName)} · ${esc(store.bank.accountNumber)}</p><p>Confirm the account and total with the store before paying.</p><form id="transfer"><label>Your transfer reference<input name="transferReference" required minlength="3" maxlength="150"></label><button class="button secondary">Submit for verification</button></form>` : ""}${store.features.onlinePayment && store.gatewayConfigured ? '<h2>Pay securely online</h2><form id="online"><label>Email address<input name="email" type="email" required></label><button class="button">Continue to Paystack</button></form>' : ""}${!handoff.url && !store.features.bankTransfer && !(store.features.onlinePayment && store.gatewayConfigured) ? '<p class="notice">Payment methods are currently unavailable. Contact the store.</p>' : ""}</section>`,
  );
}
function contact() {
  return shell(
    `${pageTitle("Let’s talk", "Questions about a product or an order?")}<div class="two-col"><section><h2>${esc(store.businessName)}</h2><p>${esc(store.address || "Location details coming soon.")}</p>${store.phone ? `<p>${esc(store.phone)}</p>` : ""}${store.email ? `<p>${esc(store.email)}</p>` : ""}${store.whatsapp ? `<a class="button" href="https://wa.me/${store.whatsapp}" target="_blank" rel="noopener">Chat on WhatsApp ↗</a>` : ""}</section><form id="enquiry" class="panel"><h2>Send an enquiry</h2><label>Your name<input name="name" maxlength="100" required autocomplete="name"></label><label>Email<input name="email" type="email" required autocomplete="email"></label><label>Message<textarea name="message" minlength="5" maxlength="3000" required></textarea></label><button class="button">Send enquiry</button><p>We store your contact details to respond to this enquiry. ${link("/privacy", "Privacy notice")}</p></form></div>`,
  );
}
function adminShell(body, active) {
  const tabs = isOwner()
    ? [
        "Overview",
        "Products",
        "Orders",
        "Categories",
        "Settings",
        "Enquiries",
        "Team",
      ]
    : ["Products"];
  return shell(
    `${pageTitle("Store workspace", `${isOwner() ? "Super Admin" : "Product Admin"} · ${session.owner}`)}<nav class="admin-tabs" aria-label="Administration">${tabs.map((t) => link("/admin/" + t.toLowerCase(), t, t === active ? "active" : "")).join("")}<button id="logout" class="text-button">Sign out</button></nav>${body}`,
  );
}
function login() {
  return shell(
    `<form id="login" class="panel login"><p class="eyebrow">PRIVATE TEAM ACCESS</p><h1>Welcome back.</h1><label>Username<input name="username" required autocomplete="username"></label><label>Password<input name="password" type="password" required autocomplete="current-password"></label><button class="button">Sign in securely</button><p>Invitation-only access. Ask your store owner for help with a staff account. Owners: contact your website administrator for recovery.</p></form>`,
  );
}
function productForm(p = {}) {
  const variants = p.variants || [
    { size: "Standard", colour: "Default", stock: 0 },
  ];
  return adminShell(
    `<form id="product-form" class="panel"><h2>${p.id ? "Edit product" : "Add product"}</h2><input type="hidden" name="id" value="${esc(p.id || "")}"><div class="two-col"><label>Product name<input name="name" value="${esc(p.name || "")}" required maxlength="150"></label><label>Category<select name="category">${categories.map((c) => `<option ${p.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label><label>Price (₦)<input name="price" type="number" step="0.01" min="0.01" value="${p.price ? p.price / 100 : ""}" required></label></div><label>Description<textarea name="description" maxlength="5000">${esc(p.description || "")}</textarea></label><label>Upload photos (up to 8)<input id="upload" type="file" accept="image/jpeg,image/png,image/webp" multiple></label><div id="photos" class="thumbnails"></div><label>Specifications (one Label: Value per line)<textarea name="specifications">${esc(
      Object.entries(p.specifications || {})
        .map(([k, v]) => k + ": " + v)
        .join("\n"),
    )}</textarea></label><h3>Variants</h3><div id="variants">${variants.map(variantRow).join("")}</div><button type="button" id="new-variant" class="text-button">Add variant</button>${isOwner() ? `<label class="check"><input type="checkbox" name="featured" ${p.featured ? "checked" : ""}> Featured product</label><label class="check"><input type="checkbox" name="published" ${p.published ? "checked" : ""}> Publish product</label>` : '<p class="notice">Save as a draft. Your Super Admin reviews and publishes it.</p>'}<button class="button">Save product</button></form>`,
    "Products",
  );
}
function variantRow(v = {}) {
  return `<div class="variant-row" data-id="${esc(v.id || "")}"><label>Size / model<input value="${esc(v.size || "")}" data-size maxlength="40"></label><label>Colour<input value="${esc(v.colour || "")}" data-colour maxlength="40"></label><label>Stock<input value="${v.stock || 0}" data-stock type="number" min="0" max="100000" required></label><button type="button" data-remove-variant class="text-button">Remove</button></div>`;
}
function orderTools(o) {
  const open = !["Paid", "Dismissed"].includes(o.status);
  const corrected = new Set(
    o.payments.filter((p) => p.corrects).map((p) => p.corrects),
  );
  return `<details class="panel"><summary>Delivery and payment agreement</summary><form id="agreement"><label>Due date<input name="due" type="date" value="${esc(o.due || "")}"></label><label>Delivery fee (₦)<input name="delivery_fee" type="number" min="0" step="0.01" value="${o.delivery_fee / 100}"></label><label class="check"><input name="rider_direct" type="checkbox" ${o.rider_direct ? "checked" : ""}> Customer pays rider directly</label><label>Agreement notes<textarea name="note">${esc(o.note)}</textarea></label><button class="button secondary">Save agreement</button></form></details>${open ? `<details class="panel"><summary>Reserve stock for this order</summary><p>Only reserve confirmed selections. Set a quantity to zero to release it.</p>${o.items.map((i, index) => `<form class="reservation" data-item="${index}"><p>${esc(i.name)} · ${esc(i.size)} / ${esc(i.colour)}</p><label>Quantity to hold<input name="qty" type="number" min="0" max="${i.qty}" value="${o.reservations.find((r) => r.product_id === i.product_id && r.variant === i.variant_id)?.qty || 0}" required></label><button class="button secondary">Update reservation</button></form>`).join("")}</details>` : ""}${
    o.payments.length && o.status !== "Dismissed"
      ? `<details class="panel"><summary>Correct a recorded receipt</summary><p>Corrections preserve the original receipt and record the reason. This does not send a refund or change money in the bank.</p><form id="correction"><label>Receipt to correct<select name="corrects">${o.payments
          .filter((p) => !corrected.has(p.id))
          .map(
            (p) =>
              `<option value="${esc(p.id)}">${esc(p.received)} · ${money(p.products)} products / ${money(p.delivery)} delivery</option>`,
          )
          .join(
            "",
          )}</select></label><label>Correct product amount (₦)<input name="products" type="number" min="0" step="0.01" required></label><label>Correct delivery amount (₦)<input name="delivery" type="number" min="0" step="0.01" required></label><label>Receipt date<input name="received" type="date" required></label><label>Correction reason<input name="reason" required></label><label>Verification / exception note<input name="note" required></label><button class="button secondary">Save correction</button></form></details>`
      : ""
  }${open ? `<details class="panel"><summary>Close this order request</summary><form id="dismiss"><p>Review every payment before closing. This is not a refund.</p><label>Type order reference<input name="review" required></label><label>Closing reason<textarea name="reason" required></textarea></label><button class="button secondary">Close request</button></form></details>` : ""}`;
}
async function adminPage(path) {
  session = await api("session");
  if (!session.owner) return login();
  if (!isOwner() && !path.startsWith("/admin/products")) {
    history.replaceState({}, "", "/admin/products");
    path = "/admin/products";
  }
  const section = path.split("/")[2] || "overview";
  if (section === "products") {
    const all = await api("products?admin=1");
    const id = path.split("/")[3];
    if (id) {
      const p = all.find((p) => p.id === id);
      if (id !== "new" && !p) throw Error("Product not found.");
      if (!isOwner() && p?.published)
        return adminShell(
          '<p class="notice">Only your Super Admin can edit live products.</p>',
          "Products",
        );
      window.editing = p || {};
      return productForm(p);
    }
    return adminShell(
      `<div class="section-heading"><h2>Products</h2>${link("/admin/products/new", "Add product", "button")}</div><div class="admin-list">${all.map((p) => `<article class="panel"><h3>${esc(p.name)}</h3><p>${money(p.price)} · ${p.archived ? "Archived" : p.published ? "Published" : "Draft"}${p.sample ? " · Demonstration" : ""}</p>${link("/admin/products/" + p.id, "Edit", "button secondary")}${isOwner() ? `<button data-lifecycle="${p.id}" data-action="${p.archived ? "restore" : "archive"}" class="text-button">${p.archived ? "Restore" : "Archive"}</button><button data-lifecycle="${p.id}" data-action="delete" class="text-button">Delete</button>` : ""}</article>`).join("") || "<p>No products yet. Add your first product.</p>"}</div>`,
      "Products",
    );
  }
  if (section === "overview") {
    const d = await api("dashboard");
    return adminShell(
      `<h2>Recorded sales</h2><p>Completed website orders, Africa/Lagos dates. These figures come from recorded payments.</p><div class="metrics">${[
        ["Paid orders", d.paid_orders],
        ["Product sales", money(d.product_sales)],
        ["Items sold", d.items_sold],
        ["Published products", d.published],
      ]
        .map(
          ([k, v]) =>
            `<article class="panel"><p>${k}</p><strong>${v}</strong></article>`,
        )
        .join("")}</div>`,
      "Overview",
    );
  }
  if (section === "orders") {
    const orders = await api("orders"),
      claims = await api("transfer-claims");
    const id = path.split("/")[3];
    if (id) {
      const o = orders.find((o) => o.id === id);
      if (!o) throw Error("Order not found.");
      window.order = o;
      return adminShell(
        `<section class="panel"><h2>${esc(o.id)}</h2><p>${esc(o.status)} · ${esc(o.fulfilment)}</p>${o.items.map((i) => `<p>${esc(i.name)} × ${i.qty} — ${money(i.price * i.qty)}</p>`).join("")}<h3>Product total ${money(o.total)} · Balance ${money(o.balance)}</h3><p>Delivery balance: ${money(o.delivery_balance)} · Product excess: ${money(o.excess)} · Delivery excess: ${money(o.delivery_excess)}</p>${claims
          .filter((c) => c.order_id === o.id)
          .map(
            (c) =>
              `<p class="notice">Unverified transfer claim: ${esc(c.reference)}</p>`,
          )
          .join(
            "",
          )}${o.inventory_conflicts.map((c) => `<p class="notice">${esc(c)}</p>`).join("")}<h3>Record a verified receipt</h3><p>Check your bank or provider records first. A transfer reference alone is not proof of payment.</p><form id="receipt"><label>Product amount (₦)<input name="products" type="number" min="0" step="0.01" required></label><label>Delivery amount (₦)<input name="delivery" type="number" min="0" step="0.01" value="0"></label><label>Date received<input name="received" type="date" required></label><label>Verification / exception note<input name="note" maxlength="1000" required></label><button class="button">Record verified payment</button></form><h3>Payment history</h3>${o.payments.map((p) => `<p>${esc(p.received)} · ${money(p.products)} products + ${money(p.delivery)} delivery · ${esc(p.actor)} · ${esc(p.note)}</p>`).join("") || "<p>No payments recorded.</p>"}${orderTools(o)}</section>`,
        "Orders",
      );
    }
    return adminShell(
      `<h2>Orders</h2>${orders.map((o) => `<article class="panel">${link("/admin/orders/" + o.id, o.id)}<p>${esc(o.status)} · ${money(o.total)} · Balance ${money(o.balance)}</p></article>`).join("") || "<p>No orders yet.</p>"}`,
      "Orders",
    );
  }
  if (section === "categories") {
    const tree = await api("category-tree");
    return adminShell(
      `<section class="panel"><h2>Categories and subcategories</h2>${tree.map((c) => `<p>${esc(c.name)}${c.parent ? " → " + esc(c.parent) : ""}</p>`).join("")}<form id="category"><label>Category name<input name="name" required maxlength="40"></label><label>Parent category<select name="parent"><option value="">No parent</option>${categories.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label><button class="button">Save category</button></form></section>`,
      "Categories",
    );
  }
  if (section === "settings")
    return adminShell(
      `<form id="settings" class="panel"><h2>Store settings</h2><p>Secrets and deployment identity are managed outside this dashboard.</p>${["businessName", "tagline", "phone", "whatsapp", "email", "address", "logo", "favicon"].map((k) => `<label>${esc(k)}<input name="${k}" value="${esc(store[k])}"></label>`).join("")}<label>Storefront layout<select name="layout"><option ${store.layout === "editorial" ? "selected" : ""}>editorial</option><option ${store.layout === "electronics" ? "selected" : ""}>electronics</option></select></label>${Object.entries(
        store.theme,
      )
        .map(
          ([k, v]) =>
            `<label>${k} colour<input name="theme.${k}" value="${v}" pattern="#[0-9a-fA-F]{6}" required></label>`,
        )
        .join("")}${Object.entries(store.features)
        .map(
          ([k, v]) =>
            `<label class="check"><input type="checkbox" name="features.${k}" ${v ? "checked" : ""}> ${k}</label>`,
        )
        .join(
          "",
        )}${["about", "privacy", "returns", "deliveryPolicy"].map((k) => `<label>${k}<textarea name="${k}">${esc(store[k])}</textarea></label>`).join("")}${Object.entries(
        store.bank,
      )
        .map(
          ([k, v]) =>
            `<label>Bank ${k}<input name="bank.${k}" value="${esc(v)}"></label>`,
        )
        .join("")}<button class="button">Save settings</button></form>`,
      "Settings",
    );
  if (section === "enquiries") {
    const all = await api("enquiries");
    return adminShell(
      `<h2>Customer enquiries</h2>${all.map((e) => `<article class="panel"><h3>${esc(e.name)}</h3><p>${esc(e.email)} · ${esc(e.status)}</p><p class="prose">${esc(e.message)}</p><button data-enquiry="${e.id}" class="button secondary">${e.status === "New" ? "Mark resolved" : "Reopen"}</button></article>`).join("") || "<p>No enquiries yet.</p>"}`,
      "Enquiries",
    );
  }
  if (section === "team") {
    const members = await api("staff"),
      activity = await api("product-activity");
    return adminShell(
      `<section class="panel"><h2>Invite a Product Admin</h2><p>Helpers save drafts; only you publish and access orders, settings and finances.</p><form id="invite"><label>Username<input name="username" minlength="3" maxlength="60" required></label><button class="button">Create invitation</button></form><div id="invite-result" role="status"></div></section>${members.map((m) => `<section class="panel"><h3>${esc(m.username)}</h3><p>${m.active ? esc(m.status) : "Revoked"}</p><button data-staff="${m.id}" data-action="reset" class="text-button">New invitation / password reset</button>${m.active ? `<button data-staff="${m.id}" data-action="revoke" class="text-button">Revoke access</button>` : ""}</section>`).join("")}<section class="panel"><h2>Recent product activity</h2>${activity.map((a) => `<p>${esc(a.actor)} · ${esc(a.action)} · ${esc(a.product_name || "Removed product")}</p>`).join("") || "<p>No changes yet.</p>"}</section>`,
      "Team",
    );
  }
  throw Error("Page not found.");
}
function handleForm(selector, handler) {
  const form = $(selector);
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const b = e.submitter;
    b.disabled = true;
    try {
      await handler(Object.fromEntries(new FormData(form)), form);
    } catch (err) {
      toast(err.message);
    } finally {
      b.disabled = false;
    }
  };
}
async function refresh() {
  [products, categories, store] = await Promise.all([
    api("products"),
    api("categories"),
    api("store"),
  ]);
  applyTheme();
  await render();
}
function bind() {
  $$("label").forEach((label) => {
    const control = label.querySelector("input,select,textarea");
    const name = [...label.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent)
      .join(" ")
      .trim();
    if (control && name) control.setAttribute("aria-label", name);
  });
  handleForm("#login", async (b) => {
    await api("login", b);
    session = await api("session");
    await go("/admin");
  });
  if ($("#logout"))
    $("#logout").onclick = async () => {
      await api("logout", {});
      session = await api("session");
      await go("/admin");
    };
  handleForm("#filters", (b) => go("/shop?" + new URLSearchParams(b)));
  if ($("#results")) filtered();
  $$("[data-photo]").forEach(
    (b) => (b.onclick = () => ($("#main-photo").src = b.dataset.photo)),
  );
  handleForm("#add-cart", async (b) => {
    const id = decodeURIComponent(location.pathname.split("/").pop()),
      p = products.find((p) => p.id === id),
      v = p.variants.find((v) => v.id === b.variant),
      qty = Number(b.qty);
    if (!v || !Number.isInteger(qty) || qty < 1 || qty > v.available)
      throw Error("Choose an available option and quantity.");
    const old = cart.find(
      (i) => i.product_id === p.id && i.variant_id === v.id,
    );
    if (old) {
      if (old.qty + qty > v.available)
        throw Error("That quantity is not available.");
      old.qty += qty;
    } else
      cart.push({
        product_id: p.id,
        variant_id: v.id,
        qty,
        price: p.price,
        name: p.name,
        image: p.images[0],
        option: v.size + " / " + v.colour,
      });
    persist();
    await go("/cart");
    toast("Added to your bag.");
  });
  $$("[data-remove]").forEach(
    (b) =>
      (b.onclick = async () => {
        cart.splice(+b.dataset.remove, 1);
        persist();
        await render();
      }),
  );
  $$("[data-quantity]").forEach(
    (i) =>
      (i.onchange = async () => {
        const n = Number(i.value);
        if (!Number.isInteger(n) || n < 1 || n > 99) {
          toast("Use a quantity of 1–99.");
          return;
        }
        cart[+i.dataset.quantity].qty = n;
        persist();
        await render();
      }),
  );
  handleForm("#checkout", async (b) => {
    let key = sessionStorage.getItem(orderKey());
    if (!key) {
      key = crypto.randomUUID();
      sessionStorage.setItem(orderKey(), key);
    }
    handoff = await api("checkout", {
      key,
      items: cart.map(({ product_id, variant_id, qty, price }) => ({
        product_id,
        variant_id,
        qty,
        price,
      })),
      fulfilment: b.fulfilment,
    });
    handoff.key = key;
    sessionStorage.setItem(orderKey() + "-handoff", JSON.stringify(handoff));
    await go("/checkout");
  });
  if ($("#copy-message"))
    $("#copy-message").onclick = async () => {
      try {
        await navigator.clipboard.writeText(handoff.message);
        toast("Order message copied.");
      } catch {
        toast("Select and copy the message above.");
      }
    };
  handleForm("#transfer", async (b) => {
    await api("transfer", {
      ...b,
      reference: handoff.reference,
      key: handoff.key,
    });
    toast("Submitted. Payment remains awaiting verification.");
  });
  handleForm("#online", async (b) => {
    const result = await api("gateway/initialize", {
      ...b,
      reference: handoff.reference,
      key: handoff.key,
    });
    location.href = result.url;
  });
  handleForm("#enquiry", async (b, f) => {
    await api("enquiries", b);
    f.reset();
    toast("Your enquiry was sent.");
  });
  $$("[data-lifecycle]").forEach(
    (b) =>
      (b.onclick = async () => {
        if (
          b.dataset.action === "delete" &&
          !confirm(
            "Permanently delete this unused product? Archive products you want to retain.",
          )
        )
          return;
        try {
          await api("products/" + b.dataset.lifecycle + "/lifecycle", {
            action: b.dataset.action,
          });
          await refresh();
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  if ($("#product-form")) bindProductForm();
  handleForm("#category", async (b) => {
    await api("category-tree", b);
    await refresh();
  });
  handleForm("#settings", async (b, f) => {
    const payload = {};
    for (const key of [
      "businessName",
      "tagline",
      "phone",
      "whatsapp",
      "email",
      "address",
      "logo",
      "favicon",
      "layout",
      "about",
      "privacy",
      "returns",
      "deliveryPolicy",
    ])
      payload[key] = b[key];
    payload.theme = Object.fromEntries(
      Object.keys(store.theme).map((k) => [k, b["theme." + k]]),
    );
    payload.features = Object.fromEntries(
      Object.keys(store.features).map((k) => [
        k,
        new FormData(f).has("features." + k),
      ]),
    );
    payload.bank = Object.fromEntries(
      Object.keys(store.bank).map((k) => [k, b["bank." + k]]),
    );
    await api("settings", payload);
    await refresh();
    toast("Store settings saved.");
  });
  $$("[data-enquiry]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await api("enquiries/" + b.dataset.enquiry, {
            status: b.textContent === "Reopen" ? "New" : "Resolved",
          });
          await render();
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  async function invite(body) {
    const result = await api("staff", body);
    await render();
    if (result.token) {
      const url = location.origin + "/admin/activate#" + result.token;
      $("#invite-result").innerHTML =
        `<p class="notice">Private link · single use · expires in 24 hours. Share with this helper only.</p><label>Invitation link<input readonly value="${esc(url)}"></label>`;
    } else toast("Access revoked.");
  }
  handleForm("#invite", (b) => invite(b));
  $$("[data-staff]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await invite({ action: b.dataset.action, id: b.dataset.staff });
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  if ($("#receipt")) {
    const keyName = orderKey() + "-receipt-" + window.order.id;
    let pending;
    try {
      pending = JSON.parse(sessionStorage.getItem(keyName));
    } catch {}
    if (
      pending &&
      window.order.payments.some((p) => p.submission_key === pending.key)
    ) {
      sessionStorage.removeItem(keyName);
      pending = null;
    }
    if (pending) {
      for (const name of ["products", "delivery", "received", "note"]) {
        const input = $(`#receipt [name="${name}"]`);
        input.value = ["products", "delivery"].includes(name)
          ? pending[name] / 100
          : pending[name];
      }
      $("#receipt").insertAdjacentHTML(
        "afterbegin",
        '<p class="notice">A previous receipt needs confirmation. Retry sends the same saved receipt to avoid a duplicate.</p>',
      );
    }
  }
  handleForm("#agreement", async (b, f) => {
    await api("orders/" + window.order.id + "/agreement", {
      ...b,
      delivery_fee: Math.round(Number(b.delivery_fee) * 100),
      rider_direct: new FormData(f).has("rider_direct"),
    });
    await render();
    toast("Agreement saved.");
  });
  $$("form.reservation").forEach((form) =>
    handleForm(
      `form.reservation[data-item="${form.dataset.item}"]`,
      async (b) => {
        const i = window.order.items[+form.dataset.item];
        await api("orders/" + window.order.id + "/reserve", {
          product_id: i.product_id,
          variant_id: i.variant_id,
          qty: Number(b.qty),
        });
        await refresh();
        toast("Reservation updated.");
      },
    ),
  );
  handleForm("#dismiss", async (b) => {
    if (b.review !== window.order.id)
      throw Error("Enter the exact order reference.");
    await api("orders/" + window.order.id + "/dismiss", b);
    await refresh();
  });
  handleForm("#correction", async (b) => {
    const keyName = orderKey() + "-correction-" + window.order.id;
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(keyName));
    } catch {}
    const payload = saved || {
      ...b,
      products: Math.round(Number(b.products) * 100),
      delivery: Math.round(Number(b.delivery) * 100),
      key: crypto.randomUUID(),
    };
    sessionStorage.setItem(keyName, JSON.stringify(payload));
    try {
      await api("orders/" + window.order.id + "/payments", payload);
    } catch (err) {
      if (err.status === 400) sessionStorage.removeItem(keyName);
      throw err;
    }
    sessionStorage.removeItem(keyName);
    await refresh();
    toast("Correction recorded.");
  });
  handleForm("#receipt", async (b) => {
    const keyName = orderKey() + "-receipt-" + window.order.id;
    let pending;
    try {
      pending = JSON.parse(sessionStorage.getItem(keyName));
    } catch {}
    if (!pending) {
      pending = {
        ...b,
        products: Math.round(Number(b.products) * 100),
        delivery: Math.round(Number(b.delivery) * 100),
        key: crypto.randomUUID(),
      };
      sessionStorage.setItem(keyName, JSON.stringify(pending));
    }
    try {
      await api("orders/" + window.order.id + "/payments", pending);
    } catch (err) {
      if (err.status === 400) sessionStorage.removeItem(keyName);
      throw err;
    }
    sessionStorage.removeItem(keyName);
    await refresh();
    toast("Verified receipt recorded.");
  });
}
async function preparePhoto(file) {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type))
    throw Error("Choose a JPG, PNG or WebP photo.");
  if (file.size > 12 * 1024 * 1024)
    throw Error("Choose a photo smaller than 12 MB.");
  let image;
  try {
    image = await createImageBitmap(file);
  } catch {
    throw Error(
      "This photo could not be opened. Choose another JPG, PNG or WebP.",
    );
  }
  try {
    if (image.width * image.height > 24000000)
      throw Error("Choose a photo under 24 megapixels.");
    const scale = Math.min(1, 1600 / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fffdf9";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.86),
    );
    if (!blob || blob.size > 3 * 1024 * 1024)
      throw Error("Photo is too large to send. Please choose a smaller image.");
    return blob;
  } finally {
    image.close();
  }
}

function bindProductForm() {
  let photos = [...(window.editing.images || [])],
    uploading = false;
  const draw = () => {
    $("#photos").innerHTML = photos
      .map(
        (im, i) =>
          `<div><img src="${esc(im)}" alt="Product photo ${i + 1}"><button type="button" data-delete-photo="${i}" aria-label="Remove photo ${i + 1}">×</button></div>`,
      )
      .join("");
    $$("[data-delete-photo]").forEach(
      (b) =>
        (b.onclick = () => {
          photos.splice(+b.dataset.deletePhoto, 1);
          draw();
        }),
    );
  };
  draw();
  const variants = () =>
    $$("[data-remove-variant]").forEach(
      (b) => (b.onclick = () => b.closest(".variant-row").remove()),
    );
  variants();
  $("#new-variant").onclick = () => {
    $("#variants").insertAdjacentHTML("beforeend", variantRow());
    variants();
  };
  $("#upload").onchange = async (e) => {
    uploading = true;
    $("#product-form button[type=submit]")?.setAttribute("disabled", "");
    try {
      const files = [...e.target.files];
      if (files.length + photos.length > 8)
        throw Error("Choose up to 8 photos.");
      for (const file of files) {
        const body = new FormData();
        body.append("photo", await preparePhoto(file), "product.jpg");
        photos.push((await api("upload", body)).url);
        draw();
      }
    } catch (err) {
      toast(err.message);
    } finally {
      uploading = false;
      e.target.value = "";
    }
  };
  handleForm("#product-form", async (b) => {
    if (uploading) throw Error("Wait for photo uploads to finish.");
    const specifications = {};
    for (const line of b.specifications.split("\n").filter((x) => x.trim())) {
      const split = line.indexOf(":");
      if (split < 1) throw Error("Use Label: Value for each specification.");
      specifications[line.slice(0, split).trim()] = line
        .slice(split + 1)
        .trim();
    }
    await api("products", {
      id: b.id || undefined,
      name: b.name,
      category: b.category,
      price: Math.round(Number(b.price) * 100),
      description: b.description,
      images: photos,
      specifications,
      featured: isOwner() && b.featured === "on",
      published: isOwner() && b.published === "on",
      variants: $$(".variant-row").map((row) => ({
        id: row.dataset.id || undefined,
        size: row.querySelector("[data-size]").value,
        colour: row.querySelector("[data-colour]").value,
        stock: Number(row.querySelector("[data-stock]").value),
      })),
    });
    await refresh();
    await go("/admin/products");
    toast("Product saved.");
  });
}
async function activation(owner) {
  const token = location.hash.slice(1);
  history.replaceState({}, "", location.pathname);
  let username = "";
  if (owner) {
    const info = await api("owner-invitation", { token });
    username = info.username;
  }
  $("#app").innerHTML = shell(
    `<form id="activation" class="panel login"><h1>${owner ? "Set up your store account" : "Join the store team"}</h1><p>${owner ? "Your username: " + esc(username) : "Use the username your Super Admin assigned."}</p><label>New password<input name="password" type="password" minlength="12" maxlength="200" autocomplete="new-password" required></label><label>Confirm password<input name="confirm" type="password" minlength="12" maxlength="200" autocomplete="new-password" required></label><button class="button">Activate account</button></form>`,
  );
  handleForm("#activation", async (b) => {
    if (b.password !== b.confirm) throw Error("Passwords do not match.");
    await api(owner ? "owner-invitation" : "staff/activate", {
      token,
      password: b.password,
    });
    session = await api("session");
    await go("/admin");
    toast("Account activated. Sign in with your assigned username.");
  });
}
async function render() {
  const version = ++revision;
  try {
    const path = location.pathname;
    if (path === "/admin/owner-setup" || path === "/admin/activate") {
      await activation(path.endsWith("owner-setup"));
      return;
    }
    let body;
    if (path.startsWith("/admin")) body = await adminPage(path);
    else if (path === "/") body = home();
    else if (path === "/shop") body = catalogue();
    else if (path.startsWith("/product/")) {
      const p = products.find(
        (p) => p.id === decodeURIComponent(path.split("/").pop()),
      );
      if (!p)
        throw Error(
          "This product is unavailable. Explore the latest collection.",
        );
      body = detail(p);
    } else if (path === "/cart") body = cartPage();
    else if (path === "/checkout") body = checkoutPage();
    else if (path === "/contact") body = contact();
    else if (path === "/payment-return") {
      const reference = new URLSearchParams(location.search).get("reference");
      await api("gateway/verify", { reference });
      body = shell(
        `${pageTitle("Payment verified", "The server verified your payment with the provider. The store will confirm fulfilment.")}${link("/shop", "Continue shopping", "button")}`,
      );
    } else if (["/about", "/privacy", "/returns", "/delivery"].includes(path)) {
      const key = path === "/delivery" ? "deliveryPolicy" : path.slice(1);
      body = shell(
        `${pageTitle({ about: "Our story", privacy: "Privacy notice", returns: "Returns & warranty", deliveryPolicy: "Delivery & pickup" }[key])}<article class="prose policy">${esc(store[key])}</article>`,
      );
    } else
      body = shell(
        `${pageTitle("Page not found")}${link("/shop", "Explore the store", "button")}`,
      );
    if (version !== revision) return;
    $("#app").innerHTML = body;
    bind();
  } catch (err) {
    if (version !== revision) return;
    $("#app").innerHTML = shell(
      `${pageTitle("We couldn’t open this page")}<p role="alert">${esc(err.message)}</p>${link("/shop", "Return to the store", "button")}`,
    );
  }
}
function applyTheme() {
  document.body.dataset.layout = store.layout;
  document.title = store.businessName + " · " + store.tagline;
  let style = $("#store-theme");
  if (!style) {
    style = document.createElement("link");
    style.id = "store-theme";
    style.rel = "stylesheet";
    document.head.append(style);
  }
  style.href = "/store-theme.css?v=" + Date.now();
  if (store.favicon) {
    let favicon = $("link[rel=icon]");
    if (!favicon) {
      favicon = document.createElement("link");
      favicon.rel = "icon";
      document.head.append(favicon);
    }
    favicon.href = store.favicon;
  }
}
(async () => {
  try {
    session = await api("session");
    [store, products, categories] = await Promise.all([
      api("store"),
      api("products"),
      api("categories"),
    ]);
    const old = restored(cartKey(), []);
    cart = Array.isArray(old)
      ? old.filter(
          (i) =>
            i &&
            typeof i.product_id === "string" &&
            typeof i.variant_id === "string" &&
            Number.isInteger(i.qty) &&
            i.qty > 0 &&
            Number.isInteger(i.price) &&
            i.price > 0,
        )
      : [];
    try {
      handoff = JSON.parse(sessionStorage.getItem(orderKey() + "-handoff"));
    } catch {}
    applyTheme();
    await render();
  } catch (e) {
    $("#app").textContent =
      "Unable to open the store. Please refresh and try again.";
  }
})();
