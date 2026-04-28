# API Reference

Base URL: `https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com`

---

## POST /analyze

Analyzes an Amazon product page, extracts review comments, and returns sentiment stats plus derived ratings.

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

| Field    | Type   | Required | Max Length | Description         |
|---------|--------|----------|------------|---------------------|
| productUrl  | string | Yes   | 2000 chars | Amazon product link  |

### Response 200 OK

```json
{
  "product": {
    "title": "MIKA3D ...",
    "asin": "B0BMLD2GYD",
    "url": "https://www.amazon.com/dp/B0BMLD2GYD",
    "amazonRating": 4.2,
    "amazonReviewCount": 4670
  },
  "reviews": [
    {
      "reviewId": "review-1-...",
      "reviewText": "Love this set! No clogging and beautiful colors!",
      "sentiment": "POSITIVE",
      "scores": {
        "positive": 0.9987,
        "negative": 0.0003,
        "neutral": 0.0008,
        "mixed": 0.0002
      },
      "rating": 4.9
    }
  ],
  "stats": {
    "reviewCount": 8,
    "averageRating": 4.55,
    "medianRating": 4.7,
    "ratingStdDev": 0.38,
    "positiveCount": 6,
    "negativeCount": 1,
    "neutralCount": 1,
    "mixedCount": 0,
    "positivePercent": 75.0,
    "negativePercent": 12.5,
    "neutralPercent": 12.5,
    "mixedPercent": 0.0,
    "ratingDistribution": { "1": 0, "2": 1, "3": 1, "4": 2, "5": 4 }
  },
  "timestamp": "2025-09-15T14:32:10.123456+00:00"
}
```

`sentiment` values: `POSITIVE` | `NEGATIVE` | `NEUTRAL` | `MIXED`.
Each extracted review gets its own derived rating, and `stats` summarizes the whole set.

### Response 400 Bad Request

```json
{ "error": "Missing required field: 'productUrl'" }
```

## Example Test Payloads

Use these to verify your deployment works end-to-end:

```bash
# Example Amazon product link
{"productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"}

# Another Amazon product link
{"productUrl": "https://www.amazon.com/dp/B07VY3PXJ4"}
```
