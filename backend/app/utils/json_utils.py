"""
JSON utility functions for handling special cases like NaN values
"""
import math
from typing import Any, Dict, List, Union


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize data structure to make it JSON-serializable.

    Handles:
    - NaN → None
    - Infinity → None
    - -Infinity → None
    - Nested dicts and lists

    Args:
        obj: Any Python object (dict, list, float, etc.)

    Returns:
        Sanitized object safe for JSON serialization
    """
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_for_json(item) for item in obj)
    elif isinstance(obj, float):
        # Check for NaN or Infinity
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    else:
        return obj


def safe_json_value(value: Any, default: Any = None) -> Any:
    """
    Return a safe JSON value, replacing NaN/Infinity with default.

    Args:
        value: Value to check
        default: Default value to use if value is NaN/Infinity (default: None)

    Returns:
        Safe value for JSON
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return default
    return value
