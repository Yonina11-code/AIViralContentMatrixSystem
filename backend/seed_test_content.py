import asyncio
from datetime import datetime
import hashlib
import uuid

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.models.content_item import ContentItem
from app.database import Base

DATABASE_URL = "postgresql+asyncpg://helloworld@localhost:5433/aiviral"
engine = create_async_engine(DATABASE_URL, echo=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def seed():
    # 模拟数据
    materials = [
        {
            "title": "经常感到疲劳？这可能是身体发出的求救信号！",
            "body": """现代人工作压力大，经常感到疲倦。但如果长期休息后仍无法缓解疲劳，这很可能是身体在发出求救信号。
1. 肝脏受损：肝脏是排毒器官，受损时人会觉得极度乏力、食欲不振、皮肤发黄。
2. 甲状腺功能减退：甲状腺素分泌不足会导致身体代谢减慢，产生慢性疲劳、体重增加、怕冷。
3. 贫血：红细胞携氧能力下降，使身体各器官缺氧，导致乏力、头晕、脸色苍白。
4. 慢性疲劳综合征：长期处于高压状态，免疫系统受损。
专家建议：如果经常感到莫名疲劳，持续超过两周，应及时就医检查。同时，保持规律作息，适当运动，多吃新鲜蔬果。""",
            "summary": "长期疲劳可能不是简单的累，而是肝脏、甲状腺或贫血等身体问题发出的求救信号，应引起警惕并及时检查。",
            "url": "https://example.com/health/fatigue",
            "source": "rss",
            "source_name": "健康科普中心",
            "author": "科普君",
            "domain": "life_common_knowledge"
        },
        {
            "title": "身体在“求救”的5个表现，千万别硬撑",
            "body": """很多大病在爆发前，身体其实已经给过我们很多次机会了。这5个表现是身体的“求救信号”：
1. 莫名胸闷、心慌：可能是心脏供血不足，甚至是心梗前兆，绝对不能忽视。
2. 伤口愈合缓慢：可能是血糖过高、糖尿病，或者免疫功能低下。
3. 长期失眠、焦虑：大脑和神经系统超负荷运转，长期下去会导致多器官功能紊乱。
4. 异常消瘦：如果没有刻意减肥，体重在短时间内大幅下降，需警惕糖尿病、甲亢或恶性肿瘤。
5. 频繁抽筋：不仅是缺钙，还可能是局部血液循环不良，或静脉曲张。
身体就像一台机器，零件出了问题就会发出警报。关注 these 信号，预防大于治疗。""",
            "summary": "胸闷心慌、伤口愈合慢、异常消瘦、长期失眠、频繁抽筋，这5个身体发出的异常警报千万不要硬撑，需及早检查排查疾病。",
            "url": "https://example.com/health/warning-signs",
            "source": "search_engine",
            "source_name": "医学百事通",
            "author": "张医生",
            "domain": "life_common_knowledge"
        }
    ]

    async with async_session_factory() as session:
        for m in materials:
            fp_str = f"{m['title']}{m['url']}"
            fingerprint = hashlib.md5(fp_str.encode()).hexdigest()
            
            # 检查是否已存在
            res = await session.execute(
                text("SELECT id FROM content_items WHERE fingerprint = :fp"),
                {"fp": fingerprint}
            )
            if res.scalar():
                print(f"Skipping: {m['title']} (already exists)")
                continue

            ci = ContentItem(
                id=str(uuid.uuid4()),
                title=m['title'],
                body=m['body'],
                summary=m['summary'],
                url=m['url'],
                source=m['source'],
                source_name=m['source_name'],
                author=m['author'],
                tags=["健康", "养生", "科普"],
                domain=m['domain'],
                fingerprint=fingerprint,
                collected_at=datetime.utcnow()
            )
            session.add(ci)
            print(f"Seeded: {m['title']}")
        await session.commit()

if __name__ == "__main__":
    asyncio.run(seed())
