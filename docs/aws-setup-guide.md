# AWS Setup Guide — AI Sentiment Analysis Project

This guide walks through deploying the app to a single **Amazon EC2**
instance (Amazon Linux 2023, t2.micro) running **nginx + gunicorn + Flask**.

---

## Step 1 — Sign up for RapidAPI and grab a key

The Flask app calls RapidAPI's **Real-Time Amazon Data** API to fetch reviews.

1. Sign up at <https://rapidapi.com/> (free, no credit card required).
2. Subscribe to
   [Real-Time Amazon Data](https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data)
   on the **Basic / Free** tier.
3. From the API page, copy the **`x-rapidapi-key`** value shown in the code
   samples. You'll paste it onto the EC2 box in Step 5.

---

## Step 2 — Create the IAM Role for the EC2 instance

The EC2 instance needs to call Comprehend. Use an instance profile so no
static AWS keys live on disk.

1. Open **IAM** → **Roles** → **Create role**.
2. **Trusted entity:** AWS service → **EC2** → Next.
3. Click **Create policy** (in a new tab) and use the **JSON** editor:
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
   Name it `ComprehendSentimentAccess` and create.
4. Back on the role-creation tab, attach `ComprehendSentimentAccess`
   (refresh the policy list if needed).
5. Name the role: `EC2SentimentRole`. Create.

---

## Step 3 — Launch the EC2 instance

1. Open **EC2** → **Instances** → **Launch instances**.
2. Fill in:
   - **Name:** `sentiment-analyzer`
   - **AMI:** Amazon Linux 2023 (free tier eligible)
   - **Instance type:** `t2.micro` (free tier)
   - **Key pair:** create a new one and download the `.pem` file (you'll
     need it to SSH in).
   - **Network → Edit → Allow:**
     - SSH (port 22) — your IP only
     - HTTP (port 80) — anywhere (0.0.0.0/0)
   - **Advanced details → IAM instance profile:** `EC2SentimentRole`
3. Click **Launch instance**.
4. After it boots, copy the **Public IPv4 DNS** (e.g.
   `ec2-3-90-12-34.compute-1.amazonaws.com`).

---

## Step 4 — SSH in and install dependencies

From your local machine:

```bash
chmod 400 ~/Downloads/sentiment-analyzer.pem
ssh -i ~/Downloads/sentiment-analyzer.pem ec2-user@<public-dns>
```

Once on the box:

```bash
sudo dnf update -y
sudo dnf install -y python3.12 python3.12-pip nginx git
```

---

## Step 5 — Deploy the application code

Still on the EC2 box:

```bash
# Clone (or scp) the repo
cd /home/ec2-user
git clone <your-repo-url> sentiment    # or scp the directory up
cd sentiment

# Create a virtualenv and install dependencies
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r server/requirements.txt
```

### Configure secrets (env file)

```bash
sudo tee /etc/sentiment.env >/dev/null <<'EOF'
RAPIDAPI_KEY=PASTE_YOUR_KEY_HERE
RAPIDAPI_AMAZON_HOST=real-time-amazon-data.p.rapidapi.com
AWS_DEFAULT_REGION=us-east-1
EOF
sudo chmod 600 /etc/sentiment.env
sudo chown root:root /etc/sentiment.env
```

The systemd unit reads this file. Keeping it at `/etc/sentiment.env` (mode
`600`, owned by root) means the RapidAPI key never gets committed to git.

### Install the systemd unit

```bash
sudo cp deploy/sentiment.service /etc/systemd/system/sentiment.service
sudo systemctl daemon-reload
sudo systemctl enable --now sentiment.service
sudo systemctl status sentiment.service
```

You should see `active (running)` and gunicorn workers listening on
`127.0.0.1:8000`. Check logs with:

```bash
sudo journalctl -u sentiment.service -f
```

### Smoke-test the app directly

```bash
curl -s http://127.0.0.1:8000/healthz
# {"ok": true, "rapidapi_configured": true}

curl -s -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"productUrl": "https://www.amazon.com/dp/B0BMLD2GYD"}' | head -c 300
```

---

## Step 6 — Configure nginx

```bash
sudo cp deploy/sentiment.nginx /etc/nginx/conf.d/sentiment.conf
```

### Remove the default server block

The stock `/etc/nginx/nginx.conf` ships with its own `server { ... }` block on
port 80, which conflicts with `sentiment.conf`. You need to delete or comment
it out. **Do not** try this with a naïve `sed` like `/server {/,/}/d` — server
blocks contain nested `location { ... }` blocks, so the range stops at the
first `}` and leaves orphan directives behind.

The simplest robust approach is a brace-aware Python script:

