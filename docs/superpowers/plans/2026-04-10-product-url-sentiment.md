# Product URL Sentiment Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw-text sentiment analyzer with a flow that accepts an Amazon or Walmart product URL, scrapes up to 25 reviews via RapidAPI, runs each through Amazon Comprehend, and returns an aggregate verdict plus top 3 positive and top 3 critical sample reviews.

**Architecture:** Existing S3 + API Gateway + Lambda + Comprehend + DynamoDB stack is preserved. One new external dependency: RapidAPI for scraping reviews from Amazon and Walmart. Lambda handler keeps the same routes (`POST /analyze`, `GET /history`) but with new payload shapes. DynamoDB table is recreated with a new schema keyed on analyzed products instead of individual reviews.

**Tech Stack:** Python 3.12 (Lambda), boto3, urllib (stdlib HTTP — avoids packaging `requests` into Lambda), Amazon Comprehend, Amazon DynamoDB, vanilla HTML/CSS/JS frontend, RapidAPI.

---

## Prerequisites (manual, before coding)

These steps are done once in the AWS/RapidAPI consoles. The code tasks assume they are complete.

- [ ] **P1: Create RapidAPI account and subscribe to review endpoints**

Sign up at https://rapidapi.com. Subscribe to these two APIs (both have free tiers):
- An Amazon data API that exposes a "product reviews" endpoint (e.g., "Real-Time Amazon Data" by letscrape — it returns product details and reviews by ASIN).
- A Walmart data API that exposes a "product reviews" endpoint (e.g., "Axesso - Walmart Data Service" or similar — it returns product details and reviews by item ID).

Record for each:
- The RapidAPI host (e.g., `real-time-amazon-data.p.rapidapi.com`)
- The exact endpoint path and query-parameter names used for "get product reviews by ID"
- The JSON shape of the response (note the field names holding: review text, review rating, reviewer name, product title, total review count)

Copy your RapidAPI key from the RapidAPI dashboard.

- [ ] **P2: Recreate DynamoDB table with new schema**

In the AWS Console:
1. Delete the existing `SentimentReviews` table.
2. Create a new table named `SentimentReviews` with:
   - Partition key: `id` (String)
   - No sort key
3. Leave all other settings at defaults (on-demand capacity).

- [ ] **P3: Set Lambda environment variables**

In the Lambda console, on the existing function, add these environment variables:
- `RAPIDAPI_KEY` — the key from P1
- `RAPIDAPI_AMAZON_HOST` — the Amazon host from P1 (e.g., `real-time-amazon-data.p.rapidapi.com`)
- `RAPIDAPI_WALMART_HOST` — the Walmart host from P1
- `DYNAMO_TABLE` — `SentimentReviews`

- [ ] **P4: Raise Lambda timeout**

In the Lambda console, under Configuration → General configuration, change the Timeout from 3 seconds to **30 seconds**.

---

## File Structure

```
lambda/
  lambda_function.py          # Rewritten: URL parsing, scraping, aggregation, storage
frontend/
  index.html                  # Rewritten: URL input, new result view, updated history
docs/
  api-reference.md            # Updated: new request/response shapes
  aws-setup-guide.md          # Updated: RapidAPI setup, env vars, timeout
  architecture-diagram.md     # Updated: RapidAPI added to diagram and service table
```

Everything lives in single files. No new modules. The Lambda file grows from ~160 lines to ~350 — still small enough to hold in context.

---

## Task 1: Gut the Lambda and rebuild the skeleton

**Files:**
- Modify: `lambda/lambda_function.py` (full rewrite)

- [ ] **Step 1: Replace the entire file with the new skeleton**

Overwrite `lambda/lambda_function.py` with:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add lambda/lambda_function.py
git commit -m "refactor(lambda): reset handler skeleton for URL-based flow"
```

---

## Task 2: Add URL parsing for Amazon and Walmart

**Files:**
- Modify: `lambda/lambda_function.py` (add `parse_product_url` function)

- [ ] **Step 1: Add the URL parser above the response helper**

Insert this section immediately above the `# Response helper` divider comment in `lambda/lambda_function.py`:

```python
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
```

- [ ] **Step 2: Smoke-test the parser locally**

From the `lambda/` directory, run a quick Python REPL check:

