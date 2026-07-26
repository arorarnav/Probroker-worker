"""
Takes the JSON that Claude gives you (pasted from a Claude.ai conversation)
and turns it into the same formatted Excel report we've been building --
Listings sheet + Matches sheet. No API key needed for this path.

Usage:
    1. Save Claude's JSON output into a file called listings.json
       (in this same folder)
    2. Run: python load_and_run.py
    3. Open report.xlsx
"""
import json
from pipeline.match import find_matches
from pipeline.report import build_report

with open("listings.json", "r", encoding="utf-8") as f:
    rows = json.load(f)

print(f"Loaded {len(rows)} listings from listings.json")

matches = find_matches(rows)
print(f"Found {len(matches)} matches")

build_report(rows, matches, "report.xlsx")
print("\nDone! Open report.xlsx to see your real formatted report.")
