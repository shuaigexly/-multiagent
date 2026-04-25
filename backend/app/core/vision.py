"""Multi-modal vision — 把图像/截图通过 vision LLM 转成文字描述。

适配任何兼容 OpenAI vision 协议的模型：
  - GLM-4V
  - GPT-4V / gpt-4o
  - DeepSeek-VL
  - Qwen-VL

环境变量：
  LLM_VISION_MODEL  → 启用 vision；缺省（空）则 analyze_image 返回 None（降级文本管线）
  LLM_VISION_BASE_URL / LLM_VISION_API_KEY → 单独配置（缺省回退到 LLM_BASE_URL / LLM_API_KEY）

API：
  analyze_image(url_or_base64, prompt=...) → str | None
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Optional

from app.core.budget import BudgetExceeded, check_budget, record_usage
from app.core.settings import get_llm_api_key, get_llm_base_url
from app.core.url_safety import UnsafeURL, fetch_public_url_bytes, validate_public_http_url

logger = logging.getLogger(__name__)


_DEFAULT_VISION_PROMPT = (
    "请精确描述这张图片的关键信息，按下列格式：\n"
    "1) 图片类型（截图/图表/表格/手写/照片）\n"
    "2) 核心数据（指标、数字、关键词；如有图表则提取所有数值）\n"
    "3) 关键文本（可读的中英文文字逐字摘录，按位置）\n"
    "4) 5 个有助于业务决策的洞察点\n"
    "限 800 字，不要寒暄、不要重复、不要附加任何免责声明。"
)


def _model() -> Optional[str]:
    return os.getenv("LLM_VISION_MODEL", "").strip() or None


def _base_url() -> str:
    return os.getenv("LLM_VISION_BASE_URL", "").strip() or get_llm_base_url()


def _api_key() -> str:
    return os.getenv("LLM_VISION_API_KEY", "").strip() or get_llm_api_key()


def _is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


async def _fetch_as_base64(url: str) -> Optional[str]:
    try:
        content, _headers, _final_url = await fetch_public_url_bytes(
            url,
            max_bytes=5 * 1024 * 1024,
            timeout=20.0,
            allowed_content_prefixes=("image/",),
        )
        return base64.b64encode(content).decode("ascii")
    except UnsafeURL as exc:
        logger.warning("vision: unsafe image url rejected url=%s err=%s", url[:80], exc)
        return None
    except Exception as exc:
        logger.warning("vision: fetch image failed url=%s err=%s", url[:80], exc)
        return None


async def analyze_image(
    image: str,
    *,
    prompt: str = _DEFAULT_VISION_PROMPT,
    max_tokens: int = 1200,
) -> Optional[str]:
    """对单张图片做 vision 分析。

    image 可以是：
      - http(s) URL
      - data:image/png;base64,xxx
      - 纯 base64 字符串（自动包成 data: URI）

    LLM_VISION_MODEL 未配置 → 返回 None（调用方应优雅降级）。
    """
    model = _model()
    if not model:
        logger.debug("vision skipped — LLM_VISION_MODEL not set")
        return None
    if not image:
        return None

    try:
        await check_budget(strict=True)
    except BudgetExceeded as exc:
        logger.warning("vision refused — budget exceeded: %s", exc)
        return None

    # 统一为 data URI
    if _is_url(image):
        try:
            image_url_block: dict = {"url": validate_public_http_url(image)}
        except UnsafeURL as exc:
            logger.warning("vision: unsafe image url rejected: %s", exc)
            return None
    elif image.startswith("data:image"):
        image_url_block = {"url": image}
    else:
        # 假设是裸 base64
        image_url_block = {"url": f"data:image/png;base64,{image}"}

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=_api_key(), base_url=_base_url())
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": image_url_block},
                        ],
                    }
                ],
                temperature=0.2,
                max_tokens=max_tokens,
            ),
            timeout=45.0,
        )
    except Exception as exc:
        logger.warning("vision call failed: %s", exc)
        return None

    usage = getattr(resp, "usage", None)
    if usage is not None:
        try:
            await record_usage(
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            )
        except Exception:
            pass

    content = ""
    try:
        content = (resp.choices[0].message.content or "").strip()
    except Exception:
        return None
    return content or None
