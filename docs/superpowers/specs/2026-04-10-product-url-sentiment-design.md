# Product URL Sentiment Analysis — Design

**Date:** 2026-04-10
**Status:** Approved, pending implementation plan

## Overview

Pivot the existing AI Sentiment Analysis app from pasting raw review text to pasting an Amazon or Walmart product URL. The system fetches reviews for the product via a third-party scraping API, runs each review through Amazon Comprehend, aggregates the results into an overall verdict, and displays the verdict plus sample reviews to the user.

The existing AWS architecture (S3 + API Gateway + Lambda + Comprehend + DynamoDB) is preserved. The only new dependency is RapidAPI as an external service for scraping reviews.

## Goals

- Accept an Amazon or Walmart product URL as input.
- Fetch 25 reviews for that product via RapidAPI.
- Run Comprehend sentiment analysis on each review.
- Return an overall verdict (POSITIVE / NEGATIVE / NEUTRAL / MIXED), a four-category breakdown, and the top 3 most-positive and top 3 most-critical individual reviews.
- Persist each analysis to DynamoDB and display recent analyses in a history view.

## Non-Goals

- Supporting sites other than Amazon and Walmart.
- User authentication or per-user history.
- Caching or re-displaying individual scraped review text from past analyses.
- Rate limiting on our own API endpoint.
- Automated integration tests that hit live RapidAPI or Comprehend.
- Star-rating conversion or comparison with the site's own star rating.

## Architecture

No new AWS services. One new external dependency (RapidAPI).

```
[User Browser]
     |
     v
[S3 static site] -- URL input
     |
     v
[API Gateway] -- POST /analyze { url }
     |
     v
[Lambda (Python)]
   |       |            |
   v       v            v
[RapidAPI] [Comprehend] [DynamoDB]
 reviews    sentiment    history
```

### End-to-End Flow (POST /analyze)

1. Frontend validates URL shape (must contain `amazon.` or `walmart.com`) and POSTs `{ "url": "..." }` to `POST /analyze`.
2. Lambda parses the URL, detects the site (Amazon or Walmart), extracts the product ID. Unsupported URLs return 400.
3. Lambda calls the appropriate RapidAPI endpoint to fetch up to 25 reviews plus the product title.
4. For each review, Lambda calls Comprehend `DetectSentiment` and collects the per-review result.
5. Lambda aggregates results into an overall verdict, a four-category score breakdown, and picks the top 3 positive and top 3 negative reviews.
6. Lambda writes a single record to DynamoDB capturing the analysis summary (no individual review text stored).
7. Lambda returns the full result payload to the frontend.
8. Frontend renders the verdict badge, breakdown bars, and sample reviews. History card refreshes from `GET /history`.

### Site & Service List

| Concern | Service |
|---|---|
| Static site hosting | Amazon S3 |
| HTTP routing | Amazon API Gateway (HTTP API) |
| Compute | AWS Lambda (Python 3.12) |
| Sentiment | Amazon Comprehend `DetectSentiment` |
| Storage | Amazon DynamoDB |
| Review scraping | RapidAPI (Amazon and Walmart data endpoints) |

## Components

### Lambda (`lambda/lambda_function.py`)

Rewritten around these functions:

- `handler(event, context)` — routes `POST /analyze` and `GET /history`.
- `parse_product_url(url) -> (site, product_id)` — supports Amazon `/dp/ASIN` and `/gp/product/ASIN`, and Walmart `/ip/.../itemId`. Raises on unsupported URL.
- `fetch_amazon_reviews(asin) -> (product_title, reviews)` — calls RapidAPI, returns up to 25 reviews plus product title.
- `fetch_walmart_reviews(item_id) -> (product_title, reviews)` — same contract.
- `analyze_reviews(reviews) -> list[dict]` — calls Comprehend `DetectSentiment` for each review, returns a list of per-review results containing the review text, the label, and the four score values.
- `aggregate(results) -> dict` — implements the aggregation logic below, returns overall verdict, aggregate scores, and top-3 picks.
- `save_to_dynamo(url, title, site, verdict, scores, count)` — writes a single item to DynamoDB.
- `load_history() -> list[dict]` — returns the 10 most recent analyses.

Configuration via Lambda environment variables:

- `RAPIDAPI_KEY`
- `RAPIDAPI_AMAZON_HOST`
- `RAPIDAPI_WALMART_HOST`
- `DYNAMO_TABLE`

Lambda timeout: **30 seconds** (up from the default 3s) to accommodate scraping plus 25 Comprehend calls.

### Aggregation Logic

Comprehend returns four scores per review (positive, negative, neutral, mixed) that sum to 1.0, plus a discrete label.

**Aggregate scores:** Average each of the four score components independently across all analyzed reviews. This directly produces the four percentages shown in the bar chart.

**Overall verdict** is determined by applying these rules in order:

1. If aggregate positive > 0.60 → **POSITIVE**
2. Else if aggregate negative > 0.40 → **NEGATIVE**
3. Else if aggregate positive > 0.30 and aggregate negative > 0.30 → **MIXED**
4. Else → **NEUTRAL**

