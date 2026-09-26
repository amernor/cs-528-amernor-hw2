"""
gcs_upload.py

Uploads a local directory of generated page-files into a GCS bucket under
a given prefix (folder).

Uses transfer_manager, which is built into the google-cloud-storage client
library, to upload files concurrently. This is explicitly allowed per your
instructor's clarification: the "no threading" rule applies to YOUR OWN
graph algorithm code (pagerank.py, centrality.py), not to file transfer --
transfer_manager isn't a graph library and isn't threading code you wrote
yourself, it's a sanctioned Google-provided tool for this exact purpose.
This is meaningfully faster than uploading 12,000 files one at a time.

Usage:
    python gcs_upload.py --bucket my-bucket-name --local_dir data --prefix pages
"""

import argparse
import os

from google.cloud import storage
from google.cloud.storage import transfer_manager


def upload_directory(bucket_name, local_dir, prefix, max_workers=8):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    filenames = sorted(
        f for f in os.listdir(local_dir)
        if os.path.isfile(os.path.join(local_dir, f))
    )

    # transfer_manager wants filenames relative to a source_directory, and
    # writes them to the same relative path (prefixed) in the bucket.
    # worker_type="thread" avoids the process-spawn overhead of the default
    # worker_type="process" -- uploads are I/O-bound (waiting on network),
    # so threads parallelize this fine without paying to start N separate
    # Python processes (which is especially costly on macOS, where new
    # processes are spawned fresh rather than forked).
    results = transfer_manager.upload_many_from_filenames(
        bucket,
        filenames,
        source_directory=local_dir,
        blob_name_prefix=f"{prefix.rstrip('/')}/",
        max_workers=max_workers,
        worker_type="thread",
        skip_if_exists=True,
    )

    failures = []
    skipped = 0
    for fname, result in zip(filenames, results):
        if result is None:
            continue
        # skip_if_exists=True causes already-uploaded files to come back as a
        # 412 Precondition Failed "error" -- that's an expected skip, not a
        # real failure, so don't report it as one.
        status_code = getattr(result, "code", None)
        if status_code == 412:
            skipped += 1
        else:
            failures.append((fname, result))

    if skipped:
        print(f"Skipped {skipped} files already present in the bucket.")
    if failures:
        print(f"WARNING: {len(failures)} files failed to upload:")
        for fname, err in failures[:10]:
            print(f"  {fname}: {err}")
    else:
        print(f"Done. {len(filenames) - skipped} files uploaded "
              f"(plus {skipped} already present) -> gs://{bucket_name}/{prefix}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--local_dir", required=True)
    parser.add_argument("--prefix", default="pages")
    parser.add_argument("--max_workers", type=int, default=8,
                         help="Number of concurrent upload workers (transfer_manager)")
    args = parser.parse_args()

    upload_directory(args.bucket, args.local_dir, args.prefix, args.max_workers)

