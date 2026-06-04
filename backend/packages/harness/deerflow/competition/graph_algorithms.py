"""Competitive landscape graph algorithms.

Lightweight pure-Python implementations for small graphs (< 50 nodes).
No external dependencies — operates on collected_data adjacency structures.

Nodes = products/companies, Edges = competitive relationships
(weighted by co-mention frequency, feature overlap, or pricing similarity).

Usage:
    from deerflow.competition.graph_algorithms import CompetitiveGraph

    g = CompetitiveGraph()
    g.add_node("Cursor")
    g.add_node("GitHub Copilot")
    g.add_edge("Cursor", "GitHub Copilot", weight=0.8)

    centrality = g.degree_centrality()
    communities = g.louvain_communities()
    pagerank = g.pagerank()
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


class CompetitiveGraph:
    """Weighted undirected graph for competitive landscape analysis.

    Each node is a product name. Each edge has a weight 0-1 indicating
    competitive intensity (how often they're co-mentioned / feature-similar).
    """

    def __init__(self) -> None:
        self._adj: dict[str, dict[str, float]] = defaultdict(dict)
        self._nodes: set[str] = set()

    def add_node(self, name: str) -> None:
        self._nodes.add(name)
        self._adj.setdefault(name, {})

    def add_edge(self, u: str, v: str, weight: float = 1.0) -> None:
        self._nodes.add(u)
        self._nodes.add(v)
        self._adj[u][v] = weight
        self._adj[v][u] = weight

    def remove_node(self, name: str) -> None:
        self._nodes.discard(name)
        self._adj.pop(name, None)
        for neighbors in self._adj.values():
            neighbors.pop(name, None)

    @property
    def nodes(self) -> list[str]:
        return sorted(self._nodes)

    @property
    def edges(self) -> list[tuple[str, str, float]]:
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str, float]] = []
        for u in self._adj:
            for v, w in self._adj[u].items():
                key = (u, v) if u < v else (v, u)
                if key not in seen:
                    seen.add(key)
                    result.append((u, v, w))
        return result

    def neighbors(self, node: str) -> list[str]:
        return sorted(self._adj.get(node, {}).keys())

    def degree(self, node: str, weighted: bool = False) -> float:
        edges = self._adj.get(node, {})
        if weighted:
            return sum(edges.values())
        return len(edges)

    # ── 中心度算法 ──────────────────────────────────────────────────

    def degree_centrality(self) -> dict[str, float]:
        """度中心度：归一化到 [0, 1]。

        高分 = 竞品分析中"最常被对标"的产品（行业制高点）。
        例如：Cursor 度中心度高 → 它被最多工具对标。
        """
        n = len(self._nodes) - 1
        if n <= 0:
            return {node: 0.0 for node in self._nodes}
        return {node: self.degree(node) / n for node in self._nodes}

    def betweenness_centrality(self) -> dict[str, float]:
        """介数中心度（Brandes 算法，无权重版）。

        高分 = 竞品关系网中"不可绕过的桥梁"。
        例如：某个产品是 AI 工具和传统 IDE 之间唯一的交集点。
        """
        cb: dict[str, float] = {v: 0.0 for v in self._nodes}
        for s in self._nodes:
            # BFS from s
            stack: list[str] = []
            pred: dict[str, list[str]] = {v: [] for v in self._nodes}
            sigma: dict[str, int] = {v: 0 for v in self._nodes}
            sigma[s] = 1
            dist: dict[str, int] = {v: -1 for v in self._nodes}
            dist[s] = 0
            queue: list[str] = [s]

            while queue:
                v = queue.pop(0)
                stack.append(v)
                for w in self._adj[v]:
                    if dist[w] < 0:
                        queue.append(w)
                        dist[w] = dist[v] + 1
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

            delta: dict[str, float] = {v: 0.0 for v in self._nodes}
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
                if w != s:
                    cb[w] += delta[w]

        # Normalize
        n = len(self._nodes)
        if n > 2:
            norm = (n - 1) * (n - 2)
            cb = {v: cb[v] / norm for v in cb}
        return cb

    def closeness_centrality(self) -> dict[str, float]:
        """接近中心度：基于最短路径之和的倒数。

        高分 = 离所有其他竞品都近（信息传播快）。
        """
        cc: dict[str, float] = {}
        n = len(self._nodes)
        if n <= 1:
            return {v: 1.0 for v in self._nodes}

        for v in self._nodes:
            dist_sum = 0.0
            reachable = 0
            # BFS
            visited: set[str] = {v}
            queue: list[tuple[str, int]] = [(v, 0)]
            while queue:
                cur, d = queue.pop(0)
                for w in self._adj[cur]:
                    if w not in visited:
                        visited.add(w)
                        dist_sum += d + 1
                        reachable += 1
                        queue.append((w, d + 1))

            if reachable == 0:
                cc[v] = 0.0
            else:
                cc[v] = reachable / dist_sum

        return cc

    # ── PageRank ────────────────────────────────────────────────────

    def pagerank(
        self,
        damping: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> dict[str, float]:
        """PageRank 算法。

        高分 = 被重要竞品对标的产品。
        阻尼因子 0.85 = 标准值。

        适用于：识别竞品生态中"谁最有影响力"。
        """
        n = len(self._nodes)
        if n == 0:
            return {}

        nodes = sorted(self._nodes)
        pr = {v: 1.0 / n for v in nodes}

        for _ in range(max_iter):
            new_pr: dict[str, float] = {}
            diff = 0.0

            for v in nodes:
                rank = (1 - damping) / n
                for u in self._adj[v]:
                    out_deg = self.degree(u)  # unweighted for PR
                    if out_deg > 0:
                        rank += damping * pr[u] / out_deg
                new_pr[v] = rank
                diff += abs(new_pr[v] - pr[v])

            pr = new_pr
            if diff < tol:
                break

        return pr

    # ── 社区检测（Louvain 简化版）───────────────────────────────────

    def louvain_communities(
        self, max_passes: int = 20
    ) -> list[list[str]]:
        """Louvain 社区检测（简化版）。

        将产品自动聚类为"赛道"（AI 编程工具 / 视频平台 / CRM...）。
        基于模块度最大化，使用局部移动启发式。

        返回: [[product_names_in_community_1], [community_2], ...]
        """
        m = sum(self._adj[u][v] for u in self._adj for v in self._adj[u]) / 2.0
        if m == 0:
            return [[v] for v in self._nodes]

        # Initialize each node in its own community
        partition: dict[str, int] = {v: i for i, v in enumerate(sorted(self._nodes))}
        node_to_comm: dict[str, int] = dict(partition)

        def _modularity() -> float:
            q = 0.0
            for u in self._adj:
                for v, w in self._adj[u].items():
                    if node_to_comm[u] == node_to_comm[v]:
                        k_u = self.degree(u, weighted=True)
                        k_v = self.degree(v, weighted=True)
                        q += w - (k_u * k_v) / (2 * m)
            return q / (2 * m)

        for _ in range(max_passes):
            improved = False
            nodes = list(self._nodes)
            import random
            random.shuffle(nodes)  # heuristic: random order avoids bias

            for v in nodes:
                # Find best community among neighbors
                comm_weights: dict[int, float] = defaultdict(float)
                for u, w in self._adj[v].items():
                    comm_weights[node_to_comm[u]] += w

                orig_comm = node_to_comm[v]
                best_comm = orig_comm
                best_gain = 0.0
                k_v = self.degree(v, weighted=True)

                for comm, w_in in comm_weights.items():
                    if comm == orig_comm:
                        continue
                    # Simplified modularity gain
                    k_comm = sum(
                        self.degree(x, weighted=True)
                        for x in self._nodes
                        if node_to_comm[x] == comm
                    )
                    gain = w_in / m - (k_v * k_comm) / (2 * m * m)
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = comm

                if best_comm != orig_comm:
                    node_to_comm[v] = best_comm
                    improved = True

            if not improved:
                break

        # Group by community
        comm_map: dict[int, list[str]] = defaultdict(list)
        for v, c in node_to_comm.items():
            comm_map[c].append(v)

        # Sort communities by size (largest first)
        return sorted(comm_map.values(), key=len, reverse=True)

    # ── 路径分析 ────────────────────────────────────────────────────

    def shortest_path(self, source: str, target: str) -> list[str] | None:
        """BFS 最短路径。

        返回: 从 source 到 target 的节点列表（含两端），或 None。

        适用于：找出两个看似无关的竞品之间的间接竞争链。
        例如：Notion → Slack → Teams — Notion 和 Teams 不直接竞争，
        但都通过 Slack 产生间接竞争关系。
        """
        if source not in self._nodes or target not in self._nodes:
            return None
        if source == target:
            return [source]

        visited: dict[str, str | None] = {source: None}
        queue: list[str] = [source]

        while queue:
            cur = queue.pop(0)
            for neighbor in self._adj[cur]:
                if neighbor not in visited:
                    visited[neighbor] = cur
                    queue.append(neighbor)
                    if neighbor == target:
                        # Reconstruct path
                        path: list[str] = []
                        node: str | None = target
                        while node is not None:
                            path.append(node)
                            node = visited[node]
                        path.reverse()
                        return path
        return None

    def all_pairs_shortest_paths(self) -> dict[tuple[str, str], int]:
        """Floyd-Warshall 全对最短路径（无权）。

        返回: {(source, target): distance}，不可达的不在 dict 中。
        """
        nodes = sorted(self._nodes)
        n = len(nodes)
        idx = {v: i for i, v in enumerate(nodes)}

        # Initialize distance matrix
        INF = 999999
        dist = [[INF] * n for _ in range(n)]
        for i in range(n):
            dist[i][i] = 0
        for u in self._adj:
            for v in self._adj[u]:
                i, j = idx[u], idx[v]
                dist[i][j] = 1

        # Floyd-Warshall
        for k in range(n):
            for i in range(n):
                for j in range(n):
                    if dist[i][k] + dist[k][j] < dist[i][j]:
                        dist[i][j] = dist[i][k] + dist[k][j]

        result: dict[tuple[str, str], int] = {}
        for i in range(n):
            for j in range(n):
                if i != j and dist[i][j] < INF:
                    result[(nodes[i], nodes[j])] = dist[i][j]
        return result

    # ── 中心产品识别（综合指标）─────────────────────────────────────

    def identify_hubs(self, top_k: int = 3) -> list[dict[str, Any]]:
        """综合识别竞品生态中的"中心产品"。

        综合度中心度、介数中心度、PageRank 三个维度。
        返回 top_k 个产品及其各项得分。
        """
        dc = self.degree_centrality()
        bc = self.betweenness_centrality()
        pr = self.pagerank()

        # Normalize each to [0, 1] for fair combination
        def _norm(d: dict[str, float]) -> dict[str, float]:
            mx = max(d.values()) if d else 1.0
            return {k: v / mx if mx > 0 else 0.0 for k, v in d.items()}

        n_dc = _norm(dc)
        n_bc = _norm(bc)
        n_pr = _norm(pr)

        scores: list[dict[str, Any]] = []
        for v in self._nodes:
            composite = n_dc[v] * 0.4 + n_bc[v] * 0.35 + n_pr[v] * 0.25
            scores.append({
                "product": v,
                "composite": round(composite, 4),
                "degree_centrality": round(dc[v], 4),
                "betweenness_centrality": round(bc[v], 4),
                "pagerank": round(pr[v], 4),
            })

        scores.sort(key=lambda x: x["composite"], reverse=True)
        return scores[:top_k]

    def summary(self) -> dict[str, Any]:
        """生成竞品图的一页摘要，用于嵌入报告。"""
        hubs = self.identify_hubs(top_k=3)
        communities = self.louvain_communities()

        return {
            "total_products": len(self._nodes),
            "total_relationships": len(self.edges),
            "density": (
                round(
                    2 * len(self.edges) / (len(self._nodes) * (len(self._nodes) - 1)),
                    4,
                )
                if len(self._nodes) > 1
                else 0.0
            ),
            "num_communities": len(communities),
            "communities": [
                {"products": comm, "size": len(comm)} for comm in communities
            ],
            "hub_products": hubs,
            "isolated_products": [
                v for v in self._nodes if self.degree(v) == 0
            ],
        }

    # ── 从 collected_data 构建图 ────────────────────────────────────

    @classmethod
    def from_collected_data(
        cls,
        products: list[str],
        co_mention_matrix: dict[str, dict[str, int]] | None = None,
        feature_overlap: dict[str, dict[str, float]] | None = None,
    ) -> "CompetitiveGraph":
        """从采集数据构建竞品关系图。

        Args:
            products: 产品名列表。
            co_mention_matrix: {product: {other_product: co_mention_count}}。
            feature_overlap: {product: {other_product: overlap_score 0-1}}。
        """
        g = cls()
        for p in products:
            g.add_node(p)

        # Add edges from co-mention data
        if co_mention_matrix:
            for u, others in co_mention_matrix.items():
                for v, count in others.items():
                    if u in products and v in products:
                        # Normalize: log scale to dampen extremes
                        weight = min(math.log(count + 1) / math.log(11), 1.0)
                        g.add_edge(u, v, weight)

        # Merge feature overlap (average with existing weights)
        if feature_overlap:
            for u, others in feature_overlap.items():
                for v, overlap in others.items():
                    if u in products and v in products:
                        existing = g._adj[u].get(v, 0.0)
                        g.add_edge(u, v, (existing + overlap) / 2.0)

        return g