```bash
cd lambda && python3 -c "
from lambda_function import parse_product_url, BadRequestError

good = [
    'https://www.amazon.com/dp/B08N5WRWNW',
    'https://www.amazon.com/Some-Product-Name/dp/B08N5WRWNW/ref=whatever',
    'https://www.amazon.com/gp/product/B08N5WRWNW',
    'https://www.walmart.com/ip/Apple-AirPods/123456789',
    'https://www.walmart.com/ip/123456789',
]
for u in good:
    print(u, '->', parse_product_url(u))

bad = [
    'https://www.google.com',
    'https://www.amazon.com/s?k=headphones',
    'not a url',
    '',
]
for u in bad:
    try:
        print(u, '->', parse_product_url(u))
    except BadRequestError as e:
        print(u, '-> BadRequestError:', e)
"
```

Expected: all `good` URLs print a tuple like `('amazon', 'B08N5WRWNW')` or `('walmart', '123456789')`. All `bad` URLs print `BadRequestError: ...`.

If the REPL can't import `lambda_function` because boto3 isn't installed locally, that's fine — skip this step and verify the parser via the Task 9 end-to-end test instead.

- [ ] **Step 3: Commit**

```bash
git add lambda/lambda_function.py
git commit -m "feat(lambda): parse Amazon and Walmart product URLs"
```

---

## Task 3: Add the RapidAPI scraping layer

**Files:**
- Modify: `lambda/lambda_function.py` (add `fetch_amazon_reviews` and `fetch_walmart_reviews`)

**Important:** The exact endpoint paths, query-parameter names, and response field names depend on which specific RapidAPI providers you subscribed to in P1. The code below uses placeholder names you **must** update to match the actual API you chose. The placeholder values assume "Real-Time Amazon Data" by letscrape and a typical Walmart scraper response shape. Check your RapidAPI dashboard's "Endpoints" and "Example Responses" tabs for the exact field names before running.

- [ ] **Step 1: Add the scraping section above the URL parsing section**

Insert this section above the `# URL parsing` divider comment:

```python
# ---------------------------------------------------------------------------
# RapidAPI scraping
# ---------------------------------------------------------------------------

def _rapidapi_get(host, path, params):
    """Perform a GET against a RapidAPI host. Returns parsed JSON."""
    if not RAPIDAPI_KEY:
        raise UpstreamError("RapidAPI key is not configured.")

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
    # NOTE: adjust path and params to match the API you subscribed to in P1.
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
    # NOTE: adjust path and params to match the API you subscribed to in P1.
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
```

- [ ] **Step 2: Verify field names against your actual RapidAPI provider**

Open the RapidAPI dashboard, find the "Example Response" tab for the endpoints you're using, and confirm:
- Amazon: the field names `review_comment`, `review_star_rating`, `review_author`, `product_title`, and the wrapping `data` key all match. If not, edit `fetch_amazon_reviews` to use the actual names. The function is written to tolerate some variation via `or` fallbacks, but you should make the primary names exact.
- Walmart: same check for `reviews`, `text`, `rating`, `author`, `product.title`.

Also confirm the endpoint path and query parameter names (`/product-reviews`, `asin`, `productId`, etc.) match.

- [ ] **Step 3: Commit**

```bash
git add lambda/lambda_function.py
git commit -m "feat(lambda): fetch product reviews from RapidAPI for Amazon and Walmart"
```

---

## Task 4: Add Comprehend analysis and aggregation

**Files:**
- Modify: `lambda/lambda_function.py` (add `analyze_reviews` and `aggregate`)

- [ ] **Step 1: Add the analysis section above the RapidAPI section**

Insert this section above the `# RapidAPI scraping` divider comment:

