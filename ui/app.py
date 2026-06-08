"""
ui/app.py — Flask backend for the Trading Bot Web UI.

Serves the dashboard at http://localhost:5000
Exposes REST endpoints that wrap the bot/ package.

Run with:
    python ui/app.py
"""

import sys
import os
from pathlib import Path

# Make sure bot/ package is importable from ui/app.py
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env from project root
try:
    from dotenv import load_dotenv
    _root = Path(__file__).parent.parent
    for _candidate in [_root / ".env", _root / "bot" / ".env"]:
        if _candidate.exists():
            load_dotenv(dotenv_path=_candidate)
            break
except ImportError:
    pass

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from bot.logging_config import setup_logging, get_logger
from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError, BinanceAuthError
from bot.validators import validate_order_params, ValidationError
from bot.orders import place_market_order, place_limit_order, place_stop_limit_order

# ── Setup ───────────────────────────────────────────────────────────────────────
setup_logging()
logger = get_logger("bot.ui")

app = Flask(__name__, static_folder="static", template_folder="static")
CORS(app)

STATIC_DIR = Path(__file__).parent / "static"


# ── Helper ──────────────────────────────────────────────────────────────────────

def _get_client() -> BinanceClient:
    return BinanceClient()


# ── API Routes ──────────────────────────────────────────────────────────────────

@app.route("/api/ping", methods=["GET"])
def ping():
    """Check testnet connectivity."""
    try:
        client = _get_client()
        ok = client.ping()
        server_time = client.get_server_time() if ok else None
        return jsonify({"connected": ok, "serverTime": server_time})
    except BinanceAuthError as e:
        return jsonify({"connected": False, "error": str(e)}), 401
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500


# Simple in-process cache so we only hit exchangeInfo once per server run
_symbols_cache: list[dict] = []

@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    """
    Return all active USDT-M perpetual symbols from Binance Futures Testnet.
    Cached after the first call so subsequent requests are instant.
    """
    global _symbols_cache
    if _symbols_cache:
        return jsonify({"symbols": _symbols_cache})

    try:
        import requests as req
        resp = req.get(
            "https://testnet.binancefuture.com/fapi/v1/exchangeInfo",
            timeout=10,
        )
        data = resp.json()

        def _parse_filters(filters: list) -> dict:
            """Extract useful trading constraints from the filters list."""
            result = {
                "minQty": None, "stepSize": None, "minNotional": None,
                "multiplierUp": None, "multiplierDown": None,
                "tickSize": None,
            }
            for f in filters:
                ft = f.get("filterType", "")
                if ft == "LOT_SIZE":
                    result["minQty"]   = f.get("minQty")
                    result["stepSize"] = f.get("stepSize")
                elif ft == "MIN_NOTIONAL":
                    result["minNotional"] = f.get("notional")
                elif ft == "PERCENT_PRICE":
                    result["multiplierUp"]   = f.get("multiplierUp")
                    result["multiplierDown"] = f.get("multiplierDown")
                elif ft == "PRICE_FILTER":
                    result["tickSize"] = f.get("tickSize")
            return result

        symbols = []
        for s in data.get("symbols", []):
            if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
                continue
            constraints = _parse_filters(s.get("filters", []))
            symbols.append({
                "symbol":              s["symbol"],
                "baseAsset":           s["baseAsset"],
                "quoteAsset":          s["quoteAsset"],
                "pricePrecision":      s.get("pricePrecision", 2),
                "quantityPrecision":   s.get("quantityPrecision", 3),
                "minQty":              constraints["minQty"],
                "stepSize":            constraints["stepSize"],
                "minNotional":         constraints["minNotional"],
                "multiplierUp":        constraints["multiplierUp"],
                "multiplierDown":      constraints["multiplierDown"],
                "tickSize":            constraints["tickSize"],
            })

        symbols.sort(key=lambda x: x["symbol"])
        _symbols_cache = symbols
        logger.info("Loaded %d USDT-M symbols from exchangeInfo", len(symbols))
        return jsonify({"symbols": symbols})
    except Exception as e:
        logger.warning("Could not fetch symbols: %s", e)
        # Fallback list of popular symbols
        fallback = [
            {"symbol": s, "baseAsset": s.replace("USDT",""), "quoteAsset": "USDT"}
            for s in ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
                      "ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT",
                      "MATICUSDT","DOTUSDT","UNIUSDT","ATOMUSDT","FILUSDT"]
        ]
        return jsonify({"symbols": fallback})


