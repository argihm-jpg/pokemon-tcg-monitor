import os
import logging
import aiohttp

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


async def send_alert(product: dict) -> bool:
    category = product.get("category", "TCG")
    price_line = f"💰 {product['price']}\n" if product.get("price") else ""
    text = (
        f"🛒 *Amazon MX — EN STOCK*\n"
        f"📦 {category}\n"
        f"{product['name']}\n"
        f"{price_line}"
        f"Vendido por Amazon.com.mx ✓\n"
        f"👉 {product['url']}"
    )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TELEGRAM_API, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    logger.info(f"Alert sent for {product['asin']}")
                    return True
                body = await resp.text()
                logger.error(f"Telegram error {resp.status}: {body}")
                return False
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False


async def send_captcha_warning(consecutive: int) -> None:
    text = (
        f"⚠️ *Amazon MX Monitor* — CAPTCHA detectado {consecutive} veces seguidas.\n"
        f"El bot está pausado 10 minutos."
    )
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(TELEGRAM_API, json=payload, timeout=aiohttp.ClientTimeout(total=10))
    except Exception:
        pass
