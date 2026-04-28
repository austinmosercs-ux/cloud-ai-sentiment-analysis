# AWS Setup Guide — AI Sentiment Analysis Project

Follow these steps in order. Everything uses the AWS Console (no CLI required).

---

## Step 1 — Sign up for RapidAPI and grab a key

The Lambda calls RapidAPI's **Real-Time Amazon Data** API to fetch reviews.

1. Sign up at <https://rapidapi.com/> (free, no credit card required).
2. Subscribe to
   [Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data)
   — pick the **Basic / Free** tier.
3. Open any endpoint page (e.g. *Product Reviews*). Your **`x-rapidapi-key`**
   is shown in the code samples — copy it. You'll paste it into the Lambda
   in Step 4.

---

## Step 2 — Create the IAM Role for Lambda

1. Open **IAM** → **Roles** → **Create role**.
2. Choose **AWS service** → **Lambda** → Next.
3. Add the **`AWSLambdaBasicExecutionRole`** managed policy (CloudWatch
   logging).
4. Click **Next**, name the role: `LambdaSentimentRole`, then **Create role**.

### Attach the Comprehend permissions

The default `ComprehendReadOnly` managed policy does **not** include
`comprehend:BatchDetectSentiment`. Add it explicitly:

1. Open the new role → **Add permissions** → **Create inline policy**.
2. Switch to the **JSON** tab and paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": [
         "comprehend:DetectSentiment",
         "comprehend:BatchDetectSentiment"
       ],
       "Resource": "*"
     }]
   }
   ```
3. Name the policy `ComprehendSentimentAccess` and save.

---

## Step 3 — Create the Lambda Function

1. Open **Lambda** → **Create function**.
2. Choose **Author from scratch**.
3. Fill in:
   - **Function name:** `SentimentAnalysisFunction`
   - **Runtime:** `Python 3.12`
   - **Architecture:** `x86_64`
   - **Permissions:** Use existing role → `LambdaSentimentRole`
4. Click **Create function**.

### Upload the code

1. In the Lambda console, click the **Code** tab.
2. Replace the default `lambda_function.py` content with all of
   `lambda/lambda_function.py` from this repo.
3. Click **Deploy**.

---

## Step 4 — Configure the Lambda environment

1. Click the **Configuration** tab → **Environment variables** → **Edit** →
   **Add environment variable**, twice:

   | Key                     | Value                                       |
   |-------------------------|---------------------------------------------|
   | `RAPIDAPI_KEY`          | *(paste your RapidAPI key from Step 1)*    |
   | `RAPIDAPI_AMAZON_HOST`  | `real-time-amazon-data.p.rapidapi.com`      |

2. **Save**.

3. Now go to **General configuration** → **Edit**:
   - **Timeout:** `1 min` (3 RapidAPI calls in parallel can take ~15–25 s,
     plus Comprehend latency)
   - **Memory:** `256 MB` is plenty
4. **Save**.

---

## Step 5 — Create the API Gateway

1. Open **API Gateway** → **Create API**.
2. Choose **HTTP API** → **Build**.
3. Click **Add integration** → **Lambda** → select `SentimentAnalysisFunction`.
4. **API name:** `SentimentAPI`
5. Click **Next**.

### Add routes

On the **Configure routes** screen:

| Method | Path      |
|--------|-----------|
| POST   | /analyze  |

Set the integration to your Lambda function.

6. Click **Next** → **Next** → **Create**.

### Get your API URL

After creation, copy the **Invoke URL** — it looks like:
```
https://abc123xyz.execute-api.us-east-1.amazonaws.com
```

---

## Step 6 — Enable CORS on API Gateway

1. In API Gateway, click your API → **CORS**.
2. Fill in:
   - **Access-Control-Allow-Origin:** `*` (use your S3 URL in production)
   - **Access-Control-Allow-Headers:** `Content-Type`
   - **Access-Control-Allow-Methods:** `GET, POST, OPTIONS`
3. Click **Save**.

---

## Step 7 — Update the Frontend

Open `frontend/index.html` and replace:
```js
const API_BASE = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com";
```
with your actual API Gateway Invoke URL.

---

## Step 8 — Host the Frontend on S3

1. Open **S3** → **Create bucket**.
2. Fill in:
   - **Bucket name:** `sentiment-analysis-frontend-YOURNAME` (must be
     globally unique)
   - **Region:** same as your Lambda (e.g. `us-east-1`)
3. **Uncheck** *Block all public access* (required for static hosting).
4. Acknowledge the warning and create the bucket.

### Enable static website hosting

1. Click your bucket → **Properties** tab.
2. Scroll to **Static website hosting** → **Edit**.
3. Enable it, set **Index document** to `index.html`.
4. Save changes.

### Upload the file

1. Go to the **Objects** tab → **Upload** → add `index.html` → **Upload**.

### Set bucket policy (make it public)

1. Go to the **Permissions** tab → **Bucket policy** → **Edit**.
2. Paste this policy (replace `YOUR-BUCKET-NAME`):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "PublicReadGetObject",
       "Effect": "Allow",
       "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
     }]
   }
   ```
