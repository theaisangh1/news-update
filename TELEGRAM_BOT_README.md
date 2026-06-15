# Telegram AI News Bot

A Telegram bot for interacting with AI news and generating content using Qwen on Kaggle.

## Architecture

```
GitHub Actions (existing)
    ↓
News Collector (already exists)
    ↓
Store Top News (reports/*.json)
    ↓
Telegram Bot (telegram_bot/bot.py)
    ↓
Request Queue (request_queue.json)
    ↓
Kaggle Notebook (Qwen)
    ↓
Telegram Response
```

## Components

### 1. Telegram Bot (`telegram_bot/`)

Commands:
- `/news` - Display latest top 5 AI news stories
- `/status` - Check if Qwen/Kaggle is online
- `/help` - Show available commands

After selecting a news item, use:
- `generate` - Create initial script
- `shorter` - Make shorter
- `longer` - Expand content
- `more viral` - Make more engaging
- `carousel` - Create carousel format
- `caption` - Generate social caption
- `30 second reel` - Short reel script
- `60 second reel` - Medium reel script

### 2. Queue System (`telegram_bot/queue_manager.py`)

JSON-based request queue storing:
- Request ID
- Article details
- Request type
- Status (pending/processing/completed/failed)
- Result

### 3. Kaggle Processor (`kaggle_processor/`)

Processes requests using Qwen model:
- Polls queue every N seconds
- Generates content using Qwen 14B/32B
- Maintains context memory per article
- Sends results to Telegram

## Setup Instructions

### 1. Create Telegram Bot

1. Open Telegram and message @BotFather
2. Send `/newbot` and follow prompts
3. Save the bot token
4. Get your chat ID by messaging @userinfobot

### 2. Configure Environment Variables

#### For Telegram Bot (GitHub Actions or local):

```bash
cd telegram_bot
cp .env.example .env
# Edit .env with your values:
# TELEGRAM_BOT_TOKEN=your_bot_token
# TELEGRAM_CHAT_ID=your_chat_id
```

#### For Kaggle:

Use Kaggle Secrets to store:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 3. Deploy Telegram Bot

#### Option A: Run Locally

```bash
cd telegram_bot
pip install -r requirements.txt
python bot.py
```

#### Option B: Deploy to GitHub Actions

Add to `.github/workflows/daily-run.yml` or create new workflow:

```yaml
  run-telegram-bot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r telegram_bot/requirements.txt
      - run: python telegram_bot/bot.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

### 4. Setup Kaggle Processor

1. Upload `kaggle_processor/kaggle_notebook.py` to Kaggle
2. Create a new Kaggle notebook
3. Add the script as a cell
4. Configure Kaggle Secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Upload `request_queue.json` or mount Google Drive
6. Set GPU runtime (T4 or better)
7. Run the notebook

### 5. Share Queue Between Components

#### Option A: GitHub Repository (Recommended)

The queue file `request_queue.json` is stored in the git repository. Both components read/write to it.

**Note:** This requires careful handling of concurrent writes. For production, consider using a database or cloud storage.

#### Option B: Google Drive

1. Mount Google Drive in Kaggle
2. Update `QUEUE_FILE` path in both configs
3. Use rclone or API to sync from GitHub Actions

#### Option C: Cloud Database (Advanced)

For production, consider:
- Firebase Realtime Database
- Supabase
- MongoDB Atlas

## Local Testing

### Test Telegram Bot

```bash
cd telegram_bot
pip install -r requirements.txt
cp .env.example .env
# Add your test bot token to .env
python bot.py
```

### Test Queue Manager

```python
from queue_manager import queue_manager

# Add a test request
request = queue_manager.add_request(
    article_id="test_123",
    article_title="Test Article",
    request_type="generate",
    user_message="generate",
    chat_id="123456789"
)
print(f"Created request: {request['id']}")

# Get pending requests
pending = queue_manager.get_pending_requests()
print(f"Pending: {len(pending)}")

# Mark as completed
queue_manager.mark_completed(request["id"], "Test script content")
```

### Test News Manager

```python
from news_manager import news_manager

# Get latest news
news = news_manager.get_latest_news(limit=5)
print(f"Found {len(news)} articles")

# Format for Telegram
formatted = news_manager.format_news_for_telegram(news)
print(formatted)
```

## File Structure

```
news-update/
├── ai_news_finder/          # Existing news collector
├── telegram_bot/
│   ├── bot.py              # Main Telegram bot
│   ├── news_manager.py     # News data handler
│   ├── queue_manager.py    # Request queue
│   ├── requirements.txt    # Dependencies
│   └── .env.example        # Config template
├── kaggle_processor/
│   ├── processor.py        # Qwen processor class
│   ├── kaggle_notebook.py  # Self-contained notebook
│   ├── requirements.txt    # Dependencies
│   └── .env.example        # Config template
├── reports/                # News JSON reports
└── request_queue.json      # Shared queue file
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | Required |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | Required |
| `QUEUE_FILE` | Path to request queue JSON | `request_queue.json` |
| `QWEN_MODEL` | Qwen model name | `Qwen/Qwen2.5-14B-Instruct` |
| `POLL_INTERVAL` | Queue poll interval (seconds) | `30` |
| `REPORTS_DIR` | Path to reports directory | `../reports` |

## Cost Optimization

- Kaggle sessions: 1-2 per day
- Model: Qwen 14B (good balance of quality/cost)
- Queue: Process all pending requests per session
- Context memory: Keep last 10 messages per article

## Troubleshooting

### Bot not responding

1. Check bot token is correct
2. Verify bot is started with `/start`
3. Check bot is not blocked

### Queue not processing

1. Verify `request_queue.json` exists
2. Check Kaggle session is running
3. Verify Telegram credentials in Kaggle Secrets

### Qwen not loading

1. Check GPU runtime is selected
2. Verify internet access in Kaggle
3. Check model name is correct

## License

Same as parent project.
