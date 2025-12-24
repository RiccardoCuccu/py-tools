# Setup Guide

This guide covers the setup requirements for the Plagiarism Checker.

## SerpApi Setup

### Why SerpApi is Recommended

- **DuckDuckGo blocks after 3-5 searches**: Makes the tool unusable for checking even a single document
- **No reliable workarounds**: Changing IPs, waiting, or using VPNs don't consistently solve the issue
- **SerpApi is the most reliable option**: Provides consistent, high-quality search results
- **Free tier available**: Generous free tier with no credit card required
- **Multi-engine access**: Google, Bing, Yahoo, DuckDuckGo, and 80+ search engines
- **Fast and reliable**: No rate limiting or blocking issues

### Getting Your API Key

1. Go to [SerpApi.com](https://serpapi.com/)
2. Click "Register" to create a free account (no credit card required)
3. Verify your email address
4. Once logged in, find your API key on the dashboard
5. Copy your API key

The script will prompt you to enter your API key on first use and will automatically save it to a `.serpapi_config` file in the script directory. This file is already added to `.gitignore` to protect your key.

### Verify Setup

Run the script:

```bash
python main.py your_document.docx
```

If configured correctly, you'll see:
```
✓ Using SerpApi key from /path/to/plagiarism_checker/.serpapi_config
[3/5] Searching online for similar content using SerpApi...
```

## Security Notes

- Never commit `.serpapi_config` to version control (it's automatically git-ignored)
- Keep your API key confidential
- If you accidentally expose your key, regenerate it immediately on SerpApi dashboard
- The free tier has usage limits, so monitor your usage on the SerpApi dashboard