# Architecture Diagram (Text/ASCII)

Use this as the basis for a diagram in your report (draw.io, Lucidchart, or
PowerPoint).

```
┌────────────────────────────────────────────────────────────────────────┐
│                            User Browser                                │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │           index.html (vanilla JS + fetch API)                │     │
│   └─────────────┬────────────────────────────────────────────────┘     │
└─────────────────┼──────────────────────────────────────────────────────┘
                  │ 1. user loads page
                  ▼
       ┌──────────────────────┐
       │     Amazon S3        │  static website hosting
       │  (frontend bucket)   │
       └──────────┬───────────┘
                  │ 2. HTML / JS served to browser
                  │
                  │ 3. POST /analyze  { productUrl: "..." }
                  ▼
       ┌──────────────────────┐
       │   API Gateway        │  HTTP API
       │  (POST /analyze)     │
       └──────────┬───────────┘
                  │ 4. routes request to Lambda
                  ▼
   ┌────────────────────────────────────────┐
   │           AWS Lambda                   │
   │      Python 3.12 / boto3               │
   │                                        │
   │   handle_analyze()                     │
   │     ├─ extract ASIN from URL           │       ┌───────────────────────┐
   │     ├─ fetch_amazon_reviews()  ────────┼──────▶│   RapidAPI            │
   │     │    3 pages in parallel           │       │ Real-Time Amazon Data │
   │     │    (ThreadPoolExecutor)          │◀──────┤  /product-reviews     │
   │     │                                  │ 5. JSON: up to 30 reviews     │
   │     ├─ batch_detect_sentiment() ───────┼──────▶┌───────────────────────┐
   │     │                                  │       │  Amazon Comprehend    │
   │     │                                  │◀──────┤  BatchDetectSentiment │
   │     │                                  │ 6. sentiment + confidence     │
   │     └─ build_stats()                   │
   └──────────────────┬─────────────────────┘
                      │ 7. JSON: product + reviews + stats
                      ▼
       ┌──────────────────────┐
       │   API Gateway        │
       └──────────┬───────────┘
                  │ 8. response
                  ▼
       ┌──────────────────────┐
       │   User Browser       │
       │   renders dashboard  │   sentiment bar, rating distribution,
       │                      │   per-review confidence + derived rating
       └──────────────────────┘
```

## Data flow (numbered)

1. User opens the S3-hosted webpage in their browser.
2. S3 serves `index.html` + inline CSS / JS.
3. User pastes an Amazon product link, clicks **Analyze Product**, browser
   sends `POST /analyze` to API Gateway.
4. API Gateway routes the request to the Lambda function.
5. Lambda extracts the ASIN, fires **3 parallel HTTPS calls** to
   **RapidAPI Real-Time Amazon Data** (`/product-reviews?asin=…&page=N`).
   Up to 25 unique reviews are collected.
6. Lambda calls **Amazon Comprehend BatchDetectSentiment** with all reviews
   in a single batch — returns sentiment label + confidence vector for each.
7. Lambda builds per-review derived ratings and aggregate stats, returns the
   payload to API Gateway.
8. API Gateway returns the JSON to the browser, which renders the dashboard
   (headline rating, sentiment bar, distribution, per-review table).

## AWS / external services used

| Service / Provider                     | Role                                                       |
|----------------------------------------|------------------------------------------------------------|
| Amazon S3                              | Static website hosting for HTML / JS frontend              |
| Amazon API Gateway                     | HTTP API — routes `POST /analyze` to Lambda                |
| AWS Lambda                             | Serverless Python backend orchestration                    |
| Amazon Comprehend                      | Managed NLP — `BatchDetectSentiment`                       |
| AWS IAM                                | Role for Lambda — least-privilege access to Comprehend     |
| Amazon CloudWatch Logs                 | Automatic log aggregation from Lambda                      |
| RapidAPI: Real-Time Amazon Data        | Third-party API that returns Amazon reviews as JSON        |

## Why serverless?

- **No EC2 servers to manage** — AWS handles scaling, patching, availability.
- **Pay per use** — Lambda charges per invocation; free tier covers a class
  project.
- **Fully managed AI** — Comprehend is a pre-trained model; no ML expertise
  needed.
- **High availability** — API Gateway and Lambda are automatically multi-AZ.
- **Stateless** — no database; the browser holds session state.

## Why an external review API?

Amazon actively blocks server-side scraping of `amazon.com` from cloud IPs
(captcha redirect, sign-in wall). A direct `urllib` fetch from Lambda
returns a ~5 KB anti-bot stub — no reviews. Routing through a managed
scraping API (RapidAPI's *Real-Time Amazon Data*) gets us clean, parsed
review JSON with no HTML scraping or CAPTCHA handling on our side.