@app.route("/api/price/<symbol>", methods=["GET"])
def get_price(symbol: str):
    """
    Return the current mark price for a symbol.
    Used by the frontend to calculate true minimum order quantity.
    """
    try:
        import requests as req
        resp = req.get(
            f"https://testnet.binancefuture.com/fapi/v1/premiumIndex",
            params={"symbol": symbol.upper()},
            timeout=5,
        )
        data = resp.json()
        mark_price = float(data.get("markPrice", 0))
        return jsonify({"symbol": symbol.upper(), "markPrice": mark_price})
    except Exception as e:
        logger.warning("Could not fetch price for %s: %s", symbol, e)
        return jsonify({"symbol": symbol.upper(), "markPrice": None, "error": str(e)}), 500


@app.route("/api/order", methods=["POST"])
def place_order():
    """
    Place an order.

    Expected JSON body:
        {
            "symbol":     "BTCUSDT",
            "side":       "BUY" | "SELL",
            "order_type": "MARKET" | "LIMIT" | "STOP_LIMIT",
            "quantity":   "0.001",
            "price":      "50000",       # required for LIMIT / STOP_LIMIT
            "stop_price": "49000"        # required for STOP_LIMIT
        }
    """
    body = request.get_json(force=True) or {}

    symbol     = body.get("symbol", "")
    side       = body.get("side", "")
    order_type = body.get("order_type", "")
    quantity   = body.get("quantity", "")
    price      = body.get("price") or None
    stop_price = body.get("stop_price") or None

    logger.info(
        "[UI] Order request | symbol=%s side=%s type=%s qty=%s price=%s stop=%s",
        symbol, side, order_type, quantity, price, stop_price,
    )

    # Validate
    try:
        params = validate_order_params(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
    except ValidationError as e:
        logger.warning("[UI] Validation error: %s", e)
        return jsonify({"success": False, "error": str(e), "field": e.field}), 400

    # Place order
    try:
        client = _get_client()
        ot = params["order_type"]

        if ot == "MARKET":
            result = place_market_order(client, params["symbol"], params["side"], params["quantity"])
        elif ot == "LIMIT":
            result = place_limit_order(client, params["symbol"], params["side"], params["quantity"], params["price"])
        elif ot == "STOP_LIMIT":
            result = place_stop_limit_order(client, params["symbol"], params["side"], params["quantity"], params["price"], params["stop_price"])
        else:
            return jsonify({"success": False, "error": f"Unknown order type: {ot}"}), 400

    except BinanceAuthError as e:
        logger.error("[UI] Auth error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 401
    except BinanceAPIError as e:
        logger.error("[UI] API error: %s", e)
        return jsonify({"success": False, "error": str(e), "code": e.code}), 400
    except BinanceNetworkError as e:
        logger.error("[UI] Network error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 503
    except Exception as e:
        logger.exception("[UI] Unexpected error")
        return jsonify({"success": False, "error": str(e)}), 500

    logger.info("[UI] Order success | orderId=%s status=%s", result.order_id, result.status)

    return jsonify({
        "success": True,
        "order": {
            "orderId":      result.order_id,
            "symbol":       result.symbol,
            "side":         result.side,
            "type":         result.order_type,
            "status":       result.status,
            "origQty":      result.orig_qty,
            "executedQty":  result.executed_qty,
            "avgPrice":     result.avg_price,
            "price":        result.price,
            "stopPrice":    result.stop_price,
            "timeInForce":  result.time_in_force,
            "clientOrderId": result.client_order_id,
        }
    })


# ── Serve frontend ──────────────────────────────────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    if path and (STATIC_DIR / path).exists():
        return send_from_directory(str(STATIC_DIR), path)
    return send_from_directory(str(STATIC_DIR), "index.html")


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Trading Bot UI  ->  http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
