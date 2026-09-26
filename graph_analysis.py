"""Graph construction and analysis, written from scratch in plain Python.

No graph library is used (no networkx / igraph / graph-tool / ...), and no
numeric library either: the graph is a list of adjacency lists and every
algorithm below is an ordinary loop over those lists.

    graph.out_links[i]  ->  list of node ids that page i links to
"""
import re
from collections import deque

# Matches href="target", HREF='target' or href=target (case-insensitive).
LINK_RE = re.compile(r"""href\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)


def parse_links(html):
    """Return the list of link targets in an HTML page, as file basenames.

    Links are kept exactly as they appear (duplicates are not removed), so
    C(X) in PageRank is the number of outgoing links written in the page.
    """
    return [target.rsplit("/", 1)[-1] for target in LINK_RE.findall(html)]


def _natural_key(name):
    """Sort key so that '2.html' comes before '10.html'."""
    return [int(tok) if tok.isdigit() else tok for tok in re.split(r"(\d+)", name)]


class Graph:
    """Directed graph stored as adjacency lists.

    Attributes:
        names       list of page names; position = node id
        n           number of nodes
        out_links   out_links[i] is the list of nodes page i links to
        out_degree  out_degree[i] = number of links on page i  (C(i))
        in_degree   in_degree[i]  = number of links pointing at page i
    """

    def __init__(self, names, out_links):
        self.names = list(names)
        self.n = len(self.names)
        self.out_links = [list(targets) for targets in out_links]
        self.out_degree = [len(targets) for targets in self.out_links]
        self.in_degree = [0] * self.n
        for targets in self.out_links:
            for v in targets:
                self.in_degree[v] += 1

    @property
    def num_edges(self):
        return sum(self.out_degree)

    @classmethod
    def from_edges(cls, n, edges, names=None):
        """Build a graph from a list of (source, target) integer pairs."""
        out_links = [[] for _ in range(n)]
        for src, dst in edges:
            out_links[src].append(dst)
        return cls(names or [str(i) for i in range(n)], out_links)


def build_graph(page_links):
    """Build a Graph from {page name: [linked page names]}.

    Links pointing to pages that are not in the collection are ignored.
    """
    names = sorted(page_links, key=_natural_key)
    index = {name: i for i, name in enumerate(names)}
    out_links = [
        [index[target] for target in page_links[name] if target in index]
        for name in names
    ]
    return Graph(names, out_links)


# ---------------------------------------------------------------- statistics

def _percentile(ordered, p):
    """p-th percentile of an already sorted list, by linear interpolation.

    The rank position is p/100 * (len - 1); when it falls between two samples
    the result is interpolated between them (the standard "linear" definition).
    """
    count = len(ordered)
    if count == 1:
        return float(ordered[0])
    position = (p / 100.0) * (count - 1)
    low = int(position)
    high = min(low + 1, count - 1)
    fraction = position - low
    return float(ordered[low]) + fraction * float(ordered[high] - ordered[low])


def degree_stats(values):
    """Average, median, max, min and quintiles (20/40/60/80th percentiles)."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("no values to summarise")
    total = 0.0
    for value in ordered:
        total += value
    return {
        "count": len(ordered),
        "average": total / len(ordered),
        "median": _percentile(ordered, 50),
        "max": ordered[-1],
        "min": ordered[0],
        "quintiles": [_percentile(ordered, p) for p in (20, 40, 60, 80)],
    }


# ------------------------------------------------------------------ PageRank

def pagerank(graph, damping=0.85, tol=0.005, max_iter=1000, fixed_iterations=None):
    """Iterative PageRank:  PR(A) = (1-d)/n + d * sum(PR(T)/C(T)) over T -> A.

    Starts from PR = 1/n and stops when the sum of all PageRanks changes by no
    more than `tol` (0.5% by default) relative to the previous iteration, which
    is the rule the assignment specifies.

    Pages with no out-links pass nothing on, so the total PageRank shrinks from
    one iteration to the next; that shrinkage is what the stopping rule sees.
    Note that the rule watches the total only: on a graph where every page has
    at least one out-link the total stays exactly 1.0, the measured change is
    zero, and the rule fires after a single iteration even though the
    individual scores are still far from their fixed point.

    Passing `fixed_iterations` runs exactly that many iterations and ignores
    the stopping rule; it is there to show how much the scores move afterwards.

    Returns (pr, iterations, sums) where sums[k] is the total PR after
    iteration k, and sums[0] is the initial total of 1.0.
    """
    n = graph.n
    pr = [1.0 / n] * n
    base = (1.0 - damping) / n
    limit = fixed_iterations if fixed_iterations else max_iter

    sums = [sum(pr)]
    iterations = 0
    for iterations in range(1, limit + 1):
        # Every page T sends PR(T) / C(T) along each of its links.  Summing
        # what arrives at page A gives PR(T1)/C(T1) + ... + PR(Tn)/C(Tn).
        incoming = [0.0] * n
        for t in range(n):
            if graph.out_degree[t]:
                share = pr[t] / graph.out_degree[t]
                for a in graph.out_links[t]:
                    incoming[a] += share
        pr = [base + damping * incoming[a] for a in range(n)]
        sums.append(sum(pr))
        if not fixed_iterations and abs(sums[-1] - sums[-2]) / sums[-2] <= tol:
            break
    return pr, iterations, sums


def top_k(scores, k):
    """Indices of the k highest scores (ties broken by lower node id)."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]


# ----------------------------------------------------------------- closeness

def bfs_distances(graph, source):
    """Hop distances from `source` following out-links; -1 means unreachable.

    Standard breadth-first search with a FIFO queue: nodes come off the queue
    in order of distance, so the first time a node is seen is along a shortest
    path.
    """
    n = graph.n
    dist = [-1] * n
    dist[source] = 0
    found = 1
    queue = deque([source])
    while queue:
        u = queue.popleft()
        for v in graph.out_links[u]:
            if dist[v] == -1:
                dist[v] = dist[u] + 1
                queue.append(v)
                found += 1
        if found == n:          # every node has its distance; nothing can change
            break
    return dist


def closeness_centrality(graph, progress=None):
    """Closeness centrality of every node, using distances along out-links.

    Runs one BFS from every node.  Uses the Wasserman-Faust form, which copes
    with nodes that cannot reach the whole graph:

        C(u) = (r / total_dist) * (r / (n - 1))

    where r is the number of nodes reachable from u (u itself excluded) and
    total_dist is the sum of hop distances from u to those r nodes.  When every
    node is reachable this is the textbook (n - 1) / total_dist.
    """
    n = graph.n
    scores = [0.0] * n
    if n < 2:
        return scores
    for u in range(n):
        dist = bfs_distances(graph, u)
        reachable = 0
        total_dist = 0
        for d in dist:
            if d > 0:
                reachable += 1
                total_dist += d
        if reachable:
            scores[u] = (reachable / total_dist) * (reachable / (n - 1))
        if progress and (u + 1) % progress == 0:
            print(f"  closeness: {u + 1}/{n} sources done", flush=True)
    return scores
