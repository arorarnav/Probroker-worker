"""
Minimal connection test -- makes exactly ONE real API call, directly from
your own computer, with no GitHub Actions involved at all.

This tells us something important either way:
  - If this WORKS from your machine but fails on GitHub -> the problem is
    specific to GitHub Actions' network environment, not your key/account
  - If this ALSO fails here, the same way -> the problem is with the key,
    the account, or a real ongoing outage -- not GitHub specifically

USAGE:
    python test_anthropic_connection.py
"""
import os
import anthropic


def load_local_env():
    if os.path.exists("admin.env"):
        with open("admin.env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


load_local_env()

# Paste your Anthropic API key directly here if it's not already set as an
# environment variable on this machine -- easiest way to test right now.
api_key = os.environ.get("ANTHROPIC_API_KEY") or "PASTE-YOUR-KEY-HERE"

print("Testing connection to Anthropic's API...")
try:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{"role": "user", "content": "Reply with exactly: Connection successful"}],
    )
    print("\nSUCCESS:")
    print(response.content[0].text)
except Exception as e:
    print(f"\nFAILED: {type(e).__name__}: {e}")
