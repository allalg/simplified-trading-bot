"""
orders.py — Order placement logic (business layer).

Sits between the CLI and the BinanceClient, returning
structured OrderResult dataclasses rather than raw dicts.
"""

from dataclasses import dataclass, field
from typing import Optional

from .client import BinanceClient
from .logging_config import get_logger

logger = get_logger("bot.orders")


# ── Result dataclass ────────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    """Structured representation of a Binance Futures order response."""

    order_id: int
    symbol: str
    side: str
    order_type: str
    status: str
    orig_qty: str
    executed_qty: str
    avg_price: str
    price: str
    stop_price: str
    time_in_force: str
    client_order_id: str
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_response(cls, data: dict) -> "OrderResult":
        """Build an OrderResult from a raw Binance API response dict.

        Handles both regular order responses and algo order responses.
        """
        # Algo orders use algoId / algoStatus / triggerPrice
        is_algo = "algoId" in data

        return cls(
            order_id=data.get("algoId") or data.get("orderId", 0),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            order_type=data.get("orderType") or data.get("type", ""),
            status=data.get("algoStatus") or data.get("status", ""),
            orig_qty=data.get("quantity") or data.get("origQty", "0"),
            executed_qty=data.get("executedQty", "0"),
            avg_price=data.get("avgPrice", "0"),
            price=data.get("price", "0"),
            stop_price=data.get("triggerPrice") or data.get("stopPrice", "0"),
            time_in_force=data.get("timeInForce", ""),
            client_order_id=data.get("clientAlgoId") or data.get("clientOrderId", ""),
            raw=data,
        )

    def as_table_rows(self) -> list[tuple[str, str]]:
        """Return key-value pairs suitable for tabular display."""
        rows = [
            ("Order ID",       str(self.order_id)),
            ("Symbol",         self.symbol),
            ("Side",           self.side),
            ("Type",           self.order_type),
            ("Status",         self.status),
            ("Orig Qty",       self.orig_qty),
            ("Executed Qty",   self.executed_qty),
            ("Avg Price",      self.avg_price),
            ("Limit Price",    self.price),
        ]
        if self.stop_price and self.stop_price != "0":
            rows.append(("Stop Price", self.stop_price))
        rows.append(("Time-in-Force", self.time_in_force))
        rows.append(("Client Order ID", self.client_order_id))
        return rows


# ── Order functions ─────────────────────────────────────────────────────────────

def place_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: float,
) -> OrderResult:
    """
    Place a MARKET order.

    Args:
        client:   Authenticated BinanceClient
        symbol:   e.g. 'BTCUSDT'
        side:     'BUY' or 'SELL'
        quantity: Quantity of the base asset

    Returns:
        OrderResult with response details.
    """
    logger.info("[MARKET] %s %s qty=%s", side, symbol, quantity)

    raw = client.new_order(
        symbol=symbol,
        side=side,
        order_type="MARKET",
        quantity=quantity,
    )

    result = OrderResult.from_response(raw)
    logger.info(
        "[MARKET] Order placed | orderId=%s status=%s executedQty=%s avgPrice=%s",
        result.order_id, result.status, result.executed_qty, result.avg_price,
    )
    return result


def place_limit_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    time_in_force: str = "GTC",
) -> OrderResult:
    """
    Place a LIMIT order.

    Args:
        client:        Authenticated BinanceClient
        symbol:        e.g. 'BTCUSDT'
        side:          'BUY' or 'SELL'
        quantity:      Quantity of the base asset
        price:         Limit price
        time_in_force: GTC / IOC / FOK (default GTC)

    Returns:
        OrderResult with response details.
    """
    logger.info("[LIMIT] %s %s qty=%s price=%s tif=%s", side, symbol, quantity, price, time_in_force)

    raw = client.new_order(
        symbol=symbol,
        side=side,
        order_type="LIMIT",
        quantity=quantity,
        price=price,
        time_in_force=time_in_force,
    )

    result = OrderResult.from_response(raw)
    logger.info(
        "[LIMIT] Order placed | orderId=%s status=%s executedQty=%s",
        result.order_id, result.status, result.executed_qty,
    )
    return result


def place_stop_limit_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    stop_price: float,
    time_in_force: str = "GTC",
) -> OrderResult:
    """
    Place a STOP-LIMIT order (bonus order type).

    The order triggers when the market hits `stop_price`, then
    submits a limit order at `price`.

    Args:
        client:      Authenticated BinanceClient
        symbol:      e.g. 'BTCUSDT'
        side:        'BUY' or 'SELL'
        quantity:    Quantity of the base asset
        price:       Limit price (executed at this price after trigger)
        stop_price:  Trigger price
        time_in_force: GTC / IOC / FOK (default GTC)

    Returns:
        OrderResult with response details.
    """
    logger.info(
        "[STOP_LIMIT] %s %s qty=%s price=%s stopPrice=%s tif=%s",
        side, symbol, quantity, price, stop_price, time_in_force,
    )

    raw = client.new_algo_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        trigger_price=stop_price,
        price=price,
        time_in_force=time_in_force,
    )

    result = OrderResult.from_response(raw)
    logger.info(
        "[STOP_LIMIT] Order placed | orderId=%s status=%s",
        result.order_id, result.status,
    )
    return result
