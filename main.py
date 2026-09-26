"""Read HTML pages from a public GCS bucket (or a local directory), build the
link graph and report link statistics, the top 5 pages by PageRank and the page
with the best closeness centrality.

Downloads from the bucket may use the storage library's built-in parallel
download (--workers).  All processing of the downloaded data runs in a single
thread, and no graph library is used.

Examples:
    python3 main.py --bucket slau-page-bucket --prefix pages/
    python3 main.py --bucket slau-page-bucket --prefix pages/ --workers 1
    python3 main.py --local-dir ./pages
"""
import argparse
import io
import os
import time

from graph_analysis import (
    build_graph,
    closeness_centrality,
    degree_stats,
    pagerank,
    parse_links,
    top_k,
)


def _download_text(blob, attempts=4):
    """Download one object, retrying a few times on a transient network error.

    A full sequential run is 12,000 requests over many minutes; without this a
    single dropped connection would throw away the whole run.
    """
    for attempt in range(1, attempts + 1):
        try:
            return blob.download_as_text()
        except Exception as exc:                      # noqa: BLE001 - retry any
            if attempt == attempts:
                raise
            wait = 2 ** (attempt - 1)
            print(f"  retrying {blob.name} after {type(exc).__name__} "
                  f"(attempt {attempt}/{attempts}, waiting {wait}s)", flush=True)
            time.sleep(wait)


def _download_batch(blobs, workers):
    """Download a batch of objects concurrently; return their text, in order.

    Uses the parallel download built into the storage library
    (transfer_manager.download_many) with a pool of `workers` threads, each
    writing one object into its own in-memory buffer.  Only the download is
    concurrent: this function returns once the whole batch has arrived, and all
    parsing happens afterwards in the main thread.  Any object whose download
    failed is fetched again one at a time.
    """
    from google.cloud.storage import transfer_manager

    buffers = [io.BytesIO() for _ in blobs]
    results = transfer_manager.download_many(
        list(zip(blobs, buffers)),
        worker_type=transfer_manager.THREAD,  # threads can fill in-memory buffers
        max_workers=workers,
        raise_exception=False,                # failures come back in `results`
    )
    texts = []
    for blob, buffer, result in zip(blobs, buffers, results):
        if isinstance(result, Exception):
            print(f"  parallel download of {blob.name} failed "
                  f"({type(result).__name__}); retrying on its own", flush=True)
            texts.append(_download_text(blob))
        else:
            texts.append(buffer.getvalue().decode("utf-8", errors="replace"))
    return texts


def read_from_bucket(bucket_name, prefix, workers=8, batch_size=500, progress=1000):
    """Download every object under `prefix` and parse its links.

    Uses an anonymous client, so it works against a world-readable bucket with
    no credentials configured at all.

    With workers > 1 the objects are downloaded in batches of `batch_size`,
    `workers` at a time, using the storage library's parallel download.  Each
    batch is then parsed sequentially in the main thread and its raw bytes are
    dropped, so only one batch (~40 MB) is ever held in memory.  With
    workers == 1 every object is downloaded and parsed strictly one at a time.
    """
    from google.cloud import storage

    client = storage.Client.create_anonymous_client()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    blobs = [blob for blob in client.list_blobs(bucket_name, prefix=prefix)
             if not blob.name.endswith("/")]  # skip folder placeholder objects
    if not blobs:
        raise SystemExit(f"no objects found under gs://{bucket_name}/{prefix}")
    print(f"  listed {len(blobs)} objects; downloading with "
          f"{workers} worker(s)", flush=True)

    page_links = {}
    if workers <= 1:
        for blob in blobs:
            page_links[blob.name.rsplit("/", 1)[-1]] = parse_links(_download_text(blob))
            if progress and len(page_links) % progress == 0:
                print(f"  downloaded {len(page_links)} files", flush=True)
        return page_links

    for start in range(0, len(blobs), batch_size):
        batch = blobs[start:start + batch_size]
        texts = _download_batch(batch, workers)
        for blob, text in zip(batch, texts):          # sequential parsing
            page_links[blob.name.rsplit("/", 1)[-1]] = parse_links(text)
        print(f"  downloaded {len(page_links)}/{len(blobs)} files", flush=True)
    return page_links


def read_from_dir(directory):
    """Read every file in a local directory and parse its links."""
    page_links = {}
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                page_links[name] = parse_links(f.read())
    return page_links


WIDTH = 60


def section(title):
    """Print a major section banner framed by '=' lines."""
    print("\n" + "=" * WIDTH)
    print(f" {title}")
    print("=" * WIDTH)


