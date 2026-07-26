"""
The automated worker. Runs on a schedule (via GitHub Actions -- see
.github/workflows/worker.yml). Each run:

  1. Asks Supabase for every report with status = 'processing'
  2. For each one: downloads the uploaded chat file, runs it through the
     pipeline (parse -> extract -> match -> report), uploads the finished
     .xlsx back to Supabase, and marks that exact row 'completed'
  3. If anything goes wrong for a given report, marks it 'failed' instead
     of leaving it stuck silently -- so it's visible, not lost

Because every report row already has the correct user_id attached to it
from the moment payment happened, there is no separate "who does this go
to" step -- the customer's own dashboard already only shows their own
rows (Row Level Security), so writing the finished file back to the same
row is the entire delivery mechanism.
"""
import os
import io
import zipfile
import tempfile
from supabase import create_client

from pipeline.parser import parse_and_group, chunk_for_extraction
from pipeline.extract import extract_all
from pipeline.match import find_matches
from pipeline.report import build_report

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
# ANTHROPIC_API_KEY is read automatically by pipeline/extract.py's own
# anthropic.Anthropic() client -- just needs to exist in the environment.

UPLOADS_BUCKET = "chat-uploads"
OUTPUT_BUCKET = "reports-output"


def get_chat_text(supabase, user_id: str, report_id: str) -> str:
    """Finds and downloads whatever file was uploaded for this report,
    and returns its raw text -- unzipping it first if it's a .zip export."""
    folder = f"{user_id}/{report_id}"
    files = supabase.storage.from_(UPLOADS_BUCKET).list(folder)
    if not files:
        raise FileNotFoundError(f"No uploaded file found for report {report_id}")

    # There's exactly one file per report folder in this design
    file_name = files[0]["name"]
    file_path = f"{folder}/{file_name}"
    raw_bytes = supabase.storage.from_(UPLOADS_BUCKET).download(file_path)

    if file_name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            # WhatsApp exports always contain a _chat.txt file
            chat_files = [n for n in z.namelist() if n.endswith(".txt")]
            if not chat_files:
                raise ValueError("No .txt chat file found inside the uploaded zip")
            return z.read(chat_files[0]).decode("utf-8", errors="replace")
    else:
        return raw_bytes.decode("utf-8", errors="replace")


def process_report(supabase, report: dict):
    report_id = report["id"]
    user_id = report["user_id"]
    print(f"[worker] Processing report {report_id} for user {user_id}...")

    raw_text = get_chat_text(supabase, user_id, report_id)

    grouped = parse_and_group(raw_text)
    print(f"  parsed {len(grouped)} message groups")

    chunks = chunk_for_extraction(grouped)
    rows = extract_all(chunks)
    print(f"  extracted {len(rows)} listings")

    # Safety check: if extraction produced nothing at all, something is
    # genuinely wrong (model unavailable, API key issue, etc.) -- treat
    # this as a failure rather than silently delivering an empty report
    # to a paying customer.
    if len(rows) == 0:
        raise RuntimeError(
            f"Extraction produced 0 listings from {len(chunks)} chunks -- "
            "likely a model/API problem, not a real empty chat. Failing "
            "this report rather than delivering an empty file."
        )

    matches = find_matches(rows)
    print(f"  found {len(matches)} matches")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "report.xlsx")
        build_report(rows, matches, out_path)

        with open(out_path, "rb") as f:
            output_path_in_bucket = f"{user_id}/{report_id}/report.xlsx"
            supabase.storage.from_(OUTPUT_BUCKET).upload(
                output_path_in_bucket, f.read(),
                file_options={"upsert": "true"}
            )

    supabase.table("reports").update({
        "status": "completed",
        "report_path": output_path_in_bucket,
    }).eq("id", report_id).execute()

    print(f"  done -> {output_path_in_bucket}")


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    pending = supabase.table("reports").select("*").eq("status", "processing").execute()
    reports = pending.data or []
    print(f"[worker] Found {len(reports)} report(s) to process")

    for report in reports:
        try:
            process_report(supabase, report)
        except Exception as e:
            print(f"[worker] FAILED report {report['id']}: {e}")
            supabase.table("reports").update({"status": "failed"}).eq("id", report["id"]).execute()


if __name__ == "__main__":
    main()
