# AWS Setup Guide — AI Sentiment Analysis Project

Follow these steps in order. Everything uses the AWS Console (no CLI required).

---

## Step 1 — Create the IAM Role for Lambda

1. Open **IAM** → **Roles** → **Create role**.
2. Choose **AWS service** → **Lambda** → Next.
3. Add these managed policies:
   - `AWSLambdaBasicExecutionRole` (CloudWatch logging)
   - `ComprehendReadOnly` (DetectSentiment)

4. Name the role: `LambdaSentimentRole`
5. Click **Create role**.

---

## Step 2 — Create the Lambda Function

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
2. Click **Upload from** → **.zip file** OR paste the code directly in the inline editor.
   - If pasting: delete the existing `lambda_function.py` content and paste all of `lambda/lambda_function.py`.
3. Click **Deploy**.

### Configure the environment

1. Click the **Configuration** tab → **General configuration** → **Edit**.
2. Set **Timeout** to `30 seconds` (Comprehend API can take a moment).
3. Click **Save**.

---

## Step 3 — Create the API Gateway

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

## Step 4 — Enable CORS on API Gateway

1. In API Gateway, click your API → **CORS**.
2. Fill in:
   - **Access-Control-Allow-Origin:** `*`  (use your S3 URL in production)
   - **Access-Control-Allow-Headers:** `Content-Type`
   - **Access-Control-Allow-Methods:** `GET, POST, OPTIONS`
3. Click **Save**.

---

## Step 5 — Update the Frontend

Open `frontend/index.html` and replace:
```js
const API_BASE = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com";
```
with your actual API Gateway Invoke URL.

Then paste an Amazon product link into the page when testing. The app now analyzes extracted review comments from the product page rather than pasted review text.

---

## Step 7 — Host the Frontend on S3

1. Open **S3** → **Create bucket**.
2. Fill in:
   - **Bucket name:** `sentiment-analysis-frontend-YOURNAME` (must be globally unique)
   - **Region:** same as your Lambda (e.g. `us-east-1`)
3. **Uncheck** "Block all public access" (required for static hosting).
4. Acknowledge the warning and create the bucket.

### Enable static website hosting

1. Click your bucket → **Properties** tab.
2. Scroll to **Static website hosting** → **Edit**.
3. Enable it, set **Index document** to `index.html`.
4. Save changes.

### Upload the file

1. Go to the **Objects** tab → **Upload** → add `index.html` → Upload.

### Set bucket policy (make it public)

1. Go to the **Permissions** tab → **Bucket policy** → **Edit**.
2. Paste this policy (replace `YOUR-BUCKET-NAME`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

3. Click **Save changes**.

### Get your website URL

In the **Properties** tab → **Static website hosting**, copy the **Bucket website endpoint**.
It will look like:
```
http://sentiment-analysis-frontend-YOURNAME.s3-website-us-east-1.amazonaws.com
```

---

## Step 6 — Test the Application

### Test Lambda directly in the console

1. Open your Lambda function → **Test** tab.
2. Create a test event with this payload:

**Test: POST /analyze**
```json
{
  "routeKey": "POST /analyze",
  "body": "{\"productUrl\": \"https://www.amazon.com/dp/B0BMLD2GYD\"}"
}
```

Expected response:
```json
{
  "statusCode": 200,
  "body": "{\"product\": {\"title\": \"...\", \"asin\": \"B0BMLD2GYD\"}, \"reviews\": [...], \"stats\": {...}, \"timestamp\": \"...\"}"
}
```

### Test via curl

```bash
# Analyze a review
curl -X POST https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/analyze \
  -H "Content-Type: application/json" \
  -d '{"productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"}'
```

---

## Troubleshooting

| Problem | Fix |
|--------|-----|
| Lambda returns 500 | Check CloudWatch Logs (Lambda → Monitor → View CloudWatch Logs) |
| CORS error in browser | Make sure API Gateway CORS is saved and re-deployed |
| "AccessDeniedException" from Comprehend | Check the IAM role has `ComprehendReadOnly` |
| Frontend shows old API URL | Hard-refresh the browser (Cmd+Shift+R) after re-uploading to S3 |
