"""微信公众号发布模块"""

import json
from datetime import date, timedelta

import httpx

from app.config import settings


class WeChatPublisher:
    """微信公众号图文消息发布器 + 数据统计回拉"""

    def __init__(self):
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self.base_url = "https://api.weixin.qq.com/cgi-bin"
        self.datacube_url = "https://api.weixin.qq.com/datacube"

    async def _get_access_token(self) -> str:
        """获取 access_token（自动缓存，带过期刷新）"""
        import time
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/token",
                params={
                    "grant_type": "client_credential",
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                },
            )
            data = resp.json()
            self._access_token = data.get("access_token", "")
            # access_token 有效期 7200 秒，提前 300 秒刷新
            expires_in = data.get("expires_in", 7200)
            self._token_expires_at = time.time() + expires_in - 300
            return self._access_token

    async def publish_article(self, title: str, body: str, summary: str | None = None) -> dict:
        """发布一篇图文消息"""
        # 本地测试模式：当微信凭证为占位符时模拟发布成功
        if 'your_wechat' in settings.wechat_app_id or 'your_wechat' in settings.wechat_app_secret:
            import uuid
            return {
                "success": True,
                "media_id": f"local_{uuid.uuid4().hex[:12]}",
                "local_mode": True,
                "info": "本地测试模式，文章已标记为已发布（未实际调用微信API）",
            }

        token = await self._get_access_token()
        if not token:
            return {"success": False, "error": "access_token 获取失败"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/draft/add",
                params={"access_token": token},
                json={
                    "articles": [
                        {
                            "title": title,
                            "content": body,
                            "digest": summary or title,
                            "need_open_comment": 1,
                            "only_fans_can_comment": 0,
                        }
                    ]
                },
            )
            data = resp.json()
            if data.get("errcode") == 0:
                return {"success": True, "media_id": data.get("media_id")}
            else:
                return {"success": False, "error": data.get("errmsg", "未知错误"), "errcode": data.get("errcode")}

    async def fetch_article_stats(self, begin_date: str, end_date: str) -> list[dict]:
        """从微信公众号拉取文章阅读统计数据（getarticlesummary）

        一次最多查 1 天，内部自动按天逐日查询并合并结果。
        返回列表，每项包含：
            ref_date, msgid, title,
            int_page_read_user, int_page_read_count,
            share_user, share_count, add_to_fav_user, etc.
        """
        token = await self._get_access_token()
        if not token:
            return []

        # 生成日期列表
        start = date.fromisoformat(begin_date)
        end = date.fromisoformat(end_date)
        all_results = []
        seen_titles = set()

        async with httpx.AsyncClient() as client:
            current = start
            while current <= end:
                ds = current.isoformat()
                resp = await client.post(
                    f"{self.datacube_url}/getarticlesummary",
                    params={"access_token": token},
                    json={"begin_date": ds, "end_date": ds},
                )
                data = resp.json()
                if data.get("errcode", 0) != 0 or "list" not in data:
                    current += timedelta(days=1)
                    continue

                for item in data["list"]:
                    title = item.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_results.append(item)
                    elif title and title in seen_titles:
                        # 合并相同文章的统计数据（取最新一条）
                        for existing in all_results:
                            if existing.get("title") == title:
                                existing.update(item)
                                break

                current += timedelta(days=1)

        return all_results

    async def fetch_user_read_sources(self, begin_date: str, end_date: str, msgid: str) -> list[dict]:
        """拉取某篇文章的阅读来源分布（getuserread）

        返回各渠道的阅读人数：
            user_source: 0=公众号消息, 1=聊天会话, 2=朋友圈,
                         3=公众号主页, 4=推荐, 5=搜一搜, 6=其他
        """
        token = await self._get_access_token()
        if not token:
            return []

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.datacube_url}/getuserread",
                params={"access_token": token},
                json={"begin_date": begin_date, "end_date": end_date, "msgid": msgid},
            )
            data = resp.json()
            if data.get("errcode", 0) == 0:
                return data.get("list", [])
            return []
