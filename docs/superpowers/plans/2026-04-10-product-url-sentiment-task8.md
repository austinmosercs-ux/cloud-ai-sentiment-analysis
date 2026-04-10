# Task 8: Replace the frontend JavaScript (companion file)

This is a companion to `2026-04-10-product-url-sentiment.md`. Complete Tasks 1–7 from that plan before starting this task, and return to Task 9 after.

**Files:**
- Modify: `frontend/index.html` (the entire `<script type="module">` block)

**Security note:** All user-supplied and API-supplied strings are routed through the existing `escapeHtml` helper before being written into the DOM. Markup templates built from aggregated data are static shapes with escaped interpolations only. This matches the existing escaping pattern already used by the file.

- [ ] **Step 1: Replace the entire contents of the `<script type="module">` block**

Open `frontend/index.html`. Find the line `<script type="module">` and the matching `</script>` near the bottom. Delete everything between those two tags and paste in the following replacement body:

```javascript
  // CONFIG
  const API_BASE = "https://wqg809a91a.execute-api.us-east-1.amazonaws.com/";

  // DOM references
  const urlInput         = document.getElementById("productUrl");
  const analyzeBtn       = document.getElementById("analyzeBtn");
  const errorMsg         = document.getElementById("errorMsg");
  const resultCard       = document.getElementById("result");
  const productTitleEl   = document.getElementById("productTitle");
  const badge            = document.getElementById("sentimentBadge");
  const reviewCountLabel = document.getElementById("reviewCountLabel");
  const scoresContainer  = document.getElementById("scoresContainer");
  const topPositiveList  = document.getElementById("topPositiveList");
  const topNegativeList  = document.getElementById("topNegativeList");

  analyzeBtn.addEventListener("click", analyzeProduct);
  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeProduct();
  });

  // URL validation
  const URL_HINT = /(amazon\.|walmart\.com)/i;

  function isLikelySupportedUrl(value) {
    return URL_HINT.test(value);
  }

  // Analyze
  async function analyzeProduct() {
    const url = urlInput.value.trim();
    errorMsg.textContent = "";

    if (!url) {
      errorMsg.textContent = "Please paste a product URL.";
      return;
    }
    if (!isLikelySupportedUrl(url)) {
      errorMsg.textContent = "Only Amazon and Walmart product links are supported.";
      return;
    }

    analyzeBtn.disabled = true;
    setButtonPhase("Fetching reviews…");

    try {
      const phaseTimer = setTimeout(() => setButtonPhase("Analyzing sentiment…"), 2500);

      const res = await fetch(`${API_BASE}/analyze`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ url }),
      });
      clearTimeout(phaseTimer);

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      renderResult(data);
      loadHistory();
    } catch (err) {
      errorMsg.textContent = `Error: ${err.message}`;
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze Reviews";
    }
  }

  function setButtonPhase(label) {
    // Rebuild via DOM nodes so the spinner can be styled without interpolating user data.
    analyzeBtn.replaceChildren();
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    analyzeBtn.appendChild(spinner);
    analyzeBtn.appendChild(document.createTextNode(label));
  }

  // Render result
  function renderResult(data) {
    productTitleEl.textContent = data.productTitle || "Result";

    if (data.reviewCount === 0) {
      badge.textContent = "—";
      badge.className = "sentiment-badge";
      reviewCountLabel.textContent = data.message || "This product has no reviews yet.";
      scoresContainer.replaceChildren();
      topPositiveList.replaceChildren();
      topNegativeList.replaceChildren();
      resultCard.style.display = "block";
      resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }

    badge.textContent = data.overallSentiment;
    badge.className = `sentiment-badge badge-${data.overallSentiment}`;
    reviewCountLabel.textContent = `based on ${data.reviewCount} reviews`;

    renderScoreBars(data.aggregateScores);
    renderSampleList(topPositiveList, data.topPositive, "positive-item");
    renderSampleList(topNegativeList, data.topNegative, "negative-item");

    resultCard.style.display = "block";
    resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderScoreBars(scores) {
    scoresContainer.replaceChildren();
    const order = ["positive", "negative", "neutral", "mixed"];
    for (const key of order) {
      const pct = (scores[key] * 100).toFixed(1);

      const row = document.createElement("div");
      row.className = "score-row";

      const label = document.createElement("span");
      label.className = "score-label";
      label.textContent = key;

      const bg = document.createElement("div");
      bg.className = "bar-bg";
      const fill = document.createElement("div");
      fill.className = `bar-fill bar-${key.toUpperCase()}`;
      fill.style.width = `${pct}%`;
      bg.appendChild(fill);

      const pctEl = document.createElement("span");
      pctEl.className = "score-pct";
      pctEl.textContent = `${pct}%`;

      row.appendChild(label);
      row.appendChild(bg);
      row.appendChild(pctEl);
      scoresContainer.appendChild(row);
    }
  }

  function renderSampleList(listEl, samples, cssClass) {
    listEl.replaceChildren();
    if (!samples || samples.length === 0) {
      const li = document.createElement("li");
      li.textContent = "No samples available.";
      listEl.appendChild(li);
      return;
    }
    for (const s of samples) {
      const li = document.createElement("li");
      li.className = cssClass;

      const truncated = s.text.length > 300 ? s.text.slice(0, 300) + "…" : s.text;
      li.appendChild(document.createTextNode(truncated));

      const scoreSpan = document.createElement("span");
      scoreSpan.className = "sample-score";
      scoreSpan.textContent = `confidence ${(s.score * 100).toFixed(0)}%`;
      li.appendChild(scoreSpan);

      listEl.appendChild(li);
    }
  }

  // History
  async function loadHistory() {
    const historyCard = document.getElementById("history");
    const tbody       = document.getElementById("historyBody");

    try {
      const res  = await fetch(`${API_BASE}/history`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

      tbody.replaceChildren();
      const analyses = data.analyses || [];

      if (analyses.length === 0) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 5;
        td.style.textAlign = "center";
        td.style.color = "#a0aec0";
        td.style.padding = "1rem";
        td.textContent = "No analyses yet.";
        tr.appendChild(td);
        tbody.appendChild(tr);
      } else {
        for (const a of analyses) {
          tbody.appendChild(buildHistoryRow(a));
        }
      }

      historyCard.style.display = "block";
    } catch (err) {
      console.error("History load failed:", err.message);
    }
  }

  function buildHistoryRow(a) {
    const tr = document.createElement("tr");

    const productCell = document.createElement("td");
    productCell.className = "review-cell";
    const link = document.createElement("a");
    link.href = a.productUrl || "#";
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = a.productTitle || "(untitled)";
    productCell.title = a.productTitle || "";
    productCell.appendChild(link);
    tr.appendChild(productCell);

    const siteCell = document.createElement("td");
    siteCell.textContent = (a.site || "").toUpperCase();
    tr.appendChild(siteCell);

    const sentimentCell = document.createElement("td");
    const sentBadge = document.createElement("span");
    sentBadge.className = `sentiment-badge badge-${a.overallSentiment}`;
    sentBadge.style.fontSize = ".75rem";
    sentBadge.style.padding = ".2rem .6rem";
    sentBadge.textContent = a.overallSentiment || "—";
    sentimentCell.appendChild(sentBadge);
    tr.appendChild(sentimentCell);

    const countCell = document.createElement("td");
    countCell.textContent = String(a.reviewCount || 0);
    tr.appendChild(countCell);

    const timeCell = document.createElement("td");
    timeCell.textContent = a.timestamp ? new Date(a.timestamp).toLocaleString() : "";
    tr.appendChild(timeCell);

    return tr;
  }

  await loadHistory();
```

Notes on the rewrite:

- All DOM is built with `document.createElement` and `textContent`, not string templates. This avoids any XSS risk from API-supplied product titles or review text, and it makes the security linter happy.
- `replaceChildren()` clears a node before refilling it — equivalent to the old pattern of reassigning the children, but without any string templating.
- The spinner is rebuilt as a child `<span>` plus a text node in `setButtonPhase`, because the old `innerHTML` version was mixing a styled element with dynamic label text.

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): rewrite JS for URL flow, verdict rendering, and sample reviews"
```

After committing, return to Task 9 in the main plan.
