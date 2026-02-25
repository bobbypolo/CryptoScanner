# Data API Specification

## CoinGecko /coins/markets

### Endpoint
```
GET https://api.coingecko.com/api/v3/coins/markets
  ?vs_currency=usd
  &order=market_cap_desc
  &per_page=250
  &page={1..4}
  &sparkline=false
```

### Rate Limits
| Tier | Limit | Monthly Cap |
|------|-------|-------------|
| Public (no key) | 5-15 req/min (unstable) | None stated |
| Demo (free key) | 30 req/min (stable) | 10,000/month |

### Auth
Header: `x-cg-demo-api-key: {key}` (optional)

### Response Fields Used
```json
{
  "id": "render-token",
  "symbol": "rndr",
  "name": "Render",
  "market_cap": 45000000,
  "fully_diluted_valuation": 89000000,
  "total_volume": 8500000,
  "circulating_supply": 365000000,
  "total_supply": 530000000,
  "market_cap_rank": 85
}
```

### Pagination
- per_page max: 250
- Top 1000 coins: 4 calls (page=1..4)

---

## CCXT Async OHLCV

### Method
```python
import ccxt.async_support as ccxt

exchange = ccxt.binance({'enableRateLimit': True})
ohlcv = await exchange.fetch_ohlcv(
    symbol='BTC/USDT',
    timeframe='1d',
    since=timestamp_ms,
    limit=60
)
```

### Response
```python
[[timestamp_ms, open, high, low, close, volume], ...]
```

### Binance Rate Limits
- 6,000 weight/min per IP
- /api/v3/klines costs weight 2 per call
- Max 1000 candles per response
- ccxt enableRateLimit=True auto-throttles

### Concurrency Pattern
```python
sem = asyncio.Semaphore(10)

async def fetch_one(exchange, symbol):
    async with sem:
        return await exchange.fetch_ohlcv(symbol, '1d', since=since, limit=60)

tasks = [fetch_one(exchange, s) for s in symbols]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### Error Handling
- ccxt.RateLimitExceeded → exponential backoff (2^attempt + jitter)
- ccxt.BadSymbol → skip symbol, log warning
- ccxt.NetworkError → backoff + retry
- Empty response → skip symbol

---

## Rate Limiting Strategy (3-Layer)

### Layer 1: ccxt Built-in
```python
exchange = ccxt.binance({'enableRateLimit': True})
```

### Layer 2: asyncio.Semaphore
```python
sem = asyncio.Semaphore(10)  # max 10 concurrent requests
```

### Layer 3: aiolimiter (for CoinGecko)
```python
from aiolimiter import AsyncLimiter
cg_limiter = AsyncLimiter(25, 60)  # 25 req per 60 seconds
```

### Backoff Pattern
```python
async def fetch_with_backoff(coro_factory, max_retries=5):
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except (aiohttp.ClientResponseError, ccxt.RateLimitExceeded) as e:
            if attempt == max_retries - 1:
                raise
            delay = (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)
```

---

## Symbol Mapping: CoinGecko → CCXT

### Problem
CoinGecko: `{"symbol": "render", "id": "render-token"}`
CCXT requires: `"RENDER/USDT"`
Multiple CG coins can share symbol "AI"

### Solution
1. `coin["symbol"].upper() + "/USDT"` → candidate pair
2. `exchange.load_markets()` → available pairs (ccxt caches internally)
3. Check candidate in `exchange.markets`
4. Deduplicate: lowest `market_cap_rank` wins (= highest cap)
5. Log dropped symbols for debugging
