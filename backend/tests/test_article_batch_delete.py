import unittest

from app.api.articles import _normalize_batch_delete_ids


class ArticleBatchDeleteTests(unittest.TestCase):
    def test_normalize_batch_delete_ids_strips_blanks_and_deduplicates(self):
        ids = _normalize_batch_delete_ids([" a ", "", "b", "a", "  c"])

        self.assertEqual(ids, ["a", "b", "c"])

    def test_normalize_batch_delete_ids_rejects_empty_result(self):
        with self.assertRaises(ValueError):
            _normalize_batch_delete_ids(["", "  "])


if __name__ == "__main__":
    unittest.main()
