SETTING UP THE AUTOMATED WORKER
==================================

This is the piece that actually watches for paid, uploaded reports and
processes them automatically -- no more manually running load_and_run.py
yourself for each customer.


PART 1 — DATABASE CHANGES
----------------------------
1. Go to Supabase -> SQL Editor -> New query
2. Paste in supabase_reports_output.sql, click Run
   (This adds a report_path column and a new private bucket for finished
   reports -- separate from the raw chat uploads bucket, same privacy
   principle: nothing here gets a permanent public link.)


PART 2 — UPDATE YOUR APP
----------------------------
Replace your dashboard file with the new one in this folder (dashboard-page.js
in this delivery) the same way you've replaced files before:
    move "C:\Users\Arnav Arora\Downloads\dashboard-page.js" "app\dashboard\page.js"

Then redeploy to Vercel (or just keep testing locally with npm run dev for now).


PART 3 — SET UP THE WORKER AS ITS OWN GITHUB REPO
------------------------------------------------------
This lives separately from your Next.js app -- same idea as how TRIGGR's
worker is its own thing from the Expo app.

1. Create a new, empty GitHub repository (e.g. "probroker-worker")
2. Put this whole probroker-worker folder's contents into it and push:
     cd probroker-worker
     git init
     git add .
     git commit -m "Initial worker"
     git branch -M main
     git remote add origin https://github.com/YOUR-USERNAME/probroker-worker.git
     git push -u origin main

3. On GitHub, go to your new repo -> Settings -> Secrets and variables ->
   Actions -> New repository secret. Add these three, one at a time:
     - SUPABASE_URL               (same value as in your app's .env.local)
     - SUPABASE_SERVICE_ROLE_KEY  (same value as in your app's .env.local)
     - ANTHROPIC_API_KEY          (your real Claude API key)

4. That's it. GitHub Actions will now run worker.py automatically every
   10 minutes, forever, for free (within GitHub's free tier of Actions
   minutes, which is generous for this volume).

5. To test it immediately without waiting up to 10 minutes: go to your
   repo -> Actions tab -> "Process Reports" workflow -> "Run workflow"
   button -> Run. Then check the logs to see exactly what happened.


PART 4 — TESTING IT FOR REAL
----------------------------------
1. On your live dashboard, pay for a test report and upload a real chat
   export, same as before
2. Instead of running load_and_run.py yourself, just wait (or manually
   trigger the workflow per step 5 above)
3. Refresh your dashboard -- the report should flip from "Processing..."
   to a "Download ->" button on its own
4. Click Download -- it should open your finished report.xlsx


WHAT TO WATCH FOR THE FIRST TIME
-------------------------------------
This is the first time extract.py (the real Claude API call) is running
against real, live data rather than the manual copy-paste process we
used earlier. If a report gets stuck on "Processing..." for a long time,
or flips to "Failed", check the GitHub Actions logs for that run (Actions
tab -> click the run -> click the "Run worker" step) -- the error will be
right there, and it's the same kind of thing we've debugged all day: read
the exact error message rather than guess.
