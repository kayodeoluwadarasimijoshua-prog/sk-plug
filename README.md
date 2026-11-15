# SK PLUG

Independent client project generated from Growthly E-commerce Starter. Public configuration is in `profiles/default.json`. No accounts, customer data, database credentials or storage secrets were copied.

## Local preview

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PREVIEW=1 .venv/bin/python app.py seed
.venv/bin/python app.py
```

Open http://localhost:3000. Demo products are hidden in production. Configure approved contacts and payment methods before checkout.

For production provisioning and security checks, follow [CLIENT_SETUP.md](CLIENT_SETUP.md). See [ARCHITECTURE.md](ARCHITECTURE.md), [CUSTOMIZATION.md](CUSTOMIZATION.md) and [TEST_REPORT.md](TEST_REPORT.md). Source-starter test results are not proof that this client has been deployed or verified live. Run the tests again after customization.
