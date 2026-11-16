"""Headless acceptance on independent editorial and electronics stores; no live messages/payments."""

import sys, tempfile, threading, secrets, json, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, issue_owner_invitation
from demo import seed
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
ART.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    servers = []
    apps = []
    for index, layout in enumerate(["editorial", "electronics"]):
        config = (
            json.loads(
                (
                    (ROOT / "examples/sk-plug/store.json")
                    if (ROOT / "examples/sk-plug/store.json").exists()
                    else (ROOT / "profiles/default.json")
                ).read_text()
            )
            if index
            else {
                "businessName": "Example Store",
                "storeId": "example",
                "categories": ["Home", "Lifestyle", "Accessories"],
            }
        )
        config["layout"] = layout
        config["whatsapp"] = "2348000000000"
        app = create_app(
            {
                "TESTING": True,
                "PREVIEW": True,
                "DATA_DIR": str(Path(directory) / str(index)),
                "STORE": config,
            }
        )
        seed(app)
        apps.append(app)
        server = make_server("127.0.0.1", 3100 + index, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    Image.new("RGB", (500, 500), "gold").save(Path(directory) / "test-product.png")
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        for index, layout in enumerate(["editorial", "electronics"]):
            page = browser.new_page(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "console",
                lambda m: errors.append(m.text) if m.type == "error" else None,
            )
            url = f"http://127.0.0.1:{3100+index}"
            page.goto(url)
            expect(page.locator(".hero h1")).to_be_visible()
            page.locator(".hero-art img").evaluate("(im)=>im.decode()")
            assert page.locator(".hero-art img").evaluate("(im)=>im.naturalWidth") > 0
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert page.locator('a[href^="/admin"]').count() == 0
            page.screenshot(path=str(ART / f"{layout}-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=str(ART / f"{layout}-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("link", name="Shop", exact=True).click()
            page.get_by_label("Search", exact=True).fill("No result should match this")
            page.get_by_role("button", name="Apply", exact=True).click()
            expect(
                page.get_by_role("heading", name="No products here yet")
            ).to_be_visible()
            page.get_by_label("Search", exact=True).fill("")
            page.get_by_label("Sort", exact=True).select_option("high")
            page.get_by_role("button", name="Apply", exact=True).click()
            expect(page.locator(".product")).to_have_count(
                len(apps[index].config["STORE"]["categories"])
            )
            page.locator(".product-copy a").first.click()
            expect(
                page.get_by_text("Demonstration product.", exact=False)
            ).to_be_visible()
            page.get_by_label("Quantity", exact=True).fill("2")
            page.get_by_role("button", name="Add to bag", exact=True).click()
            expect(page.locator(".cart-line")).to_have_count(1)
            page.reload()
            expect(page.locator(".cart-line")).to_have_count(1)
            page.get_by_role("button", name="Continue to checkout").click()
            expect(
                page.get_by_role("heading", name="Your order request is saved")
            ).to_be_visible()
            assert (
                page.get_by_role("link", name="Send order on WhatsApp")
                .get_attribute("href")
                .startswith("https://wa.me/2348000000000?text=")
            )
            page.goto(url + "/contact")
            page.get_by_label("Your name").fill("Test Customer")
            page.get_by_label("Email", exact=True).fill("test@example.test")
            page.get_by_label("Message", exact=True).fill(
                "A test enquiry about availability."
            )
            page.get_by_role("button", name="Send enquiry", exact=True).click()
            expect(page.locator("#toast")).to_contain_text("sent")
            for path in ["about", "privacy", "returns", "delivery"]:
                page.goto(url + "/" + path)
                expect(page.locator(".policy")).to_be_visible()
            token = issue_owner_invitation(apps[index], "owner")
            password = secrets.token_urlsafe(20)
            page.goto(url + "/admin/owner-setup#" + token)
            page.get_by_label("New password", exact=True).fill(password)
            page.get_by_label("Confirm password", exact=True).fill(password)
            page.get_by_role("button", name="Activate account", exact=True).click()
            page.get_by_label("Username", exact=True).fill("owner")
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in securely", exact=True).click()
            expect(page.get_by_role("heading", name="Recorded sales")).to_be_visible()
            page.get_by_role("link", name="Products", exact=True).click()
            page.get_by_role("link", name="Add product", exact=True).click()
            page.get_by_label("Product name", exact=True).fill(
                "Browser verified product"
            )
            page.get_by_label("Price (₦)", exact=True).fill("12345")
            page.get_by_label("Description", exact=True).fill(
                "Synthetic acceptance product."
            )
            page.locator("#upload").set_input_files(
                Path(directory) / "test-product.png"
            )
            expect(page.locator("#photos img")).to_have_count(1)
            page.get_by_label("Stock", exact=True).fill("3")
            page.get_by_label("Specifications", exact=False).fill(
                "Condition: Demonstration"
            )
            page.get_by_label("Featured product", exact=True).check()
            page.get_by_label("Publish product", exact=True).check()
            page.get_by_role("button", name="Save product", exact=True).click()
            expect(
                page.get_by_role("heading", name="Browser verified product")
            ).to_be_visible()
            page.get_by_role("link", name="Orders", exact=True).click()
            page.locator('a[href^="/admin/orders/"]').first.click()
            expect(
                page.get_by_role("heading", name="Record a verified receipt")
            ).to_be_visible()
            page.get_by_text("Delivery and payment agreement", exact=True).click()
            page.get_by_label("Delivery fee (₦)", exact=True).fill("1200")
            page.get_by_label("Agreement notes", exact=True).fill(
                "Test delivery agreement"
            )
            page.get_by_role("button", name="Save agreement", exact=True).click()
            expect(page.locator("#toast")).to_have_text("Agreement saved.")
            page.get_by_text("Reserve stock for this order", exact=True).click()
            page.get_by_label("Quantity to hold", exact=True).fill("1")
            page.get_by_role("button", name="Update reservation", exact=True).click()
            expect(page.locator("#toast")).to_have_text("Reservation updated.")
            total = page.evaluate("window.order.total")
            page.get_by_label("Product amount (₦)", exact=True).fill(str(total / 100))
            page.get_by_label("Delivery amount (₦)", exact=True).fill("1200")
            page.get_by_label("Date received", exact=True).fill("2026-11-15")
            page.get_by_label("Verification / exception note", exact=True).fill(
                "Verified test receipt"
            )
            page.get_by_role(
                "button", name="Record verified payment", exact=True
            ).click()
            expect(page.get_by_text("Paid · Pickup", exact=True)).to_be_visible()
            page.get_by_text("Correct a recorded receipt", exact=True).click()
            page.get_by_label("Correct product amount (₦)", exact=True).fill("0")
            page.get_by_label("Correct delivery amount (₦)", exact=True).fill("0")
            page.get_by_label("Receipt date", exact=True).fill("2026-11-15")
            page.get_by_label("Correction reason", exact=True).fill("Test reversal")
            page.locator("#correction input[name=note]").fill("Correcting test fixture")
            page.get_by_role("button", name="Save correction", exact=True).click()
            expect(
                page.get_by_text("Awaiting payment · Pickup", exact=True)
            ).to_be_visible()
            page.get_by_role("link", name="Settings", exact=True).click()
            page.get_by_label("tagline", exact=True).fill("Updated test tagline")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".announcement")).to_have_text("Updated test tagline")
            page.get_by_role("link", name="Enquiries", exact=True).click()
            expect(
                page.get_by_role("heading", name="Test Customer", exact=True)
            ).to_be_visible()
            page.get_by_role("link", name="Team", exact=True).click()
            page.get_by_label("Username", exact=True).fill("helper")
            page.get_by_role("button", name="Create invitation", exact=True).click()
            expect(page.get_by_label("Invitation link", exact=True)).to_be_visible()
            invite = page.get_by_label("Invitation link", exact=True).input_value()
            helper = browser.new_page(viewport={"width": 390, "height": 844})
            helper.on("pageerror", lambda e: errors.append(str(e)))
            helper.goto(invite)
            helper.get_by_label("New password", exact=True).fill(password)
            helper.get_by_label("Confirm password", exact=True).fill(password)
            helper.get_by_role("button", name="Activate account", exact=True).click()
            helper.get_by_label("Username", exact=True).fill("helper")
            helper.get_by_label("Password", exact=True).fill(password)
            helper.get_by_role("button", name="Sign in securely", exact=True).click()
            expect(
                helper.get_by_role("heading", name="Products", exact=True)
            ).to_be_visible()
            expect(helper.locator(".admin-tabs a")).to_have_count(1)
            page.get_by_role("button", name="Revoke access", exact=True).click()
            expect(page.get_by_text("Revoked", exact=True)).to_be_visible()
            helper.reload()
            expect(
                helper.get_by_role("button", name="Sign in securely")
            ).to_be_visible()
            page.screenshot(
                path=str(ART / f"{layout}-admin-mobile.png"), full_page=True
            )
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.close()
            helper.close()
        browser.close()
    for server in servers:
        server.shutdown()
    assert not errors, errors
print(
    "PASS: both layouts, 390/1440px, images, empty search, sort, cart persistence, checkout handoff, enquiry, policies, owner setup, upload/publish, settings, team invitations, restricted role, revocation; no JS/console errors or horizontal overflow."
)
