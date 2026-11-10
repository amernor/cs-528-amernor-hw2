"""HW7: Apache Beam analysis of the HW2 HTML pages.

One pipeline computes three things over every page matched by --input:

  1. the top 5 files with the most INCOMING links (links from other pages)
  2. the top 5 files with the most OUTGOING links (links written in the page)
  3. the top 5 most frequent word trigrams (three consecutive words)

The same code runs on the laptop (DirectRunner, the default) and on Google
Cloud Dataflow (--runner DataflowRunner plus the usual project / region /
temp_location flags).  Results are written as text files under --output and
then printed by this script once the pipeline has finished, so the output looks
the same whichever runner did the work.

Examples:
    # local laptop, reading from the bucket
    python beam_analysis.py --input 'gs://cs528-amernor/pages/*' \\
        --output ./output

    # local laptop, reading the HW2 pages from disk
    python beam_analysis.py --input '../hw2/data/*.html' --output ./output

    # Cloud Dataflow
    python beam_analysis.py --input 'gs://cs528-amernor/pages/*' \\
        --output gs://cs528-amernor/hw7/output \\
        --runner DataflowRunner --project superb-heaven-507521-u2 \\
        --region us-central1 --temp_location gs://cs528-amernor/hw7/tmp
"""
import argparse
import re
import time
from collections import Counter

import apache_beam as beam
from apache_beam.io import fileio
from apache_beam.io.filesystems import FileSystems
from apache_beam.options.pipeline_options import PipelineOptions, SetupOptions

TOP_N = 5