3. Click **Save changes**.

### Get your website URL

In the **Properties** tab → **Static website hosting**, copy the
**Bucket website endpoint**:
```
http://sentiment-analysis-frontend-YOURNAME.s3-website-us-east-1.amazonaws.com
```

---

## Step 9 — Test the Application

### Test Lambda directly in the console

1. Open your Lambda function → **Test** tab.
2. Create a test event with this payload:

   ```json
   {
     "routeKey": "POST /analyze",
     "body": "{\"productUrl\": \"https://www.amazon.com/dp/B0BMLD2GYD\"}"
   }
   ```

3. Expected: `statusCode: 200` with `product`, `reviews`, `stats`, and
   `timestamp` in the body. First invocation can take 20–30 s while
   RapidAPI fetches all three pages.

### Test via curl

```bash
curl -X POST https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/analyze \
  -H "Content-Type: application/json" \
  -d '{"productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"}'
```

### Test in the browser

Open the S3 website URL, paste an Amazon product link, click **Analyze
Product**. You should see:
- Headline average sentiment rating (e.g. `4.45 / 5`)
- A horizontal sentiment-breakdown bar (positive / negative / neutral / mixed)
- A 5-star rating distribution
- A table of every analyzed review with sentiment + confidence

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `500 — Server is missing RAPIDAPI_KEY or RAPIDAPI_AMAZON_HOST` | Re-check Step 4. Both env vars must be set on the Lambda. |
| `502 — RapidAPI rejected the API key` | Key is wrong, expired, or you haven't subscribed to *Real-Time Amazon Data* yet. |
| `502 — RapidAPI rate limit hit` | Free tier is 1 req/sec. Wait a few seconds and retry. If chronic, switch the Lambda to sequential pagination (one page at a time). |
| `502 — No reviews could be retrieved` (with `diagnostics`) | Look at the diagnostics array — `status: "OK"` with `review_count_in_payload: 0` means the product simply has no reviews on Amazon. |
| `504 — Review fetch timed out` | Bump the Lambda timeout above 60 s, or check that RapidAPI is up. |
| `AccessDeniedException` from Comprehend | Step 2 inline policy is missing `comprehend:BatchDetectSentiment`. |
| CORS error in browser | Make sure Step 6 CORS is saved. API Gateway HTTP APIs apply CORS immediately — no redeploy needed. |
| Frontend shows old API URL | Hard-refresh the browser (Cmd+Shift+R) after re-uploading `index.html`. |
| 0 reviews from a busy product | RapidAPI's `TOP_REVIEWS` paginator can return duplicate sets across pages — this caps unique reviews below 25 for some products. |
