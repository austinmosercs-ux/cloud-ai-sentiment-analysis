# API Reference

Base URL: `http://<EC2_PUBLIC_DNS>` — same origin as the frontend. nginx
serves `index.html` and reverse-proxies `/analyze` and `/healthz` to
gunicorn on `127.0.0.1:8000`.

The Flask app requires two environment variables (set in
`/etc/sentiment.env` and read by the systemd unit):

| Env var                 | Value                                       |
|-------------------------|---------------------------------------------|
| `RAPIDAPI_KEY`          | Your RapidAPI account key                   |
| `RAPIDAPI_AMAZON_HOST`  | `real-time-amazon-data.p.rapidapi.com`      |

AWS credentials for Comprehend come from the EC2 **instance profile** —
no static keys live on the instance.

## GET /healthz

Liveness probe. Returns 200 always; `ok` is `true` only when both
RapidAPI env vars are set.

```json
{ "ok": true, "rapidapi_configured": true }
```

---

## POST /analyze

Pulls up to 25 reviews for an Amazon product (via RapidAPI's Real-Time Amazon
Data), runs sentiment analysis on them with Amazon Comprehend
`BatchDetectSentiment`, and returns per-review results plus aggregate stats.

### Request

```http
POST /analyze
Content-Type: application/json
```

```json
{
  "productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"
}
```

| Field        | Type   | Required | Description                                              |
|--------------|--------|----------|----------------------------------------------------------|
| `productUrl` | string | Yes      | Amazon product link. Must contain `/dp/<ASIN>`, `/gp/product/<ASIN>`, or `/product-reviews/<ASIN>`. |

The Flask app extracts the ASIN from the URL and ignores the rest of the
path / query string, so links pasted directly from Amazon (with affiliate /
tracking parameters) work fine.

### Response 200 OK

```json
{
  "product": {
    "asin": "B0BMLD2GYD",
    "url": "https://www.amazon.com/dp/B0BMLD2GYD",
    "title": "MIKA3D Bicolor Dual-Color 3D Printer Filament",
    "amazonRating": 4.5,
    "amazonReviewCount": 1234
  },
  "reviews": [
    {
      "reviewId": "review-1-1700000000000",
      "reviewText": "Love this set! No clogging and beautiful colors!",
      "reviewTitle": "Great quality filament",
      "amazonStars": 5,
      "sentiment": "POSITIVE",
      "scores": {
        "positive": 0.9987,
        "negative": 0.0003,
        "neutral":  0.0008,
        "mixed":    0.0002
      },
      "rating": 4.9
    }
  ],
  "stats": {
    "reviewCount": 25,
    "averageRating": 4.45,
    "medianRating": 5.00,
    "ratingStdDev": 0.21,
    "positiveCount": 21,
    "negativeCount": 1,
    "neutralCount":  2,
    "mixedCount":    1,
    "positivePercent": 84.0,
    "negativePercent":  4.0,
    "neutralPercent":   8.0,
    "mixedPercent":     4.0,
    "ratingDistribution": { "1": 1, "2": 0, "3": 2, "4": 1, "5": 21 }
  },
  "timestamp": "2026-04-28T14:32:10.123456+00:00"
}
```

#### Field notes

- **`product.amazonRating` / `product.amazonReviewCount`** — Amazon's own
  star average and rating count, from the RapidAPI response. May be `null`
  if RapidAPI does not return them.
- **`reviews[].amazonStars`** — the original star rating the reviewer gave
  (1–5), separate from our derived `rating`.
- **`reviews[].sentiment`** — Comprehend's classification; one of
  `POSITIVE`, `NEGATIVE`, `NEUTRAL`, `MIXED`.
- **`reviews[].scores`** — Comprehend's confidence per class (sums to ~1.0).
- **`reviews[].rating`** — derived 1–5 score from the confidence vector
  (positive → 5, neutral → 3, mixed → 2.5, negative → 1, weighted average
  then clamped).
- **`stats.averageRating` / `medianRating` / `ratingStdDev`** — computed
  over all derived ratings.
- **`stats.ratingDistribution`** — counts of derived ratings rounded to the
  nearest integer star.

### Response 400 Bad Request

The request was malformed.

```json
{ "error": "Missing required field: 'productUrl'" }
```

```json
{ "error": "Could not find the product ASIN. The link should contain /dp/XXXXXXXXXX." }
```

### Response 500 Internal Server Error

The server is missing required env vars.

```json
{ "error": "Server is missing RAPIDAPI_KEY or RAPIDAPI_AMAZON_HOST environment variables." }
```

### Response 502 Bad Gateway

RapidAPI returned an error or no reviews.

```json
{ "error": "RapidAPI rejected the API key.", "detail": "..." }
```

```json
{ "error": "RapidAPI rate limit hit. Try again shortly.", "detail": "..." }
```

```json
{
  "error": "No reviews could be retrieved for that product.",
  "diagnostics": [
    { "page": 1, "status": "OK", "review_count_in_payload": 0,
      "has_data_field": true, "message": null }
  ]
}
```

The `diagnostics` array surfaces RapidAPI's raw `status` and the per-page
review count, so an empty or rate-limited response is debuggable from the
browser without checking CloudWatch.

### Response 504 Gateway Timeout

```json
{ "error": "Review fetch timed out. Try again." }
```

## Example test payloads

Use these to verify your deployment works end-to-end. Replace `<EC2_PUBLIC_DNS>`
with the instance's public DNS (e.g. `ec2-3-90-12-34.compute-1.amazonaws.com`).

```bash
# A product likely to have many reviews
curl -X POST http://<EC2_PUBLIC_DNS>/analyze \
  -H "Content-Type: application/json" \
  -d '{"productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"}'

# Pasted directly from Amazon (with tracking params) — also works
curl -X POST http://<EC2_PUBLIC_DNS>/analyze \
  -H "Content-Type: application/json" \
  -d '{"productUrl": "https://www.amazon.com/MoKo-Generation-Stand/dp/B0B8STRJYJ/?th=1"}'

# Liveness check
curl http://<EC2_PUBLIC_DNS>/healthz
```
