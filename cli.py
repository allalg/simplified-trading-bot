"""
cli.py — Command-line interface for the Simplified Trading Bot.

Usage examples:
    python cli.py market --symbol BTCUSDT --side BUY --quantity 0.001
    python cli.py limit  --symbol BTCUSDT --side SELL --quantity 0.001 --price 30000
    python cli.py stop-limit --symbol BTCUSDT --side BUY --quantity 0.001 --price 30000 --stop-price 29500
    python cli.py --interactive
"""

import argparse
import io
import os
import sys

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError with box chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Load .env file if python-dotenv is available
# Searches: project root, bot/ subdir, and script directory (in priority order)
try:
    from pathlib import Path
    from dotenv import load_dotenv

    _script_dir = Path(__file__).parent
    _env_candidates = [
        _script_dir / ".env",           # project root (next to cli.py)
        _script_dir / "bot" / ".env",   # bot/ subdirectory
        Path.cwd() / ".env",            # current working directory
    ]
    for _env_path in _env_candidates:
        if _env_path.exists():
            load_dotenv(dotenv_path=_env_path, override=False)
            break
except ImportError:
    pass  # dotenv optional; env vars can be set manually

from bot.logging_config import setup_logging, get_logger
from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError, BinanceAuthError
from bot.validators import validate_order_params, ValidationError
from bot.orders import place_market_order, place_limit_order, place_stop_limit_order, OrderResult

# ── Setup logging before anything else ─────────────────────────────────────────
setup_logging()
logger = get_logger("bot.cli")


# ── ANSI colours (gracefully disabled on Windows without VT support) ───────────
def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


GREEN   = "\033[92m" if _supports_color() else ""
RED     = "\033[91m" if _supports_color() else ""
YELLOW  = "\033[93m" if _supports_color() else ""
CYAN    = "\033[96m" if _supports_color() else ""
BOLD    = "\033[1m"  if _supports_color() else ""
RESET   = "\033[0m"  if _supports_color() else ""


# ── Display helpers ─────────────────────────────────────────────────────────────

def _print_banner() -> None:
    line = "=" * 44
    print(f"\n{CYAN}{BOLD}+{line}+")
    print(f"|   Binance Futures Testnet Trading Bot    |")
    print(f"|   USDT-M Perpetual Futures               |")
    print(f"+{line}+{RESET}\n")


def _print_order_summary(params: dict) -> None:
    """Print the order request summary before sending."""
    print(f"\n{BOLD}── Order Request ──────────────────────────{RESET}")
    rows = [
        ("Symbol",     params["symbol"]),
        ("Side",       params["side"]),
        ("Type",       params["order_type"]),
        ("Quantity",   str(params["quantity"])),
    ]
    if params.get("price"):
        rows.append(("Price", str(params["price"])))
    if params.get("stop_price"):
        rows.append(("Stop Price", str(params["stop_price"])))

    for label, value in rows:
        print(f"  {CYAN}{label:<14}{RESET} {value}")
    print()


def _print_order_result(result: OrderResult) -> None:
    """Print the order response table."""
    print(f"{BOLD}── Order Response ─────────────────────────{RESET}")
    for label, value in result.as_table_rows():
        color = GREEN if label == "Status" and "FILLED" in value else ""
        print(f"  {CYAN}{label:<18}{RESET} {color}{value}{RESET}")
    print()


def _print_success(result: OrderResult) -> None:
    status = result.status
    print(f"{GREEN}{BOLD}✅  Order placed successfully! "
          f"[orderId={result.order_id}  status={status}]{RESET}\n")
    logger.info("SUCCESS | orderId=%s status=%s", result.order_id, status)


def _print_failure(error: Exception) -> None:
    print(f"{RED}{BOLD}❌  Order failed: {error}{RESET}\n")
    logger.error("FAILURE | %s", error)


# ── Interactive mode ────────────────────────────────────────────────────────────

def _prompt(prompt_text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"  {CYAN}{prompt_text}{suffix}: {RESET}").strip()
        return value if value else default
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)


