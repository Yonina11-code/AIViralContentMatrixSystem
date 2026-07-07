import json
import re
from openai import AsyncOpenAI

from app.config import settings

def parse_llm_json(raw: str) -> dict:
    """从大语言模型返回的原始字符串中稳健提取并解析 JSON"""
    if not raw:
        return {}
    
    raw_str = raw.strip()
    
    # 1. 尝试直接解析（大模型只输出了纯 JSON）
    try:
        return json.loads(raw_str, strict=False)
    except json.JSONDecodeError:
        pass
        
    # 2. 尝试提取 ```json ... ``` 包裹的内容
    match = re.search(r"```json\s*(.*?)\s*```", raw_str, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip(), strict=False)
        except json.JSONDecodeError:
            pass
            
    # 3. 尝试提取最外层的 { ... } 内容
    match = re.search(r"(\{.*\})", raw_str, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip(), strict=False)
        except json.JSONDecodeError:
            pass
            
    raise json.JSONDecodeError("无法提取有效的 JSON 内容", raw, 0)

_client = None


def get_llm_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    return _client


async def llm_chat(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    client = get_llm_client()
    response = await client.chat.completions.create(
        model=model or settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
