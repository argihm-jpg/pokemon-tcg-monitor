import asyncio
import logging
import sys

from scraper import run_scrape
from notifier import send_alert, send_captcha_warning
from state_tracker import load_state, save_state, compute_transitions, update_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("--- Starting scrape cycle ---")
    previous = load_state()

    results = await run_scrape(known_asins=set(previous.keys()))

    if results and results[0].get("_captcha"):
        logger.warning("CAPTCHA detected — skipping cycle")
        await send_captcha_warning(1)
        return

    newly_available = compute_transitions(results, previous)
    save_state(update_state(results, previous))

    for product in sorted(newly_available, key=lambda r: (r.get("priority_rank", 9), r.get("name", ""))):
        await send_alert(product)

    logger.info(f"Cycle done — {len(newly_available)} new products")


if __name__ == "__main__":
    asyncio.run(main())
