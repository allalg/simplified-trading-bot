# Simplified Trading Bot — Binance Futures Testnet (USDT-M)

A clean, well-structured Python trading bot that places **Market**, **Limit**, and **Stop-Limit** orders on the Binance Futures Testnet (USDT-M), built as a Python Developer Intern assignment for Primetrade.ai.

---

## Features

- ✅ **Market** and **Limit** orders (+ bonus **Stop-Limit**)
- ✅ **BUY** and **SELL** sides
- ✅ CLI via `argparse` with subcommands + interactive mode
- ✅ Structured logging to `logs/trading_bot.log` (rotating, max 5 MB)
- ✅ Full exception handling (validation errors, API errors, network failures)
- ✅ Clean layered architecture: `client.py` → `orders.py` → `cli.py`
- ✅ **[Bonus] Web UI** — dark-themed dashboard at `http://localhost:5000`

---

## Project Structure

```
trading_bot/
  bot/
    __init__.py         # package + public API
    client.py           # Binance REST client (HMAC signing, error handling)
    orders.py           # order placement logic + OrderResult dataclass
    validators.py       # input validation (raises ValidationError)
    logging_config.py   # rotating file + console logging setup
  ui/
    app.py              # Flask backend (REST API wrapper)
    static/
      index.html        # Dark-themed single-page trading dashboard
  cli.py                # CLI entry point (argparse subcommands)
  .env.example          # credential template
  requirements.txt
  logs/
    trading_bot.log     # auto-created on first run
```

---

## Setup

### 1. Get Binance Futures Testnet credentials

1. Go to **https://testnet.binancefuture.com**
2. Sign in with GitHub or create an account
3. Navigate to **API Management** → generate a new API key
4. Copy the **API Key** and **Secret Key**

### 2. Clone / extract the project

```bash
# If using git:
git clone <repo-url>
cd "Simplified Trading Bot"

# Or just unzip and cd into the folder
```

### 3. Create a virtual environment & install dependencies

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate

# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Configure credentials

```bash
copy .env.example .env   # Windows
# or
cp .env.example .env     # macOS/Linux
```

Open `.env` and replace the placeholders:

```ini
BINANCE_API_KEY=your_actual_testnet_api_key
BINANCE_SECRET_KEY=your_actual_testnet_secret_key
```

---

## How to Run

### Show help

```bash
python cli.py --help
python cli.py market --help
python cli.py limit --help
python cli.py stop-limit --help
```

### Place a MARKET order

```bash
# Buy 0.001 BTC at market price
python cli.py market --symbol BTCUSDT --side BUY --quantity 0.001

# Sell 0.002 ETH at market price
python cli.py market --symbol ETHUSDT --side SELL --quantity 0.002
```

### Place a LIMIT order

```bash
# Buy 0.002 BTC if price drops to 30,000 USDT (notional = $60 > $50 minimum)
python cli.py limit --symbol BTCUSDT --side BUY --quantity 0.002 --price 30000

# Buy 0.001 BTC at 50,000 USDT (notional = $50, meets minimum)
python cli.py limit --symbol BTCUSDT --side BUY --quantity 0.001 --price 50000

# Sell 0.002 BTC when price reaches 40,000 USDT
python cli.py limit --symbol BTCUSDT --side SELL --quantity 0.002 --price 40000

# With custom time-in-force (IOC cancels unfilled portion immediately)
python cli.py limit --symbol BTCUSDT --side BUY --quantity 0.002 --price 30000 --time-in-force IOC
```

### Place a STOP-LIMIT order (bonus)

```bash
# BUY stop-limit: trigger at 109,000, execute limit at 110,000
# (trigger must be BELOW current price for BUY; notional = 0.002 x 109000 = $218)
python cli.py stop-limit --symbol BTCUSDT --side BUY --quantity 0.002 --price 110000 --stop-price 109000
```

### Interactive mode (bonus UX)

```bash
python cli.py --interactive
# or
python cli.py -i
```

Interactive mode walks you through every parameter with prompts and asks for confirmation before placing the order.

### Web UI (bonus)

```bash
python ui/app.py
```

Then open **http://localhost:5000** in your browser.

The dashboard provides:
- Order type tabs: **Market / Limit / Stop-Limit**
- BUY / SELL toggle with colour coding
- Dynamic form (price fields appear only when needed)
- Order history table with live status badges
- Real-time testnet connection indicator
- Inline validation error messages

---

## Log Files

Logs are written to `logs/trading_bot.log` automatically on first run.

Each log line includes a timestamp, log level, module name, and message.  
API requests, full responses, and any errors are all captured.

Sample log output:
```
2025-01-15 10:23:45 | INFO     | bot.cli                    | [Interactive] Starting order flow
2025-01-15 10:23:52 | INFO     | bot.client                 | POST https://testnet.binancefuture.com/fapi/v1/order  body={...}
2025-01-15 10:23:52 | DEBUG    | bot.client                 | HTTP 200  body={...}
2025-01-15 10:23:52 | INFO     | bot.orders                 | [MARKET] Order placed | orderId=12345 status=FILLED executedQty=0.001 avgPrice=42000.0
2025-01-15 10:23:52 | INFO     | bot.cli                    | SUCCESS | orderId=12345 status=FILLED
```

---

## Assumptions

1. **Testnet only** — the base URL is hard-coded to `https://testnet.binancefuture.com`. To use mainnet, change `TESTNET_BASE_URL` in `bot/client.py`.
2. **USDT-M perpetual futures** — targets the `/fapi/v1/order` endpoint for USDT-margined perpetual contracts; Stop-Limit uses `/fapi/v1/algoOrder` (Binance Algo Order API).
3. **Minimum notional** — Binance requires each order's notional value (quantity × price) to be at least a symbol-specific minimum (e.g. $50 USDT for BTCUSDT, $5 for many altcoins). The validator checks this before sending. The Web UI calculates and displays the exact minimum quantity needed from live mark price.
4. **Precision auto-rounding** — quantity is rounded to the symbol's `LOT_SIZE.stepSize`; price to the symbol's `PRICE_FILTER.tickSize`. The Web UI does this automatically on submit.
5. **No position management** — this bot only places orders; it does not track open positions, PnL, or account balance.
6. **GTC by default** — Limit and Stop-Limit orders use `GTC` (Good Till Cancelled) unless `--time-in-force` is specified.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Missing `.env` / empty API key | `BinanceAuthError` with setup instructions |
| Invalid symbol / side / quantity | `ValidationError` printed clearly before any API call |
| Binance API rejects order | `BinanceAPIError` with error code + message |
| Network timeout / DNS failure | `BinanceNetworkError` with human-readable message |
| Unexpected exception | Full traceback logged to file; clean message in console |

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP client for all Binance REST API calls |
| `python-dotenv` | Load `.env` credentials file |
| `tabulate` | Table formatting for CLI order output |
| `flask` | Web server for the bonus UI dashboard |
| `flask-cors` | CORS headers for the Flask API |

---

## Bonus Features Implemented

| Bonus | Details |
|---|---|
| **Stop-Limit order** | Via Binance Algo Order API (`/fapi/v1/algoOrder`); CLI subcommand `stop-limit` |
| **Enhanced CLI UX** | `--interactive` / `-i` mode with guided prompts, confirmation step, and coloured output |
| **Lightweight Web UI** | Dark-themed SPA at `http://localhost:5000`; live symbol autocomplete, per-symbol min qty/price range hints, tick-size auto-rounding |
