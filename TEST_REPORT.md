# Test report

Executed in this workspace on 15 November 2026. Tests use synthetic inventory, temporary databases and test-only passwords; no production customer data, live WhatsApp messages or real payments were used.

| Check | Result | Evidence / scope |
|---|---|---|
| Fresh dependency installation | Passed | Created the starter's own `.venv`; installed `requirements-postgres-test.txt`, including pinned Flask, Pillow, psycopg, Cloudinary, pytest, Playwright, pgserver and Gunicorn |
| Backend/integration suite | **65 passed** | `.venv/bin/python -m pytest -q` — 19.09 s on the final independent environment run |
| SQLite + PostgreSQL commerce | Passed | Variant identity and reservations, publication, price/stock validation, order snapshots, idempotent checkout/receipts, delivery/product splits, partial payments, corrections, dashboard accounting and conflict warnings |
| Accounts and permissions | Passed | Owner setup, expired/replaced/reused invitations, role escalation denial, staff activation, revocation, password reset/session invalidation and unauthenticated access denial |
| Starter extensions | Passed | Public-setting validation, protected settings, theme CSS, specs/featured metadata, archive/restore/delete safeguards, category cycles, enquiries/throttling, bank claims remaining unpaid |
| Payment provider boundary | Passed with simulated provider responses | Server verification checks reference, success, NGN and exact amount; wrong currency/amount rejected; duplicate verify/webhook credits once; unsigned webhook rejected; no live provider call claimed |
| Client separation / scaffolding | Passed | Independent databases and cookie secrets/names, no enquiry leakage, separate configurations; generator excludes `.git`, `.env`, `.venv`, databases, artifacts and example client files |
| Browser acceptance | Passed | `.venv/bin/python tests/browser_acceptance.py`; Chromium `/usr/bin/chromium`, editorial and electronics layouts, 390×844 and 1440×1000 screenshots |
| Browser shopping | Passed | Images decode, empty search, price sorting, product options, quantity, cart persistence, checkout creation, explicit WhatsApp URL without sending, enquiries and policy pages |
| Browser admin | Passed | Owner activation/login, raster image upload, product publication, delivery agreement, reservation, verified receipt, correction reversing paid state, settings, enquiries, team invitation, restricted navigation and immediate revocation |
| Browser diagnostics | Passed | No JavaScript or console errors; no horizontal overflow on checked mobile/desktop home/admin views |
| JavaScript syntax | Passed | `node --check static/app.js` |
| Python compilation | Passed | `python -m compileall -q app.py persistence.py extensions.py gateway.py migrations.py store_config.py demo.py scripts` |
| WSGI startup | Passed | `python -m gunicorn --check-config app:app`; integration suite also starts a real Gunicorn process and checks store JSON, homepage, shop, theme and JS routes |
| Vercel package declarations | Passed locally | Entrypoint exists; template/static/profile/example inclusion checked. This is a configuration check, not an actual Vercel build |
| Source project preservation | Passed | Original `/workspace/lolaluxe` stays at `6fffa22` with no working-tree changes; no source production push/deploy performed |

## Issues corrected during validation

New default categories initially did not match inherited synthetic test fixtures; test-specific store profiles now declare their own categories. Cookie tests now use the new store-specific cookie name. Browser select controls received explicit accessible labels. An invalid modern-HTML username pattern was replaced by length constraints with strict server validation. Theme styles are served under CSP as external CSS. Demo artwork captions no longer overlap. Phone photos are resized before upload to remain under serverless body limits. New-client generation writes the client default profile and client-specific README, without retaining another client's examples or local data.

## Not verified / remaining work

No live Vercel deployment/build, domain/DNS/HTTPS configuration, actual Paystack test/live transaction or webhook delivery, real Cloudinary/Supabase account upload, SMTP, production backup restore, penetration test, load benchmark or formal accessibility certification. Storage transports are stubbed in integration tests; PostgreSQL is a real temporary local server. Checked viewport snapshots are not coverage of every browser/device/zoom combination.

Client-approved inventory/photos/contact details/bank instructions/policies and unique database/storage/session/payment credentials are prerequisites to launch. SK Plug instalments remain disabled. Large-catalogue pagination, category rename/delete UI, fulfilment/returns/refund ledger, 2FA and queued payment reconciliation remain limitations documented in ARCHITECTURE.md. Receipt corrections adjust the record and stock; they do not execute a refund. The store owner must reconcile actual bank/provider money and physical stock.
