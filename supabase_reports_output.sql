-- Run this in Supabase SQL Editor before deploying the worker.

-- Add a column to store WHERE the finished report file lives in storage.
-- We store a path, not a permanent public link -- the dashboard generates
-- a fresh, temporary signed link each time someone views it, since these
-- reports contain other people's phone numbers and personal data and
-- shouldn't have a permanent public URL floating around.
alter table public.reports add column if not exists report_path text;

-- A second private bucket, separate from the raw chat uploads, to hold
-- the finished .xlsx reports
insert into storage.buckets (id, name, public)
values ('reports-output', 'reports-output', false)
on conflict (id) do nothing;

-- Users can read (and therefore generate a signed link for) only their
-- own finished reports
create policy "Users can view their own finished reports"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'reports-output'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- No insert/update policy needed here for regular users -- only the worker
-- writes to this bucket, using the service_role key, which bypasses RLS
-- entirely (the same trusted-server-side pattern as verify-payment/route.js)
