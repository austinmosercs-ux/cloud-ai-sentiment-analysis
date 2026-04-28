"""
AI Sentiment Analysis - AWS Lambda Function
Routes:
  POST /analyze  - Analyze sentiment of a review using Amazon Comprehend
"""

import json
import boto3
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from statistics import mean, median, pstdev
from urllib.parse import urlparse
from botocore.config import Config

# Configure logging - visible in CloudWatch Logs
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Explicit timeouts satisfy SonarQube S7618 and prevent hanging Lambda executions
_config = Config(connect_timeout=5, read_timeout=25)

# AWS clients (initialized once, reused across warm Lambda invocations)
comprehend = boto3.client("comprehend", config=_config)


class TextExtractor(HTMLParser):
    """Convert HTML into readable text while skipping script and style blocks."""

    block_tags = {
        "article", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p",
        "section", "tr", "td", "th", "br", "hr", "table", "thead", "tbody",
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return
        if self.skip_depth == 0 and tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        if self.skip_depth == 0 and tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data)

    def text(self):
        text = unescape("".join(self.parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    API Gateway HTTP API sends events with:
            event["routeKey"]  -> e.g. "POST /analyze"
      event["body"]      -> JSON string for POST requests
    """
    logger.info("Event received: %s", json.dumps(event))

    route = event.get("routeKey", "")

    try:
        if route == "POST /analyze":
            return handle_analyze(event)
        else:
            return response(404, {"error": f"Route not found: {route}"})

    except Exception as e:
        logger.error("Unhandled error: %s", str(e), exc_info=True)
        return response(500, {"error": "Internal server error", "detail": str(e)})


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------

def handle_analyze(event):
    """Parse an Amazon product URL, pull review comments, and return stats."""

    # Parse request body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    product_url = body.get("productUrl", "").strip() or body.get("review", "").strip()

    if not product_url:
        return response(400, {"error": "Missing required field: 'productUrl'"})

    if not product_url.startswith("http://") and not product_url.startswith("https://"):
        return response(400, {"error": "Please paste a full Amazon product link."})

    parsed_url = urlparse(product_url)
    if "amazon." not in parsed_url.netloc:
        return response(400, {"error": "Please paste an Amazon product link."})

    try:
        page = fetch_page(product_url)
    except urllib.error.URLError as exc:
        logger.error("Failed to fetch Amazon page: %s", exc, exc_info=True)
        return response(502, {"error": "Could not fetch the Amazon product page", "detail": str(exc)})

    text = html_to_text(page)
    product = parse_product_page(text, page, product_url)

    if not product["reviews"]:
        return response(502, {"error": "No review comments could be extracted from the Amazon page."})

    analyzed_reviews = []
    for index, review_text in enumerate(product["reviews"], start=1):
        if len(review_text) > 5000:
            review_text = review_text[:5000]

        logger.info("Calling Comprehend for review %d of length %d", index, len(review_text))
        comprehend_result = comprehend.detect_sentiment(Text=review_text, LanguageCode="en")

        sentiment = comprehend_result["Sentiment"]
        scores = comprehend_result["SentimentScore"]
        scores_rounded = {k: round(v, 4) for k, v in scores.items()}
        scores_response = {
            "positive": scores_rounded["Positive"],
            "negative": scores_rounded["Negative"],
            "neutral": scores_rounded["Neutral"],
            "mixed": scores_rounded["Mixed"],
        }

        rating = calculate_rating(scores_response)
        analyzed_reviews.append({
            "reviewId": f"review-{index}-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            "reviewText": review_text,
            "sentiment": sentiment,
            "scores": scores_response,
            "rating": rating,
        })

    stats = build_stats(analyzed_reviews, product)
    timestamp = datetime.now(timezone.utc).isoformat()

    return response(200, {
        "product": {
            "title": product["title"],
            "asin": product["asin"],
            "url": product_url,
            "amazonRating": product["amazon_rating"],
            "amazonReviewCount": product["amazon_review_count"],
        },
        "reviews": analyzed_reviews,
        "stats": stats,
        "timestamp": timestamp,
    })


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def calculate_rating(scores):
    """Convert Comprehend sentiment scores into a 1-5 review rating."""
    weighted = (
        (scores["positive"] * 5.0)
        + (scores["neutral"] * 3.0)
        + (scores["mixed"] * 2.5)
        + (scores["negative"] * 1.0)
    )
    return round(max(1.0, min(5.0, weighted)), 1)


def fetch_page(url):
    """Fetch the Amazon product page with browser-like headers."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response_handle:
        return response_handle.read().decode("utf-8", errors="ignore")


def html_to_text(html):
    extractor = TextExtractor()
    extractor.feed(html)
    return extractor.text()


def extract_asin(url):
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product-reviews/([A-Z0-9]{10})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def parse_product_page(text, html, url):
    asin = extract_asin(url)
    title = extract_page_title(html) or asin or "Amazon product"
    amazon_rating, amazon_review_count = extract_amazon_rating(text)
    histogram = extract_histogram(text)
    reviews = extract_reviews(text)

    return {
        "asin": asin,
        "title": title,
        "amazon_rating": amazon_rating,
        "amazon_review_count": amazon_review_count,
        "histogram": histogram,
        "reviews": reviews,
    }


def extract_page_title(html):
    match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if match:
        return unescape(match.group(1)).strip()
    match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if match:
        return unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return ""


def extract_amazon_rating(text):
    rating_match = re.search(r"([0-9.]+) out of 5 stars\s+([\d,]+) (?:global )?ratings", text, re.I)
    if not rating_match:
        return None, None
    return float(rating_match.group(1)), int(rating_match.group(2).replace(",", ""))


def extract_histogram(text):
    histogram = {}
    for stars, percentage in re.findall(r"(\d+) percent of reviews have ([1-5]) stars", text, re.I):
        histogram[int(stars)] = int(percentage)
    return histogram


def extract_reviews(text, limit=8):
    section_start = text.find("Top reviews from the United States")
    if section_start == -1:
        section_start = text.find("Top reviews")
    if section_start == -1:
        section_start = text.find("Customer reviews")
    if section_start == -1:
        return []

    section = text[section_start:]
    section = section.split("Top reviews from other countries")[0]
    section = section.split("See more reviews")[0]

    reviews = []
    start_pattern = re.compile(r"(?P<reviewer>[A-Za-z0-9 .,'\-]+)\s+(?P<rating>[1-5]) out of 5 stars\s+", re.S)
    matches = list(start_pattern.finditer(section))

    for index, match in enumerate(matches):
        start_index = match.end()
        end_index = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        content = normalize_review_text(section[start_index:end_index])
        if len(content) < 20:
            continue
        reviews.append(content)
        if len(reviews) >= limit:
            break
    return reviews


def normalize_review_text(text):
    text = re.sub(r"Reviewed in [A-Za-z ]+ on [A-Za-z0-9, ]+", " ", text)
    text = re.sub(r"Verified Purchase", " ", text, flags=re.I)
    text = re.sub(r"Read more", " ", text, flags=re.I)
    text = re.sub(r"Submit Report", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_stats(analyzed_reviews, product):
    ratings = [item["rating"] for item in analyzed_reviews]
    sentiments = [item["sentiment"] for item in analyzed_reviews]

    sentiment_counts = {
        "positive": sum(1 for value in sentiments if value == "POSITIVE"),
        "negative": sum(1 for value in sentiments if value == "NEGATIVE"),
        "neutral": sum(1 for value in sentiments if value == "NEUTRAL"),
        "mixed": sum(1 for value in sentiments if value == "MIXED"),
    }

    rating_distribution = dict.fromkeys(range(1, 6), 0)
    for rating in ratings:
        star = int(round(rating))
        star = max(1, min(5, star))
        rating_distribution[star] += 1

    if ratings:
        average_rating = round(mean(ratings), 2)
        median_rating = round(median(ratings), 2)
        rating_std_dev = round(pstdev(ratings), 2) if len(ratings) > 1 else 0.0
    else:
        average_rating = 0.0
        median_rating = 0.0
        rating_std_dev = 0.0

    total_reviews = len(analyzed_reviews)
    return {
        "reviewCount": total_reviews,
        "averageRating": average_rating,
        "medianRating": median_rating,
        "ratingStdDev": rating_std_dev,
        "positiveCount": sentiment_counts["positive"],
        "negativeCount": sentiment_counts["negative"],
        "neutralCount": sentiment_counts["neutral"],
        "mixedCount": sentiment_counts["mixed"],
        "positivePercent": percent(sentiment_counts["positive"], total_reviews),
        "negativePercent": percent(sentiment_counts["negative"], total_reviews),
        "neutralPercent": percent(sentiment_counts["neutral"], total_reviews),
        "mixedPercent": percent(sentiment_counts["mixed"], total_reviews),
        "ratingDistribution": rating_distribution,
        "amazonRating": product["amazon_rating"],
        "amazonReviewCount": product["amazon_review_count"],
        "histogram": product["histogram"],
    }


def percent(count, total):
    if total == 0:
        return 0.0
    return round((count / total) * 100.0, 1)


def response(status_code, body):
    """Build a properly formatted API Gateway HTTP response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # Allow requests from your S3 website or localhost during testing
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }
