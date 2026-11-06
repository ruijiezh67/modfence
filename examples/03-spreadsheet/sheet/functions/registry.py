"""A registry mapping function names to implementations."""

from collections.abc import Callable, Sequence

from sheet.functions import builtins

Function = Callable[[Sequence[float]], float]


class Registry:
    """Case-insensitive name to function lookup."""

    def __init__(self) -> None:
        self._functions: dict[str, Function] = {}

    def register(self, name: str, func: Function) -> None:
        """Add or replace a function."""
        self._functions[name.upper()] = func

    def get(self, name: str) -> Function | None:
        """Return the function, or None if unknown."""
        return self._functions.get(name.upper())

    def names(self) -> list[str]:
        """Sorted names of all registered functions."""
        return sorted(self._functions)


def default_registry() -> Registry:
    """A registry holding SUM, MIN, MAX and AVG."""
    registry = Registry()
    registry.register("SUM", builtins.fn_sum)
    registry.register("MIN", builtins.fn_min)
    registry.register("MAX", builtins.fn_max)
    registry.register("AVG", builtins.fn_avg)
    return registry
