from app.collectors.base import ContentItemData
from app import tasks


def _item(index: int) -> ContentItemData:
    return ContentItemData(
        title=f"素材 {index}",
        fingerprint=f"fp-{index}",
        domain="health_regimen",
    )


def test_candidate_fetch_limit_expands_manual_collection_window():
    assert tasks._candidate_fetch_limit(10) == 30
    assert tasks._candidate_fetch_limit(20) == 60
    assert tasks._candidate_fetch_limit(None) is None


def test_select_new_content_items_skips_existing_and_batch_duplicates(monkeypatch):
    monkeypatch.setattr(tasks, "_existing_fingerprints", lambda _: {"fp-1", "fp-3"})
    monkeypatch.setattr(tasks, "_existing_content_identity_keys", lambda _: set())
    items = [_item(1), _item(2), _item(2), _item(3), _item(4), _item(5)]

    selected = tasks._select_new_content_items(items, limit=2)

    assert [item.fingerprint for item in selected] == ["fp-2", "fp-4"]


def test_select_new_content_items_skips_existing_identity_with_changed_fingerprint(monkeypatch):
    existing_key = ("health_regimen", "wechat", "【健康科普】关于控糖的四大误区", "太仓市璜泾人民医院")
    monkeypatch.setattr(tasks, "_existing_fingerprints", lambda _: set())
    monkeypatch.setattr(tasks, "_existing_content_identity_keys", lambda _: {existing_key})
    item = ContentItemData(
        title="【健康科普】关于控糖的四大误区",
        source="wechat",
        source_name="太仓市璜泾人民医院",
        fingerprint="new-url-derived-fingerprint",
        domain="health_regimen",
    )

    selected = tasks._select_new_content_items([item], limit=10)

    assert selected == []


def test_per_keyword_limit_uses_expanded_candidate_count():
    assert tasks._per_keyword_limit(30, ["科学养生", "养生误区", "失眠调理"]) == 10
    assert tasks._per_keyword_limit(8, ["科学养生", "养生误区", "失眠调理"]) == 3
    assert tasks._per_keyword_limit(None, ["科学养生"]) is None
