"""
ONE-TIME CLEANUP -- empties both storage buckets completely (chat-uploads
and reports-output). Run this once before real customer traffic starts,
to clear out anything you uploaded while testing.

This uses Supabase's actual Storage API to delete files (not raw SQL on
storage.objects) -- that's the safe way to do this, since the real file
data is managed by Supabase's Storage system, not just tracked in that
table. Deleting rows there directly can leave things inconsistent.

SETUP: same admin.env file you already have for admin_tools.py -- this
script reads the same two values from it.

USAGE:
    python clear_storage.py
"""
import os
from supabase import create_client


def load_local_env():
    if os.path.exists("admin.env"):
        with open("admin.env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def clear_bucket(supabase, bucket_name):
    print(f"Clearing bucket: {bucket_name}")
    all_paths = []

    def walk(prefix=""):
        items = supabase.storage.from_(bucket_name).list(prefix)
        for item in items:
            full_path = f"{prefix}/{item['name']}" if prefix else item["name"]
            # A folder shows up with no real metadata id; a real file has one.
            if item.get("id") is None:
                walk(full_path)
            else:
                all_paths.append(full_path)

    walk()

    if not all_paths:
        print("  Already empty.")
        return

    print(f"  Found {len(all_paths)} file(s), deleting...")
    supabase.storage.from_(bucket_name).remove(all_paths)
    print("  Done.")


if __name__ == "__main__":
    load_local_env()
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    clear_bucket(supabase, "chat-uploads")
    clear_bucket(supabase, "reports-output")
    print("\nBoth buckets cleared.")
