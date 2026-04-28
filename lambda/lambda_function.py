"""
AI Sentiment Analysis - AWS Lambda Function
Routes:
  POST /analyze  - Pull reviews for an Amazon product (via ScraperAPI)
                   and run sentiment analysis on each with Amazon Comprehend.

Required environment variable:
  SCRAPERAPI_KEY  - ScraperAPI account key (https://www.scraperapi.com/)
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

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Explicit timeouts satisfy SonarQube S7618 and prevent hanging Lambda executions
_config = Config(connect_timeout=5, read_timeout=25)
comprehend = boto3.client("comprehend", config=_config)

SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
SCRAPERAPI_BASE = "https://api.scraperapi.com/structured/amazon/review"

# ScraperAPI returns up to ~10 reviews per page; 3 pages -> up to 30, we cap at 25
PAGES_TO_FETCH = 3
TARGET_REVIEWS = 25
SCRAPERAPI_TIMEOUT = 20

# Amazon Comprehend DetectSentiment limit is 5000 UTF-8 bytes per document
COMPREHEND_MAX_BYTES = 5000


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    logger.info("Event received: %s", json.dumps(event))
    route = event.get("routeKey", "")
    try:
        if route == "POST /analyze":
            return handle_analyze(event)
        return response(404, {"error": f"Route not found: {route}"})
    except Exception as e:
        logger.error("Unhandled error: %s", str(e), exc_info=True)
        return response(500, {"error": "Internal server error", "detail": str(e)})


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------

def handle_analyze(event):
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    asin, error = _validate_request(body)
    if error:
        return error

    try:
        review_items, product_meta = fetch_amazon_reviews(asin)
    except urllib.error.HTTPError as exc:
        return _scraperapi_error_response(exc)
    except urllib.error.URLError as exc:
        logger.error("ScraperAPI URLError: %s", exc, exc_info=True)
        return response(504, {"error": "Review fetch timed out. Try again."})

    if not review_items:
        return response(502, {"error": "No reviews could be retrieved for that product."})

    documents = [truncate_to_bytes(item["text"], COMPREHEND_MAX_BYTES) for item in review_items]
    sentiments = batch_detect_sentiment(documents)
    analyzed_reviews = _build_analyzed_reviews(review_items, documents, sentiments)

    if not analyzed_reviews:
        return response(502, {"error": "All reviews failed sentiment analysis."})

    return response(200, {
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
    })


def _validate_request(body):
    """Return (asin, None) on success, or (None, error_response) on failure."""
    product_url = (body.get("productUrl") or "").strip()
    if not product_url:
        return None, response(400, {"error": "Missing required field: 'productUrl'"})

    if not product_url.startswith(("http://", "https://")):
        return None, response(400, {"error": "Please paste a full Amazon product link."})

    if "amazon." not in urlparse(product_url).netloc:
        return None, response(400, {"error": "That doesn't look like an Amazon link."})

    asin = extract_asin(product_url)
    if not asin:
        return None, response(400, {
            "error": "Could not find the product ASIN. The link should contain /dp/XXXXXXXXXX."
        })

    if not SCRAPERAPI_KEY:
        logger.error("SCRAPERAPI_KEY env var is not set on this Lambda.")
        return None, response(500, {"error": "Server is missing the SCRAPERAPI_KEY environment variable."})

    return asin, None


def _scraperapi_error_response(exc):
    logger.error("ScraperAPI HTTPError: %s", exc, exc_info=True)
    if exc.code == 401:
        return response(502, {"error": "ScraperAPI rejected the API key."})
    if exc.code == 429:
        return response(502, {"error": "ScraperAPI rate limit hit. Try again shortly."})
    return response(502, {"error": f"Review fetch failed (HTTP {exc.code})."})


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
# ScraperAPI integration
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
    """Fetch up to TARGET_REVIEWS reviews by calling ScraperAPI for several pages in parallel."""
    pages = list(range(1, PAGES_TO_FETCH + 1))
    page_results = _fetch_pages_in_parallel(asin, pages)

    review_items = []
    product_meta = {}
    for page in pages:
        data = page_results.get(page)
        if not data:
            continue
        if not product_meta:
            product_meta = _extract_product_meta(data)
        review_items.extend(_extract_review_items(data))
        if len(review_items) >= TARGET_REVIEWS:
            break
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
                logger.warning("ScraperAPI page %d failed: %s", page, exc)
                page_results[page] = None
    return page_results


def _extract_product_meta(data):
    return {
        "title": (data.get("name") or "").strip(),
        "amazon_rating": _to_float(data.get("average_rating")),
        "amazon_review_count": _to_int(
            data.get("total_ratings") or data.get("total_reviews")
        ),
    }


def _extract_review_items(data):
    items = []
    for entry in (data.get("reviews") or []):
        text = (entry.get("review") or "").strip()
        if len(text) < 5:
            continue
        items.append({
            "text": text,
            "amazonStars": _to_int(entry.get("stars")),
            "title": (entry.get("title") or "").strip(),
        })
    return items


def _fetch_one_page(asin, page):
    params = urllib.parse.urlencode({
        "api_key": SCRAPERAPI_KEY,
        "asin": asin,
        "country": "us",
        "tld": "com",
        "page": str(page),
    })
    url = f"{SCRAPERAPI_BASE}?{params}"
    logger.info("Fetching ScraperAPI page %d for ASIN %s", page, asin)
    with urllib.request.urlopen(url, timeout=SCRAPERAPI_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


# ---------------------------------------------------------------------------
# Comprehend
# ---------------------------------------------------------------------------

def batch_detect_sentiment(documents):
    """Return Comprehend results aligned to input order; None for any per-doc errors."""
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
