"""
MANUAL PROCESSING TOOL -- for the concierge phase, before the automated
worker gets switched on (planned once you cross 100 users).

This does NOT call any LLM. It's just the plumbing between your manual
process and the live app: see who's paid and waiting, grab their chat
file, and push your finished report back onto their dashboard once
you've built it (using load_and_run.py, same as always).

SETUP (once):
    Copy admin.env.example to admin.env, fill in your real Supabase URL
    and service_role key (same two values as your GitHub secrets).
    Also run supabase_short_id.sql once, in Supabase's SQL Editor, if
    you haven't already -- it adds the simple numbered IDs this tool uses.

USAGE:
    python admin_tools.py list
        Shows every report that's paid and waiting for you to process,
        each with a simple number (#1, #2, ...) -- use that number below,
        not the long UUID.

    python admin_tools.py download <short_id>
        Downloads that customer's raw chat export to your computer, so
        you can run it through your usual Claude.ai extraction process.

    python admin_tools.py finish <short_id> <path_to_report.xlsx>
        Uploads your finished report and marks it "completed" -- the
        customer will see a real Download button on their dashboard
        within seconds, no automation involved.
"""
import os
import sys
from supabase import create_client


def load_local_env():
    """Loads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from admin.env,
    so you don't have to re-type them into the terminal every session."""
    if os.path.exists("admin.env"):
        with open("admin.env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


UPLOADS_BUCKET = "chat-uploads"
OUTPUT_BUCKET = "reports-output"


def get_client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def resolve_report(supabase, identifier):
    """
    Accepts either the simple short number shown by `list` (e.g. "12") or,
    for backward compatibility, the full UUID -- and returns the actual
    row either way. Internally, everything still uses the real UUID for
    storage paths etc; the short number is purely a convenience for you
    to type without risking a copy-paste mistake.
    """
    if identifier.isdigit():
        result = supabase.table("reports").select("*").eq("short_id", int(identifier)).execute()
    else:
        result = supabase.table("reports").select("*").eq("id", identifier).execute()

    rows = result.data or []
    return rows[0] if rows else None


def cmd_list(supabase):
    pending = supabase.table("reports").select("*").eq("status", "processing").order("short_id").execute()
    reports = pending.data or []
    if not reports:
        print("No reports waiting right now.")
        return
    print(f"{len(reports)} report(s) waiting for you:\n")
    for r in reports:
        print(f"  #{r.get('short_id')}  (use this number below)")
        print(f"    filename:     {r.get('filename')}")
        print(f"    months_back:  {r.get('months_back')} months")
        print(f"    paid on:      {r.get('created_at')}")
        print()


def cmd_download(supabase, identifier):
    row = resolve_report(supabase, identifier)
    if not row:
        print("No report found with that number.")
        return

    report_id = row["id"]
    folder = f"{row['user_id']}/{report_id}"
    files = supabase.storage.from_(UPLOADS_BUCKET).list(folder)
    if not files:
        print("No uploaded file found for this report yet.")
        return

    file_name = files[0]["name"]
    raw_bytes = supabase.storage.from_(UPLOADS_BUCKET).download(f"{folder}/{file_name}")
    local_path = f"downloaded_report{row.get('short_id')}_{file_name}"
    with open(local_path, "wb") as f:
        f.write(raw_bytes)

    print(f"Saved to: {local_path}")
    print(f"Customer wants the last {row.get('months_back')} months only -- "
          f"remember to apply that same window in your extraction.")


def cmd_finish(supabase, identifier, report_path_local):
    row = resolve_report(supabase, identifier)
    if not row:
        print("No report found with that number.")
        return

    report_id = row["id"]
    output_path_in_bucket = f"{row['user_id']}/{report_id}/report.xlsx"
    with open(report_path_local, "rb") as f:
        supabase.storage.from_(OUTPUT_BUCKET).upload(
            output_path_in_bucket, f.read(), file_options={"upsert": "true"}
        )

    supabase.table("reports").update({
        "status": "completed",
        "report_path": output_path_in_bucket,
    }).eq("id", report_id).execute()

    print(f"Done! Report #{row.get('short_id')} -- the customer will see a Download button now.")


if __name__ == "__main__":
    load_local_env()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    supabase = get_client()
    command = sys.argv[1]

    if command == "list":
        cmd_list(supabase)
    elif command == "download":
        if len(sys.argv) < 3:
            print("Usage: python admin_tools.py download <short_id>")
            sys.exit(1)
        cmd_download(supabase, sys.argv[2])
    elif command == "finish":
        if len(sys.argv) < 4:
            print("Usage: python admin_tools.py finish <short_id> <path_to_report.xlsx>")
            sys.exit(1)
        cmd_finish(supabase, sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
