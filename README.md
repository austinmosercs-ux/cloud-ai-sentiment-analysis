# AI Sentiment Analysis — Cloud Computing Final Project

A fully serverless AWS application that pulls customer reviews from an Amazon
product page, scores each one with **Amazon Comprehend**, and presents a
sentiment dashboard with per-review ratings, an overall sentiment breakdown,
and a star-rating distribution.

## What it does

1. User pastes an Amazon product link into the static S3-hosted page.
2. The frontend POSTs the URL to API Gateway.
3. The Lambda extracts the ASIN, fetches up to **25 reviews** via the
   **RapidAPI Real-Time Amazon Data** API (3 paginated pages, in parallel).
4. The Lambda hands all reviews to **Amazon Comprehend BatchDetectSentiment**
   in a single batched call (returns POSITIVE / NEGATIVE / NEUTRAL / MIXED
   plus a confidence breakdown for each review).
5. Each review is converted to a derived 1–5 rating, then aggregated:
   average / median / std-dev rating, sentiment counts and percentages, and
   a 5-star distribution.
6. The frontend renders the analysis in a dashboard card.

## Project structure

```
cloud-ai-sentiment-analysis/
├── lambda/
│   └── lambda_function.py     ← Python Lambda (POST /analyze)
├── frontend/
│   └── index.html             ← Static website (S3-hosted)
├── docs/
│   ├── aws-setup-guide.md     ← Step-by-step AWS Console + RapidAPI setup
│   ├── api-reference.md       ← Request/response formats + test payloads
│   └── architecture-diagram.md← ASCII diagram + service table for the report
└── README.md
```

## Quick start

1. **Sign up for RapidAPI** and subscribe (free tier) to
   [Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data).
   Copy your API key.
2. Follow [docs/aws-setup-guide.md](docs/aws-setup-guide.md) to create the IAM
   role, Lambda, API Gateway, and S3 bucket.
3. Set the Lambda environment variables:
   - `RAPIDAPI_KEY` = your RapidAPI key
   - `RAPIDAPI_AMAZON_HOST` = `real-time-amazon-data.p.rapidapi.com`
4. Bump the Lambda timeout to **60 seconds**.
5. Update `API_BASE` in [frontend/index.html](frontend/index.html) with your
   API Gateway Invoke URL, then upload the file to your S3 bucket.
6. Open the S3 website endpoint and paste an Amazon product link
   (e.g. `https://www.amazon.com/dp/B0BMLD2GYD`).

## Architecture

- **Frontend:** Amazon S3 (static website hosting)
- **API:** Amazon API Gateway (HTTP API)
- **Backend:** AWS Lambda (Python 3.12, boto3, no external Python deps)
- **AI:** Amazon Comprehend (BatchDetectSentiment)
- **Reviews:** RapidAPI — Real-Time Amazon Data (`/product-reviews`)
- **Storage:** none — browser session only

## API endpoints

| Method | Path      | Description                                                |
|--------|-----------|------------------------------------------------------------|
| POST   | /analyze  | Pull reviews for an Amazon product and return sentiment stats |

See [docs/api-reference.md](docs/api-reference.md) for the full request /
response contract.

## Cost notes

- **Comprehend:** the AWS free tier covers 50K units/month for the first 12
  months; one batch of 25 reviews ≈ 25 units.
- **RapidAPI Real-Time Amazon Data:** free tier is typically 100 requests /
  month with a 1 req/sec rate limit. Each analysis = 3 requests
  (one per review page), so ~33 analyses/month on the free tier.
- **Lambda + API Gateway + S3:** all comfortably inside AWS free tier for a
  class-project workload.
