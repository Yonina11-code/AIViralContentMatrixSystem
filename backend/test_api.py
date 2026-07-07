import asyncio
import traceback
from app.database import async_session_factory
from app.api.articles import generate_article

async def test():
    async with async_session_factory() as db:
        try:
            res = await generate_article(domain="life_common_knowledge", db=db)
            print("Success res:", res)
        except Exception as e:
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
