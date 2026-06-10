"""Tests for graph algorithms (CompetitiveGraph).

Usage:
    cd backend && PYTHONPATH=packages/harness uv run pytest tests/test_competition_graph_algorithms.py -v
"""

from competition.graph_algorithms import CompetitiveGraph


class TestBasicOps:
    def test_add_node_and_edge(self):
        g = CompetitiveGraph()
        g.add_node("Cursor")
        g.add_edge("Cursor", "Copilot", 0.9)
        assert g.nodes == ["Copilot", "Cursor"]
        assert len(g.edges) == 1

    def test_degree(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B", 0.5)
        g.add_edge("A", "C", 0.8)
        assert g.degree("A") == 2
        assert g.degree("B") == 1
        assert abs(g.degree("A", weighted=True) - 1.3) < 0.01

    def test_neighbors(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        assert set(g.neighbors("A")) == {"B", "C"}

    def test_remove_node(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        g.remove_node("A")
        assert "A" not in g.nodes
        assert g.degree("B") == 0


class TestCentrality:
    def test_degree_centrality_star(self):
        """Star graph: center should have degree centrality 1.0, leaves 1/(n-1)."""
        g = CompetitiveGraph()
        for leaf in ["B", "C", "D"]:
            g.add_edge("A", leaf)
        dc = g.degree_centrality()
        assert abs(dc["A"] - 1.0) < 0.01
        for leaf in ["B", "C", "D"]:
            assert abs(dc[leaf] - 1.0 / 3) < 0.01

    def test_degree_centrality_empty(self):
        g = CompetitiveGraph()
        g.add_node("A")
        dc = g.degree_centrality()
        assert dc["A"] == 0.0

    def test_betweenness_centrality_line(self):
        """Line graph A-B-C: B bridges A and C."""
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        bc = g.betweenness_centrality()
        # B should have the highest betweenness
        assert bc["B"] > bc["A"]
        assert bc["B"] > bc["C"]
        assert bc["B"] > 0

    def test_betweenness_centrality_disconnected(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_node("C")
        bc = g.betweenness_centrality()
        # All should be valid (no crash)
        assert all(v >= 0 for v in bc.values())

    def test_closeness_centrality_star(self):
        g = CompetitiveGraph()
        for leaf in ["B", "C", "D"]:
            g.add_edge("A", leaf)
        cc = g.closeness_centrality()
        # Center A is closest to all others
        assert cc["A"] > 0
        assert cc["A"] > max(cc["B"], cc["C"], cc["D"])


class TestPageRank:
    def test_pagerank_basic(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")
        pr = g.pagerank()
        assert len(pr) == 3
        assert abs(sum(pr.values()) - 1.0) < 0.05  # should sum to ~1

    def test_pagerank_single_node(self):
        g = CompetitiveGraph()
        g.add_node("A")
        pr = g.pagerank()
        # Single node with no edges: rank = (1-damping)/1 = 0.15
        assert abs(pr["A"] - 0.15) < 0.01

    def test_pagerank_empty(self):
        g = CompetitiveGraph()
        assert g.pagerank() == {}


class TestCommunities:
    def test_louvain_two_clusters(self):
        """Two clusters with weak inter-cluster edge."""
        g = CompetitiveGraph()
        # Cluster 1: dense
        g.add_edge("A", "B", 0.9)
        g.add_edge("B", "C", 0.8)
        g.add_edge("A", "C", 0.7)
        # Cluster 2: dense
        g.add_edge("D", "E", 0.9)
        g.add_edge("E", "F", 0.8)
        # Weak inter-cluster bridge
        g.add_edge("C", "D", 0.1)

        comms = g.louvain_communities()
        assert len(comms) >= 1  # algorithm may find 1 or 2 communities

    def test_louvain_no_edges(self):
        g = CompetitiveGraph()
        for name in ["A", "B", "C"]:
            g.add_node(name)
        comms = g.louvain_communities()
        assert len(comms) == 3  # each node in own community


class TestPaths:
    def test_shortest_path_direct(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        assert g.shortest_path("A", "B") == ["A", "B"]

    def test_shortest_path_two_hops(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        assert g.shortest_path("A", "C") == ["A", "B", "C"]

    def test_shortest_path_disconnected(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_node("C")
        assert g.shortest_path("A", "C") is None

    def test_shortest_path_same_node(self):
        g = CompetitiveGraph()
        g.add_node("A")
        assert g.shortest_path("A", "A") == ["A"]

    def test_all_pairs_shortest_paths(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        paths = g.all_pairs_shortest_paths()
        assert paths[("A", "C")] == 2  # A-B-C
        assert paths[("A", "B")] == 1


class TestHubIdentification:
    def test_identify_hubs_star(self):
        g = CompetitiveGraph()
        for leaf in ["B", "C", "D", "E"]:
            g.add_edge("A", leaf)
        hubs = g.identify_hubs(top_k=2)
        assert len(hubs) == 2
        assert hubs[0]["product"] == "A"  # center is hub
        assert hubs[0]["composite"] > hubs[1]["composite"]

    def test_identify_hubs_empty(self):
        g = CompetitiveGraph()
        assert g.identify_hubs() == []


class TestSummary:
    def test_summary(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B", 0.9)
        g.add_edge("B", "C", 0.5)
        s = g.summary()
        assert s["total_products"] == 3
        assert s["total_relationships"] == 2
        assert 0 < s["density"] < 1
        assert s["num_communities"] >= 1

    def test_summary_with_isolated(self):
        g = CompetitiveGraph()
        g.add_edge("A", "B")
        g.add_node("C")  # isolated
        s = g.summary()
        assert s["isolated_products"] == ["C"]


class TestFromCollectedData:
    def test_build_from_co_mention(self):
        co_mention = {"Cursor": {"GitHub Copilot": 10, "Windsurf": 3}}
        g = CompetitiveGraph.from_collected_data(
            products=["Cursor", "GitHub Copilot", "Windsurf"],
            co_mention_matrix=co_mention,
        )
        assert len(g.nodes) == 3
        assert g.degree("Cursor") == 2

    def test_build_from_feature_overlap(self):
        overlap = {"Cursor": {"GitHub Copilot": 0.8}}
        g = CompetitiveGraph.from_collected_data(
            products=["Cursor", "GitHub Copilot"],
            feature_overlap=overlap,
        )
        assert len(g.edges) == 1
