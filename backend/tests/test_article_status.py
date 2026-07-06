import unittest

from app.models.article import ArticleStatus, article_status_db_label, article_status_public_value


class ArticleStatusTests(unittest.TestCase):
    def test_published_status_uses_database_enum_label_for_raw_sql(self):
        self.assertEqual(article_status_db_label(ArticleStatus.PUBLISHED), "PUBLISHED")

    def test_status_public_value_remains_lowercase_for_api_clients(self):
        self.assertEqual(article_status_public_value(ArticleStatus.PUBLISHED), "published")
        self.assertEqual(article_status_public_value("PUBLISHED"), "published")


if __name__ == "__main__":
    unittest.main()
