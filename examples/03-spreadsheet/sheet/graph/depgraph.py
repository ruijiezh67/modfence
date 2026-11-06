"""Dependency graph between hashable nodes (cells, in practice)."""

from collections import deque
from collections.abc import Hashable, Iterable
from typing import Generic, TypeVar

T = TypeVar("T", bound=Hashable)


class CycleError(Exception):
    """Raised when ordering fails.

    ``members`` are the nodes that could not be ordered (cycle members and
    anything downstream of them). ``ordered`` is the part that could be ordered.
    """

    def __init__(self, members: set, ordered: list) -> None:
        super().__init__(f"cycle among {len(members)} nodes")
        self.members = members
        self.ordered = ordered


class DependencyGraph(Generic[T]):
    """Edges point from a precedent (input) to its dependents (users)."""

    def __init__(self) -> None:
        self._precedents: dict[T, set[T]] = {}
        self._dependents: dict[T, set[T]] = {}

    def set_precedents(self, node: T, precedents: Iterable[T]) -> None:
        """Replace the inputs of ``node``."""
        for old in self._precedents.get(node, ()):
            self._dependents[old].discard(node)
        new = set(precedents)
        self._precedents[node] = new
        for p in new:
            self._dependents.setdefault(p, set()).add(node)

    def precedents_of(self, node: T) -> set[T]:
        """Direct inputs of ``node``."""
        return set(self._precedents.get(node, ()))

    def dependents_of(self, node: T) -> set[T]:
        """Nodes that directly use ``node``."""
        return set(self._dependents.get(node, ()))

    def descendants(self, node: T) -> set[T]:
        """All nodes that transitively depend on ``node``."""
        seen: set[T] = set()
        stack = [node]
        while stack:
            for dep in self._dependents.get(stack.pop(), ()):
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return seen

    def topological_order(self, nodes: Iterable[T]) -> list[T]:
        """Order ``nodes`` so every precedent comes before its dependents.

        Only edges between the given nodes count. Raises CycleError on a cycle.
        """
        subset = set(nodes)
        waiting = {n: len(self._precedents.get(n, set()) & subset) for n in subset}
        ready = deque(n for n, count in waiting.items() if count == 0)
        order: list[T] = []
        while ready:
            node = ready.popleft()
            order.append(node)
            for dep in self._dependents.get(node, ()):
                if dep in waiting:
                    waiting[dep] -= 1
                    if waiting[dep] == 0:
                        ready.append(dep)
        if len(order) < len(subset):
            raise CycleError(subset - set(order), order)
        return order