def _run_interactive() -> None:
    """Full interactive menu with prompts for all order parameters."""
    _print_banner()
    print(f"{BOLD}Interactive Mode — follow the prompts below.{RESET}\n")

    print(f"  Order types: {YELLOW}1{RESET}=MARKET  {YELLOW}2{RESET}=LIMIT  {YELLOW}3{RESET}=STOP_LIMIT")
    type_map = {"1": "MARKET", "2": "LIMIT", "3": "STOP_LIMIT",
                "market": "MARKET", "limit": "LIMIT", "stop_limit": "STOP_LIMIT",
                "stop-limit": "STOP_LIMIT"}
    raw_type = _prompt("Order type (1/2/3 or name)", "1")
    order_type = type_map.get(raw_type.lower(), raw_type.upper())

    symbol      = _prompt("Symbol (e.g. BTCUSDT)", "BTCUSDT")
    side_raw    = _prompt("Side (BUY/SELL)", "BUY")
    quantity    = _prompt("Quantity", "0.001")

    price       = None
    stop_price  = None

    if order_type in ("LIMIT", "STOP_LIMIT"):
        price = _prompt("Limit price")

    if order_type == "STOP_LIMIT":
        stop_price = _prompt("Stop (trigger) price")

    # Validate
    try:
        params = validate_order_params(
            symbol=symbol,
            side=side_raw,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
    except ValidationError as e:
        print(f"\n{RED}Validation error — {e}{RESET}")
        sys.exit(1)

    _print_order_summary(params)
    confirm = _prompt("Confirm and place order? (yes/no)", "yes")
    if confirm.lower() not in ("yes", "y"):
        print("Order cancelled.")
        sys.exit(0)

    _dispatch_order(params)


# ── Order dispatch ──────────────────────────────────────────────────────────────

def _dispatch_order(params: dict) -> None:
    """Create the client and call the appropriate order function."""
    try:
        client = BinanceClient()
    except BinanceAuthError as e:
        print(f"\n{RED}Auth error: {e}{RESET}")
        logger.error("Auth error: %s", e)
        sys.exit(1)

    # Verify connectivity
    if not client.ping():
        print(f"\n{YELLOW}⚠  Warning: testnet may be unreachable. Attempting order anyway...{RESET}")

    result: OrderResult

    try:
        ot = params["order_type"]

        if ot == "MARKET":
            result = place_market_order(
                client=client,
                symbol=params["symbol"],
                side=params["side"],
                quantity=params["quantity"],
            )

        elif ot == "LIMIT":
            result = place_limit_order(
                client=client,
                symbol=params["symbol"],
                side=params["side"],
                quantity=params["quantity"],
                price=params["price"],
            )

        elif ot == "STOP_LIMIT":
            result = place_stop_limit_order(
                client=client,
                symbol=params["symbol"],
                side=params["side"],
                quantity=params["quantity"],
                price=params["price"],
                stop_price=params["stop_price"],
            )

        else:
            print(f"{RED}Unknown order type: {ot}{RESET}")
            sys.exit(1)

    except ValidationError as e:
        _print_failure(e)
        sys.exit(1)
    except BinanceAPIError as e:
        _print_failure(e)
        sys.exit(1)
    except BinanceNetworkError as e:
        _print_failure(e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        _print_failure(e)
        sys.exit(1)

    _print_order_result(result)
    _print_success(result)


# ── Argument parser ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="Simplified Trading Bot — Binance Futures Testnet (USDT-M)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py market --symbol BTCUSDT --side BUY --quantity 0.001
  python cli.py limit  --symbol BTCUSDT --side SELL --quantity 0.001 --price 30000
  python cli.py stop-limit --symbol BTCUSDT --side BUY --quantity 0.001 --price 30000 --stop-price 29500
  python cli.py --interactive
""",
    )

    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Launch interactive prompt mode",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="ORDER_TYPE")

    # ── Shared parent parser for common args ────────────────────────────────────
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--symbol",   "-s", required=True,  help="Trading pair, e.g. BTCUSDT")
    common.add_argument("--side",     "-d", required=True,  help="BUY or SELL")
    common.add_argument("--quantity", "-q", required=True,  help="Order quantity")

    # ── market ──────────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "market",
        parents=[common],
        help="Place a MARKET order (executed immediately at best price)",
        description="Place a MARKET order on Binance Futures Testnet.",
    )

    # ── limit ───────────────────────────────────────────────────────────────────
    limit_p = subparsers.add_parser(
        "limit",
        parents=[common],
        help="Place a LIMIT order (executed at a specific price or better)",
        description="Place a LIMIT order on Binance Futures Testnet.",
    )
    limit_p.add_argument("--price", "-p", required=True, help="Limit price")
    limit_p.add_argument(
        "--time-in-force", "-t",
        default="GTC",
        choices=["GTC", "IOC", "FOK"],
        help="Time-in-force (default: GTC)",
    )

    # ── stop-limit (bonus) ──────────────────────────────────────────────────────
    sl_p = subparsers.add_parser(
        "stop-limit",
        parents=[common],
        help="[BONUS] Place a STOP-LIMIT order (triggers at stop price, executes at limit price)",
        description="Place a STOP-LIMIT order on Binance Futures Testnet.",
    )
    sl_p.add_argument("--price",      "-p", required=True, help="Limit price (execution price)")
    sl_p.add_argument("--stop-price", "-sp", required=True, dest="stop_price", help="Stop (trigger) price")
    sl_p.add_argument(
        "--time-in-force", "-t",
        default="GTC",
        choices=["GTC", "IOC", "FOK"],
        help="Time-in-force (default: GTC)",
    )

    return parser


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    _print_banner()

    # Interactive mode
    if args.interactive:
        _run_interactive()
        return

    # No subcommand given → show help
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Map CLI args to order_type string
    order_type_map = {
        "market":     "MARKET",
        "limit":      "LIMIT",
        "stop-limit": "STOP_LIMIT",
    }
    order_type = order_type_map[args.command]

    price      = getattr(args, "price",      None)
    stop_price = getattr(args, "stop_price", None)

    # Validate inputs
    try:
        params = validate_order_params(
            symbol=args.symbol,
            side=args.side,
            order_type=order_type,
            quantity=args.quantity,
            price=price,
            stop_price=stop_price,
        )
    except ValidationError as e:
        print(f"\n{RED}Validation error — {e}{RESET}\n")
        logger.warning("Validation error: %s", e)
        sys.exit(1)

    _print_order_summary(params)
    _dispatch_order(params)


if __name__ == "__main__":
    main()
