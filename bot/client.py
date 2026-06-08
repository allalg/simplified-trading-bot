"""
client.py — Binance Futures Testnet REST API client wrapper.

Handles:
  - HMAC-SHA256 request signing
  - Timestamp injection
  - HTTP request execution (GET / POST)
  - Typed error classes for API vs. network failures
"""

import hashlib
import hmac
import os
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from .logging_config import get_logger

logger = get_logger("bot.client")

# ── Constants ───────────────────────────────────────────────────────────────────
TESTNET_BASE_URL = "https://testnet.binancefuture.com"
DEFAULT_TIMEOUT = 10  # seconds
RECV_WINDOW = 5000    # milliseconds


# ── Custom exceptions ───────────────────────────────────────────────────────────

class BinanceAPIError(Exception):
    """Raised when the Binance API returns an error response."""

    def __init__(self, code: int, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"Binance API Error {code}: {msg}")


class BinanceNetworkError(Exception):
    """Raised when a network-level failure occurs."""


class BinanceAuthError(Exception):
    """Raised when API credentials are missing or invalid."""


# ── Client ──────────────────────────────────────────────────────────────────────

class BinanceClient:
    """
    Lightweight Binance Futures Testnet REST client.

    Reads credentials from environment variables (or a .env file loaded
    by the caller):
        BINANCE_API_KEY
        BINANCE_SECRET_KEY

    Example:
        client = BinanceClient()
        result = client.new_order(symbol="BTCUSDT", side="BUY",
                                  order_type="MARKET", quantity=0.001)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: str = TESTNET_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.environ.get("BINANCE_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("BINANCE_SECRET_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        if not self.api_key or not self.secret_key:
            raise BinanceAuthError(
                "API credentials not found. "
                "Set BINANCE_API_KEY and BINANCE_SECRET_KEY environment variables "
                "(or copy .env.example to .env and fill in your testnet keys)."
            )

        self._session = requests.Session()
        self._session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        logger.debug("BinanceClient initialised. Base URL: %s", self.base_url)

    # ── Signing helpers ─────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        """Add a HMAC-SHA256 signature and timestamp to a parameter dict."""
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = RECV_WINDOW
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    # ── HTTP helpers ────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        params = self._sign(params or {})
        logger.debug("GET %s  params=%s", url, {k: v for k, v in params.items() if k != "signature"})
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            logger.error("Network error on GET %s: %s", url, exc)
            raise BinanceNetworkError(f"Network error: {exc}") from exc

        return self._handle_response(resp)

    def _post(self, endpoint: str, params: dict) -> Any:
        url = f"{self.base_url}{endpoint}"
        params = self._sign(params)
        safe_params = {k: v for k, v in params.items() if k != "signature"}
        logger.info("POST %s  body=%s", url, safe_params)
        try:
            resp = self._session.post(url, data=params, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            logger.error("Network error on POST %s: %s", url, exc)
            raise BinanceNetworkError(f"Network error: {exc}") from exc

        return self._handle_response(resp)

    def _handle_response(self, resp: requests.Response) -> Any:
        logger.debug("HTTP %d  body=%s", resp.status_code, resp.text[:500])
        try:
            data = resp.json()
        except ValueError:
            logger.error("Non-JSON response (HTTP %d): %s", resp.status_code, resp.text[:200])
            raise BinanceNetworkError(f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:200]}")

        if isinstance(data, dict) and "code" in data and data["code"] != 200:
            # Binance error responses have a negative code field
            if int(data["code"]) < 0:
                logger.error("API error: code=%s msg=%s", data["code"], data.get("msg", ""))
                raise BinanceAPIError(code=int(data["code"]), msg=data.get("msg", "Unknown error"))

        if not resp.ok:
            logger.error("HTTP error %d: %s", resp.status_code, resp.text[:200])
            raise BinanceAPIError(code=resp.status_code, msg=resp.text[:200])

        return data

    # ── Public API methods ──────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Returns True if the testnet server is reachable."""
        try:
            resp = self._session.get(
                f"{self.base_url}/fapi/v1/ping", timeout=self.timeout
            )
            logger.debug("Ping response: HTTP %d", resp.status_code)
            return resp.status_code == 200
        except requests.exceptions.RequestException as exc:
            logger.warning("Ping failed: %s", exc)
            return False

    def get_server_time(self) -> int:
        """Returns server time in milliseconds."""
        resp = self._session.get(
            f"{self.base_url}/fapi/v1/time", timeout=self.timeout
        )
        data = resp.json()
        return data.get("serverTime", 0)

    def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "GTC",
    ) -> dict:
        """
        Places a MARKET or LIMIT order on Binance Futures Testnet.

        For stop-limit / conditional orders use new_algo_order() instead,
        as Binance requires those via /fapi/v1/algoOrder (error -4120 otherwise).

        Args:
            symbol:        Trading pair, e.g. 'BTCUSDT'
            side:          'BUY' or 'SELL'
            order_type:    'MARKET' or 'LIMIT'
            quantity:      Order size
            price:         Limit price (required for LIMIT orders)
            time_in_force: 'GTC', 'IOC', or 'FOK' (default 'GTC')

        Returns:
            Raw API response dict.

        Raises:
            BinanceAPIError, BinanceNetworkError
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }

        if order_type == "LIMIT":
            params["price"] = price
            params["timeInForce"] = time_in_force

        logger.info(
            "Placing order | symbol=%s side=%s type=%s qty=%s price=%s stopPrice=%s",
            symbol, side, order_type, quantity, price, stop_price,
        )

        response = self._post("/fapi/v1/order", params)
        logger.info("Order response: %s", response)
        return response

    def new_algo_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        trigger_price: float,
        price: Optional[float] = None,
        time_in_force: str = "GTC",
    ) -> dict:
        """
        Places a STOP-LIMIT conditional order via the Binance Algo Order API.

        Binance Futures requires conditional orders (STOP, TAKE_PROFIT, etc.)
        to go through /fapi/v1/algoOrder — the standard /fapi/v1/order
        endpoint rejects them with error -4120.

        Args:
            symbol:        Trading pair, e.g. 'BTCUSDT'
            side:          'BUY' or 'SELL'
            quantity:      Order size
            trigger_price: Price that triggers the order
            price:         Limit execution price (if None uses STOP_MARKET)
            time_in_force: 'GTC', 'IOC', or 'FOK' (default 'GTC')

        Returns:
            Raw API response dict.

        Raises:
            BinanceAPIError, BinanceNetworkError
        """
        order_type = "STOP" if price is not None else "STOP_MARKET"

        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": order_type,
            "quantity": quantity,
            "triggerPrice": trigger_price,
            "timeInForce": time_in_force,
        }

        if price is not None:
            params["price"] = price

        logger.info(
            "Placing algo order | symbol=%s side=%s type=%s qty=%s "
            "triggerPrice=%s limitPrice=%s",
            symbol, side, order_type, quantity, trigger_price, price,
        )

        response = self._post("/fapi/v1/algoOrder", params)
        logger.info("Algo order response: %s", response)
        return response
