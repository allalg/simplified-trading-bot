"""
validators.py — Input validation for order parameters.

All validators raise ValueError with clear messages on bad input.
"""

from typing import Optional


VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_LIMIT"}

# Reasonable sanity bounds (not exchange minimums — those are enforced server-side)
MIN_QUANTITY = 0.0
MIN_PRICE = 0.0

# Binance Futures Testnet minimum notional value per order (in USDT)
# Error -4164 is thrown when quantity * price < this value
BINANCE_MIN_NOTIONAL = 50.0  # Binance Futures minimum order notional (error -4164 if below this)


class ValidationError(ValueError):
    """Raised when user-provided order parameters fail validation."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"[{field}] {message}")


def validate_symbol(symbol: str) -> str:
    """
    Validates a trading pair symbol.
    Returns the uppercased symbol string.
    """
    if not symbol or not isinstance(symbol, str):
        raise ValidationError("symbol", "Symbol must be a non-empty string (e.g. BTCUSDT).")

    symbol = symbol.strip().upper()

    if len(symbol) < 4 or len(symbol) > 20:
        raise ValidationError(
            "symbol",
            f"Symbol '{symbol}' looks invalid. Expected something like BTCUSDT or ETHUSDT.",
        )

    if not symbol.isalnum():
        raise ValidationError(
            "symbol",
            f"Symbol '{symbol}' contains invalid characters. Use letters and digits only.",
        )

    return symbol


def validate_side(side: str) -> str:
    """
    Validates the order side.
    Returns the uppercased side string ('BUY' or 'SELL').
    """
    if not side or not isinstance(side, str):
        raise ValidationError("side", "Side must be 'BUY' or 'SELL'.")

    side = side.strip().upper()

    if side not in VALID_SIDES:
        raise ValidationError(
            "side",
            f"Invalid side '{side}'. Must be one of: {', '.join(sorted(VALID_SIDES))}.",
        )

    return side


def validate_order_type(order_type: str) -> str:
    """
    Validates the order type.
    Returns the uppercased order type string.
    """
    if not order_type or not isinstance(order_type, str):
        raise ValidationError("order_type", "Order type must be MARKET, LIMIT, or STOP_LIMIT.")

    order_type = order_type.strip().upper().replace("-", "_")

    if order_type not in VALID_ORDER_TYPES:
        raise ValidationError(
            "order_type",
            f"Invalid order type '{order_type}'. Must be one of: {', '.join(sorted(VALID_ORDER_TYPES))}.",
        )

    return order_type


def validate_quantity(quantity: str | float) -> float:
    """
    Validates the order quantity.
    Returns a positive float.
    """
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise ValidationError("quantity", f"Quantity '{quantity}' is not a valid number.")

    if qty <= MIN_QUANTITY:
        raise ValidationError("quantity", f"Quantity must be greater than 0, got {qty}.")

    return qty


def validate_price(price: str | float, field: str = "price") -> float:
    """
    Validates a price value (used for both limit price and stop price).
    Returns a positive float.
    """
    try:
        p = float(price)
    except (TypeError, ValueError):
        raise ValidationError(field, f"Price '{price}' is not a valid number.")

    if p <= MIN_PRICE:
        raise ValidationError(field, f"Price must be greater than 0, got {p}.")

    return p


def validate_order_params(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str | float,
    price: Optional[str | float] = None,
    stop_price: Optional[str | float] = None,
) -> dict:
    """
    Validates all order parameters together and returns a clean dict.

    Raises ValidationError if any parameter is invalid.
    """
    clean = {
        "symbol": validate_symbol(symbol),
        "side": validate_side(side),
        "order_type": validate_order_type(order_type),
        "quantity": validate_quantity(quantity),
        "price": None,
        "stop_price": None,
    }

    ot = clean["order_type"]

    if ot == "LIMIT":
        if price is None:
            raise ValidationError("price", "Price is required for LIMIT orders.")
        clean["price"] = validate_price(price, "price")

    elif ot == "STOP_LIMIT":
        if price is None:
            raise ValidationError("price", "Limit price is required for STOP_LIMIT orders.")
        if stop_price is None:
            raise ValidationError("stop_price", "Stop price is required for STOP_LIMIT orders.")
        clean["price"] = validate_price(price, "price")
        clean["stop_price"] = validate_price(stop_price, "stop_price")

    elif ot == "MARKET":
        if price is not None:
            # Soft warning — MARKET orders ignore price
            pass

    # ── Notional value check (only when price is known) ────────────────────────
    # Binance rejects orders where qty * price < minimum notional (error -4164)
    if clean["price"] and clean["price"] > 0:
        notional = clean["quantity"] * clean["price"]
        if notional < BINANCE_MIN_NOTIONAL:
            min_qty = BINANCE_MIN_NOTIONAL / clean["price"]
            raise ValidationError(
                "quantity",
                f"Order notional too small: {clean['quantity']} x {clean['price']} = "
                f"${notional:.2f} USDT. "
                f"Binance requires at least ${BINANCE_MIN_NOTIONAL} USDT. "
                f"Use quantity >= {min_qty:.4f} at this price.",
            )

    return clean
