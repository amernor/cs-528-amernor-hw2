# cs-528-amernor-hw2

- **Project:** `superb-heaven-507521-u2`
- **Bucket:** `gs://cs-528-amernor/` (region `us-central1`, world-readable)
- **Pages live under the prefix:** `pages/`

---

## What you need first

```
pip install google-cloud-storage
```

(On the VM use `pip3 install --break-system-packages google-cloud-storage`. Cloud Shell
usually already has it.)

---

## How to run

The program takes a bucket and a prefix and does everything:

```
python3 main.py --bucket cs-528-amernor --prefix pages/
```

That's the whole program. It prints the link stats, the top 5 PageRank pages, the most
central page, and timings.

Useful options:

| Flag | What it does | Default |
|---|---|---|
| `--bucket` | GCS bucket to read | — |
| `--prefix` | Folder inside the bucket | `pages/` |
| `--workers` | Download threads (`1` = fully single-threaded download) | `8` |
| `--local-dir` | Read from a local folder instead of the bucket | — |
| `--top` | How many top PageRank pages to print | `5` |
| `--pr-iterations` | Run this many PageRank rounds instead of the 0.5% stop rule | — |

---

## Running in each of the 3 environments

The command is the same everywhere. Only where you run it changes.

### 1. Local computer (laptop)

```
pip install google-cloud-storage
python3 main.py --bucket cs-528-amernor --prefix pages/
```

### 2. Cloud Shell

Open Cloud Shell, then:

```
git clone https://github.com/amernor/cs-528-amernor-hw2.git
cd cs-528-amernor-hw2
python3 main.py --bucket cs-528-amernor --prefix pages/
```

If the direct read times out (Cloud Shell's connection to storage can be flaky), first
copy the files to local disk, then read them from there:

```
mkdir -p staged/pages
gcloud storage rsync -r gs://cs-528-amernor/pages ./staged/pages
python3 main.py --local-dir ./staged/pages
```

### 3. VM (e2-medium, us-central1)

Create it:

```
gcloud compute instances create hw2-vm \
  --project=superb-heaven-507521-u2 --zone=us-central1-a \
  --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud
```

SSH in and run:

```
gcloud compute ssh hw2-vm --zone=us-central1-a
# on the VM:
sudo apt-get update && sudo apt-get install -y python3-pip git
git clone https://github.com/amernor/cs-528-amernor-hw2.git
cd cs-528-amernor-hw2
pip3 install --break-system-packages google-cloud-storage
python3 main.py --bucket cs-528-amernor --prefix pages/
```

Delete the VM when done so it stops billing:

```
gcloud compute instances delete hw2-vm --zone=us-central1-a
```

---

## Running the tests

```
python3 -m pytest test_graph_analysis.py -q
```
