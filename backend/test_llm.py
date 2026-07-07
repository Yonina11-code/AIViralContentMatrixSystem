import asyncio
from app.llm import llm_chat

async def test():
    try:
        res = await llm_chat("You are a helpful assistant", "Hello, test!")
        print("Success:", res)
    except Exception as e:
        print("Error details:", str(e))
        print("Error type:", type(e))

if __name__ == "__main__":
    asyncio.run(test())
