"""
AI Sentiment Analysis - Flask web server (EC2-deployable).

POST /analyze - Pull reviews for an Amazon product (via RapidAPI's
                Real-Time Amazon Data) and run sentiment analysis on
                each with Amazon Comprehend.
GET  /healthz - Liveness check.

Required environment variables:
  RAPIDAPI_KEY          - RapidAPI account key
  RAPIDAPI_AMAZON_HOST  - e.g. real-time-amazon-data.p.rapidapi.com

AWS credentials come from the EC2 instance profile (no static keys).
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Explicit timeouts prevent hung worker processes
_config = Config(connect_timeout=5, read_timeout=25)
comprehend = boto3.client("comprehend", config=_config)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_AMAZON_HOST", "")

PAGES_TO_FETCH = 3
TARGET_REVIEWS = 25
RAPIDAPI_TIMEOUT = 25
COMPREHEND_MAX_BYTES = 5000

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/healthz", methods=["GET"])
def healthz():
    ok = bool(RAPIDAPI_KEY and RAPIDAPI_HOST)
    return _json({"ok": ok, "rapidapi_configured": ok}, 200)


@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return _json({}, 204)

    body = request.get_json(silent=True) or {}
    asin, error = _validate_request(body)
    if error:
        return error

    try:
        review_items, product_meta = fetch_amazon_reviews(asin)
    except urllib.error.HTTPError as exc:
        return _rapidapi_error_response(exc)
    except urllib.error.URLError as exc:
        logger.error("RapidAPI URLError: %s", exc, exc_info=True)
        return _json({"error": "Review fetch timed out. Try again."}, 504)

    if not review_items:
        return _json({
            "error": "No reviews could be retrieved for that product.",
            "diagnostics": product_meta.get("_diagnostics") or [],
        }, 502)

    documents = [truncate_to_bytes(item["text"], COMPREHEND_MAX_BYTES) for item in review_items]
    sentiments = batch_detect_sentiment(documents)
    analyzed_reviews = _build_analyzed_reviews(review_items, documents, sentiments)

    if not analyzed_reviews:
        return _json({"error": "All reviews failed sentiment analysis."}, 502)

    return _json({
        "product": {
            "asin": asin,
            "url": (body.get("productUrl") or "").strip(),
            "title": product_meta.get("title") or "Amazon product",
            "amazonRating": product_meta.get("amazon_rating"),
            "amazonReviewCount": product_meta.get("amazon_review_count"),
        },
        "reviews": analyzed_reviews,
        "stats": build_stats(analyzed_reviews),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, 200)


@app.errorhandler(404)
def not_found(_):
    return _json({"error": "Not found"}, 404)


@app.errorhandler(500)
def server_error(exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return _json({"error": "Internal server error"}, 500)


# ---------------------------------------------------------------------------
# Request validation / error helpers
# ---------------------------------------------------------------------------

def _validate_request(body):
    """Return (asin, None) on success, or (None, response) on failure."""
    product_url = (body.get("productUrl") or "").strip()
    if not product_url:
        return None, _json({"error": "Missing required field: 'productUrl'"}, 400)

    if not product_url.startswith(("http://", "https://")):
        return None, _json({"error": "Please paste a full Amazon product link."}, 400)

    if "amazon." not in urlparse(product_url).netloc:
        return None, _json({"error": "That doesn't look like an Amazon link."}, 400)

    asin = extract_asin(product_url)
    if not asin:
        return None, _json({
            "error": "Could not find the product ASIN. The link should contain /dp/XXXXXXXXXX."
        }, 400)

    if not RAPIDAPI_KEY or not RAPIDAPI_HOST:
        logger.error("RAPIDAPI_KEY or RAPIDAPI_AMAZON_HOST is not set.")
        return None, _json({
            "error": "Server is missing RAPIDAPI_KEY or RAPIDAPI_AMAZON_HOST environment variables."
        }, 500)

    return asin, None


def _rapidapi_error_response(exc):
    logger.error("RapidAPI HTTPError %s: %s", exc.code, exc, exc_info=True)
    detail = ""
    try:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
    except Exception:
        pass
    if exc.code in (401, 403):
        return _json({"error": "RapidAPI rejected the API key.", "detail": detail}, 502)
    if exc.code == 429:
        return _json({"error": "RapidAPI rate limit hit. Try again shortly.", "detail": detail}, 502)
    return _json({"error": f"Review fetch failed (HTTP {exc.code}).", "detail": detail}, 502)


def _build_analyzed_reviews(review_items, documents, sentiments):
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    analyzed = []
    for index, (item, document, sentiment_result) in enumerate(
        zip(review_items, documents, sentiments), start=1
    ):
        if sentiment_result is None:
            continue
        scores = sentiment_result["SentimentScore"]
        scores_response = {
            "positive": round(scores["Positive"], 4),
            "negative": round(scores["Negative"], 4),
            "neutral": round(scores["Neutral"], 4),
            "mixed": round(scores["Mixed"], 4),
        }
        analyzed.append({
            "reviewId": f"review-{index}-{timestamp_ms}",
            "reviewText": document,
            "reviewTitle": item.get("title", ""),
            "amazonStars": item.get("amazonStars"),
            "sentiment": sentiment_result["Sentiment"],
            "scores": scores_response,
            "rating": calculate_rating(scores_response),
        })
    return analyzed


# ---------------------------------------------------------------------------
# RapidAPI integration (Real-Time Amazon Data)
# ---------------------------------------------------------------------------

def extract_asin(url):
    for pattern in (
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product-reviews/([A-Z0-9]{10})",
    ):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def fetch_amazon_reviews(asin):
    pages = list(range(1, PAGES_TO_FETCH + 1))
    page_results = _fetch_pages_in_parallel(asin, pages)

    review_items = []
    product_meta = {}
    diagnostics = []
    for page in pages:
        data = page_results.get(page)
        if not data:
            diagnostics.append({"page": page, "fetched": False})
            continue
        diagnostics.append(_diagnose_response(data, page))
        if not product_meta:
            product_meta = _extract_product_meta(data)
        review_items.extend(_extract_review_items(data))
        if len(review_items) >= TARGET_REVIEWS:
            break
    product_meta["_diagnostics"] = diagnostics
    return review_items[:TARGET_REVIEWS], product_meta


def _fetch_pages_in_parallel(asin, pages):
    page_results = {}
    with ThreadPoolExecutor(max_workers=len(pages)) as pool:
        futures = {pool.submit(_fetch_one_page, asin, p): p for p in pages}
        for future in as_completed(futures):
            page = futures[future]
            try:
                page_results[page] = future.result()
            except Exception as exc:
                logger.warning("RapidAPI page %d failed: %s", page, exc)
                page_results[page] = None
    return page_results


def _fetch_one_page(asin, page):
    params = urllib.parse.urlencode({
        "asin": asin,
        "country": "US",
        "sort_by": "TOP_REVIEWS",
        "star_rating": "ALL",
        "verified_purchases_only": "false",
        "images_or_videos_only": "false",
        "current_format_only": "false",
        "page": str(page),
    })
    url = f"https://{RAPIDAPI_HOST}/product-reviews?{params}"
    req = urllib.request.Request(url, headers={
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    })
    logger.info("Fetching RapidAPI for ASIN %s page %d", asin, page)
    with urllib.request.urlopen(req, timeout=RAPIDAPI_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    logger.info("Page %d: status=%s, reviews=%d", page,
                data.get("status"),
                len((data.get("data") or {}).get("reviews") or []))
    return data


def _extract_product_meta(data):
    payload = data.get("data") or {}
    return {
        "title": (payload.get("product_title") or "").strip(),
        "amazon_rating": _to_float(
            payload.get("rating") or payload.get("product_star_rating")
        ),
        "amazon_review_count": _to_int(
            payload.get("total_ratings") or payload.get("total_reviews")
        ),
    }


def _extract_review_items(data):
    payload = data.get("data") or {}
    items = []
    for entry in (payload.get("reviews") or []):
        text = (entry.get("review_comment") or "").strip()
        if len(text) < 5:
            continue
        items.append({
            "text": text,
            "amazonStars": _to_int(entry.get("review_star_rating")),
            "title": (entry.get("review_title") or "").strip(),
        })
    return items


def _diagnose_response(data, page):
    payload = data.get("data") if isinstance(data, dict) else None
    return {
        "page": page,
        "status": (data or {}).get("status"),
        "review_count_in_payload": len((payload or {}).get("reviews") or []),
        "has_data_field": isinstance(payload, dict),
        "message": (data or {}).get("message"),
    }


# ---------------------------------------------------------------------------
# Comprehend
# ---------------------------------------------------------------------------

def batch_detect_sentiment(documents):
    if not documents:
        return []
    result = comprehend.batch_detect_sentiment(TextList=documents, LanguageCode="en")
    aligned = [None] * len(documents)
    for entry in result.get("ResultList", []):
        aligned[entry["Index"]] = entry
    for err in result.get("ErrorList", []):
        logger.warning("Comprehend error on doc %s: %s", err.get("Index"), err.get("ErrorMessage"))
    return aligned


# ---------------------------------------------------------------------------
# Stats / helpers
# ---------------------------------------------------------------------------

def truncate_to_bytes(text, max_bytes):
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def calculate_rating(scores):
    weighted = (
        (scores["positive"] * 5.0)
        + (scores["neutral"] * 3.0)
        + (scores["mixed"] * 2.5)
        + (scores["negative"] * 1.0)
    )
    return round(max(1.0, min(5.0, weighted)), 1)


def build_stats(analyzed_reviews):
    ratings = [item["rating"] for item in analyzed_reviews]
    sentiments = [item["sentiment"] for item in analyzed_reviews]

    sentiment_counts = {
        "positive": sum(1 for v in sentiments if v == "POSITIVE"),
        "negative": sum(1 for v in sentiments if v == "NEGATIVE"),
        "neutral":  sum(1 for v in sentiments if v == "NEUTRAL"),
        "mixed":    sum(1 for v in sentiments if v == "MIXED"),
    }

    rating_distribution = dict.fromkeys(range(1, 6), 0)
    for rating in ratings:
        star = max(1, min(5, int(round(rating))))
        rating_distribution[star] += 1

    if ratings:
        average_rating = round(mean(ratings), 2)
        median_rating = round(median(ratings), 2)
        rating_std_dev = round(pstdev(ratings), 2) if len(ratings) > 1 else 0.0
    else:
        average_rating = median_rating = rating_std_dev = 0.0

    total = len(analyzed_reviews)
    return {
        "reviewCount": total,
        "averageRating": average_rating,
        "medianRating": median_rating,
        "ratingStdDev": rating_std_dev,
        "positiveCount": sentiment_counts["positive"],
        "negativeCount": sentiment_counts["negative"],
        "neutralCount": sentiment_counts["neutral"],
        "mixedCount": sentiment_counts["mixed"],
        "positivePercent": percent(sentiment_counts["positive"], total),
        "negativePercent": percent(sentiment_counts["negative"], total),
        "neutralPercent": percent(sentiment_counts["neutral"], total),
        "mixedPercent": percent(sentiment_counts["mixed"], total),
        "ratingDistribution": rating_distribution,
    }


def percent(count, total):
    if total == 0:
        return 0.0
    return round((count / total) * 100.0, 1)


def _to_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value):
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _json(payload, status_code):
    response = jsonify(payload)
    response.status_code = status_code
    for key, value in CORS_HEADERS.items():
        response.headers[key] = value
    return response


if __name__ == "__main__":
    # Local development only; production runs via gunicorn (see deploy/sentiment.service)
    app.run(host="0.0.0.0", port=8000, debug=True)
