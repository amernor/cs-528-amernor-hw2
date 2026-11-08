# HW7 — Apache Beam / Cloud Dataflow

Builds on [HW2](../hw2/): processes the HTML pages stored in the HW2 Cloud Storage bucket.

## Tasks
1. Using Apache Beam on Cloud Dataflow, find and print:
   - the top 5 files with the most **incoming** links
   - the top 5 files with the most **outgoing** links
2. Using Apache Beam on Cloud Dataflow, find the top 5 most frequent **word trigrams**
   (consecutive word triplets) across the files in the bucket.
3. Run on both the local laptop (DirectRunner) and Cloud Dataflow (DataflowRunner) and
   report the respective runtimes.

## Deliverables
- PDF report: configuration/run steps, program output, explanation of the code
- GitHub link to the Python code (listed in the report)