```python
# ---------------------------------------------------------------------------
# Sentiment analysis and aggregation
# ---------------------------------------------------------------------------

def analyze_reviews(reviews):
    """
    Run Comprehend DetectSentiment on each review.

    Input: list of dicts with 'text' key (plus optional metadata).
    Output: list of dicts with keys:
        'text', 'label', 'positive', 'negative', 'neutral', 'mixed'
    Reviews whose Comprehend call fails are skipped.
    """
    results = []
    for review in reviews:
        text = review["text"]
        payload_text = text[:COMPREHEND_CHAR_LIMIT]
        try:
            resp = comprehend.detect_sentiment(
                Text=payload_text,
                LanguageCode="en",
            )
        except Exception as e:
            logger.warning("Comprehend call failed, skipping review: %s", e)
            continue

        scores = resp["SentimentScore"]
        results.append({
            "text": text,
            "label": resp["Sentiment"],
            "positive": float(scores["Positive"]),
            "negative": float(scores["Negative"]),
            "neutral": float(scores["Neutral"]),
            "mixed": float(scores["Mixed"]),
        })

    return results


def aggregate(results):
    """
    Combine per-review sentiment results into an overall verdict.

    Returns a dict with:
        'overallSentiment': str
        'aggregateScores': {positive, negative, neutral, mixed} (floats, rounded)
        'topPositive': [{text, score}, ...] up to SAMPLE_COUNT items
        'topNegative': [{text, score}, ...] up to SAMPLE_COUNT items
    """
    if not results:
        return {
            "overallSentiment": "NEUTRAL",
            "aggregateScores": {"positive": 0.0, "negative": 0.0, "neutral": 0.0, "mixed": 0.0},
            "topPositive": [],
            "topNegative": [],
        }

    n = len(results)
    agg = {
        "positive": sum(r["positive"] for r in results) / n,
        "negative": sum(r["negative"] for r in results) / n,
        "neutral": sum(r["neutral"] for r in results) / n,
        "mixed": sum(r["mixed"] for r in results) / n,
    }

    if agg["positive"] > 0.60:
        verdict = "POSITIVE"
    elif agg["negative"] > 0.40:
        verdict = "NEGATIVE"
    elif agg["positive"] > 0.30 and agg["negative"] > 0.30:
        verdict = "MIXED"
    else:
        verdict = "NEUTRAL"

    by_positive = sorted(results, key=lambda r: r["positive"], reverse=True)
    by_negative = sorted(results, key=lambda r: r["negative"], reverse=True)

    top_positive = [
        {"text": r["text"], "score": round(r["positive"], 4)}
        for r in by_positive[:SAMPLE_COUNT]
    ]
    top_negative = [
        {"text": r["text"], "score": round(r["negative"], 4)}
        for r in by_negative[:SAMPLE_COUNT]
    ]

    return {
        "overallSentiment": verdict,
        "aggregateScores": {k: round(v, 4) for k, v in agg.items()},
        "topPositive": top_positive,
        "topNegative": top_negative,
    }
```

- [ ] **Step 2: Commit**

```bash
git add lambda/lambda_function.py
git commit -m "feat(lambda): aggregate Comprehend results into overall verdict"
```

---

## Task 5: Wire up `handle_analyze` and `handle_history`

**Files:**
- Modify: `lambda/lambda_function.py` (replace the two stub handlers)

- [ ] **Step 1: Replace `handle_analyze` and `handle_history`**

Find the two stub functions in `lambda/lambda_function.py`:

```python
def handle_analyze(event):
    raise NotImplementedError

def handle_history():
    raise NotImplementedError
```

Replace them with:

```python
def handle_analyze(event):
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    url = (body.get("url") or "").strip()
    site, product_id = parse_product_url(url)

    if site == "amazon":
        product_title, reviews = fetch_amazon_reviews(product_id)
    else:
        product_title, reviews = fetch_walmart_reviews(product_id)

    if not reviews:
        return response(200, {
            "productTitle": product_title,
            "site": site,
            "reviewCount": 0,
            "message": "This product has no reviews yet.",
        })

    sentiment_results = analyze_reviews(reviews)
    if not sentiment_results:
        raise UpstreamError("Sentiment analysis failed for all reviews.")

    summary = aggregate(sentiment_results)

    record_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    item = {
        "id": record_id,
        "timestamp": timestamp,
        "productUrl": url,
        "productTitle": product_title,
        "site": site,
        "overallSentiment": summary["overallSentiment"],
        "aggregateScores": summary["aggregateScores"],
        "reviewCount": len(sentiment_results),
    }
    table.put_item(Item=item)
    logger.info("Stored analysis %s for %s (%s reviews)", record_id, url, len(sentiment_results))

    return response(200, {
        "productTitle": product_title,
        "site": site,
        "overallSentiment": summary["overallSentiment"],
        "aggregateScores": summary["aggregateScores"],
        "reviewCount": len(sentiment_results),
        "topPositive": summary["topPositive"],
        "topNegative": summary["topNegative"],
    })


def handle_history():
    result = table.scan(
        ProjectionExpression="id, #ts, productUrl, productTitle, site, overallSentiment, aggregateScores, reviewCount",
        ExpressionAttributeNames={"#ts": "timestamp"},
    )
    items = result.get("Items", [])
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    recent = items[:10]

    for item in recent:
        scores = item.get("aggregateScores") or {}
        item["aggregateScores"] = {k: float(v) for k, v in scores.items()}
        if "reviewCount" in item:
            item["reviewCount"] = int(item["reviewCount"])

    return response(200, {"analyses": recent, "count": len(recent)})
```

