import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "state.json"


def load_state() -> dict:
    """Returns {asin: name} for all ASINs we've already alerted on."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def compute_transitions(results: list[dict], previous: dict) -> list[dict]:
    """Returns products that appear in results but were NOT in previous state (new arrivals)."""
    return [r for r in results if r["asin"] not in previous]


def update_state(results: list[dict], previous: dict) -> dict:
    """Add all currently found Amazon-sold ASINs to state."""
    new_state = dict(previous)
    for r in results:
        new_state[r["asin"]] = r["name"]
    return new_state