def subsection(title):
    """Print a minor section banner framed by '-' lines."""
    print("\n" + "-" * WIDTH)
    print(f" {title}")
    print("-" * WIDTH)


def print_stats(title, stats):
    quintiles = " | ".join(f"{x:.2f}" for x in stats["quintiles"])
    subsection(title.upper())
    print(f"  average    {stats['average']:.4f}")
    print(f"  median     {stats['median']:.2f}")
    print(f"  max        {stats['max']:.0f}")
    print(f"  min        {stats['min']:.0f}")
    print(f"  quintiles  {quintiles}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", help="GCS bucket holding the pages")
    parser.add_argument("--prefix", default="pages/",
                        help="directory inside the bucket (default: pages/)")
    parser.add_argument("--workers", type=int, default=8,
                        help="parallel download threads used by the storage "
                             "library (default: 8); 1 downloads one file at a "
                             "time. Processing is always single-threaded")
    parser.add_argument("--local-dir",
                        help="read pages from this local directory instead of GCS")
    parser.add_argument("--tol", type=float, default=0.005,
                        help="PageRank stopping threshold on the change in the "
                             "sum of PageRanks (default: 0.005 = 0.5%%)")
    parser.add_argument("--damping", type=float, default=0.85,
                        help="PageRank damping factor (default: 0.85)")
    parser.add_argument("--pr-iterations", type=int,
                        help="run exactly this many PageRank iterations and "
                             "ignore the 0.5%% stopping rule (for comparison)")
    parser.add_argument("--top", type=int, default=5,
                        help="how many PageRank pages to print (default: 5)")
    args = parser.parse_args()
    if not args.bucket and not args.local_dir:
        parser.error("give either --bucket or --local-dir")

    timings = {}
    t_start = time.perf_counter()

    t = time.perf_counter()
    if args.local_dir:
        page_links = read_from_dir(args.local_dir)
        source = args.local_dir
    else:
        page_links = read_from_bucket(args.bucket, args.prefix, workers=args.workers)
        source = f"gs://{args.bucket}/{args.prefix}"
    timings["Read + parse files"] = time.perf_counter() - t

    t = time.perf_counter()
    graph = build_graph(page_links)
    timings["Build graph"] = time.perf_counter() - t
    section("GRAPH SUMMARY")
    print(f" Source : {source}")
    print(f" Pages  : {graph.n:,}      Links : {graph.num_edges:,}")

    t = time.perf_counter()
    in_stats = degree_stats(graph.in_degree)
    out_stats = degree_stats(graph.out_degree)
    timings["Link statistics"] = time.perf_counter() - t
    print_stats("Incoming links", in_stats)
    print_stats("Outgoing links", out_stats)

    t = time.perf_counter()
    pr, iterations, sums = pagerank(graph, damping=args.damping, tol=args.tol,
                                    fixed_iterations=args.pr_iterations)
    timings["PageRank"] = time.perf_counter() - t
    change = abs(sums[-1] - sums[-2]) / sums[-2]
    stop = ("fixed iteration count" if args.pr_iterations
            else f"threshold {args.tol * 100:g}%")
    section("PAGERANK")
    print(f" Stopped after {iterations} iteration(s) ({stop})")
    print(f" Sum of PR {sums[-2]:.6f} -> {sums[-1]:.6f} "
          f"({change * 100:.4f}% change)")
    print(f"\n>>> TOP {args.top} PAGES BY PAGERANK")
    for rank, i in enumerate(top_k(pr, args.top), start=1):
        print(f"    #{rank}  {graph.names[i]:<12} {pr[i]:.8f}")

    section("CLOSENESS CENTRALITY")
    print(" Running one BFS per page ...", flush=True)
    t = time.perf_counter()
    closeness = closeness_centrality(graph, progress=1000)
    timings["Closeness centrality"] = time.perf_counter() - t
    best = top_k(closeness, 1)[0]
    print(f"\n Best closeness : {graph.names[best]} "
          f"(score {closeness[best]:.6f})")
    print(f"\n>>> TOP 5 PAGES BY CLOSENESS")
    for rank, i in enumerate(top_k(closeness, 5), start=1):
        print(f"    #{rank}  {graph.names[i]:<12} {closeness[i]:.6f}")

    timings["TOTAL"] = time.perf_counter() - t_start
    section("TIMING (seconds)")
    for name, secs in timings.items():
        print(f"  {name:<22} {secs:10.2f}")


if __name__ == "__main__":
    main()
