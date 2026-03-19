"""
AI Chat API - 专注对话（DeepSeek / OpenAI-compatible）：

- 路由
  - POST /api/ai/chat         非流式对话，返回完整 reply
  - POST /api/ai/chat/stream  流式对话（SSE），逐段推送 delta

- 请求体（两者一致）
  - message: str                用户输入（必填）
  - context: str                页面上下文（home/backtest/trading/strategy_run）
  - history: [{role, content}]  短期对话历史（可选，自动截断）

- 响应
  - /chat:
    - reply: str
    - model: str
    - usage: dict（若上游返回）
  - /chat/stream（SSE）：
    - data: {"delta": "..."}   # 增量片段
    - data: [DONE]             # 结束标记
    - data: {"error": "..."}   # 异常（前端应提示）

- 约束（强约定）
  - 仅使用 DeltaFStation 概念/页面操作/本项目 API；不主动推荐其他量化框架（Backtrader 等）。
  - 禁止实盘下单：仅允许模拟/仿真相关建议。
"""

from __future__ import annotations

import json
import time
import sys

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from backend.core.llm.deepseek_client import DeepSeekClient

ai_bp = Blueprint("ai", __name__)


def _system_prompt(context: str, *, provider: str, base_url: str) -> str:
    ctx = (context or "home").strip().lower()
    ctx_name = {
        "backtest": "策略回测页面",
        "trading": "手动交易页面",
        "strategy_run": "策略运行页面",
        "home": "主页",
    }.get(ctx, "当前页面")

    return (
        "You are DeltaFStation AI assistant.\n"
        f"Current UI context: {ctx_name}.\n"
        f"Model provider: {provider} (OpenAI-compatible API at {base_url}).\n"
        "- Use ONLY DeltaFStation concepts, UI actions, and this project's APIs.\n"
        "- Do NOT proactively mention or recommend other quant frameworks/libraries (e.g., Backtrader, Zipline, vn.py, QuantConnect).\n"
        "- If the user explicitly asks for alternatives, briefly compare but keep DeltaFStation as the primary solution.\n"
        "- Be concise and actionable.\n"
        "- If user asks to place real-money trades, refuse; only paper/simulation is allowed.\n"
        "- If you are uncertain, ask a clarifying question.\n"
        "- If user asks which LLM/model you are using, answer truthfully using the provided model name.\n"
    )


def _normalize_history(history: object, max_items: int = 20):
    if not isinstance(history, list):
        return []
    out = []
    for item in history[-max_items:]:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").strip()
        content = item.get("content")
        if role not in ("user", "assistant", "system"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out


def _client_from_app() -> DeepSeekClient:
    api_key = (current_app.config.get("DEEPSEEK_API_KEY") or "").strip() or None
    base_url = (current_app.config.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").strip()
    model = (current_app.config.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
    timeout = float(current_app.config.get("DEEPSEEK_TIMEOUT") or 60.0)
    max_retries = int(current_app.config.get("DEEPSEEK_MAX_RETRIES") or 2)
    return DeepSeekClient(api_key=api_key, base_url=base_url, model=model, timeout=timeout, max_retries=max_retries)


def _provider() -> str:
    return (current_app.config.get("DEEPSEEK_PROVIDER") or "DeepSeek").strip()


def _build_messages(*, context: str, client: DeepSeekClient, history: list, message: str) -> list:
    provider = _provider()
    return [
        {"role": "system", "content": _system_prompt_with_model(context, provider=provider, base_url=client.base_url, model=client.model)},
        *history,
        {"role": "user", "content": message},
    ]


def _system_prompt_with_model(context: str, *, provider: str, base_url: str, model: str) -> str:
    return _system_prompt(context, provider=provider, base_url=base_url) + f"Model name: {model}\n"


def _safe_console_text(text: str) -> str:
    """
    Windows consoles often use GBK/CP936 and can crash on Unicode output.
    Convert to a representation that always prints without raising UnicodeEncodeError.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(enc, errors="backslashreplace").decode(enc, errors="strict")
    except Exception:
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8", errors="strict")


@ai_bp.route("/chat", methods=["POST"])
def chat():
    """非流式对话接口。body: message, context?, history?"""
    payload = request.get_json() or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    context = payload.get("context") or "home"
    history = _normalize_history(payload.get("history"), max_items=20)

    client = _client_from_app()
    messages = _build_messages(context=context, client=client, history=history, message=message)

    try:
        t0 = time.time()
        result = client.chat(messages)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    """流式对话接口（SSE）。body: message, context?, history?"""
    payload = request.get_json() or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    context = payload.get("context") or "home"
    history = _normalize_history(payload.get("history"), max_items=20)
    client = _client_from_app()
    messages = _build_messages(context=context, client=client, history=history, message=message)

    def generate():
        t0 = time.time()
        try:
            for token in client.stream(messages):
                yield f"data: {json.dumps({'delta': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            _ = t0  # keep local for future debugging if needed
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