```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.orig

sudo python3 - <<'PY'
import re, pathlib
p = pathlib.Path("/etc/nginx/nginx.conf")
src = p.read_text()
out, i, n = [], 0, len(src)
while i < n:
    m = re.search(r'(?m)^\s*server\s*\{', src[i:])
    if not m:
        out.append(src[i:]); break
    out.append(src[i:i + m.start()])
    j, depth = i + m.end(), 1
    while j < n and depth > 0:
        c = src[j]
        if c == '#':
            while j < n and src[j] != '\n': j += 1
        elif c == '{': depth += 1; j += 1
        elif c == '}': depth -= 1; j += 1
        else: j += 1
    if j < n and src[j] == '\n': j += 1
    i = j
p.write_text(''.join(out))
PY
```

Or, if you'd rather do it by hand, open `/etc/nginx/nginx.conf` with `sudo
nano` and delete the entire `server { ... }` block (the one with `listen 80
default_server;`) — making sure to remove from the opening `server {` all the
way to its matching closing `}`.

### Let nginx read the static frontend

By default `/home/ec2-user` is mode `700`, so the `nginx` worker user can't
traverse into it to read the frontend files. Add the search bit to that one
directory (private subdirectories like `~/.ssh` keep their own `700` perms,
so this doesn't expose them):

```bash
sudo chmod o+x /home/ec2-user
```

### Validate and start

```bash
sudo nginx -t                  # syntax check
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

> **SELinux:** Amazon Linux 2023 ships with SELinux enabled (though usually
> in Permissive mode). If nginx logs show `Permission denied` connecting to
> `127.0.0.1:8000`, allow nginx to proxy:
>
> ```bash
> sudo setsebool -P httpd_can_network_connect 1
> ```

---

## Step 7 — Open the site

Visit `http://<public-dns>/` in your browser. You should see the analyzer
page. Paste an Amazon product link (e.g.
`https://www.amazon.com/dp/B0BMLD2GYD`) and click **Analyze Product**.

First request takes ~20–30 s while RapidAPI fetches all three pages.

---

## Updating the code

```bash
ssh ec2-user@<public-dns>
cd /home/ec2-user/sentiment
git pull
.venv/bin/pip install -r server/requirements.txt   # if deps changed
sudo systemctl restart sentiment.service
sudo systemctl reload nginx                        # only if frontend or nginx config changed
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `502 Bad Gateway` from nginx | gunicorn isn't running. `sudo systemctl status sentiment.service`, then `sudo journalctl -u sentiment.service -n 50`. |
| `Permission denied` in nginx logs (SELinux) | `sudo setsebool -P httpd_can_network_connect 1` |
| `404 Not Found` on `/` (frontend), `stat() "/home/ec2-user/sentiment/frontend/" failed (13: Permission denied)` in `/var/log/nginx/error.log` | The `nginx` worker can't traverse `/home/ec2-user`. `sudo chmod o+x /home/ec2-user` |
| `nginx: [emerg] "location" directive is not allowed here` after editing `nginx.conf` | A previous `sed` deletion left orphan directives because it stopped at a nested `}`. Restore from `nginx.conf.orig` (or reinstall nginx) and use the Python script in Step 6 instead. |
| `/healthz` returns `{"ok": false}` | `RAPIDAPI_KEY` or `RAPIDAPI_AMAZON_HOST` missing in `/etc/sentiment.env`. Restart `sentiment.service` after editing. |
| `RapidAPI rejected the API key` | Wrong key, or you haven't subscribed to *Real-Time Amazon Data*. |
| `RapidAPI rate limit hit` | Free tier is 1 req/sec. Wait a few seconds. |
| `No reviews could be retrieved` (with `diagnostics`) | Inspect the `diagnostics` array in the JSON response — `status: "OK"` with `review_count_in_payload: 0` means the product has no reviews on Amazon. |
| `AccessDeniedException` from Comprehend | The instance profile is missing or doesn't have `comprehend:BatchDetectSentiment`. Check the role attached to the instance. |
| Browser can't reach `<public-dns>` | Security group is missing port 80, or you're using `https://` (this setup is HTTP only — add a load balancer + ACM cert for HTTPS). |
| Site loads but `Analyze` does nothing | Open devtools → Network. If you see CORS errors, you're hitting the gunicorn port directly (`:8000`); use the nginx port (`:80` / no port). |

---

## (Optional) HTTPS via Caddy

If you want HTTPS without configuring ACM + ALB, swap nginx for **Caddy** —
it auto-provisions Let's Encrypt certs:

```bash
sudo dnf install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
your-domain.example.com {
    root * /home/ec2-user/sentiment/frontend
    file_server
    reverse_proxy /analyze 127.0.0.1:8000
    reverse_proxy /healthz 127.0.0.1:8000
}
EOF
sudo systemctl enable --now caddy
```

You'll need to point a real DNS record at the EC2 instance's IP for cert
issuance to succeed.
