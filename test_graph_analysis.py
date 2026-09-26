"""Correctness tests on small hand-built graphs.

None of these tests touch the randomly generated 12K-page collection or the
GCS bucket: every graph here is written out by hand (or generated with a fixed
seed) and every expected value is either computed by hand in the comments or by
a deliberately naive reference implementation included in this file.
"""
import random

import pytest

from graph_analysis import (
    Graph,
    bfs_distances,
    build_graph,
    closeness_centrality,
    degree_stats,
    pagerank,
    parse_links,
    top_k,
)


# ---------------------------------------------------------------- parsing

def test_parse_links():
    html = '<a HREF="12.html">x</a><p><a href="dir/7.html">y</a><a href="12.html">z</a>'
    assert parse_links(html) == ["12.html", "7.html", "12.html"]


def test_parse_links_ignores_pages_without_links():
    assert parse_links("<html><body>no links here</body></html>") == []


def test_build_graph_degrees_and_missing_targets():
    graph = build_graph({
        "0.html": ["1.html", "2.html"],
        "1.html": ["2.html", "missing.html"],   # missing page is ignored
        "2.html": ["0.html"],
    })
    assert graph.names == ["0.html", "1.html", "2.html"]
    assert graph.out_links == [[1, 2], [2], [0]]
    assert graph.out_degree == [2, 1, 1]
    assert graph.in_degree == [1, 1, 2]
    assert graph.num_edges == 4


def test_build_graph_orders_names_numerically():
    graph = build_graph({"10.html": [], "2.html": [], "1.html": []})
    assert graph.names == ["1.html", "2.html", "10.html"]


# ------------------------------------------------------------- statistics

def test_degree_stats_odd_count():
    s = degree_stats([1, 2, 3, 4, 5])
    assert s["average"] == 3 and s["median"] == 3
    assert s["min"] == 1 and s["max"] == 5
    # position for the 20th percentile is 0.2 * 4 = 0.8, i.e. 1 + 0.8*(2-1)
    assert s["quintiles"] == pytest.approx([1.8, 2.6, 3.4, 4.2])


def test_degree_stats_even_count_interpolates_median():
    s = degree_stats([4, 1, 3, 2])           # unsorted input
    assert s["median"] == pytest.approx(2.5)
    assert s["average"] == pytest.approx(2.5)
    assert s["quintiles"] == pytest.approx([1.6, 2.2, 2.8, 3.4])


def test_degree_stats_handles_zeros_and_single_value():
    assert degree_stats([0, 0, 0])["average"] == 0
    s = degree_stats([7])
    assert s["median"] == 7 and s["quintiles"] == [7, 7, 7, 7]


def test_degree_stats_of_a_graph():
    graph = build_graph({"0.html": ["1.html"], "1.html": [], "2.html": ["1.html"]})
    assert degree_stats(graph.in_degree)["max"] == 2
    assert degree_stats(graph.out_degree)["min"] == 0


# --------------------------------------------------------------- PageRank

def naive_pagerank(n, edges, damping=0.85, tol=0.005, max_iter=1000):
    """Direct transcription of the assignment's formula, organised the other
    way round from the real code: it loops over each page A and looks up the
    pages T that point at it."""
    out_deg = [0] * n
    incoming = [[] for _ in range(n)]
    for s, d in edges:
        out_deg[s] += 1
        incoming[d].append(s)
    pr = [1.0 / n] * n
    for _ in range(max_iter):
        new = [(1 - damping) / n
               + damping * sum(pr[t] / out_deg[t] for t in incoming[a])
               for a in range(n)]
        old_sum, new_sum = sum(pr), sum(new)
        pr = new
        if abs(new_sum - old_sum) / old_sum <= tol:
            break
    return pr


