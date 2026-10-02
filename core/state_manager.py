# language: Python, file: core/state_manager.py, target: Python 3.10+
"""
In-Memory Fast Session State Manager for Interactive Menu Workflows:
Tracks user input states (e.g. waiting for custom watermark text, headline, admin global watermark, custom captions).
"""

from typing import Dict, Any, Optional

_USER_STATES: Dict[int, Dict[str, Any]] = {}


def set_user_state(user_id: int, state: str, extra: Optional[Dict[str, Any]] = None):
    """Sets the pending input state for a user."""
    _USER_STATES[user_id] = {
        "state": state,
        "extra": extra or {},
    }


def get_user_state(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves the pending input state for a user, or None."""
    return _USER_STATES.get(user_id)


def clear_user_state(user_id: int):
    """Clears any pending input state for a user."""
    _USER_STATES.pop(user_id, None)
