import unittest

from sheet.graph.depgraph import CycleError, DependencyGraph


class GraphTests(unittest.TestCase):
    def chain(self):
        graph = DependencyGraph()
        graph.set_precedents("b", {"a"})
        graph.set_precedents("c", {"b", "a"})
        return graph

    def test_queries(self):
        graph = self.chain()
        self.assertEqual(graph.precedents_of("c"), {"a", "b"})
        self.assertEqual(graph.dependents_of("a"), {"b", "c"})
        self.assertEqual(graph.descendants("a"), {"b", "c"})

    def test_topological_order(self):
        order = self.chain().topological_order({"a", "b", "c"})
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("b"), order.index("c"))

    def test_replacing_precedents_removes_old_edges(self):
        graph = self.chain()
        graph.set_precedents("c", set())
        self.assertEqual(graph.dependents_of("b"), set())
        self.assertEqual(graph.descendants("a"), {"b"})

    def test_cycle_detected(self):
        graph = DependencyGraph()
        graph.set_precedents("a", {"b"})
        graph.set_precedents("b", {"a"})
        graph.set_precedents("c", {"b"})
        graph.set_precedents("d", set())
        with self.assertRaises(CycleError) as ctx:
            graph.topological_order({"a", "b", "c", "d"})
        self.assertEqual(ctx.exception.members, {"a", "b", "c"})
        self.assertEqual(ctx.exception.ordered, ["d"])

    def test_self_loop_is_a_cycle(self):
        graph = DependencyGraph()
        graph.set_precedents("a", {"a"})
        with self.assertRaises(CycleError):
            graph.topological_order({"a"})


if __name__ == "__main__":
    unittest.main()