def test_pagerank_cycle_is_uniform():
    graph = Graph.from_edges(3, [(0, 1), (1, 2), (2, 0)])
    pr, _, _ = pagerank(graph)
    assert pr == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_pagerank_hand_computed():
    # A=0 -> B, C ; B=1 -> C ; C=2 -> A.  No dangling pages, so the total PR
    # stays 1.0 and the 0.5% sum rule stops after one iteration:
    #   PR(A) = 0.05 + 0.85 * (1/3)             = 0.333333
    #   PR(B) = 0.05 + 0.85 * (1/3)/2           = 0.191667
    #   PR(C) = 0.05 + 0.85 * ((1/3)/2 + 1/3)   = 0.475000
    graph = Graph.from_edges(3, [(0, 1), (0, 2), (1, 2), (2, 0)])
    pr, iterations, _ = pagerank(graph)
    assert iterations == 1
    assert pr == pytest.approx([0.333333, 0.191667, 0.475], abs=1e-6)
    assert top_k(pr, 1)[0] == 2


def test_pagerank_sum_rule_fires_immediately_without_dangling_pages():
    # Every page here has an out-link, so the total PageRank stays exactly 1.0
    # and the "sum changed by <= 0.5%" rule is satisfied after one iteration
    # however tight the threshold is.  This documents the rule's blind spot.
    graph = Graph.from_edges(3, [(0, 1), (0, 2), (1, 2), (2, 0)])
    _, iterations, sums = pagerank(graph, tol=1e-12)
    assert iterations == 1
    assert sums == pytest.approx([1.0, 1.0])


def test_pagerank_fixed_iterations_reach_the_fixed_point():
    # Run far past the stopping rule; the scores must then satisfy the formula
    # exactly, with C(0) = 2 for page 0's two out-links.
    graph = Graph.from_edges(3, [(0, 1), (0, 2), (1, 2), (2, 0)])
    pr, iterations, _ = pagerank(graph, fixed_iterations=300)
    assert iterations == 300
    assert sum(pr) == pytest.approx(1.0)
    for a, incoming in {0: [(2, 1)], 1: [(0, 2)], 2: [(0, 2), (1, 1)]}.items():
        expected = 0.05 + 0.85 * sum(pr[t] / c for t, c in incoming)
        assert pr[a] == pytest.approx(expected)


def test_pagerank_matches_naive_and_stopping_rule():
    # Page 3 has no out-links, so PR "leaks" and several iterations are needed.
    edges = [(0, 1), (0, 2), (1, 2), (2, 0), (2, 3), (4, 0)]
    graph = Graph.from_edges(5, edges)
    pr, iterations, sums = pagerank(graph)
    assert pr == pytest.approx(naive_pagerank(5, edges))
    assert iterations > 1
    changes = [abs(b - a) / a for a, b in zip(sums, sums[1:])]
    assert changes[-1] <= 0.005                  # stopped when the rule was met
    assert all(c > 0.005 for c in changes[:-1])  # and not one iteration earlier


def test_pagerank_matches_naive_on_small_random_graph():
    rng = random.Random(42)
    n = 40
    edges = [(s, rng.randrange(n)) for s in range(n) for _ in range(rng.randint(0, 6))]
    pr, _, _ = pagerank(Graph.from_edges(n, edges))
    assert pr == pytest.approx(naive_pagerank(n, edges))


def test_pagerank_counts_duplicate_links_in_the_out_degree():
    # 0 links to 1 twice, so C(0) = 2 and half of PR(0) flows along each link.
    graph = Graph.from_edges(2, [(0, 1), (0, 1)])
    pr, _, _ = pagerank(graph, tol=1e-12)
    assert graph.out_degree == [2, 0]
    assert pr[1] == pytest.approx(0.075 + 0.85 * pr[0])


# -------------------------------------------------------------- closeness

def undirected(n, pairs):
    return Graph.from_edges(n, [e for a, b in pairs for e in ((a, b), (b, a))])


def naive_closeness(n, edges):
    """Independent reference: BFS written with a dict and list.pop(0)."""
    adj = [[] for _ in range(n)]
    for s, d in edges:
        adj[s].append(d)
    scores = []
    for source in range(n):
        dist = {source: 0}
        queue = [source]
        while queue:
            u = queue.pop(0)
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        reached = [d for v, d in dist.items() if v != source]
        r = len(reached)
        scores.append((r / sum(reached)) * (r / (n - 1)) if r else 0.0)
    return scores


