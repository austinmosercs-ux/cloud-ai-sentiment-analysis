# Architecture Diagram (Text/ASCII)

Use this as the basis for a diagram in your report (draw.io, Lucidchart, or PowerPoint).

```
┌─────────────────────────────────────────────────────────────────┐
│                          User Browser                           │
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │              index.html (JavaScript + fetch)             │  │
│   └───────────────────┬──────────────────────────────────────┘  │
└───────────────────────┼─────────────────────────────────────────┘
                        │  1. User loads page
                        │
            ┌───────────▼───────────┐
            │     Amazon S3         │
            │  (Static Website      │
            │   Hosting)            │
            └───────────┬───────────┘
                        │  2. HTML/JS served to browser
                        │
            ┌───────────▼───────────┐
            │    API Gateway        │
            │   (HTTP API)          │
            │                       │
            │  POST /analyze   ─────┼──┐
            │  GET  /history   ─────┼──┤
            └───────────────────────┘  │
                                       │  3. Route to Lambda
                        ┌──────────────▼──────────────┐
                        │     AWS Lambda              │
                        │   (Python 3.12 / boto3)     │
                        │                             │
                        │  handle_analyze()  ─────────┼──► Amazon Comprehend
                        │  handle_history()           │   (DetectSentiment API)
                        └──────────────┬──────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │       DynamoDB          │
                          │   SentimentReviews      │
                          │                         │
                          │  reviewId (PK)          │
                          │  timestamp              │
                          │  reviewText             │
                          │  sentiment              │
                          │  scores (Map)           │
                          └─────────────────────────┘
```

## Data Flow (numbered)

1. User opens the S3-hosted webpage in their browser
2. User pastes a review and clicks **Analyze Sentiment**
3. Browser sends `POST /analyze` with JSON body to API Gateway
4. API Gateway routes the request to the Lambda function
5. Lambda calls **Amazon Comprehend DetectSentiment**
6. Comprehend returns sentiment label + confidence scores
7. Lambda writes the result to **DynamoDB**
8. Lambda returns the result to API Gateway → browser
9. Browser displays sentiment badge and score bars
10. Separately, `GET /history` fetches recent reviews from DynamoDB

## AWS Services Used

| Service            | Role                                        |
|--------------------|---------------------------------------------|
| Amazon S3          | Static website hosting for HTML/JS frontend |
| Amazon API Gateway | HTTP API — routes POST and GET requests     |
| AWS Lambda         | Serverless Python backend (no servers!)     |
| Amazon Comprehend  | Managed NLP — detects sentiment from text   |
| Amazon DynamoDB    | NoSQL database — stores analyzed reviews    |
| AWS IAM            | Permissions — Lambda role with least-privilege access |
| Amazon CloudWatch  | Automatic logging from Lambda               |

## Why Serverless?

- **No EC2 servers to manage** — AWS handles scaling, patching, and availability
- **Pay per use** — Lambda charges per invocation (free tier covers a student project)
- **Fully managed AI** — Comprehend is a pre-trained model; no ML expertise needed
- **High availability** — API Gateway and Lambda are automatically multi-AZ
