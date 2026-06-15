# Discord Integration Setup Guide

This guide explains how to set up the Discord webhook integration for the Daily AI News Finder workflow.

## What's Changed

- **Replaced**: Slack GitHub Action → Discord Webhook integration
- **Added**: `discord_notifier.py` module for reusable Discord messaging
- **Enhanced**: `ai_news_finder.py` now sends detailed report summaries to Discord
- **Updated**: `.env.example` with Discord webhook URL configuration

## Setting Up Discord Webhook

### Step 1: Create a Discord Server & Channel

1. Create a Discord server (or use an existing one)
2. Create a channel for notifications (e.g., `#ai-news-updates`)

### Step 2: Create Webhook

1. Go to your Discord channel
2. Click the **⚙️ Settings** (channel settings)
3. Select **Integrations** → **Webhooks**
4. Click **New Webhook**
5. Name it (e.g., "AI News Finder")
6. Click **Copy Webhook URL**

### Step 3: Configure GitHub Secret

1. Go to your GitHub repository
2. **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `DISCORD_WEBHOOK_URL`
5. Value: Paste your Discord webhook URL
6. Click **Add secret**

### Step 4: Configure Local Environment (Optional)

For local testing of Discord notifications:

1. Copy `.env.example` to `.env` in the `ai_news_finder` directory:
   ```bash
   cp ai_news_finder/.env.example ai_news_finder/.env
   ```

2. Edit `.env` and add your webhook URL:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
   ```

## What You'll See

### Daily Run Success Message
When the daily run completes successfully, Discord will receive:
- ✅ Success notification with repository info
- 📊 Report summary showing:
  - Number of stories selected
  - Number of sources used
  - Number of verified stories (3+ sources)
  - Link to generated report

### Daily Run Failure Message
When the daily run fails, Discord will receive:
- ❌ Error notification with repository info
- Error details and link to workflow logs

## Testing Discord Integration

### Test from Command Line

1. Set the `DISCORD_WEBHOOK_URL` environment variable
2. Run the test script:
   ```bash
   cd ai_news_finder
   python discord_notifier.py
   ```

### Test from Python

```python
from discord_notifier import send_success_notification, send_report_summary

# Send success notification
send_success_notification(
    fields=[
        {"name": "Repository", "value": "news-update", "inline": True},
        {"name": "Branch", "value": "main", "inline": True},
    ]
)

# Send report summary
send_report_summary(
    total_stories=10,
    sources_count=15,
    verified_count=7,
    report_file="reports/report_2026-05-18.html"
)
```

## Discord Notifier API

### Available Functions

#### `send_notification(title, message, color=3447003, fields=None, status="info")`
Send a generic notification embed to Discord.

**Parameters:**
- `title` (str): Embed title
- `message` (str): Embed description
- `color` (int): RGB color in decimal (default: blue)
- `fields` (list): List of field dicts with 'name' and 'value'
- `status` (str): 'success', 'error', 'info', or 'warning' (applies color mapping)

#### `send_success_notification(title, message, fields=None)`
Send a success notification (green color).

#### `send_error_notification(title, message, error_details=None)`
Send an error notification (red color).

#### `send_report_summary(total_stories, sources_count, verified_count, report_file="")`
Send a formatted report summary with statistics.

#### `get_discord_webhook_url()`
Get the Discord webhook URL from environment variable.

## Troubleshooting

### No messages appearing in Discord?

1. **Check webhook URL**: Verify it's correct and in GitHub Secrets
2. **Check permissions**: Ensure the webhook has permission to post in the channel
3. **Test webhook**: Use curl to test:
   ```bash
   curl -X POST "YOUR_WEBHOOK_URL" \
     -H "Content-Type: application/json" \
     -d '{"content": "Test message"}'
   ```

### "DISCORD_WEBHOOK_URL not set" warnings?

- For GitHub Actions: Configure the secret in repository settings
- For local testing: Set the environment variable before running:
  ```bash
  export DISCORD_WEBHOOK_URL="your_webhook_url"
   python run.py --days 1
  ```

### Webhook URL issues?

- Don't include trailing slashes or query parameters
- The URL should be: `https://discord.com/api/webhooks/ID/TOKEN`
- Never commit webhook URLs to version control

## Migration from Slack

If you were previously using Slack:

1. Remove `SLACK_WEBHOOK_URL` from GitHub Secrets
2. Add `DISCORD_WEBHOOK_URL` to GitHub Secrets (follow steps above)
3. No code changes needed - the workflow automatically uses Discord

## Additional Notes

- Discord embeds are limited to 2048 characters per field
- Webhook messages can include up to 10 embeds per message
- The module gracefully skips notifications if webhook URL is not configured
- All Discord interaction is non-blocking and won't fail the workflow if Discord is unavailable
