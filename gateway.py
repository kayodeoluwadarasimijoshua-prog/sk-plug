"""Paystack transport: fixed provider origin; no customer-controlled redirect/URL."""

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class GatewayError(ValueError):
    pass


def paystack(secret, path, body=None):
    request = Request(
        "https://api.paystack.co/" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + secret,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if not payload.get("status") or not isinstance(payload.get("data"), dict):
            raise GatewayError("Payment provider could not complete the request.")
        return payload["data"]
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise GatewayError(
            "Payment provider is unavailable. Please try again."
        ) from error
