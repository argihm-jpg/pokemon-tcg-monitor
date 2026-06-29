import asyncio
import json
import random
import logging
from pathlib import Path
from urllib.parse import urlencode
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"
AMAZON_BASE = "https://www.amazon.com.mx"
SELLER_NAME = "Amazon.com.mx"

EXCLUDE_KEYWORDS = ["figura", "funko", "peluche", "juguete", "mochila", "camiseta", "poster", "sticker", "llavero", "rompecabezas", "puzzle"]
POKEMON_KEYWORDS = ["pokemon", "pokémon", "tcg", "trainer box", "booster", "elite trainer", "ultra premium"]

ADD_TO_CART_SELECTORS = [
    "#add-to-cart-button",
    "#addToCart",
    "input[id='add-to-cart-button']",
]

SELLER_SELECTORS = [
    "#merchantInfoFeature_feature_div .offer-display-feature-text-message",
    "#tabular-buybox-container .tabular-buybox-text[tabular-attribute-name='Vendido por'] span",
    "#sellerProfileTriggerId",
    "#merchant-info a",
    "#newMerchantInfo a",
    "#tabular-buybox-truncate-0 .tabular-buybox-text span",
]


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def classify_product(name: str, priority_rules: list[dict]) -> tuple[str, int]:
    name_lower = name.lower()
    for rule in sorted(priority_rules, key=lambda r: r["rank"]):
        if not rule["keywords"]:
            continue
        if any(kw in name_lower for kw in rule["keywords"]):
            return rule["label"], rule["rank"]
    last = max(priority_rules, key=lambda r: r["rank"])
    return last["label"], last["rank"]


def is_excluded(name: str) -> bool:
    return any(kw in name.lower() for kw in EXCLUDE_KEYWORDS)


def is_pokemon_tcg(name: str) -> bool:
    return any(kw in name.lower() for kw in POKEMON_KEYWORDS)


def is_captcha(page) -> bool:
    return "validateCaptcha" in page.url or "api-services-support" in page.url


async def collect_asins_from_search(page, query: str) -> dict:
    """Search one query, return {asin: {name, url}} candidates."""
    candidates = {}
    url = f"{AMAZON_BASE}/s?{urlencode({'k': query})}"

    for page_num in range(1, 2):  # solo página 1 — suficiente para ciclos de 2 min
        paginated = url if page_num == 1 else f"{url}&page={page_num}"
        logger.info(f"  Search '{query}' — page {page_num}")

        try:
            await page.goto(paginated, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(random.randint(2000, 3500))
        except PlaywrightTimeoutError:
            logger.warning(f"  Timeout on search page {page_num}")
            break

        if is_captcha(page):
            logger.warning("  CAPTCHA on search page")
            return {"_captcha": True}

        cards = await page.query_selector_all('div[data-component-type="s-search-result"]')
        if not cards:
            break

        new_this_page = 0
        for card in cards:
            asin = await card.get_attribute("data-asin")
            if not asin or asin in candidates:
                continue

            link_el = await card.query_selector('[data-cy="title-recipe"] a')
            if not link_el:
                continue

            name = (await link_el.inner_text()).strip()
            if not name or is_excluded(name) or not is_pokemon_tcg(name):
                continue

            href = await link_el.get_attribute("href")
            if not href:
                continue

            product_url = f"{AMAZON_BASE}{href.split('?')[0]}"
            candidates[asin] = {"name": name, "url": product_url}
            new_this_page += 1

        if new_this_page == 0:
            break

        await asyncio.sleep(random.uniform(1.5, 3))

    return candidates


async def verify_product(page, asin: str, info: dict, priority_rules: list[dict]) -> dict | None:
    """Visit product page. Returns product dict if sold by Amazon.com.mx and in stock."""
    try:
        await page.goto(info["url"], wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(random.randint(1500, 3000))
    except PlaywrightTimeoutError:
        logger.warning(f"  Timeout verifying {asin}")
        return None

    if is_captcha(page):
        return {"_captcha": True}

    # Check add-to-cart button
    has_cart = False
    for sel in ADD_TO_CART_SELECTORS:
        el = await page.query_selector(sel)
        if el and await el.is_visible():
            has_cart = True
            break

    if not has_cart:
        logger.info(f"  {asin}: no add-to-cart — skip")
        return None

    # Check seller
    seller_text = None
    for sel in SELLER_SELECTORS:
        el = await page.query_selector(sel)
        if el:
            text = (await el.inner_text()).strip()
            if text:
                seller_text = text
                break

    logger.info(f"  {asin}: seller='{seller_text}'")
    if not seller_text or SELLER_NAME not in seller_text:
        return None

    # Get price
    price = None
    price_whole = await page.query_selector(".a-price-whole")
    if price_whole:
        whole = (await price_whole.inner_text()).strip().replace(",", "").replace(".", "")
        fraction_el = await page.query_selector(".a-price-fraction")
        fraction = (await fraction_el.inner_text()).strip() if fraction_el else "00"
        price = f"${whole}.{fraction} MXN"

    label, rank = classify_product(info["name"], priority_rules)
    logger.info(f"  FOUND [{label}] {info['name'][:50]} — {price}")

    return {
        "asin": asin,
        "name": info["name"],
        "url": info["url"],
        "price": price,
        "category": label,
        "priority_rank": rank,
    }


async def run_scrape(known_asins: set | None = None) -> list[dict]:
    """
    1. Search all queries → collect candidate ASINs
    2. Visit each new product page → verify sold by Amazon.com.mx
    Returns list sorted by priority, or [{"_captcha": True}] on block.
    """
    config = load_config()
    queries = config["search_queries"]
    priority_rules = config["priority"]
    known_asins = known_asins or set()

    all_candidates: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="es-MX",
        )
        page = await context.new_page()
        await stealth_async(page)

        # Phase 1: collect candidates from all search queries
        for query in queries:
            result = await collect_asins_from_search(page, query)
            if isinstance(result, dict) and result.get("_captcha"):
                await browser.close()
                return [{"_captcha": True}]
            for asin, info in result.items():
                if asin not in all_candidates:
                    all_candidates[asin] = info
            await asyncio.sleep(random.uniform(3, 5))

        new_asins = {a: i for a, i in all_candidates.items() if a not in known_asins}
        logger.info(
            f"Search done — {len(all_candidates)} candidates, "
            f"{len(known_asins)} known, {len(new_asins)} to verify"
        )

        # Phase 2: verify seller on product page (only new ASINs)
        verified = []
        for asin, info in new_asins.items():
            result = await verify_product(page, asin, info, priority_rules)
            if isinstance(result, dict) and result.get("_captcha"):
                await browser.close()
                return [{"_captcha": True}]
            if result:
                verified.append(result)
            await asyncio.sleep(random.uniform(2, 4))

        await browser.close()

    return sorted(verified, key=lambda r: (r["priority_rank"], r["name"]))
