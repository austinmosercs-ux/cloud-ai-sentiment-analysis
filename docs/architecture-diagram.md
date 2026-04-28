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
                  │ 1. http://<ec2-public-dns>/
                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Amazon EC2 (t2.micro)                            │
│                                                                        │
│   ┌──────────────────────────┐                                         │
│   │   nginx (port 80)        │ 2. serves index.html (static)           │
│   │                          │ 3. reverse-proxy /analyze ──────────┐   │
│   └──────────────────────────┘                                     │   │
│                                                                    ▼   │
│                                                  ┌──────────────────┐  │
│                                                  │ gunicorn :8000   │  │
│                                                  │  (systemd unit)  │  │
│                                                  │                  │  │
│                                                  │  Flask: app.py   │  │
│                                                  │   /analyze       │  │
│                                                  │   /healthz       │  │
│                                                  └────────┬─────────┘  │
│                                                           │            │
│           ┌─── boto3 (uses EC2 instance profile) ─────────┤            │
│           │                                               │            │
│           │   ┌─── HTTPS ────────────────────────────────┘            │
│           │   │                                                        │
└───────────┼───┼────────────────────────────────────────────────────────┘
            │   │
            │   │ 4. /product-reviews?asin=…&page=N (×3 in parallel)
            │   ▼
            │   ┌───────────────────────┐
            │   │ RapidAPI              │
            │   │ Real-Time Amazon Data │  returns review JSON
            │   └───────────────────────┘
            │
            │ 5. BatchDetectSentiment(TextList=[…])
            ▼
            ┌───────────────────────┐
            │  Amazon Comprehend    │  per-review sentiment + confidence
            └───────────────────────┘
```

## Data flow (numbered)

1. User opens the EC2 instance's public DNS in their browser.
2. nginx serves `index.html` from `/home/ec2-user/sentiment/frontend/`.
3. User pastes an Amazon product link, clicks **Analyze Product**, browser
   sends `POST /analyze`. nginx reverse-proxies to gunicorn on
   `127.0.0.1:8000`.
4. Flask extracts the ASIN, fires **3 parallel HTTPS calls** to
   **RapidAPI Real-Time Amazon Data** (`/product-reviews?asin=…&page=N`).
   Up to 25 unique reviews are collected.
5. Flask calls **Amazon Comprehend BatchDetectSentiment** with all reviews
   in a single batch — returns sentiment label + confidence vector for each.
   AWS credentials come from the **EC2 instance profile**; no static keys
   live on the instance.
6. Flask builds per-review derived ratings and aggregate stats, returns the
   JSON response, which nginx hands back to the browser. The page renders
   the dashboard (headline rating, sentiment bar, distribution, per-review
   table).

## AWS / external services used

| Service / Provider                     | Role                                                       |
|----------------------------------------|------------------------------------------------------------|
| Amazon EC2                             | Linux VM running nginx + gunicorn + Flask                  |
| AWS IAM (instance profile)             | Grants the EC2 instance access to Comprehend; no static keys |
| Amazon Comprehend                      | Managed NLP — `BatchDetectSentiment`                       |
| Amazon CloudWatch Logs (optional)      | Forward gunicorn / nginx logs via the CloudWatch agent     |
| RapidAPI: Real-Time Amazon Data        | Third-party API that returns Amazon reviews as JSON        |
| nginx                                  | Reverse proxy + static file server, runs on the EC2 box    |
| gunicorn                               | WSGI server hosting the Flask app, runs on the EC2 box     |
| systemd                                | Auto-starts gunicorn on boot, restarts on failure          |

## Why a VM instead of Lambda?

This project intentionally uses a long-lived EC2 instance instead of a
serverless function. Tradeoffs:

| Concern                  | EC2 (this project)                          | Serverless (Lambda)                              |
|--------------------------|---------------------------------------------|--------------------------------------------------|
| Cold starts              | None — process is always warm               | ~1 s cold start on first invocation              |
| Long timeouts            | Limited only by nginx / gunicorn settings   | API Gateway HTTP API caps integration at 30 s    |
| Concurrent connections   | Multiple gunicorn workers + threads         | Each invocation is its own short-lived sandbox   |
| OS access                | Full Linux box — install whatever is needed | No filesystem persistence between invocations    |
| Patching / availability  | Manual (or via SSM Patch Manager)           | Fully managed by AWS                             |
| Idle cost                | Charged 24/7 (free tier covers t2.micro)    | Truly $0 when idle                               |

## Why an external review API?

Amazon actively blocks server-side scraping of `amazon.com` from cloud IPs
(captcha redirect, sign-in wall). A direct `urllib` fetch from the EC2
instance returns a ~5 KB anti-bot stub — no reviews. Routing through a
managed scraping API (RapidAPI's *Real-Time Amazon Data*) gets us clean,
parsed review JSON with no HTML scraping or CAPTCHA handling on our side.
