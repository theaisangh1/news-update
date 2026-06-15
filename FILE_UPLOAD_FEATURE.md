# 📄 Discord File Upload Feature - Added

## What's New

The `.txt` report file generated in the `reports/` folder is now automatically sent to Discord after each successful run!

## How It Works

1. **Script Runs**: AI News Finder collects and processes stories
2. **Report Generated**: `report_YYYY-MM-DD.txt` created in `reports/` folder
3. **Discord Notification**: Report summary sent with stats
4. **File Uploaded**: The `.txt` file is uploaded to Discord as an attachment

## In Discord, You'll See

**Message:**
```
📄 Daily AI News Report - 2026-05-18

10 stories selected from 15 sources
```

**Plus:** The actual `.txt` file as a downloadable attachment in Discord

Users can then:
- View the file directly in Discord
- Download it for offline reading
- Share it with team members

## Changes Made

### 1. Enhanced `discord_notifier.py`
Added new function:
```python
send_report_file(file_path, file_description)
```

This function:
- Reads the `.txt` file from the reports folder
- Uploads it to Discord as a file attachment
- Includes a description message
- Handles errors gracefully

### 2. Updated `ai_news_finder.py`
After generating the report, the script now:
1. Sends the summary notification (stats embed)
2. Uploads the `.txt` file to Discord

## Discord Features

- ✅ File appears as downloadable attachment in Discord
- ✅ Message description shows story count and source count
- ✅ File name includes date (e.g., `report_2026-05-18.txt`)
- ✅ Works with Discord's file preview
- ✅ Graceful error handling if file not found

## Testing Locally

```python
from discord_notifier import send_report_file

send_report_file(
    "reports/report_2026-05-18.txt",
    "📄 Daily AI News Report - 2026-05-18\n\n10 stories selected"
)
```

Set `DISCORD_WEBHOOK_URL` environment variable first:
```bash
export DISCORD_WEBHOOK_URL="your_webhook_url"
python -c "from discord_notifier import send_report_file; send_report_file('path/to/report.txt', 'Test')"
```

## File Size Limits

Discord webhook file uploads have a size limit:
- Free tier: 8 MB per file
- Nitro: 100 MB per file

The `.txt` reports are typically very small (<1 MB) so no issues expected.

## What Gets Sent

Every successful run now sends:

1. **✅ Success Notification** (green embed)
   - Title: "Daily AI News Run Completed"
   - Stats: Stories, Sources, Verified count

2. **📄 Report File**
   - Filename: `report_YYYY-MM-DD.txt`
   - Content: Full report with all stories and details
   - Description: Story count and source count

## Error Handling

If the file:
- **Doesn't exist**: Logged as error, doesn't fail the workflow
- **Is unreadable**: Logged as error, doesn't fail the workflow
- **Upload fails**: Logged as error, doesn't fail the workflow

The workflow completes successfully either way - Discord notifications are non-blocking.

## Next Steps

1. Push the changes to GitHub:
   ```bash
   git add ai_news_finder/discord_notifier.py ai_news_finder/ai_news_finder.py
   git commit -m "Add: Send .txt report file to Discord"
   git push
   ```

2. Run the workflow manually to test:
   - Go to Actions → Daily AI News Run → Run workflow
   - Check Discord channel for the file upload

3. You should see:
   - 📊 Report summary embed
   - 📄 Downloadable .txt file attachment

## Benefits

✨ **Advantages:**
- Reports available directly in Discord (no need to download separately)
- File history in Discord channel for reference
- Team members can access without repository access
- Easy sharing and review
- Automated without manual uploading
