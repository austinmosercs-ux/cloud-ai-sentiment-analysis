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
