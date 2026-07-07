import asyncio
from datetime import datetime
from sqlalchemy import select
from app.database import async_session_factory
from app.models.domain import Domain

custom_domains = [
    {
        "id": "home_hacks",
        "label": "家居收纳与清洁",
        "description": "专注于日常家居清洁技巧、空间收纳艺术与实用的生活窍门。",
        "folo_keywords": ["家居收纳", "去污妙招", "清洁死角", "衣物洗涤窍门", "省空间收纳"],
        "search_keywords": ["收纳技巧", "去污妙招", "衣物去渍", "家务省力", "厨房去油污"],
        "rss_feed_urls": []
    },
    {
        "id": "food_safety",
        "label": "菜场智慧与食品安全",
        "description": "关注食材挑选、食物储存技巧与避坑指南，科普食品安全知识。",
        "folo_keywords": ["食材挑选", "防腐剂误区", "剩菜保存", "农副产品防坑", "伪健康食品", "食品安全科普"],
        "search_keywords": ["蔬菜农残", "买肉防坑", "水果挑选", "临期食品", "食物相克谣言"],
        "rss_feed_urls": []
    },
    {
        "id": "smart_living",
        "label": "家电妙用与数码避坑",
        "description": "解锁智能家电的隐藏功能，提供家庭用电省电攻略和日常设备维护。",
        "folo_keywords": ["空调省电", "路由器摆放", "家电清洁", "冰箱除异味", "省电窍门"],
        "search_keywords": ["家电清洗", "空调省电", "网速慢排查", "热水器维护", "数码避坑"],
        "rss_feed_urls": []
    },
    {
        "id": "safety_first",
        "label": "防骗与家庭急救",
        "description": "科普社会新型诈骗套路，提供突发情况下的急救和居家安全防范知识。",
        "folo_keywords": ["新型诈骗", "海姆立克急救", "家庭用火用电安全", "老年人防骗", "突发疾病自救"],
        "search_keywords": ["冒充客服诈骗", "家庭用气安全", "中风前兆自救", "防溺水急救"],
        "rss_feed_urls": []
    }
]

async def insert():
    async with async_session_factory() as session:
        added_count = 0
        for d_data in custom_domains:
            # 检查是否已存在
            existing = await session.get(Domain, d_data["id"])
            if existing:
                print(f"Domain '{d_data['label']}' ({d_data['id']}) already exists. Skipping.")
                continue
            
            d = Domain(
                id=d_data["id"],
                label=d_data["label"],
                description=d_data["description"],
                folo_keywords=d_data["folo_keywords"],
                search_keywords=d_data["search_keywords"],
                rss_feed_urls=d_data["rss_feed_urls"],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(d)
            added_count += 1
            print(f"Inserting domain: {d_data['label']}")
        
        if added_count > 0:
            await session.commit()
            print(f"Successfully added {added_count} new domains.")
        else:
            print("No new domains were added.")

if __name__ == "__main__":
    asyncio.run(insert())
