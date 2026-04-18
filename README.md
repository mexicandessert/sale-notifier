# Sale Notification Bot

A GitHub Actions-powered sale monitor that scrapes 31 menswear brands daily, filters results by your sizes, and sends a consolidated Telegram notification when **new** qualifying sales are detected.

---

## How it works

```
Daily cron (3 PM UTC)
        │
        ▼
Run all 31 brand scrapers  ──────────────────────────────────────┐
        │                                                         │
        ▼                                                    18 Shopify brands
Diff against state.json                                   (JSON API — fast, reliable)
(new sale = brand was NOT on sale last run)                       │
        │                                                    13 custom scrapers
        ▼                                                   (HTML / embedded JSON)
Filter: site-wide sale OR ≥25% off
        │
        ▼
Check your sizes are in stock
        │
        ▼
Send single Telegram message  →  save updated state.json  →  git commit
```

---

## Setup (one-time, ~10 minutes)

### 1 — Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to choose a name and username
3. BotFather gives you an **API token** — save it (looks like `123456:ABC-DEF...`)
4. Start a chat with your new bot (search for it, press Start)
5. Get your **chat ID**:
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   - Send any message to your bot, then refresh
   - Find `"chat":{"id":XXXXXXX}` — that number is your chat ID

### 2 — Fork or create the GitHub repo

Push this entire directory to a new GitHub repository (public or private).

```bash
git init
git add .
git commit -m "Initial commit"
gh repo create sale-notification-bot --private --source=. --push
```

### 3 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name           | Value                               |
|-----------------------|-------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | Your bot token from BotFather       |
| `TELEGRAM_CHAT_ID`    | Your chat ID (the number from step 1) |

### 4 — Enable the Action

Go to **Actions** → you should see "Sale Monitor". GitHub may ask you to enable workflows — click the green button.

### 5 — Test it immediately

Go to **Actions → Sale Monitor → Run workflow**, select `force_notify: true`, and click **Run workflow**. Within a few minutes you'll get a Telegram message (even if no sales are active, it will show current sale status).

---

## Manual trigger

You can trigger a run anytime from the GitHub UI or CLI:

```bash
# Send notification only if new sales are detected
gh workflow run sale-monitor.yml

# Force a notification regardless
gh workflow run sale-monitor.yml -f force_notify=true
```

---

## Customise your sizes

Edit [config.py](config.py):

```python
USER_SIZES = {
    "tops": ["L", "XL"],                     # Add/remove as needed
    "bottoms_inch": {
        "waist": [34, 35],
        "inseam_min": 32.5,
        "inseam_ideal_min": 33,              # Flag as "long" at this inseam
    },
    "bottoms_alpha": ["L"],
    "shoes_us": [12],
    "shoes_eu": [45, 46],
}

SALE_THRESHOLD_PCT = 25                      # Min % to report (non-site-wide)
```

---

## Change the schedule

Edit [.github/workflows/sale-monitor.yml](.github/workflows/sale-monitor.yml):

```yaml
schedule:
  - cron: '0 15 * * *'  # 3 PM UTC daily
```

Use [crontab.guru](https://crontab.guru) to build your preferred schedule.

---

## Brands monitored (29 total)

### Shopify brands (fastest — JSON API)
| Brand | Domain | Notes |
|---|---|---|
| Todd Snyder | toddsnyder.com | |
| Buck Mason | buckmason.com | |
| Aime Leon Dore | aimeleondore.com | ⚠️ Rare sales |
| Percival | percivalclo.com | ⚠️ Rare sales |
| Wax London | waxlondon.com | |
| Spier & Mackay | spierandmackay.com | |
| Our Legacy | ourlegacy.se | |
| Merz B. Schwanen | merzbschwanen.com | ⚠️ Rare sales |
| Alex Mill | alexmill.com | |
| Noah NYC | noahny.com | ⚠️ Rare sales |
| NN07 | nn07.com | |
| Taylor Stitch | taylorstitch.com | |
| Faherty | fahertybrand.com | |
| GH Bass | ghbass.com | |
| Drake's | drakes.com | ⚠️ Rare sales |
| Filson | filson.com | |

### Custom scrapers (HTML / embedded JSON)
| Brand | Notes |
|---|---|
| Banana Republic | GAP Inc family |
| Madewell | J.Crew Group |
| J.Crew | |
| Abercrombie | |
| Polo Ralph Lauren | Includes RRL collection |
| Asics | US site |
| Lululemon | |
| Massimo Dutti | |
| Reiss | |
| Levi's | US site |
| Asket | Outlet section |
| Proper Cloth | Made-to-measure — fabric/promo discounts only |
| Huckberry | Multi-brand retailer — monitored broadly |

---

## How new sales are detected

`state.json` stores the sale status from the **previous** run. A sale triggers a notification only when:

- The brand **was not on sale** last run, AND
- The current run finds a sale with **discount ≥ 25%** OR a **site-wide** event

Once notified, you won't get a repeat alert for the same ongoing sale — only when a new one starts.

---

## Adding a new brand

**If it's a Shopify store**, add one line to `brands_config.py`:

```python
("Brand Name", "domain.com", "sale", False),
#                              ^^^^    ^^^^
#                     sale collection  low_frequency flag
```

**If it's a custom platform**, copy the closest existing scraper in `scrapers/` and adapt it. Register the new class in the `CUSTOM_SCRAPERS` list in `main.py`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No Telegram message received | Check secrets are set correctly; try `force_notify=true` manually |
| A brand always shows "error" | The site may have changed — check the URL in that scraper file |
| Workflow fails to push state.json | Ensure the repo's Actions settings allow write access (Settings → Actions → General → Workflow permissions → Read and write) |
| Selenium-related errors | The Chrome install step should handle this; check the Actions log for the Chrome version step |

---

## Local development

```bash
# Install dependencies
pip install -r requirements.txt

# Set secrets as env vars
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Run (won't send notification unless there are new sales)
python main.py

# Force a notification for testing
FORCE_NOTIFY=true python main.py
```
