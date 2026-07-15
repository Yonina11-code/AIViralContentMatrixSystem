from app.api.articles import _apply_source_boundary_fallback, _normalize_claim_plan


SOURCE_MATERIALS = """
### 素材 1
- 标题：健康科普| 纠正饮食误区，守护血压平稳
- 来源：河北大学附属医院门诊部
- 摘录：少放酱油、味精和豆瓣酱。警惕那些吃起来不咸但钠含量爆表的隐形盐，比如方便面、薯片、挂面、饼干和各类腌制肉制品。多吃菠菜、香蕉、土豆等高钾食物，帮助身体排出多余的钠。
"""


def test_claim_plan_downgrades_unsupported_cold_dish_sauce_claims():
    decision = {
        "selected_topic": "凉拌菜里那勺盐，比你想象的可能要多",
        "angle": "凉拌菜的隐形盐可能来自酱料，生抽、蚝油、辣椒酱都要留意。",
        "claim_plan": {
            "core_claim": "凉拌菜的酱料可能含有较多钠。",
            "must_not_claim": [],
            "supported_by_source": True,
        },
    }

    plan = _normalize_claim_plan(decision, SOURCE_MATERIALS)

    assert plan["supported_by_source"] is False
    assert "凉拌菜" in plan["core_claim"]
    assert any("凉拌菜" in item and "营养结论" in item for item in plan["must_not_claim"])


def test_source_boundary_fallback_softens_cold_dish_sauce_overclaims():
    written = {
        "title": "凉拌菜里那勺盐，比你想象的可能要多",
        "summary": "凉拌菜里的盐可能比你想象中多，吃完口干和手指发胀说明钠可能偏高。",
        "body": """
## 酱料才是真正的“隐形盐大户”

有的生抽每15毫升含钠700多毫克，有的可能只有400多。凉拌菜的钠可能比一盘炒菜还多。

如果你吃完凉拌菜后，觉得口干、想喝水，或者第二天早上起来眼皮、手指有点发胀，那这一餐的钠可能偏高了。
""",
    }
    unsupported_claims = [
        "15毫升",
        "酱料才是真正的隐形盐大户",
        "凉拌菜的钠可能比一盘炒菜还多",
        "口干、想喝水，眼皮、手指有点发胀",
    ]

    fixed = _apply_source_boundary_fallback(written, unsupported_claims)
    combined = "\n".join([fixed["title"], fixed["summary"], fixed["body"]])

    assert "15毫升" not in combined
    assert "700多毫克" not in combined
    assert "400多" not in combined
    assert "隐形盐大户" not in combined
    assert "比一盘炒菜还多" not in combined
    assert "眼皮" not in combined
    assert "手指" not in combined
    assert "酱油、味精、豆瓣酱" in combined
