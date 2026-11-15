"""Public branding and feature settings. Credentials never belong here."""

import copy
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT = {
    "storeId": "demo",
    "businessName": "Your Store",
    "tagline": "Good products. Personal service.",
    "currency": "NGN",
    "phone": "",
    "whatsapp": "",
    "email": "",
    "address": "",
    "logo": "",
    "favicon": "",
    "layout": "editorial",
    "orderPrefix": "GS",
    "theme": {"primary": "#224d42", "secondary": "#faf8f2", "accent": "#bd8548"},
    "features": {
        "whatsappCheckout": True,
        "bankTransfer": False,
        "onlinePayment": False,
        "instalments": False,
        "delivery": True,
        "pickup": True,
    },
    "categories": ["Featured", "Everyday essentials", "Accessories"],
    "about": "Add your business story before launch.",
    "privacy": "Draft policy: replace with your approved privacy notice before launch.",
    "returns": "Draft policy: add your returns, warranty and exchange terms before launch.",
    "deliveryPolicy": "Draft policy: confirm delivery fees, service areas and times before launch.",
    "bank": {"name": "", "accountName": "", "accountNumber": ""},
}


def validate(config):
    if set(config) - set(DEFAULT):
        raise ValueError("Unknown public store setting.")
    result = copy.deepcopy(DEFAULT)
    for key, value in config.items():
        if isinstance(result.get(key), dict):
            if not isinstance(value, dict) or set(value) - set(result[key]):
                raise ValueError("Unknown store setting option.")
            result[key].update(value)
        else:
            result[key] = value
    for key in [
        "storeId",
        "businessName",
        "tagline",
        "phone",
        "whatsapp",
        "email",
        "address",
        "logo",
        "favicon",
        "layout",
        "orderPrefix",
        "about",
        "privacy",
        "returns",
        "deliveryPolicy",
    ]:
        if not isinstance(result[key], str) or len(result[key]) > (
            10000 if key in ["about", "privacy", "returns", "deliveryPolicy"] else 300
        ):
            raise ValueError("Invalid store setting: " + key)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,39}", result["storeId"]):
        raise ValueError(
            "storeId must be 2–40 lowercase letters, digits, hyphens or underscores."
        )
    if (
        result["layout"] not in ["editorial", "electronics"]
        or result["currency"] != "NGN"
    ):
        raise ValueError("Choose editorial or electronics layout and NGN currency.")
    if not re.fullmatch(r"[A-Z0-9]{2,8}", result["orderPrefix"]):
        raise ValueError("Use a short uppercase order prefix.")
    if result["whatsapp"] and not re.fullmatch(r"[1-9][0-9]{7,14}", result["whatsapp"]):
        raise ValueError("WhatsApp must include country code, digits only.")
    if any(type(v) is not bool for v in result["features"].values()):
        raise ValueError("Feature flags must be true or false.")
    if any(
        not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v)
        for v in result["theme"].values()
    ):
        raise ValueError("Use six-digit hex theme colours.")
    for key in ["logo", "favicon"]:
        value = result[key]
        if value and (not value.startswith("/static/") or ".." in value):
            raise ValueError("Brand assets must be local /static/ paths.")
    if (
        not isinstance(result["categories"], list)
        or not 1 <= len(result["categories"]) <= 50
        or any(
            not isinstance(c, str) or not 1 <= len(c) <= 40
            for c in result["categories"]
        )
    ):
        raise ValueError("Provide 1–50 category names.")
    if any(not isinstance(v, str) or len(v) > 120 for v in result["bank"].values()):
        raise ValueError("Invalid bank details.")
    return result


def load_config(override=None):
    filename = os.getenv("STORE_CONFIG_PATH")
    if override is not None:
        return validate(override)
    if filename:
        return validate(json.loads(Path(filename).read_text()))
    if (ROOT / "profiles/default.json").exists():
        return validate(json.loads((ROOT / "profiles/default.json").read_text()))
    return validate({})


def read_settings(app, database):
    row = database.execute("SELECT value FROM store_settings WHERE id=1").fetchone()
    settings = validate(json.loads(row[0]) if row else app.config["STORE"])
    # Identity is deployment configuration, never changeable via the dashboard.
    settings["storeId"] = app.config["STORE"]["storeId"]
    return settings