# Same link pattern as HW2's graph_analysis.parse_links, so counts agree.
LINK_RE = re.compile(r"""href\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]*>")
WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


# --------------------------------------------------------------------------
# Plain functions used by the pipeline (also unit-tested on their own)
# --------------------------------------------------------------------------

def basename(path):
    """'gs://bucket/pages/12.html' -> '12.html'."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def parse_links(html):
    """Link targets in a page, as file basenames.  Duplicates are kept."""
    return [basename(target) for target in LINK_RE.findall(html)]


def page_words(html):
    """The visible words of a page: tags removed, lower-cased, punctuation dropped."""
    return WORD_RE.findall(TAG_RE.sub(" ", html).lower())


def trigrams(words):
    """Every run of three consecutive words, as a single space-joined string."""
    return [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]


def natural_key(name):
    """Sort key so that '2.html' comes before '10.html'."""
    return [int(tok) if tok.isdigit() else tok for tok in re.split(r"(\d+)", name)]


def rank_key(item):
    """Order (name, count) pairs by count descending, then name ascending.

    Used with Top.Of(..., reverse=True), which keeps the *smallest* keys, so a
    higher count must give a smaller key.  The name makes ties deterministic.
    """
    name, count = item
    return (-count, natural_key(name))


def join_incoming(item):
    """CoGroupByKey output -> (page, incoming count) for pages that exist.

    Links pointing at a file that is not in the collection are dropped, and
    pages nobody links to get a count of 0 (same rules as HW2's build_graph).
    """
    name, grouped = item
    if grouped["page"]:
        yield name, sum(grouped["hits"])


def format_ranking(title, ranked, unit):
    lines = [title]
    for rank, (name, count) in enumerate(ranked, start=1):
        lines.append(f"  #{rank}  {name:<28} {count:>8,} {unit}")
    return "\n".join(lines)


def format_tie_note(max_and_ties):
    """Note how many trigrams share the highest count (there are many ties)."""
    if not max_and_ties:
        return "  (no trigrams found)"
    max_count, how_many = max_and_ties[0]
    return (f"  {how_many:,} distinct trigram(s) share the top count of "
            f"{max_count:,}; ties are broken alphabetically.")


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def write_text(pcoll, path, label):
    """Write a PCollection of strings to exactly one file at `path`."""
    return pcoll | f"Write {label}" >> beam.io.WriteToText(
        path, shard_name_template="", num_shards=1)


def build_pipeline(p, input_pattern, output_dir):
    # (file name, html) for every file matched by the input pattern
    pages = (
        p
        | "Match files" >> fileio.MatchFiles(input_pattern)
        # Without this, Beam fuses the listing with the reads and all 12,000
        # files are downloaded one by one on a single thread.  Reshuffling the
        # file list spreads the reads across workers and threads.
        | "Spread reads" >> beam.Reshuffle()
        | "Read files" >> fileio.ReadMatches()
        | "Name + text" >> beam.Map(
            lambda f: (basename(f.metadata.path), f.read_utf8()))
    )

    # ---- links -----------------------------------------------------------
    links = pages | "Parse links" >> beam.MapTuple(
        lambda name, html: (name, parse_links(html)))

    # Outgoing: just the length of each page's own link list.
    outgoing = links | "Count outgoing" >> beam.MapTuple(
        lambda name, targets: (name, len(targets)))

    # Incoming: emit one (target, 1) per link, sum per target, then join with
    # the set of existing pages so dangling links are dropped.
    hits = (
        links
        | "Emit link targets" >> beam.FlatMap(
            lambda kv: ((target, 1) for target in kv[1]))
        | "Sum per target" >> beam.CombinePerKey(sum)
    )
    page_names = pages | "Page names" >> beam.MapTuple(lambda name, _: (name, 1))
    incoming = (
        {"page": page_names, "hits": hits}
        | "Join with pages" >> beam.CoGroupByKey()
        | "Keep existing pages" >> beam.FlatMap(join_incoming)
    )

    top_in = incoming | "Top incoming" >> beam.combiners.Top.Of(
        TOP_N, key=rank_key, reverse=True)
    top_out = outgoing | "Top outgoing" >> beam.combiners.Top.Of(
        TOP_N, key=rank_key, reverse=True)

    # ---- trigrams --------------------------------------------------------
    # Count inside each page first (in-mapper combining): a page emits ~75
    # (trigram, count) pairs instead of thousands of single trigrams, which
    # cuts the elements shuffled from ~140 million to under a million.
    trigram_counts = (
        pages
        | "Trigram counts per page" >> beam.FlatMapTuple(
            lambda name, html: Counter(trigrams(page_words(html))).items())
        | "Sum trigram counts" >> beam.CombinePerKey(sum)
    )
    top_tri = trigram_counts | "Top trigrams" >> beam.combiners.Top.Of(
        TOP_N, key=rank_key, reverse=True)
    tie_note = (
        trigram_counts
        | "Trigram counts only" >> beam.Values()
        | "How many per count" >> beam.combiners.Count.PerElement()
        | "Highest count" >> beam.combiners.Top.Of(1, key=lambda kv: kv[0])
        | "Format tie note" >> beam.Map(format_tie_note)
    )

    # ---- write results ---------------------------------------------------
    write_text(top_in | "Format incoming" >> beam.Map(
        lambda r: format_ranking(f"TOP {TOP_N} FILES BY INCOMING LINKS", r, "links")),
        f"{output_dir}/top_incoming.txt", "incoming")
    write_text(top_out | "Format outgoing" >> beam.Map(
        lambda r: format_ranking(f"TOP {TOP_N} FILES BY OUTGOING LINKS", r, "links")),
        f"{output_dir}/top_outgoing.txt", "outgoing")
    write_text(top_tri | "Format trigrams" >> beam.Map(
        lambda r: format_ranking(f"TOP {TOP_N} WORD TRIGRAMS", r, "times")),
        f"{output_dir}/top_trigrams.txt", "trigrams")
    write_text(tie_note, f"{output_dir}/trigram_ties.txt", "tie note")
    write_text(
        pages | "Count files" >> beam.combiners.Count.Globally()
        | "Format file count" >> beam.Map(lambda n: f"Files processed: {n:,}"),
        f"{output_dir}/file_count.txt", "file count")


RESULT_FILES = ["file_count.txt", "top_incoming.txt", "top_outgoing.txt",
                "top_trigrams.txt", "trigram_ties.txt"]


def print_results(output_dir):
    """Read the result files back (local path or gs://) and print them."""
    for name in RESULT_FILES:
        with FileSystems.open(f"{output_dir}/{name}") as f:
            text = f.read().decode("utf-8").rstrip()
        print(("\n" if name != "file_count.txt" else "") + text)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="gs://cs528-amernor/pages/*",
                        help="file pattern to read (default: %(default)s)")
    parser.add_argument("--output", default="./output",
                        help="directory (local or gs://) for result files")
    args, beam_args = parser.parse_known_args(argv)
    output_dir = args.output.rstrip("/")

    options = PipelineOptions(beam_args)
    # Ship this module's functions to the Dataflow workers.
    options.view_as(SetupOptions).save_main_session = True
    runner = options.get_all_options().get("runner") or "DirectRunner"

    print(f"Runner : {runner}")
    print(f"Input  : {args.input}")
    print(f"Output : {output_dir}", flush=True)

    start = time.perf_counter()
    p = beam.Pipeline(options=options)
    build_pipeline(p, args.input, output_dir)
    result = p.run()
    result.wait_until_finish()
    elapsed = time.perf_counter() - start

    print("\n" + "=" * 60)
    print_results(output_dir)
    print("\n" + "=" * 60)
    print(f"Pipeline wall-clock time ({runner}): {elapsed:,.1f} s")
    job_id = getattr(result, "job_id", None)
    if callable(job_id):
        print(f"Dataflow job id: {job_id()}")


if __name__ == "__main__":
    main()