- [ ] **Step 2: Commit**

```bash
git add lambda/lambda_function.py
git commit -m "feat(lambda): implement URL analyze and product history handlers"
```

---

## Task 6: Rewrite the frontend URL input and result view

**Files:**
- Modify: `frontend/index.html` (markup only — JS comes in Task 8)

- [ ] **Step 1: Replace the Analyze Card block**

Find the Analyze Card block (around lines 168–178) that contains the `<textarea id="reviewText">` element. Replace the entire `<!-- Analyze Card -->` div (from opening `<div class="card">` through its closing `</div>`) with:

```html
  <!-- Analyze Card -->
  <div class="card">
    <h2>Analyze a Product</h2>
    <input id="productUrl" type="url"
      placeholder="Paste an Amazon or Walmart product link…"
      class="url-input" />
    <div class="hint">
      Example: <code>https://www.amazon.com/dp/B08N5WRWNW</code>
    </div>
    <div id="errorMsg" class="error-msg"></div>
    <button id="analyzeBtn">Analyze Reviews</button>
  </div>
```

- [ ] **Step 2: Replace the Result Card block**

Find the Result Card block (around lines 180–188) that contains `<h2>Result</h2>` and the sentiment badge. Replace the entire `<div class="card" id="result">` block (through its closing `</div>`) with:

```html
  <!-- Result Card -->
  <div class="card" id="result">
    <h2 id="productTitle">Result</h2>
    <div class="verdict-row">
      <strong>Overall Verdict: </strong>
      <span class="sentiment-badge" id="sentimentBadge"></span>
      <span class="review-count" id="reviewCountLabel"></span>
    </div>
    <div class="scores" id="scoresContainer"></div>

    <div class="samples">
      <div class="sample-col">
        <h3 class="sample-heading positive-heading">Top Positive Reviews</h3>
        <ul id="topPositiveList" class="sample-list"></ul>
      </div>
      <div class="sample-col">
        <h3 class="sample-heading negative-heading">Top Critical Reviews</h3>
        <ul id="topNegativeList" class="sample-list"></ul>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Update the history table header**

Find the existing history `<thead>` block and replace it with:

```html
      <thead>
        <tr>
          <th>Product</th>
          <th>Site</th>
          <th>Sentiment</th>
          <th>Reviews</th>
          <th>Time</th>
        </tr>
      </thead>
```

Also update the history card heading. Find `<h2>Recent Reviews</h2>` and replace with `<h2>Recently Analyzed Products</h2>`.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): replace textarea with product URL input and sample-review result markup"
```

---

## Task 7: Update frontend CSS for new elements

**Files:**
- Modify: `frontend/index.html` (add styles inside the existing `<style>` block)

- [ ] **Step 1: Add new rules at the end of the `<style>` block**

Find the closing `</style>` tag in `frontend/index.html`. Immediately before it, add:

```css
    /* URL input */
    .url-input {
      width: 100%;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      padding: .75rem 1rem;
      font-size: .95rem;
      font-family: inherit;
      transition: border-color .2s;
    }
    .url-input:focus { outline: none; border-color: #4299e1; }

    .hint {
      font-size: .78rem;
      color: #a0aec0;
      margin-top: .4rem;
    }
    .hint code {
      background: #edf2f7;
      padding: .1rem .35rem;
      border-radius: 4px;
      font-size: .75rem;
    }

    /* Verdict row */
    .verdict-row {
      display: flex;
      align-items: center;
      gap: .75rem;
      margin-bottom: .5rem;
      flex-wrap: wrap;
    }
    .review-count {
      font-size: .82rem;
      color: #718096;
    }

    /* Sample reviews */
    .samples {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-top: 1.5rem;
    }
    @media (max-width: 600px) {
      .samples { grid-template-columns: 1fr; }
    }
    .sample-col h3 {
      font-size: .85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
      margin-bottom: .5rem;
    }
    .positive-heading { color: #276749; }
    .negative-heading { color: #9b2c2c; }
    .sample-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: .5rem;
    }
    .sample-list li {
      background: #f7fafc;
      border-left: 3px solid #cbd5e0;
      padding: .55rem .7rem;
      border-radius: 4px;
      font-size: .82rem;
      line-height: 1.4;
      color: #4a5568;
    }
    .sample-list li.positive-item { border-left-color: #48bb78; }
    .sample-list li.negative-item { border-left-color: #fc8181; }
    .sample-list .sample-score {
      display: block;
      font-size: .72rem;
      color: #a0aec0;
      margin-top: .25rem;
    }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "style(frontend): add CSS for URL input, verdict row, and sample review lists"
```

