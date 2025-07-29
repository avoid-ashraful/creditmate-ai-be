"""
This module maintains backward compatibility by importing from the new validators structure.
"""

# Re-import validator from the new structure for backward compatibility
from .validators import CreditCardDataValidator

# Re-export for backward compatibility
__all__ = [
    "CreditCardDataValidator",
]
