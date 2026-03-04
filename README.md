# AI Sentiment Analysis — Cloud Computing Final Project

A fully serverless AWS application that analyzes the sentiment of customer reviews
using Amazon Comprehend and stores results in DynamoDB.

## Project Structure

```
cloud-ai-sentiment-analysis/
├── lambda/
│   └── lambda_function.py     ← Python Lambda (POST /analyze, GET /history)
├── frontend/
│   └── index.html             ← Static website (S3-hosted)
├── docs/
│   ├── aws-setup-guide.md     ← Step-by-step AWS Console setup
│   ├── api-reference.md       ← Request/response formats + test payloads
│   └── architecture-diagram.md← ASCII diagram + service table for report
└── README.md
```

## Quick Start

1. Follow **docs/aws-setup-guide.md** to deploy all AWS resources
2. Update `API_BASE` in `frontend/index.html` with your API Gateway URL
3. Upload `frontend/index.html` to S3
4. Open your S3 website URL and analyze a review

## Architecture

- **Frontend:** Amazon S3 (static website)
- **API:** Amazon API Gateway (HTTP API)
- **Backend:** AWS Lambda (Python 3.12 + boto3)
- **AI:** Amazon Comprehend (DetectSentiment)
- **Database:** Amazon DynamoDB

## API Endpoints

| Method | Path      | Description                        |
|--------|-----------|------------------------------------|
| POST   | /analyze  | Analyze sentiment of a review      |
| GET    | /history  | Get 10 most recent stored reviews  |

See **docs/api-reference.md** for full request/response details.