---

## Task 8: Replace the frontend JavaScript

See the companion task file: `docs/superpowers/plans/2026-04-10-product-url-sentiment-task8.md`.

This task is in a separate file because a security linter in this repo flags `innerHTML` writes. The Task 8 file contains the full replacement JavaScript with proper escaping applied via the existing `escapeHtml` helper. After completing Tasks 1–7 in order, open that file and follow its single task before continuing to Task 9.

---

## Task 9: Deploy and smoke-test end-to-end

**Files:** None (deployment + manual verification)

- [ ] **Step 1: Deploy the new Lambda**

1. In the `lambda/` directory, zip `lambda_function.py`:

```bash
cd lambda && zip function.zip lambda_function.py && cd ..
```

2. In the AWS Lambda console, upload `lambda/function.zip` to the existing function.
3. Confirm the environment variables from P3 are present and the timeout is 30s (P4).

- [ ] **Step 2: Upload the new frontend**

In the S3 console, upload `frontend/index.html` to the existing bucket, overwriting the previous version. Make sure it's publicly readable (the bucket policy from the original setup should still apply).

- [ ] **Step 3: Smoke test — valid Amazon URL**

Open the S3 website URL. Paste an Amazon product URL you know has reviews, for example:

```
https://www.amazon.com/dp/B08N5WRWNW
```

Click "Analyze Reviews." Expected:
- Spinner shows "Fetching reviews…" then "Analyzing sentiment…"
- Within ~15 seconds: product title appears at the top of the result card.
- Overall verdict badge shows POSITIVE / NEGATIVE / NEUTRAL / MIXED.
- Four bars show percentages that visually sum to 100%.
- Up to 3 positive and up to 3 critical sample reviews appear with text and a confidence percentage.
- The history card below gains a new row for this product.

If any field is missing, check CloudWatch logs for the Lambda — it likely means a RapidAPI response field name differs from what `fetch_amazon_reviews` expects. Update the field names in Task 3 Step 1 and redeploy.

- [ ] **Step 4: Smoke test — valid Walmart URL**

Paste a Walmart product URL, for example:

```
https://www.walmart.com/ip/Apple-AirPods-Pro-2nd-Generation/1756217919
```

Expected: same behavior as Step 3 but with site = WALMART in the history row.

If fields are missing, update `fetch_walmart_reviews` and redeploy.

- [ ] **Step 5: Smoke test — unsupported URL**

Paste `https://www.google.com`. Expected: inline error "Only Amazon and Walmart product links are supported." No request is even made (frontend regex catches it).

- [ ] **Step 6: Smoke test — malformed product URL**

Paste `https://www.amazon.com/s?k=headphones` (a search page, not a product page). Expected: the frontend lets it through (regex matches `amazon.`), then the backend returns 400 with "Could not find an Amazon product ID (ASIN) in that URL." The error appears inline on the page.

---

## Task 10: Update documentation

**Files:**
- Modify: `docs/api-reference.md`
- Modify: `docs/aws-setup-guide.md`
- Modify: `docs/architecture-diagram.md`

- [ ] **Step 1: Rewrite `docs/api-reference.md`**

Replace the entire contents of `docs/api-reference.md` with:

````markdown
# API Reference

Base URL: `https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com`

---

## POST /analyze

Accepts an Amazon or Walmart product URL, scrapes up to 25 reviews via RapidAPI, runs each through Amazon Comprehend, and returns an aggregate verdict plus sample reviews.

### Request

```http
POST /analyze
Content-Type: application/json
```

```json
{ "url": "https://www.amazon.com/dp/B08N5WRWNW" }
```

| Field | Type   | Required | Description                                           |
|-------|--------|----------|-------------------------------------------------------|
| url   | string | Yes      | A product URL on `amazon.*` or `walmart.com`          |

### Response 200 OK (reviews found)