def test_bfs_distances_on_a_chain():
    graph = Graph.from_edges(5, [(0, 1), (1, 2), (2, 3)])   # node 4 isolated
    assert bfs_distances(graph, 0) == [0, 1, 2, 3, -1]


def test_bfs_distances_takes_the_shortest_route():
    # 0 -> 1 -> 2 -> 3 and a shortcut 0 -> 3: node 3 must be at distance 1.
    graph = Graph.from_edges(4, [(0, 1), (1, 2), (2, 3), (0, 3)])
    assert bfs_distances(graph, 0) == [0, 1, 2, 1]


def test_bfs_distances_follows_link_direction():
    graph = Graph.from_edges(3, [(0, 1), (1, 2)])
    assert bfs_distances(graph, 2) == [-1, -1, 0]


def test_closeness_star():
    # Center 0: distance 1 to all 4 leaves -> 4/4 = 1.0
    # Leaf: 1 to center, 2 to each other leaf -> 4/7
    graph = undirected(5, [(0, 1), (0, 2), (0, 3), (0, 4)])
    c = closeness_centrality(graph)
    assert top_k(c, 1)[0] == 0
    assert c == pytest.approx([1.0, 4 / 7, 4 / 7, 4 / 7, 4 / 7])


def test_closeness_path():
    # 0-1-2-3-4: distance sums are 10, 7, 6, 7, 10 -> closeness 4/sum
    graph = undirected(5, [(0, 1), (1, 2), (2, 3), (3, 4)])
    c = closeness_centrality(graph)
    assert top_k(c, 1)[0] == 2
    assert c == pytest.approx([0.4, 4 / 7, 4 / 6, 4 / 7, 0.4])


def test_closeness_with_unreachable_nodes():
    # Directed 0 -> 1 -> 2.  Node 0 reaches 2 nodes (distance sum 3):
    #   (2/3) * (2/2) = 0.6667;  node 1 reaches 1 node: (1/1) * (1/2) = 0.5
    graph = Graph.from_edges(3, [(0, 1), (1, 2)])
    c = closeness_centrality(graph)
    assert c == pytest.approx([2 / 3, 0.5, 0.0])
    assert top_k(c, 1)[0] == 0


def test_closeness_two_disconnected_triangles():
    # Each component is a 3-cycle: 2 nodes reachable, distances 1 and 2.
    #   (2/3) * (2/5) = 0.2666...   for every node
    graph = Graph.from_edges(6, [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)])
    assert closeness_centrality(graph) == pytest.approx([(2 / 3) * (2 / 5)] * 6)


def test_closeness_isolated_node_scores_zero():
    graph = Graph.from_edges(3, [(0, 1)])
    assert closeness_centrality(graph)[2] == 0.0


def test_closeness_directed_ring():
    # In a one-way ring of n nodes every node sees distances 1, 2, ..., n-1,
    # so the sum is n(n-1)/2 and closeness is (n-1) / (n(n-1)/2) = 2/n.
    n = 50
    graph = Graph.from_edges(n, [(i, (i + 1) % n) for i in range(n)])
    assert closeness_centrality(graph) == pytest.approx([2 / n] * n)


@pytest.mark.parametrize("seed", [0, 1, 2, 7, 99])
def test_closeness_matches_naive_reference_on_random_graphs(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 60)
    edges = [(s, rng.randrange(n)) for s in range(n) for _ in range(rng.randint(0, 4))]
    graph = Graph.from_edges(n, edges)
    assert closeness_centrality(graph) == pytest.approx(naive_closeness(n, edges))


# -------------------------------------------------------------------- misc

def test_top_k_orders_and_breaks_ties_by_node_id():
    assert top_k([0.1, 0.5, 0.5, 0.2], 3) == [1, 2, 3]
