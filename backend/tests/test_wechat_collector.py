import unittest

from app.collectors.wechat_collector import WeChatArticleCollector


class WeChatArticleCollectorTests(unittest.TestCase):
    def setUp(self):
        self.collector = WeChatArticleCollector()

    def test_parse_sogou_search_results_extracts_title_summary_and_link(self):
        html = """
        <ul>
          <li id="sogou_vr_11002601_box_0">
            <h3><a href="/link?url=abc&amp;type=2">冬病夏治&middot;顺势养阳</a></h3>
            <p class="txt-info">三伏天养生科普摘要</p>
          </li>
        </ul>
        """

        results = self.collector.parse_sogou_search_results(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "冬病夏治·顺势养阳")
        self.assertEqual(results[0]["summary"], "三伏天养生科普摘要")
        self.assertEqual(results[0]["url"], "https://weixin.sogou.com/link?url=abc&type=2")

    def test_parse_sogou_redirect_url_rebuilds_obfuscated_mp_link(self):
        html = """
        <script>
          setTimeout(function () {
            var url = '';
            url += 'https://mp.';
            url += 'weixin.qq.c';
            url += 'om/s?src=11';
            url += '&timestamp=1783593561';
            url.replace("@", "");
            window.location.replace(url)
          }, 100);
        </script>
        """

        url = self.collector.parse_sogou_redirect_url(html)

        self.assertEqual(url, "https://mp.weixin.qq.com/s?src=11&timestamp=1783593561")

    def test_parse_wechat_article_extracts_content_metadata_and_fingerprint(self):
        html = """
        <html>
          <head>
            <meta property="og:title" content="夏季防暑养生科普" />
            <meta name="description" content="讲好健康科普" />
          </head>
          <body>
            <span class="rich_media_meta rich_media_meta_nickname" id="profileBt">
              <a id="js_name">健康科普号</a>
            </span>
            <script>
              var msg_title = '夏季防暑养生科普'.html(false);
              var msg_desc = htmlDecode("讲好健康科普");
              var msg_cdn_url = "https://mmbiz.qpic.cn/cover.jpg";
            </script>
            <script>
              var appmsg_info = {
                create_time: '2026-07-09 17:46'
              };
            </script>
            <div id="js_content">
              <p>第一段：注意补水。</p>
              <p>第二段：科学使用空调。</p>
            </div>
            <script>window.__after = true;</script>
          </body>
        </html>
        """

        item = self.collector.parse_wechat_article(
            html,
            article_url="https://mp.weixin.qq.com/s/example",
            domain="health_regimen",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.title, "夏季防暑养生科普")
        self.assertEqual(item.source, "wechat")
        self.assertEqual(item.source_name, "健康科普号")
        self.assertEqual(item.summary, "讲好健康科普")
        self.assertIn("wechat", item.tags)
        self.assertTrue(any(t.startswith("quality:") for t in item.tags))
        self.assertIn("topic:健康科普", item.tags)
        self.assertEqual(item.domain, "health_regimen")
        self.assertEqual(item.published_at.year, 2026)
        self.assertIn("第一段：注意补水。", item.body)
        self.assertIn("第二段：科学使用空调。", item.body)
        self.assertIsNotNone(item.fingerprint)

    def test_wechat_fingerprint_ignores_ephemeral_signed_url(self):
        html = """
        <html><body>
          <a id="js_name">太仓市璜泾人民医院</a>
          <script>
            var msg_title = '【健康科普】关于控糖的四大误区'.html(false);
            var msg_desc = htmlDecode("控糖误区科普");
          </script>
          <script>var appmsg_info = { create_time: '2026-07-09 17:46' };</script>
          <div id="js_content">
            <p>同一篇文章正文第一段。</p>
            <p>同一篇文章正文第二段。</p>
          </div><script></script>
        </body></html>
        """

        first = self.collector.parse_wechat_article(
            html,
            article_url="https://mp.weixin.qq.com/s?src=11&timestamp=1&signature=aaa&new=1",
            domain="health_regimen",
        )
        second = self.collector.parse_wechat_article(
            html,
            article_url="https://mp.weixin.qq.com/s?src=11&timestamp=2&signature=bbb&new=1",
            domain="health_regimen",
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_quality_evaluation_rewards_credible_science_article(self):
        item = self.collector.parse_wechat_article(
            """
            <html><body>
              <a id="js_name">中国中医药报官方号</a>
              <script>
                var msg_title = '糖尿病饮食误区科普'.html(false);
                var msg_desc = htmlDecode("医生科普饮食误区");
              </script>
              <script>var appmsg_info = { create_time: '2025-05-08 10:00' };</script>
              <div id="js_content">
                <p>本文来自正规医疗科普，介绍糖尿病患者常见饮食误区。</p>
                <p>建议结合医生指导，关注主食摄入、膳食纤维和规律运动。</p>
              </div><script></script>
            </body></html>
            """,
            article_url="https://mp.weixin.qq.com/s/good",
            domain="health_regimen",
        )

        quality = self.collector.evaluate_quality(item)

        self.assertGreaterEqual(quality["score"], 75)
        self.assertIn("饮食误区", quality["topics"])
        self.assertTrue(self.collector.is_search_collectable(item))

    def test_quality_evaluation_filters_low_trust_pseudoscience_article(self):
        item = self.collector.parse_wechat_article(
            """
            <html><body>
              <a id="js_name">祖传偏方秘方大全</a>
              <script>
                var msg_title = '神奇秘方根治百病'.html(false);
                var msg_desc = htmlDecode("每天免费分享偏方");
              </script>
              <script>var appmsg_info = { create_time: '2017-01-01 10:00' };</script>
              <div id="js_content">
                <p>祖传偏方可以治愈多种疾病，三天见效，包治疑难杂症。</p>
                <p>神奇特效方法不用看医生。</p>
              </div><script></script>
            </body></html>
            """,
            article_url="https://mp.weixin.qq.com/s/bad",
            domain="health_regimen",
        )

        quality = self.collector.evaluate_quality(item)

        self.assertLess(quality["score"], 45)
        self.assertIn("偏方", quality["risks"])
        self.assertFalse(self.collector.is_search_collectable(item))


if __name__ == "__main__":
    unittest.main()
