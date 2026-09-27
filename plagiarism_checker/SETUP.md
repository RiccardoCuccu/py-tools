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

### Where the Key is Stored

The key is looked up in this order:

1. The `SERPAPI_API_KEY` environment variable, if set. Takes priority over everything else, useful for one-off runs or CI.
2. The OS keyring (Windows Credential Manager, or the equivalent on macOS/Linux), under the service name `py-tools/plagiarism_checker`.
3. A one-time migration from the old `.serpapi_config` file, if one exists from a previous version of this tool: the key is read, saved to the keyring, and the file is deleted only after the keyring read-back succeeds. If saving to the keyring fails, the file is kept and a warning is printed, so no data is lost.
4. A prompt, shown only when running with `--search-engine serpapi` and no key was found above. The key is typed with `getpass`, so it is not echoed to the screen, then saved to the keyring.

If no keyring backend is available on the system, the key is used for that run only and is never written to disk.

### Resetting the Key

To rotate or remove the stored key:

```bash
python main.py --reset-serpapi-key
```

This deletes the key from the OS keyring and prints the result. It works without specifying a document file.

### Verify Setup

Run the script:

```bash
python main.py your_document.docx
```

If configured correctly, you'll see:
```
[3/5] Searching online for similar content using SerpApi...
```

## Contact Email for CrossRef and Unpaywall

The `--use-apis` flag queries CrossRef and Unpaywall, both of which ask for a contact email in the request. Copy `config.example.json` to `config.json` in this folder and set `contact_email` to your own address; `config.json` is gitignored so it never leaves your machine. If `config.json` is missing or invalid, a placeholder email is used instead.

## Security Notes

- The SerpApi key lives only in the OS keyring (or the `SERPAPI_API_KEY` environment variable for a single run), never in a plaintext file
- Keep your API key confidential
- If you accidentally expose your key, regenerate it immediately on the SerpApi dashboard and run `--reset-serpapi-key` locally
- The free tier has usage limits, so monitor your usage on the SerpApi dashboard