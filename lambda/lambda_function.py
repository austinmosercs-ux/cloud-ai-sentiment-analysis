"""
AI Sentiment Analysis - AWS Lambda Function
Routes:
  POST /analyze  - Analyze sentiment of a review using Amazon Comprehend
  GET  /history  - Retrieve the 10 most recent reviews from DynamoDB
"""

import json
import boto3
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from botocore.config import Config

# Configure logging - visible in CloudWatch Logs
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Explicit timeouts satisfy SonarQube S7618 and prevent hanging Lambda executions
_config = Config(connect_timeout=5, read_timeout=25)

# AWS clients (initialized once, reused across warm Lambda invocations)
comprehend = boto3.client("comprehend", config=_config)
dynamodb = boto3.resource("dynamodb", config=_config)

TABLE_NAME = "SentimentReviews"
table = dynamodb.Table(TABLE_NAME)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    API Gateway HTTP API sends events with:
      event["routeKey"]  -> e.g. "POST /analyze" or "GET /history"
      event["body"]      -> JSON string for POST requests
    """
    logger.info("Event received: %s", json.dumps(event))

    route = event.get("routeKey", "")

    try:
        if route == "POST /analyze":
            return handle_analyze(event)
        elif route == "GET /history":
            return handle_history()
        else:
            return response(404, {"error": f"Route not found: {route}"})

    except Exception as e:
        logger.error("Unhandled error: %s", str(e), exc_info=True)
        return response(500, {"error": "Internal server error", "detail": str(e)})


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------

def handle_analyze(event):
    """Parse the review text, call Comprehend, store result in DynamoDB."""

    # Parse request body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    review_text = body.get("review", "").strip()

    if not review_text:
        return response(400, {"error": "Missing required field: 'review'"})

    if len(review_text) > 5000:
        return response(400, {"error": "Review text exceeds 5000 character limit"})

    # Call Amazon Comprehend
    logger.info("Calling Comprehend for text of length %d", len(review_text))
    comprehend_result = comprehend.detect_sentiment(
        Text=review_text,
        LanguageCode="en"
    )

    sentiment = comprehend_result["Sentiment"]           # e.g. "POSITIVE"
    scores = comprehend_result["SentimentScore"]        # dict of floats

    # Round scores to 4 decimal places for readability
    scores_rounded = {k: round(v, 4) for k, v in scores.items()}

    # API response scores (plain floats for JSON serialization)
    scores_response = {
        "positive": scores_rounded["Positive"],
        "negative": scores_rounded["Negative"],
        "neutral":  scores_rounded["Neutral"],
        "mixed":    scores_rounded["Mixed"],
    }

    # Build the item to store
    review_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    item = {
        "reviewId":  review_id,
        "timestamp": timestamp,
        "reviewText": review_text,
        "sentiment": sentiment,
        # DynamoDB resource client requires Decimal, not float
        "scores": {k: Decimal(str(v)) for k, v in scores_response.items()},
    }

    # Store in DynamoDB
    table.put_item(Item=item)
    logger.info("Stored review %s with sentiment %s", review_id, sentiment)

    return response(200, {
        "reviewId":  review_id,
        "sentiment": sentiment,
        "scores":    scores_response,
        "timestamp": timestamp,
    })


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------

def handle_history():
    """Return the 10 most recent reviews from DynamoDB."""

    # Scan the whole table (fine for a student project with small data)
    result = table.scan(
        ProjectionExpression="reviewId, #ts, reviewText, sentiment, scores",
        ExpressionAttributeNames={"#ts": "timestamp"},  # 'timestamp' is reserved
    )

    items = result.get("Items", [])

    # Sort by timestamp descending, return top 10
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    recent = items[:10]

    return response(200, {"reviews": recent, "count": len(recent)})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

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
