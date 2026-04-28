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
            └───────────────────────┘  │
                                       │  3. Route to Lambda
                        ┌──────────────▼──────────────┐
                        │     AWS Lambda              │
                        │   (Python 3.12 / boto3)     │
                        │                             │
                        │  handle_analyze()  ─────────┼──► Amazon Comprehend
                        │  returns rating + sentiment  │   (DetectSentiment API)
                        └──────────────┬──────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │   Browser session state  │
                          │   analyzed review list   │
                          │                         │
                          │  reviewId / rating      │
                          │  timestamp              │
                          │  reviewText             │
                          │  sentiment              │
                          │  scores                 │
                          └─────────────────────────┘
```

## Data Flow (numbered)

1. User opens the S3-hosted webpage in their browser
2. User pastes an Amazon product link and clicks **Analyze Product**
3. Browser sends `POST /analyze` with a product URL in the JSON body
4. API Gateway routes the request to the Lambda function
5. Lambda calls **Amazon Comprehend DetectSentiment**
6. Comprehend returns sentiment label + confidence scores
7. Lambda returns the sentiment and derived rating to API Gateway
8. API Gateway returns the result to the browser
9. Browser displays sentiment badge, score bars, and rating
10. The frontend stores analyzed reviews in memory for the current browser session

## AWS Services Used

| Service            | Role                                        |
|--------------------|---------------------------------------------|
| Amazon S3          | Static website hosting for HTML/JS frontend |
| Amazon API Gateway | HTTP API — routes POST requests             |
| AWS Lambda         | Serverless Python backend (no servers!)     |
| Amazon Comprehend  | Managed NLP — detects sentiment from text   |
| Browser session     | Temporary storage for analyzed reviews       |
| AWS IAM            | Permissions — Lambda role with least-privilege access |
| Amazon CloudWatch  | Automatic logging from Lambda               |

## Why Serverless?

- **No EC2 servers to manage** — AWS handles scaling, patching, and availability
- **Pay per use** — Lambda charges per invocation (free tier covers a student project)
- **Fully managed AI** — Comprehend is a pre-trained model; no ML expertise needed
- **High availability** — API Gateway and Lambda are automatically multi-AZ
