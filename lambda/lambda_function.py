"""
AI Sentiment Analysis - AWS Lambda Function

Routes:
  POST /analyze  - Accept a product URL, scrape reviews, analyze sentiment, store summary.
  GET  /history  - Return the 10 most recently analyzed products.
"""

import json
import os
import re
import uuid
import logging
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

import boto3
from botocore.config import Config

# ---------------------------------------------------------------------------
# Logging and AWS clients
# ---------------------------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_config = Config(connect_timeout=5, read_timeout=25)

comprehend = boto3.client("comprehend", config=_config)
dynamodb = boto3.resource("dynamodb", config=_config)

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "SentimentReviews")
table = dynamodb.Table(TABLE_NAME)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_AMAZON_HOST = os.environ.get("RAPIDAPI_AMAZON_HOST", "")
RAPIDAPI_WALMART_HOST = os.environ.get("RAPIDAPI_WALMART_HOST", "")

REVIEW_COUNT_TARGET = 25
COMPREHEND_CHAR_LIMIT = 5000
SAMPLE_COUNT = 3


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    logger.info("Event received: %s", json.dumps(event))

    route = event.get("routeKey", "")

    try:
        if route == "POST /analyze":
            return handle_analyze(event)
        elif route == "GET /history":
            return handle_history()
        else:
            return response(404, {"error": f"Route not found: {route}"})

    except BadRequestError as e:
        return response(400, {"error": str(e)})
    except UpstreamError as e:
        return response(502, {"error": str(e)})
    except Exception as e:
        logger.error("Unhandled error: %s", str(e), exc_info=True)
        return response(500, {"error": "Internal server error", "detail": str(e)})


class BadRequestError(Exception):
    pass


class UpstreamError(Exception):
    pass


# ---------------------------------------------------------------------------
# Route handlers (filled in by later tasks)
# ---------------------------------------------------------------------------

def handle_analyze(event):
    raise NotImplementedError

def handle_history():
    raise NotImplementedError


# ---------------------------------------------------------------------------
# RapidAPI scraping
# ---------------------------------------------------------------------------

def _rapidapi_get(host, path, params):
    """Perform a GET against a RapidAPI host. Returns parsed JSON."""
    if not RAPIDAPI_KEY:
        raise UpstreamError("RapidAPI key is not configured.")
    if not host:
        raise UpstreamError("RapidAPI host is not configured.")

    query = urllib.parse.urlencode(params)
    url = f"https://{host}{path}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": host,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        logger.error("RapidAPI HTTP error: %s %s", e.code, e.reason)
        raise UpstreamError(f"Scraping API returned HTTP {e.code}.")
    except urllib.error.URLError as e:
        logger.error("RapidAPI URL error: %s", e.reason)
        raise UpstreamError("Scraping API is unreachable.")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise UpstreamError("Scraping API returned invalid JSON.")


def fetch_amazon_reviews(asin):
    """
    Call the RapidAPI Amazon reviews endpoint.

    Returns (product_title, reviews) where reviews is a list of dicts
    with keys: 'text' (str), 'rating' (int or None), 'author' (str or None).
    """
    # NOTE: adjust path and params to match the API you subscribed to.
    data = _rapidapi_get(
        RAPIDAPI_AMAZON_HOST,
        "/product-reviews",
        {
            "asin": asin,
            "country": "US",
            "sort_by": "TOP_REVIEWS",
            "verified_purchases_only": "false",
            "page_size": str(REVIEW_COUNT_TARGET),
        },
    )

    # Typical shape for Real-Time Amazon Data:
    #   { "data": { "product_title": "...", "reviews": [ { "review_comment": "...", "review_star_rating": "5", "review_author": "..." }, ... ] } }
    payload = data.get("data") or {}
    product_title = payload.get("product_title") or "Unknown product"
    raw_reviews = payload.get("reviews") or []

    reviews = []
    for r in raw_reviews[:REVIEW_COUNT_TARGET]:
        text = (r.get("review_comment") or r.get("review_text") or "").strip()
        if not text:
            continue
        rating_raw = r.get("review_star_rating") or r.get("rating")
        try:
            rating = int(float(rating_raw)) if rating_raw is not None else None
        except (TypeError, ValueError):
            rating = None
        author = r.get("review_author") or r.get("author")
        reviews.append({"text": text, "rating": rating, "author": author})

    return product_title, reviews


def fetch_walmart_reviews(item_id):
    """
    Call the RapidAPI Walmart reviews endpoint.

    Returns (product_title, reviews) with the same shape as fetch_amazon_reviews.
    """
    # NOTE: adjust path and params to match the API you subscribed to.
    data = _rapidapi_get(
        RAPIDAPI_WALMART_HOST,
        "/product-reviews",
        {
            "productId": item_id,
            "page": "1",
        },
    )

    # Typical shape:
    #   { "product": { "title": "..." }, "reviews": [ { "text": "...", "rating": 4, "author": "..." }, ... ] }
    product_title = (
        (data.get("product") or {}).get("title")
        or data.get("product_title")
        or "Unknown product"
    )
    raw_reviews = data.get("reviews") or []

    reviews = []
    for r in raw_reviews[:REVIEW_COUNT_TARGET]:
        text = (r.get("text") or r.get("review_text") or "").strip()
        if not text:
            continue
        rating_raw = r.get("rating") or r.get("stars")
        try:
            rating = int(float(rating_raw)) if rating_raw is not None else None
        except (TypeError, ValueError):
            rating = None
        author = r.get("author") or r.get("user_name")
        reviews.append({"text": text, "rating": rating, "author": author})

    return product_title, reviews


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

AMAZON_ASIN_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})(?:[/?]|$)"),
    re.compile(r"/gp/product/([A-Z0-9]{10})(?:[/?]|$)"),
    re.compile(r"/gp/aw/d/([A-Z0-9]{10})(?:[/?]|$)"),
]

WALMART_ITEM_PATTERN = re.compile(r"/ip/(?:[^/]+/)?(\d+)(?:[/?]|$)")


def parse_product_url(url):
    """
    Return (site, product_id) for a supported product URL.

    site is 'amazon' or 'walmart'.
    Raises BadRequestError for anything else.
    """
    if not url or not isinstance(url, str):
        raise BadRequestError("Missing or invalid URL.")

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        raise BadRequestError("Malformed URL.")

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if "amazon." in host:
        for pattern in AMAZON_ASIN_PATTERNS:
            match = pattern.search(path)
            if match:
                return "amazon", match.group(1)
        raise BadRequestError(
            "Could not find an Amazon product ID (ASIN) in that URL."
        )

    if "walmart.com" in host:
        match = WALMART_ITEM_PATTERN.search(path)
        if match:
            return "walmart", match.group(1)
        raise BadRequestError(
            "Could not find a Walmart item ID in that URL."
        )

    raise BadRequestError(
        "Only Amazon and Walmart product links are supported."
    )


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------

def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }
