# HW7 — Apache Beam / Cloud Dataflow

Builds on [HW2](../hw2/): an Apache Beam pipeline over the 12,000 HTML pages in
`gs://cs528-amernor/pages/` that finds

1. the top 5 files with the most **incoming** links,
2. the top 5 files with the most **outgoing** links,
3. the top 5 most frequent **word trigrams** (three consecutive words),

and runs both on the laptop (DirectRunner) and on Google Cloud Dataflow.

- **Project:** `superb-heaven-507521-u2`
- **Region:** `us-central1`
- **Bucket:** `gs://cs528-amernor/` (pages under `pages/`)

---

## Files

| File | What it is |
|---|---|
| `beam_analysis.py` | The whole pipeline + command-line entry point |
| `test_beam_analysis.py` | Unit tests, plus an end-to-end check against a plain-Python count |
| `requirements.txt` | `apache-beam[gcp]`, `pytest` |

---

## How the code works

`beam_analysis.py` builds one Beam pipeline:

```
MatchFiles(--input) -> Reshuffle -> ReadMatches -> (file name, html)   "pages"
   |
   +-- parse_links -> (name, [targets])                           "links"
   |      +-- len(targets)                -> Top 5   = top outgoing
   |      +-- (target, 1) -> CombinePerKey(sum)
   |             -> CoGroupByKey with page names               -> Top 5 = top incoming
   |
   +-- strip tags, lower-case, split words, Counter(trigrams) per page
          -> CombinePerKey(sum)                                 -> Top 5 = top trigrams
```

- **Links** use the same regex as HW2 (`href="..."`, case-insensitive), so counts
  match HW2. Duplicate links on a page all count.
- **Outgoing** is just the length of each page's own link list. Nothing has to be
  shuffled, which is why it is the easy one.
- **Incoming** sends a `(target, 1)` for every link, sums per target, then joins with
  the list of real file names (`CoGroupByKey`). This drops links to files that don't
  exist and gives pages nobody links to a count of 0.
- **Trigrams** strip HTML tags, lower-case the text and drop punctuation. Trigrams are
  taken *within* a page, never across two files. Each page counts its own trigrams
  with a `Counter` first, so it emits about 75 `(trigram, count)` pairs instead of
  about 12,000 single trigrams. That cuts the data shuffled from ~140 M elements to
  under 1 M, and the local runtime from ~250 s to ~85 s.
- **Reading in parallel.** Without the `Reshuffle`, Beam fuses the file listing with
  the reads. All 12,000 files are then downloaded one by one on a single thread, even
  when Dataflow adds workers. The first Dataflow run did exactly this and took 41 min.
  `Reshuffle` breaks the fusion and spreads the file list across workers and threads.
  The same code then took 14.9 min.
- **Ties** are broken the same way everywhere: higher count first, then file name in
  numeric order (`2.html` before `10.html`) or trigram in alphabetical order. The
  generated pages repeat the same Lorem-ipsum paragraph, so 71 trigrams tie for first.
  The program prints how many share the top count.
- Results are written as text files under `--output` (a local folder or `gs://`).
  The script then reads them back and prints them along with the wall-clock time,
  so the output looks the same for both runners.

---

## Setup (once)

```
cd hw7
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Beam needs Python 3.10–3.13 (developed with 3.12 and Beam 2.77).

Log in to Google Cloud. The second command gives Beam credentials to read and write
the bucket:

```
gcloud auth login
gcloud auth application-default login
gcloud config set project superb-heaven-507521-u2
```

For Dataflow, also enable the APIs (once per project):

```
gcloud services enable dataflow.googleapis.com compute.googleapis.com \
    storage.googleapis.com logging.googleapis.com
```

Dataflow workers run as the project's default Compute Engine service account. If the
job fails with a permissions error, give that account the worker and storage roles:

```
PROJECT_NUMBER=$(gcloud projects describe superb-heaven-507521-u2 --format='value(projectNumber)')
SA=${PROJECT_NUMBER}-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding superb-heaven-507521-u2 \
    --member=serviceAccount:$SA --role=roles/dataflow.worker
gcloud projects add-iam-policy-binding superb-heaven-507521-u2 \
    --member=serviceAccount:$SA --role=roles/storage.objectAdmin
```

---

## Running

### 1. Local laptop (DirectRunner)

Reading straight from the bucket:

```
python beam_analysis.py --input 'gs://cs528-amernor/pages/*' --output ./output \
    --runner apache_beam.runners.portability.fn_api_runner.FnApiRunner \
    --direct_num_workers 8 --direct_running_mode multi_threading
```

This uses Beam's in-process Python runner with 8 threads. Since Beam 2.6x, the plain
`DirectRunner` hands work to the Prism runner. On this laptop, Prism dropped its gRPC
connection ("Stream removed (Socket closed)") a few minutes into reading from GCS, on
every attempt. It works fine on local files.

Or reading the HW2 pages already on disk (no network):

```
python beam_analysis.py --input '../hw2/data/*.html' --output ./output
```

### 2. Google Cloud Dataflow

```
python beam_analysis.py \
    --input 'gs://cs528-amernor/pages/*' \
    --output gs://cs528-amernor/hw7/output \
    --runner DataflowRunner \
    --project superb-heaven-507521-u2 \
    --region us-central1 \
    --temp_location gs://cs528-amernor/hw7/tmp \
    --job_name hw7-links-trigrams
```

The command waits for the job to finish, then prints the results, the wall-clock
time and the Dataflow job ID. You can watch the job graph at
<https://console.cloud.google.com/dataflow/jobs?project=superb-heaven-507521-u2>.

Options:

| Flag | Meaning | Default |
|---|---|---|
| `--input` | File pattern to read (local or `gs://`) | `gs://cs528-amernor/pages/*` |
| `--output` | Folder for the result files (local or `gs://`) | `./output` |
| `--runner` | `DirectRunner` (laptop) or `DataflowRunner` | `DirectRunner` |
| any other Beam flag | passed straight to Beam (`--max_num_workers`, `--machine_type`, …) | |

---

## Results

```
Files processed: 12,000

TOP 5 FILES BY INCOMING LINKS
  #1  5984.html                         233 links
  #2  6710.html                         210 links
  #3  9835.html                         209 links
  #4  1912.html                         208 links
  #5  4183.html                         207 links

TOP 5 FILES BY OUTGOING LINKS
  #1  93.html                           323 links
  #2  130.html                          323 links
  #3  944.html                          323 links
  #4  978.html                          323 links
  #5  1698.html                         323 links

TOP 5 WORD TRIGRAMS
  #1  ad minim veniam              1,946,934 times
  #2  adipiscing elit sed          1,946,934 times
  #3  aliqua ut enim               1,946,934 times
  #4  aliquip ex ea                1,946,934 times
  #5  amet consectetur adipiscing  1,946,934 times

  71 distinct trigram(s) share the top count of 1,946,934; ties are broken alphabetically.
```

### Runtimes

| Where | Input | Wall-clock |
|---|---|---|
All runs read the same 12,000 pages and printed identical results. Beam 2.77,
Python 3.12, Apple Silicon laptop.

| Where | Input | Wall-clock |
|---|---|---|
| Laptop, DirectRunner (Prism) | local disk `../hw2/data` | **83.6 s** |
| Laptop, FnApiRunner, 8 threads | `gs://cs528-amernor/pages/*` | **555.0 s** (9.3 min) |
| Cloud Dataflow, ≤ 4 × n1-standard-1, `us-central1` | `gs://cs528-amernor/pages/*` | **895.3 s** (14.9 min) |
| Cloud Dataflow, first version without `Reshuffle` | `gs://cs528-amernor/pages/*` | 2,459 s (41.0 min) |

Where the Dataflow time went (job `2026-11-08_19_52_00-2717440404910574617`):

| Phase | Time |
|---|---|
| Launch + worker VM startup | ~3.0 min |
| Read + process all files (1 worker, autoscaled to 4 after ~1 min) | ~10.7 min |
| Final combines, write results, shut down workers | ~1.2 min |

**Why Dataflow is slower here:** the data set is small, about 976 MB in 12,000 small
files. Each file is a separate GCS request, so the run is dominated by per-file
request overhead and by Dataflow's fixed costs (starting VMs, staging code,
shutting down), not by computation. The laptop reading local disk avoids the network
completely. Dataflow pays off when the input is far bigger than one machine can read
in reasonable time: the work then spreads over many workers, while the fixed
~4 minutes of overhead stays the same.

---

## Tests

```
python -m pytest test_beam_analysis.py -q
```

The tests check the helper functions, then run the full pipeline on a small hand-made
set of pages and on all 12,000 HW2 pages (if `../hw2/data` exists). They compare the
output with a plain-Python count of the same files. Takes about 3 minutes.
