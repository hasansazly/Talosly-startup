"""Wallet interaction graph reputation model for Talosly."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


def graph_reputation_score(
    transactions: list[dict[str, Any]],
    wallet: str,
    flagged_wallets: set[str] | None = None,
) -> float:
    """Score a wallet from 0-1 using weighted interactions and 2-hop penalties."""
    flagged = {item.lower() for item in (flagged_wallets or set())}
    wallet_key = wallet.lower()
    if not wallet_key:
        return 0.5

    try:
        import networkx as nx

        graph = nx.DiGraph()
        for tx in transactions:
            source = str(tx.get("from_address") or tx.get("from") or "").lower()
            target = str(tx.get("to_address") or tx.get("to") or "").lower()
            if not source or not target:
                continue
            weight = _float(tx.get("tx_value", tx.get("value_eth", tx.get("value", 1))), default=1.0)
            graph.add_edge(source, target, weight=max(weight, 0.000001))

        if wallet_key not in graph:
            return 0.5
        ranks = nx.pagerank(graph, weight="weight")
        base = _normalize_rank(ranks.get(wallet_key, 0.0), ranks.values())
        penalty = _flagged_penalty_networkx(graph, wallet_key, flagged)
        return round(max(0.0, min(1.0, base * (1.0 - penalty))), 4)
    except ImportError:
        graph = _adjacency(transactions)
        degree = len(graph.get(wallet_key, set()))
        max_degree = max((len(edges) for edges in graph.values()), default=1)
        base = degree / max(max_degree, 1)
        penalty = _flagged_penalty_fallback(graph, wallet_key, flagged)
        return round(max(0.0, min(1.0, base * (1.0 - penalty))), 4)


def combine_reputation(existing_reputation: float, graph_score: float, weight: float = 0.30) -> float:
    """Blend graph reputation with existing reputation signals."""
    existing = max(0.0, min(1.0, existing_reputation))
    graph = max(0.0, min(1.0, graph_score))
    return round(existing * (1.0 - weight) + graph * weight, 4)


def _adjacency(transactions: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Build an undirected fallback adjacency map."""
    graph: dict[str, set[str]] = defaultdict(set)
    for tx in transactions:
        source = str(tx.get("from_address") or tx.get("from") or "").lower()
        target = str(tx.get("to_address") or tx.get("to") or "").lower()
        if source and target:
            graph[source].add(target)
            graph[target].add(source)
    return graph


def _flagged_penalty_networkx(graph: Any, wallet: str, flagged: set[str]) -> float:
    """Return a penalty for flagged wallets within two hops using networkx."""
    if not flagged:
        return 0.0
    neighbors = set(graph.successors(wallet)) | set(graph.predecessors(wallet))
    if neighbors & flagged:
        return 0.6
    second_hop: set[str] = set()
    for neighbor in neighbors:
        second_hop.update(graph.successors(neighbor))
        second_hop.update(graph.predecessors(neighbor))
    return 0.3 if second_hop & flagged else 0.0


def _flagged_penalty_fallback(graph: dict[str, set[str]], wallet: str, flagged: set[str]) -> float:
    """Return a penalty for flagged wallets within two hops without networkx."""
    if not flagged:
        return 0.0
    queue: deque[tuple[str, int]] = deque([(wallet, 0)])
    seen = {wallet}
    while queue:
        node, distance = queue.popleft()
        if distance > 0 and node in flagged:
            return 0.6 if distance == 1 else 0.3
        if distance == 2:
            continue
        for neighbor in graph.get(node, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, distance + 1))
    return 0.0


def _normalize_rank(rank: float, ranks: Any) -> float:
    """Normalize one PageRank value into a 0-1 score."""
    values = list(ranks)
    if not values:
        return 0.5
    high = max(values)
    low = min(values)
    if high == low:
        return 0.5
    return (rank - low) / (high - low)


def _float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float with a safe fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