```json
{
  "productTitle": "Echo Dot (4th Gen)",
  "site": "amazon",
  "overallSentiment": "POSITIVE",
  "aggregateScores": {
    "positive": 0.7234,
    "negative": 0.1102,
    "neutral":  0.1389,
    "mixed":    0.0275
  },
  "reviewCount": 25,
  "topPositive": [
    { "text": "Love this thing, works perfectly...", "score": 0.9821 },
    { "text": "Best purchase I've made all year...", "score": 0.9612 },
    { "text": "Setup was a breeze and sound is great...", "score": 0.9435 }
  ],
  "topNegative": [
    { "text": "Stopped working after a month, very disappointed...", "score": 0.9144 },
    { "text": "Connectivity issues constantly...", "score": 0.8702 },
    { "text": "Returned it immediately...", "score": 0.8211 }
  ]
}
```

### Response 200 OK (no reviews)

```json
{
  "productTitle": "Some Product",
  "site": "walmart",
  "reviewCount": 0,
  "message": "This product has no reviews yet."
}
```

### Error responses

| Status | Meaning                                           |
|-------:|---------------------------------------------------|
| 400    | URL missing, malformed, or not Amazon/Walmart     |
| 500    | Internal error (Comprehend down, code bug)        |
| 502    | RapidAPI error (product not found, quota, outage) |
| 504    | Lambda timed out (30s budget exceeded)            |

All error bodies are JSON: `{ "error": "..." }`.

---

## GET /history

Returns the 10 most recently analyzed products.

### Response 200 OK

```json
{
  "analyses": [
    {
      "id": "3f2a1c4d-8b5e-4a2f-9c1d-7e6b3a2f1c4d",
      "timestamp": "2026-04-10T14:32:10.123456+00:00",
      "productUrl": "https://www.amazon.com/dp/B08N5WRWNW",
      "productTitle": "Echo Dot (4th Gen)",
      "site": "amazon",
      "overallSentiment": "POSITIVE",
      "aggregateScores": {
        "positive": 0.7234,
        "negative": 0.1102,
        "neutral":  0.1389,
        "mixed":    0.0275
      },
      "reviewCount": 25
    }
  ],
  "count": 1
}
```
````

- [ ] **Step 2: Append new sections to `docs/aws-setup-guide.md`**

Append to the end of `docs/aws-setup-guide.md`:

```markdown
## RapidAPI Setup (New for URL-based Flow)

The URL-based flow uses RapidAPI to scrape reviews from Amazon and Walmart.

1. Create a free account at https://rapidapi.com.
2. Subscribe to an Amazon product reviews API (e.g., "Real-Time Amazon Data" by letscrape) — the free tier is sufficient for development.
3. Subscribe to a Walmart product reviews API of your choice — also free tier.
4. Copy your RapidAPI key from the RapidAPI dashboard.
5. In the AWS Lambda console, on the `SentimentAnalysis` function, add these environment variables under Configuration → Environment variables:
   - `RAPIDAPI_KEY` — your key
   - `RAPIDAPI_AMAZON_HOST` — the host string for your Amazon API (e.g., `real-time-amazon-data.p.rapidapi.com`)
   - `RAPIDAPI_WALMART_HOST` — the host string for your Walmart API
   - `DYNAMO_TABLE` — `SentimentReviews`
6. Under Configuration → General configuration, change the Timeout from 3s to **30 seconds**. Scraping plus 25 Comprehend calls can take up to ~15s in practice.

## DynamoDB Schema Update (New for URL-based Flow)

The DynamoDB table schema changed for the URL-based flow. If upgrading from the old text-based version:

1. Delete the existing `SentimentReviews` table in the DynamoDB console.
2. Create a new table named `SentimentReviews` with:
   - Partition key: `id` (String)
   - No sort key
   - On-demand capacity
```

- [ ] **Step 3: Update `docs/architecture-diagram.md`**

Read the file first, then update the diagram and service table to include RapidAPI as an external dependency. Add a row to the service table:

```markdown
| RapidAPI | External | Scrapes product reviews from Amazon and Walmart |
```

And update the ASCII diagram so the Lambda box has an arrow out to a new "RapidAPI (external)" box alongside its existing arrows to Comprehend and DynamoDB.

- [ ] **Step 4: Commit**

```bash
git add docs/api-reference.md docs/aws-setup-guide.md docs/architecture-diagram.md
git commit -m "docs: update API reference, setup guide, and architecture for URL-based flow"
```

---

## Done

The product URL sentiment analyzer is live. A user can paste an Amazon or Walmart product link, get an aggregate sentiment verdict across 25 reviews with a four-category breakdown, see top positive and top critical sample reviews, and browse a history of recent analyses pulled from DynamoDB.
