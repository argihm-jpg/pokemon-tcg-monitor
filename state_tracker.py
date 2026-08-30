import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "state.json"


def load_state() -> dict:
    """Returns {asin: {"name": str, "in_stock": bool}} for every ASIN ever seen.

    Migrates the old {asin: name} format (values were plain strings) by assuming
    in_stock=True, since old entries were only ever added when verified in stock.
    """
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        state = json.load(f)
    return {
        asin: ({"name": v, "in_stock": True} if isinstance(v, str) else v)
        for asin, v in state.items()
    }


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def compute_transitions(results: list[dict], previous: dict) -> list[dict]:
    """Returns products newly in stock: never seen before, or previously marked out of stock."""
    return [r for r in results if not previous.get(r["asin"], {}).get("in_stock")]


def update_state(candidates: dict[str, dict], results: list[dict], previous: dict) -> dict:
    """Record in_stock status for every candidate checked this cycle."""
    new_state = dict(previous)
    verified_asins = {r["asin"] for r in results}
    for asin, info in candidates.items():
        new_state[asin] = {"name": info["name"], "in_stock": asin in verified_asins}
    return new_state


def _demo() -> None:
    import tempfile, os

    global STATE_FILE
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"OLD1": "Legacy string-format entry"}, f)
        old_file = f.name
    real_state_file = STATE_FILE
    STATE_FILE = Path(old_file)
    try:
        migrated = load_state()
        assert migrated == {"OLD1": {"name": "Legacy string-format entry", "in_stock": True}}, migrated
    finally:
        STATE_FILE = real_state_file
        os.unlink(old_file)

    prev = {
        "A1": {"name": "ETB known, still in stock", "in_stock": True},
        "A2": {"name": "ETB known, was out of stock", "in_stock": False},
    }
    candidates = {
        "A1": {"name": "ETB known, still in stock"},
        "A2": {"name": "ETB known, was out of stock"},
        "A3": {"name": "ETB brand new"},
        "A4": {"name": "ETB seen before, now out of stock"},
    }
    prev["A4"] = {"name": "ETB seen before, now out of stock", "in_stock": True}
    results = [
        {"asin": "A1", "name": "ETB known, still in stock"},
        {"asin": "A2", "name": "ETB known, was out of stock"},
        {"asin": "A3", "name": "ETB brand new"},
    ]

    alerts = {r["asin"] for r in compute_transitions(results, prev)}
    assert alerts == {"A2", "A3"}, f"expected restock+new alerts, got {alerts}"

    new_state = update_state(candidates, results, prev)
    assert new_state["A1"]["in_stock"] is True
    assert new_state["A2"]["in_stock"] is True
    assert new_state["A3"]["in_stock"] is True
    assert new_state["A4"]["in_stock"] is False
    print("state_tracker self-check OK")


if __name__ == "__main__":
    _demo()
