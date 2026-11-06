import unittest

from sheet.functions.registry import Registry, default_registry


class FunctionTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def call(self, name, values):
        return self.registry.get(name)(values)

    def test_builtins(self):
        self.assertEqual(self.call("SUM", [1, 2, 3]), 6)
        self.assertEqual(self.call("MIN", [4, 2, 9]), 2)
        self.assertEqual(self.call("MAX", [4, 2, 9]), 9)
        self.assertEqual(self.call("AVG", [2, 4]), 3)

    def test_empty_inputs(self):
        self.assertEqual(self.call("SUM", []), 0)
        with self.assertRaises(ZeroDivisionError):
            self.call("AVG", [])

    def test_lookup_is_case_insensitive(self):
        self.assertIs(self.registry.get("sum"), self.registry.get("SUM"))
        self.assertIsNone(self.registry.get("NOPE"))

    def test_register_custom(self):
        registry = Registry()
        registry.register("count", len)
        self.assertEqual(registry.get("COUNT")([1, 2]), 2)
        self.assertEqual(registry.names(), ["COUNT"])


if __name__ == "__main__":
    unittest.main()
