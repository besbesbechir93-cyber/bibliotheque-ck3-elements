"""Verify every distributed JSON schema is syntactically valid JSON."""
import json
from pathlib import Path
import unittest


class SchemaSyntaxTests(unittest.TestCase):
    def test_all_schemas_parse(self):
        directory = Path(__file__).resolve().parents[1] / 'schemas'
        paths = sorted(directory.glob('*.schema.json'))
        self.assertGreater(len(paths), 1)
        for path in paths:
            with self.subTest(schema=path.name):
                self.assertIsInstance(json.loads(path.read_text(encoding='utf-8')), dict)


if __name__ == '__main__':
    unittest.main()
