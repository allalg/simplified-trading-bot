"""
Simplified Trading Bot — Binance Futures Testnet (USDT-M)
"""

__version__ = "1.0.0"
__author__ = "Trading Bot"

from .client import BinanceClient
from .orders import place_market_order, place_limit_order, place_stop_limit_order
from .validators import validate_order_params

__all__ = [
    "BinanceClient",
    "place_market_order",
    "place_limit_order",
    "place_stop_limit_order",
    "validate_order_params",
]
