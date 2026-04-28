# AI Sentiment Analysis — Cloud Computing Final Project

A cloud-deployed web application that pulls customer reviews from an Amazon
product page, scores each one with **Amazon Comprehend**, and presents a
sentiment dashboard with per-review ratings, an overall sentiment breakdown,
and a star-rating distribution.

Hosted on a single **Amazon EC2** instance running **nginx + gunicorn**:
nginx serves the static frontend and reverse-proxies the `/analyze` API to a
Flask app. AWS credentials come from the EC2 instance profile (no static
keys on disk).

## What it does

1. User pastes an Amazon product link into the page.
2. The frontend POSTs the URL to `/analyze` (same origin).
3. The Flask app extracts the ASIN, fetches up to **25 reviews** via the
   **RapidAPI Real-Time Amazon Data** API (3 paginated pages, in parallel).
4. The app hands all reviews to **Amazon Comprehend BatchDetectSentiment**
   in a single batched call (returns POSITIVE / NEGATIVE / NEUTRAL / MIXED
   plus a confidence breakdown for each review).
5. Each review is converted to a derived 1–5 rating, then aggregated:
   average / median / std-dev rating, sentiment counts and percentages, and
   a 5-star distribution.
6. The frontend renders the analysis in a dashboard card.

## Project structure

```
cloud-ai-sentiment-analysis/
├── server/
│   ├── app.py                 ← Flask app (POST /analyze, GET /healthz)
│   └── requirements.txt
├── frontend/
│   └── index.html             ← Static page served by nginx
├── deploy/
│   ├── sentiment.service      ← systemd unit (gunicorn)
│   └── sentiment.nginx        ← nginx server block
├── docs/
│   ├── aws-setup-guide.md     ← EC2 + RapidAPI setup, step-by-step
│   ├── api-reference.md       ← Request / response schema
│   └── architecture-diagram.md← ASCII diagram + service table for the report
├── README.md
└── .gitignore
```

## Quick start

1. **Sign up for RapidAPI** and subscribe (free tier) to
   [Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data).
   Copy your API key.
2. Follow [docs/aws-setup-guide.md](docs/aws-setup-guide.md) to launch an EC2
   instance with the right IAM role + security group, install nginx +
   Python, deploy the code, and set up the systemd unit.
3. Open the EC2 instance's public DNS and paste an Amazon product link
   (e.g. `https://www.amazon.com/dp/B0BMLD2GYD`).

## Architecture

- **Compute:** Amazon EC2 (t2.micro, Amazon Linux 2023)
- **Web tier:** nginx — serves `frontend/index.html`, reverse-proxies
  `/analyze` and `/healthz` to gunicorn
- **App tier:** gunicorn + Flask (`server/app.py`), managed by systemd
- **AI:** Amazon Comprehend (`BatchDetectSentiment`)
- **Reviews source:** RapidAPI — Real-Time Amazon Data (`/product-reviews`)
- **Auth:** EC2 instance profile (IAM role attached to the instance)
- **Storage:** none — browser session only

## API endpoints

| Method | Path       | Description                                                |
|--------|------------|------------------------------------------------------------|
| POST   | /analyze   | Pull reviews for an Amazon product, return sentiment stats |
| GET    | /healthz   | Liveness check (200 if RapidAPI env vars are configured)   |

See [docs/api-reference.md](docs/api-reference.md) for the full schema.

## Cost notes

- **EC2 t2.micro:** free tier covers 750 hours/month for 12 months — one
  instance running 24/7 stays inside the free tier.
- **Comprehend:** the AWS free tier covers 50K units/month for the first
  12 months; one batch of 25 reviews ≈ 25 units.
- **RapidAPI Real-Time Amazon Data:** free tier is typically 100 requests /
  month with a 1 req/sec rate limit. Each analysis = 3 requests
  (one per review page), so ~33 analyses/month on the free tier.
- **Data transfer:** 1 GB/month free; this app's responses are tiny.

## Local development

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export RAPIDAPI_KEY=your_key
export RAPIDAPI_AMAZON_HOST=real-time-amazon-data.p.rapidapi.com
export AWS_REGION=us-east-1
export AWS_PROFILE=your_aws_cli_profile   # or use env vars
python app.py                              # serves on http://localhost:8000
```

Then open `frontend/index.html` directly (CORS headers are sent), or run
nginx locally pointing at the `frontend/` directory.
