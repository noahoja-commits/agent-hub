"""
Mammon 💰 — Finance Agent
Stock/crypto prices, market data, portfolio tracking via Yahoo Finance (free, no API key).
"""
from __future__ import annotations
import logging, os, json, re
from typing import Any
import httpx
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.finance")

class FinanceAgent(BaseAgent):
    name = "Mammon"
    emoji = "💰"
    color = "#ccaa00"
    personality = "Greed is good. I track every tick, every coin, every opportunity."
    codename = "mammon"
    description = "Financial data — stock prices, crypto, market trends, portfolio tracking"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "stock_price": "Get current stock price, change, and key metrics",
            "crypto_price": "Get crypto price from major exchanges",
            "market_summary": "Get overall market summary (S&P, NASDAQ, DOW, BTC, ETH)",
            "portfolio_value": "Calculate portfolio value from a list of holdings",
            "convert_currency": "Convert between currencies at current rates",
            "company_info": "Get company overview, market cap, P/E ratio",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _h_stock_price(self, p):
        symbol = (p.get("symbol","") or p.get("query","")).upper().strip()
        if not symbol: return self._fail("symbol required (e.g. AAPL, TSLA)")
        data = await self._yahoo_quote(symbol)
        if not data: return self._fail(f"Could not fetch data for {symbol}")
        price = data.get("regularMarketPrice", data.get("ask","?"))
        change = data.get("regularMarketChange", 0)
        pct = data.get("regularMarketChangePercent", 0)
        name = data.get("shortName", data.get("longName", symbol))
        direction = "📈" if change >= 0 else "📉"
        summary = f"{direction} **{name} ({symbol})**\n💵 ${price} | {'+' if change >= 0 else ''}{change:.2f} ({'+' if pct >= 0 else ''}{pct:.2f}%)"
        return self._ok(summary=summary, data=data)

    async def _h_crypto_price(self, p):
        coin = (p.get("coin","") or p.get("query","")).upper().strip()
        if not coin: return self._fail("coin symbol required (e.g. BTC, ETH)")
        data = await self._crypto_quote(coin)
        if not data: return self._fail(f"Could not fetch crypto data for {coin}")
        price = data.get("price", "?")
        change24h = data.get("change24h", 0)
        direction = "📈" if change24h >= 0 else "📉"
        summary = f"{direction} **{coin}**\n💎 ${price:,.2f} | 24h: {'+' if change24h >= 0 else ''}{change24h:.2f}%"
        return self._ok(summary=summary, data=data)

    async def _h_market_summary(self, p):
        symbols = ["^GSPC","^IXIC","^DJI"]
        lines = ["📊 **Market Summary**"]
        for s in symbols:
            d = await self._yahoo_quote(s)
            if d:
                price = d.get("regularMarketPrice","?")
                chg = d.get("regularMarketChangePercent",0)
                name = {"^GSPC":"S&P 500","^IXIC":"NASDAQ","^DJI":"DOW"}.get(s,s)
                direction = "🟢" if chg >= 0 else "🔴"
                lines.append(f"  {direction} {name}: ${price:,.0f} ({'+' if chg>=0 else ''}{chg:.2f}%)")
        # Crypto
        for coin in ["BTC","ETH"]:
            d = await self._crypto_quote(coin)
            if d:
                lines.append(f"  💎 {coin}: ${d.get('price',0):,.0f} ({d.get('change24h',0):+.1f}%)")
        return self._ok(summary="\n".join(lines), data={})

    async def _h_portfolio_value(self, p):
        holdings = p.get("holdings", {})  # {"AAPL": 10, "TSLA": 5}
        if not holdings: return self._fail("holdings dict required: {'AAPL': shares, 'TSLA': shares}")
        total = 0; lines = ["💼 **Portfolio**"]
        for sym, shares in holdings.items():
            d = await self._yahoo_quote(sym.upper())
            if d:
                price = d.get("regularMarketPrice",0)
                val = price * shares; total += val
                lines.append(f"  {sym}: {shares} × ${price:.2f} = ${val:,.2f}")
        lines.append(f"\n  💰 **Total: ${total:,.2f}**")
        return self._ok(summary="\n".join(lines), data={"total":total,"holdings":holdings})

    async def _h_convert_currency(self, p):
        from_cur = (p.get("from","") or p.get("query","")).upper().strip()[:3]
        to_cur = p.get("to","USD").upper().strip()[:3]
        amount = p.get("amount", 1)
        if not from_cur: return self._fail("from currency required")
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.get(f"https://open.er-api.com/v6/latest/{from_cur}")
                if r.status_code == 200:
                    d = r.json()
                    rate = d.get("rates",{}).get(to_cur, 0)
                    if rate:
                        converted = amount * rate
                        return self._ok(summary=f"💱 {amount} {from_cur} = {converted:.2f} {to_cur} (rate: {rate:.4f})", data={"from":from_cur,"to":to_cur,"rate":rate,"converted":converted})
        except: pass
        return self._fail("Currency conversion unavailable")

    async def _h_company_info(self, p):
        symbol = (p.get("symbol","") or p.get("query","")).upper().strip()
        if not symbol: return self._fail("symbol required")
        d = await self._yahoo_quote(symbol)
        if not d: return self._fail(f"Could not find: {symbol}")
        lines = [f"🏢 **{d.get('longName',d.get('shortName',symbol))}** ({symbol})"]
        for k, label in [("marketCap","Market Cap"),("trailingPE","P/E"),("fiftyTwoWeekHigh","52W High"),("fiftyTwoWeekLow","52W Low"),("dividendYield","Div Yield"),("averageVolume","Avg Volume")]:
            v = d.get(k)
            if v is not None:
                if k == "marketCap" and v > 1e9: v = f"${v/1e9:.1f}B"
                elif k == "marketCap": v = f"${v/1e6:.0f}M"
                elif k in ("trailingPE","fiftyTwoWeekHigh","fiftyTwoWeekLow"): v = f"${v:.2f}"
                elif k == "dividendYield": v = f"{v*100:.2f}%"
                lines.append(f"  {label}: {v}")
        return self._ok(summary="\n".join(lines), data=d)

    async def _yahoo_quote(self, symbol):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.get(url, headers={"User-Agent":"AgentHub/1.0"})
                if r.status_code != 200:
                    # Try quote endpoint
                    r2 = await cl.get(f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}", headers={"User-Agent":"AgentHub/1.0"})
                    if r2.status_code == 200:
                        d = r2.json()
                        result = d.get("quoteResponse",{}).get("result",[])
                        return result[0] if result else {}
                    return {}
                d = r.json()
                meta = d.get("chart",{}).get("result",[{}])[0].get("meta",{})
                return meta
        except Exception as e:
            logger.debug("Yahoo quote failed for %s: %s", symbol, e)
            return {}

    async def _crypto_quote(self, coin):
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin.lower()}&vs_currencies=usd&include_24hr_change=true")
                if r.status_code == 200:
                    d = r.json()
                    data = d.get(coin.lower(),{})
                    return {"price": data.get("usd",0), "change24h": data.get("usd_24h_change",0)}
        except: pass
        # Fallback: use pre-mapped names
        coingecko_map = {"BTC":"bitcoin","ETH":"ethereum","SOL":"solana","DOGE":"dogecoin","XRP":"ripple","ADA":"cardano","DOT":"polkadot","AVAX":"avalanche-2"}
        mapped = coingecko_map.get(coin, coin.lower())
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.get(f"https://api.coingecko.com/api/v3/simple/price?ids={mapped}&vs_currencies=usd&include_24hr_change=true")
                if r.status_code == 200:
                    d = r.json()
                    data = d.get(mapped,{})
                    return {"price": data.get("usd",0), "change24h": data.get("usd_24h_change",0)}
        except: pass
        return {}