Thresholds are deliberately asymmetric: negative needs a lower bar because product reviews skew positive overall, so a 40% negative signal is genuinely bad.

**Sample reviews:** Sort the analyzed reviews by individual `positive` score descending and take the first 3 for the positive samples. Sort by individual `negative` score descending and take the first 3 for the negative samples. Each sample includes the review text (truncated to ~300 characters for display) and its dominant score.

### DynamoDB Schema

Existing table is repurposed with a new item shape. The old table should be deleted and recreated during deployment because the schema is incompatible with the previous one.

Each item:

- `id` (partition key, UUID)
- `timestamp` (sort key or GSI key for recent-first queries)
- `productUrl`
- `productTitle`
- `site` (`amazon` or `walmart`)
- `overallSentiment` (`POSITIVE` / `NEGATIVE` / `NEUTRAL` / `MIXED`)
- `aggregateScores` (map: positive, negative, neutral, mixed)
- `reviewCount`

Individual review text is not stored.

### Frontend (`frontend/index.html`)

Structural rewrite of markup and JS. Existing CSS (cards, bar colors, sentiment badges) is reused so the visual language stays consistent.

- **Input card:** Single-line URL input replacing the textarea. Placeholder: "Paste an Amazon or Walmart product link…". Example URLs shown below the input. Button label: "Analyze Reviews."
- **Result card:** Product title at top. Large overall sentiment badge. Four-bar breakdown (reusing existing `.bar-fill` styles). Two side-by-side sections: "Top Positive Reviews" (up to 3) and "Top Critical Reviews" (up to 3). Each sample shows truncated review text and its dominant score as a percentage.
- **History card:** Table columns: Product (linked to original URL), Site, Sentiment, Time.
- **Loading state:** Spinner message updates in phases ("Fetching reviews… Analyzing sentiment… Ready") since total latency is ~8–12 seconds.
- **Frontend URL validation:** Lightweight regex check that the URL contains `amazon.` or `walmart.com` before making the request. Real validation happens server-side.

### Docs

- `docs/aws-setup-guide.md` — Add a section on creating a RapidAPI account, subscribing to Amazon and Walmart data endpoints, and setting the Lambda environment variables.
- `docs/api-reference.md` — Update request and response shapes for `POST /analyze` and `GET /history`.
- `docs/architecture-diagram.md` — Add RapidAPI as an external box in the diagram and service table.

## API Shapes

### POST /analyze

Request:

```json
{ "url": "https://www.amazon.com/dp/B08N5WRWNW" }
```

Success response (200):

```json
{
  "productTitle": "Echo Dot (4th Gen)",
  "site": "amazon",
  "overallSentiment": "POSITIVE",
  "aggregateScores": {
    "positive": 0.72,
    "negative": 0.12,
    "neutral": 0.13,
    "mixed": 0.03
  },
  "reviewCount": 25,
  "topPositive": [
    { "text": "Love this thing...", "score": 0.98 },
    { "text": "...", "score": 0.96 },
    { "text": "...", "score": 0.94 }
  ],
  "topNegative": [
    { "text": "Stopped working after a month...", "score": 0.91 },
    { "text": "...", "score": 0.87 },
    { "text": "...", "score": 0.82 }
  ]
}
```

No-reviews response (200):

```json
{
  "productTitle": "Some Product",
  "site": "walmart",
  "reviewCount": 0,
  "message": "This product has no reviews yet."
}
```

Error responses:

- `400` — Unsupported or malformed URL. Body: `{ "error": "Only Amazon and Walmart product links are supported." }`
- `502` — RapidAPI failure (product not found, rate limit, upstream error). Body: `{ "error": "Could not fetch reviews from Amazon. Try again or try a different product." }`
- `500` — Comprehend failure or other internal error.
- `504` — Surfaced by API Gateway if Lambda exceeds 30s timeout.

### GET /history

Unchanged contract. Returns the 10 most recent DynamoDB items in the new schema.

## Error Handling & Edge Cases

- **Unsupported URL** — Return 400 with a clear message.
- **Zero reviews returned** — Return 200 with `reviewCount: 0` and a friendly message. Do not write to DynamoDB.
- **RapidAPI error or rate limit** — Return 502 with a user-facing message. Do not write to DynamoDB.
- **Lambda timeout** — API Gateway surfaces 504. Frontend shows "Request timed out."
- **Fewer than 25 reviews** — Analyze whatever was returned. Show the actual count in the result ("Based on 12 reviews"). Top-3 lists may contain fewer than 3 items if the total sample is small.
- **Single Comprehend call fails** — Skip that review and continue.
- **Comprehend entirely down** — Fail the whole request with 500.
- **Review over 5000 characters** — Truncate before sending to Comprehend (Comprehend's per-call limit). Full text is still shown in the sample-reviews section of the response.
- **No auth, no rate limiting on our API** — Intentional for a course project. Documented as a known limitation.

## Known Limitations (for write-up)

- No authentication or per-IP rate limiting on the public endpoint; a real deployment would need both to prevent burning the RapidAPI quota.
- Scraping APIs can break when source sites change markup.
- Free tier quotas on RapidAPI cap total analyses; this is acceptable for demo and development.
