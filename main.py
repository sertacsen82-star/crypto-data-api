from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import redis
import json
import os
from datetime import datetime

app = FastAPI(title="Crypto Data API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

REDIS_URL = os.getenv("REDIS_URL", None)
cache = None
if REDIS_URL:
    try:
        cache = redis.from_url(REDIS_URL, decode_responses=True)
        cache.ping()
    except Exception as e:
        print(f"Redis not available: {e}")

BINANCE_BASE = "https://api.binance.com/api/v3"

def get_cache(key):
    if cache:
        try:
            data = cache.get(key)
            if data:
                return json.loads(data)
        except:
            pass
    return None

def set_cache(key, value, ttl=10):
    if cache:
        try:
            cache.setex(key, ttl, json.dumps(value))
        except:
            pass

@app.get("/")
async def root():
    return {"status": "ok", "service": "crypto-data-api", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy", "redis": cache is not None}

@app.get("/price/{symbol}")
async def get_price(symbol: str):
    symbol = symbol.upper()
    cached = get_cache(f"price:{symbol}")
    if cached:
        cached["cached"] = True
        return cached
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            result = {
                "symbol": symbol,
                "price": float(data["lastPrice"]),
                "change_24h": float(data["priceChangePercent"]),
                "high_24h": float(data["highPrice"]),
                "low_24h": float(data["lowPrice"]),
                "volume_24h": float(data["volume"]),
                "cached": False
            }
            set_cache(f"price:{symbol}", result, ttl=10)
            return result
        except:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

@app.get("/candles/{symbol}")
async def get_candles(symbol: str, interval: str = "1h", limit: int = 50):
    symbol = symbol.upper()
    cached = get_cache(f"candles:{symbol}:{interval}")
    if cached:
        return {"symbol": symbol, "interval": interval, "candles": cached, "cached": True}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{BINANCE_BASE}/klines", params={"symbol": symbol, "interval": interval, "limit": limit})
            resp.raise_for_status()
            candles = [{"time": c[0], "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in resp.json()]
            set_cache(f"candles:{symbol}:{interval}", candles, ttl=30)
            return {"symbol": symbol, "interval": interval, "candles": candles, "cached": False}
        except:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

@app.get("/top")
async def get_top_coins(limit: int = 10):
    cached = get_cache(f"top:{limit}")
    if cached:
        return {"coins": cached, "cached": True}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BINANCE_BASE}/ticker/24hr")
        all_tickers = resp.json()
        usdt_pairs = sorted([t for t in all_tickers if t["symbol"].endswith("USDT")], key=lambda x: float(x["quoteVolume"]), reverse=True)[:limit]
        result = [{"symbol": t["symbol"], "price": float(t["lastPrice"]), "change_24h": float(t["priceChangePercent"]), "volume_usdt": float(t["quoteVolume"])} for t in usdt_pairs]
        set_cache(f"top:{limit}", result, ttl=60)
        return {"coins": result, "cached": False}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
