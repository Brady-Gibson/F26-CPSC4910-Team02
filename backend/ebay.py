"""eBay Browse API client: search listings and fetch one listing, for sponsor catalogs.

Config (backend/.env locally, Beanstalk environment properties when deployed):
    EBAY_CLIENT_ID       App ID from developer.ebay.com -> Application Keys
    EBAY_CLIENT_SECRET   Cert ID from the same keyset
    EBAY_ENV             "sandbox" (default) or "production"; must match the keyset

Uses an application token (client credentials grant), so no eBay user login is involved.
Raises EbayError for anything that goes wrong; routes turn it into a JSON error.
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_US"
TIMEOUT = 10  # seconds per request

_token = {"value": None, "expires": 0.0}
_lock = threading.Lock()


class EbayError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def configured():
    return bool(os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET"))


def _base():
    return "https://api.ebay.com" if os.getenv("EBAY_ENV", "sandbox") == "production" else "https://api.sandbox.ebay.com"


def _request(url, headers, data=None):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise EbayError("That eBay listing no longer exists.", 404)
        raise EbayError(f"eBay returned an error ({e.code}). Try again in a moment.")
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise EbayError("Couldn't reach eBay. Try again in a moment.")


def _access_token():
    """Cached application token; eBay issues them for about 2 hours."""
    if not configured():
        raise EbayError("The eBay catalog isn't set up on this server yet.", 503)
    with _lock:
        if _token["value"] and time.time() < _token["expires"] - 60:
            return _token["value"]
        basic = base64.b64encode(f"{os.environ['EBAY_CLIENT_ID']}:{os.environ['EBAY_CLIENT_SECRET']}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": SCOPE}).encode()
        data = _request(f"{_base()}/identity/v1/oauth2/token",
                        {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, body)
        _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 7200)))
        return _token["value"]


def _get(path, params=None):
    url = f"{_base()}/buy/browse/v1{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    return _request(url, {"Authorization": f"Bearer {_access_token()}", "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE})


def _price(item):
    try:
        price = item.get("price") or {}
        return Decimal(price["value"]) if price.get("currency") == "USD" else None
    except (KeyError, InvalidOperation):
        return None


def _product(item):
    """eBay item (summary or full) -> the PRODUCT columns we store."""
    stock = [a.get("estimatedAvailabilityStatus") for a in item.get("estimatedAvailabilities") or []]
    category = (item.get("categoryPath") or "").split("|")[-1] or \
        next((c.get("categoryName") for c in item.get("categories") or []), None)
    price = _price(item)
    return {
        "external_product_id": item["itemId"],
        "product_name": (item.get("title") or "Untitled listing")[:255],
        "description": item.get("shortDescription") or item.get("condition"),
        "dollar_price": price,
        "availability": "UNAVAILABLE" if price is None or "OUT_OF_STOCK" in stock else "AVAILABLE",
        "image_url": ((item.get("image") or {}).get("imageUrl") or "")[:1000] or None,
        "category": (category or "eBay")[:100],
        "item_web_url": item.get("itemWebUrl"),
    }


def search(q, limit=20, offset=0):
    """Fixed-price US listings matching q. Returns (products, total)."""
    data = _get("/item_summary/search", {"q": q, "limit": limit, "offset": offset,
                                         "filter": "buyingOptions:{FIXED_PRICE},priceCurrency:USD"})
    return [_product(i) for i in data.get("itemSummaries") or []], int(data.get("total") or 0)


def get_item(item_id):
    """Current details for one listing (price, stock). Raises EbayError(status=404) if it's gone."""
    return _product(_get(f"/item/{urllib.parse.quote(item_id, safe='')}"))
