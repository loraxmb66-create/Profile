"""Telegram bot sử dụng Google AI Studio (Gemini) để trả lời tin nhắn.

Yêu cầu:
    pip install python-telegram-bot google-generativeai

Cấu hình thông qua biến môi trường:
    TELEGRAM_BOT_TOKEN  – mã token bot Telegram
    GOOGLE_API_KEY      – API key của Google AI Studio (Gemini)
    GOOGLE_MODEL        – (tuỳ chọn) tên model, mặc định "gemini-1.5-flash"

Chạy:
    python telegram_bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict
from functools import partial

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    import google.generativeai as genai
except ImportError as exc:  # pragma: no cover - rõ ràng lỗi phụ thuộc
    raise SystemExit(
        "Thư viện 'google-generativeai' chưa được cài đặt. "
        "Chạy: pip install google-generativeai"
    ) from exc

LOGGER = logging.getLogger(__name__)


REQUIRED_ENV_VARS: Dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "Token bot Telegram lấy từ @BotFather.",
    "GOOGLE_API_KEY": "API key tạo tại https://aistudio.google.com/app/apikey.",
}


def _ensure_required_env() -> Dict[str, str]:
    """Đọc các biến môi trường bắt buộc và báo chi tiết nếu thiếu."""

    missing: list[str] = []
    values: Dict[str, str] = {}
    for name, description in REQUIRED_ENV_VARS.items():
        value = os.environ.get(name)
        if value:
            values[name] = value
            continue
        missing.append(f"  • {name}: {description}")

    if missing:
        help_lines = [
            "Thiếu biến môi trường bắt buộc:",
            *missing,
            "",
            "Cách thiết lập tạm thời:",
            "  • Windows (cmd):     set TÊN=GIÁ_TRỊ",
            "  • Windows (PowerShell): $Env:TÊN=\"GIÁ_TRỊ\"",
            "  • macOS/Linux (bash): export TÊN=GIÁ_TRỊ",
            "",
            "Sau đó chạy lại: python telegram_bot.py",
        ]
        raise RuntimeError("\n".join(help_lines))

    return values


def _init_gemini(api_key: str, model_name: str) -> genai.GenerativeModel:
    genai.configure(api_key=api_key)
    LOGGER.info("Sử dụng model Gemini: %s", model_name)
    return genai.GenerativeModel(model_name)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Xin chào! Gửi cho tôi câu hỏi của bạn và tôi sẽ hỏi Google AI Studio (Gemini) giúp bạn."
    )


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, model: genai.GenerativeModel
) -> None:
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    if not user_text:
        return

    loop = asyncio.get_running_loop()
    try:
        LOGGER.debug("Gửi yêu cầu tới Gemini: %s", user_text)
        response = await loop.run_in_executor(None, partial(model.generate_content, user_text))
    except Exception as exc:  # pragma: no cover - xử lý lỗi runtime
        LOGGER.exception("Lỗi gọi Gemini")
        await update.message.reply_text(
            "Xin lỗi, tôi không thể liên hệ với Google AI Studio ngay lúc này. Vui lòng thử lại sau."
        )
        return

    text = _extract_text(response)
    await update.message.reply_text(text)


def _extract_text(response: object) -> str:
    """Đưa kết quả của Gemini về chuỗi hiển thị."""
    if response is None:
        return "Không nhận được phản hồi từ Gemini."

    try:
        parts = getattr(response, "text", None)
        if isinstance(parts, str):
            return parts.strip() or "Gemini trả về phản hồi trống."

        candidates = getattr(response, "candidates", None)
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None)
                if parts:
                    joined = "\n".join(str(getattr(p, "text", p)) for p in parts if p)
                    if joined.strip():
                        return joined.strip()
    except Exception:  # pragma: no cover - lenient parsing
        LOGGER.exception("Không phân tích được phản hồi Gemini")

    return str(response)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    env_values = _ensure_required_env()
    token = env_values["TELEGRAM_BOT_TOKEN"]
    model_name = os.environ.get("GOOGLE_MODEL", "gemini-1.5-flash")
    model = _init_gemini(env_values["GOOGLE_API_KEY"], model_name)

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))

    async def _message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, context, model)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_router))

    LOGGER.info("Bot đã sẵn sàng và bắt đầu polling...")
    application.run_polling()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
