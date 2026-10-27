"""S7 全站收藏 + 学习轨迹接口回归测试。

覆盖
----
1. 收藏 CRUD：新增（幂等）/ 列表 / 类型筛选 / 关键词 / check / toggle / 删除（404）
2. 类型校验：非法 item_type 返回 422
3. 学习轨迹：GET /api/growth/timeline 返回结构完整；连续打卡与仪表盘同源

隔离说明：走 conftest 的 kaoyan_test 测试库；收藏数据自造自清。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def fav_payload():
    return {
        "item_type": "document",
        "item_id": 880001,
        "title": "测试收藏-高数讲义",
        "snippet": "第三章 微分中值定理",
        "meta": {"subject": "数学"},
    }


@pytest.fixture
def cleanup_fav(client, fav_payload):
    yield
    client.delete(f"/api/favorites/{fav_payload['item_type']}/{fav_payload['item_id']}")


class TestFavoritesCRUD:
    def test_add_and_check(self, client, fav_payload, cleanup_fav):
        r = client.post("/api/favorites", json=fav_payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True

        # check
        r = client.get(
            "/api/favorites/check",
            params={"item_type": fav_payload["item_type"], "item_id": fav_payload["item_id"]},
        )
        assert r.json()["favorited"] is True

    def test_add_idempotent(self, client, fav_payload, cleanup_fav):
        client.post("/api/favorites", json=fav_payload)
        r = client.post("/api/favorites", json=fav_payload)  # 重复收藏不报错
        assert r.status_code == 200

        r = client.get("/api/favorites", params={"item_type": "document"})
        rows = [x for x in r.json()["items"] if x["item_id"] == fav_payload["item_id"]]
        assert len(rows) == 1, "重复收藏不得产生重复行"

    def test_toggle_on_off(self, client, fav_payload):
        r = client.post("/api/favorites/toggle", json=fav_payload)
        assert r.json()["favorited"] is True
        r = client.post("/api/favorites/toggle", json=fav_payload)
        assert r.json()["favorited"] is False
        # 清理兜底（toggle off 已删）

    def test_list_filter_and_search(self, client, fav_payload, cleanup_fav):
        client.post("/api/favorites", json=fav_payload)
        r = client.get("/api/favorites", params={"q": "微分中值"})
        items = [x for x in r.json()["items"] if x["item_id"] == fav_payload["item_id"]]
        assert len(items) == 1
        assert items[0]["title"] == fav_payload["title"]
        assert items[0]["meta"] == fav_payload["meta"]

    def test_invalid_type_422(self, client):
        r = client.post("/api/favorites", json={"item_type": "hacker", "item_id": 1})
        assert r.status_code == 422

    def test_delete_404(self, client):
        r = client.delete("/api/favorites/document/99999999")
        assert r.status_code == 404

    def test_delete_ok(self, client, fav_payload):
        client.post("/api/favorites", json=fav_payload)
        r = client.delete(f"/api/favorites/{fav_payload['item_type']}/{fav_payload['item_id']}")
        assert r.status_code == 200
        r = client.get(
            "/api/favorites/check",
            params={"item_type": fav_payload["item_type"], "item_id": fav_payload["item_id"]},
        )
        assert r.json()["favorited"] is False


class TestGrowthTimeline:
    def test_structure(self, client):
        r = client.get("/api/growth/timeline", params={"days": 7})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days"] == 7
        assert isinstance(body["timeline"], list)
        assert isinstance(body["subject_breakdown"], list)
        assert body["streak_days"] >= 0
        # active_days 从 2026-10-16 起改由日活台账（services/study_calendar）给出，
        # 与「事件流水里有几天的日子」不再是同一个数：study_events 是埋点流，
        # 台账读事实表，某天可能只有埋点而未达有效学习门槛。
        assert 0 <= body["active_days"] <= body["days"]
        for row in body["timeline"]:
            assert set(row) >= {"date", "events", "graded", "correct", "study_seconds"}
            if row["graded"]:
                assert row["accuracy"] is not None

    def test_streak_is_one_number_across_endpoints(self, client):
        """连续打卡在产品里只能有一个答案。

        历史坑：成长页按 study_events 自数日期 + 跨零点宽限，仪表盘按日活台账，
        同一用户两处不同。本用例把三个出口钉死成同一个数（D-02 口径唯一）。
        """
        tl = client.get("/api/growth/timeline", params={"days": 7}).json()
        gs = client.get("/api/growth/summary").json()
        dash = client.get("/api/dashboard/summary").json()
        assert tl["streak_days"] == gs["stats"]["streak_days"] == dash["kpi"]["streak"]["current"]
        # 活跃天数同源且时间窗是历史全量的子集：窗口内不可能多于全量
        assert tl["active_days"] <= gs["stats"]["active_days"]
