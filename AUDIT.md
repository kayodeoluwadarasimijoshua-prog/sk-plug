# Existing-project audit and extraction plan

Source inspected: `/workspace/lolaluxe`, commit `6fffa22`. Inspection included Flask routes, persistence/storage adapters, database initialization, role guards, owner/staff invitation lifecycle, public/admin rendering, CSS, tests and Vercel configuration. No production database, customer records or live provider accounts were accessed. The original repository remains unmodified.

## Verified implementation

| Area | Existing implementation | Reuse / change |
|---|---|---|
| Frontend | Vanilla JS SPA with History API, one large renderer/binder file, plain CSS, Flask HTML shell | Keep lightweight stack; replace boutique-specific public rendering with configurable reusable components and two layouts |
| Backend | Flask JSON APIs for products, categories, uploads, checkout, owner receipts, orders, reservations, dashboard and invitations | Preserve transaction-based commerce; add isolated settings/catalogue/payment/enquiry modules |
| Database | SQLite development, PostgreSQL production adapter; inline idempotent schema creation, no migration versions | Move baseline schema into migrations module, add versioned additive extensions; no live DB migration |
| Authentication | One owner, invitation-only Product Admins, password hashing, signed sessions, role checks, hashed expiring invitations, revocation/session version checks | Reuse with per-store cookie identity and unique per-deployment secrets |
| Products | Images, NGN integer prices, exact size/colour variants and per-variant stock, draft/publication | Add specs, featured/archive metadata, guarded hard deletion and category parent relationships |
| Admin | Product creation/editing/upload, owner financial/orders tools, actual recorded analytics, team invitations/activity | Reusable dashboard adds settings, enquiries and lifecycle/category screens; server accounting endpoints retained |
| Storage | Pillow re-encoding, upload size/pixel limits, Cloudinary signed uploads or Supabase service uploads | Reuse adapters with neutral folder names; require independent client storage accounts |
| Checkout | Client cart, server-side current-price/variant/availability checks, order snapshots and retry keys | Preserve server validation; namespaced cart and configurable fulfilment/payment methods |
| WhatsApp | Correct explicit customer handoff, but recipient/business text hardcoded to source client | Move recipient/name into validated store settings; do not invent client contact details |
| Payments | Owner-entered verified receipt ledger, product/delivery split, corrections, retries and stock reconciliation | No gateway existed in source. Add Paystack server verification; transfer claims remain unverified until owner checks funds |
| Deployment | Vercel Python builder; persistent PostgreSQL and external storage required; local run/Gunicorn options | Retain builder, add explicit production configuration guard and independent-client instructions |

## Findings and remediation

1. **High: copying a working deployment can copy its identity and credentials.** Source business name, category defaults, phone, image assets and storage prefix were client-specific. Extract source code only into a new project; omit `data`, `.env`, `.git`, uploaded/generated client images and accounts. Generic configuration and separate SK Plug profile replace these values. No production database is reused.
2. **High: a gateway must never trust a browser success flag.** No gateway existed. New Paystack adapter validates provider state, currency, exact integer amount and reference on the server; webhook HMAC is verified and server verification repeated. Idempotent credit occurs inside the commerce write lock. Manual transfer references never mark orders paid.
3. **Medium: public endpoints other than login lacked durable throttling.** Add DB-backed request buckets for state-changing browser APIs, with tighter limits for login, checkout, enquiries and gateway initialization. Host ingress identity still needs deployment verification. Webhooks use signature authentication; provider-level abuse protection remains operational work.
4. **Medium: malformed text identifiers could reach DB binding.** Add text/boolean validation before protected handlers. Validate settings keys/types, public asset paths, colours and feature flags; keep credentials outside settings.
5. **Medium: no product archive/delete or hierarchy workflow.** Add archive/restore and reject hard deletion of products referenced by orders. Existing order snapshots remain intact. Reject category cycles.
6. **Performance: one reservation query per variant and unpaginated lists.** Aggregate reservations once per request. Catalogue, orders and activity screens still need pagination before very large inventories; no load benchmark is claimed.
7. **Maintainability: schema and presentation bundled into large files.** Extract configuration, baseline/additive migrations, extensions and payment transport. Keep stable commerce and frontend component functions rather than a risky framework rewrite. Further decomposition remains a future maintenance improvement.
8. **Client-specific instalment assumptions.** Customer-facing instalment messaging is conditional and disabled for SK Plug; the ledger still faithfully records real receipts. Existing correction/reservation/accounting APIs remain supported, with delivery agreement, reservation, correction and dismissal forms in the reusable admin.
9. **Presentation security and accessibility.** Store text is escaped, no public admin link, server role checks retained. Serve validated theme CSS externally under strict CSP. Browser tests exposed ambiguous select labels and an invalid browser regex; both were corrected. Focus indicators, semantic controls, skip link, labelled images and reduced-motion behaviour are present; no formal WCAG certification is claimed.

## Proposed architecture and migration sequence

Keep Flask/PostgreSQL and existing commerce contracts. Build a separate source-only project, introduce public profile + DB settings, add catalogue/enquiry/gateway modules and migration metadata, replace storefront presentation, add an isolated SK Plug example, test both SQL backends and browser layouts, then document independent client provisioning. This sequence was implemented without changing the live project's branch, source or deployment.

## Known limits before client launch

Client-approved inventory, photos, contacts, bank details, policies, domain, storage/DB credentials and admin invitation are required. The starter has no real SK Plug inventory or invented instalment agreement. No live Paystack transaction, webhook delivery, provider deployment, production Vercel build or domain/DNS check has been performed. No fulfilment/refund ledger, 2FA, automated invitation email, queued payment reconciliation, full category rename/delete UI or large-catalogue pagination is included. Accounting correction, reservations, delivery agreement and dismissal APIs are retained, exposed in order tools and covered by inherited integration tests. These are explicit scope limitations, not completed launch checks.
