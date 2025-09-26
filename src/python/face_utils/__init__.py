# Utils package initialization
# Import existing utils functions for backward compatibility
try:
    from ..utils import get_current_datetime_other_format
except (ImportError, ValueError):
    # If utils.py exists at same level
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from utils import get_current_datetime_other_format
    except ImportError:
        pass