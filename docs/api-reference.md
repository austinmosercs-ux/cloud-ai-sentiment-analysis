# API Reference

Base URL: `https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com`

---

## POST /analyze

Analyzes the sentiment of a customer review using Amazon Comprehend.

### Request

```http
POST /analyze
Content-Type: application/json
```

```json
{
  "review": "This product is absolutely amazing! Best purchase I've ever made."
}
```

| Field    | Type   | Required | Max Length | Description         |
|---------|--------|----------|------------|---------------------|
| review  | string | Yes      | 5000 chars | The review text     |

### Response 200 OK

```json
{
  "reviewId": "3f2a1c4d-8b5e-4a2f-9c1d-7e6b3a2f1c4d",
  "sentiment": "POSITIVE",
  "scores": {
    "positive": 0.9987,
    "negative": 0.0003,
    "neutral":  0.0008,
    "mixed":    0.0002
  },
  "timestamp": "2025-09-15T14:32:10.123456+00:00"
}
```

`sentiment` values: `POSITIVE` | `NEGATIVE` | `NEUTRAL` | `MIXED`

All scores are floats between 0 and 1 that sum to ~1.0.

### Response 400 Bad Request

```json
{ "error": "Missing required field: 'review'" }
```

---

## GET /history

Returns the 10 most recently analyzed reviews.

### Request

```http
GET /history
```

No request body needed.

### Response 200 OK

```json
{
  "reviews": [
    {
      "reviewId":   "3f2a1c4d-8b5e-4a2f-9c1d-7e6b3a2f1c4d",
      "timestamp":  "2025-09-15T14:32:10.123456+00:00",
      "reviewText": "This product is absolutely amazing! Best purchase I've ever made.",
      "sentiment":  "POSITIVE",
      "scores": {
        "positive": 0.9987,
        "negative": 0.0003,
        "neutral":  0.0008,
        "mixed":    0.0002
      }
    },
    {
      "reviewId":   "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "timestamp":  "2025-09-15T14:28:03.456789+00:00",
      "reviewText": "The shipping was late and the product was broken. Very disappointed.",
      "sentiment":  "NEGATIVE",
      "scores": {
        "positive": 0.0011,
        "negative": 0.9923,
        "neutral":  0.0054,
        "mixed":    0.0012
      }
    }
  ],
  "count": 2
}
```

---

## Example Test Payloads

Use these to verify your deployment works end-to-end:

```bash
# Strongly positive
{"review": "Absolutely love this! Far exceeded my expectations. Will definitely buy again."}

# Strongly negative
{"review": "Terrible product. Broke after one day, customer service was useless. Do not buy."}

# Neutral / informational
{"review": "I purchased this item on Tuesday and it arrived on Friday as expected."}

# Mixed sentiment
{"review": "The price is great and delivery was fast, but the quality isn't what I expected."}

# Edge case — very short
{"review": "Good."}

# Edge case — question / no clear sentiment
{"review": "Does this come in blue?"}
```
