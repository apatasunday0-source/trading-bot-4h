import asyncio
import os
import requests
import pandas as pd
from ta.trend import EMAIndicator
from telegram import Bot

# Load credentials securely from GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PAIRS = [
    "USDCHF=X", "USDCAD=X", "GBPCAD=X", "AUDCAD=X",
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", 
    "NZDUSD=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X", 
    "AUDNZD=X", "EURAUD=X", "GBPNZD=X", "AUDCHF=X", 
    "NZDCAD=X", "CADJPY=X", "CHFJPY=X", "GC=F", "BTC-USD"
]

TIMEFRAMES = ["4h"]
ENABLE_TREND_CONTINUATION = True
ENABLE_PHISON_20MA = True

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

async def send_alert(message: str):
    if not bot or not CHAT_ID:
        print("Telegram bot or chat ID not configured.")
        return
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        print("Telegram alert sent successfully.")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def fetch_forex_data(symbol: str, timeframe: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=60m&range=2mo"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, unit="s"),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote.get("volume", [0] * len(timestamps)),
        })
        df = df.dropna().set_index("timestamp")
        df = df.resample("4h").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        })
        return df.dropna().reset_index()
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def calculate_support_resistance(df: pd.DataFrame, window: int = 10) -> tuple:
    df["ph"] = df["high"].rolling(window=window, center=True).apply(lambda x: x[window // 2] == max(x), raw=True)
    df["pl"] = df["low"].rolling(window=window, center=True).apply(lambda x: x[window // 2] == min(x), raw=True)
    recent_res = df[df["ph"] == 1]["high"].iloc[-1] if not df[df["ph"] == 1].empty else df["high"].max()
    recent_sup = df[df["pl"] == 1]["low"].iloc[-1] if not df[df["pl"] == 1].empty else df["low"].min()
    return recent_res, recent_sup

def check_strategies(df: pd.DataFrame, symbol: str, tf: str):
    if len(df) < 50:
        return [], 0

    df["ema_20"] = EMAIndicator(close=df["close"], window=20).ema_indicator()
    df["ema_50"] = EMAIndicator(close=df["close"], window=50).ema_indicator()
    df["ema_100"] = EMAIndicator(close=df["close"], window=min(100, len(df) - 1)).ema_indicator()
    df["ema_200"] = EMAIndicator(close=df["close"], window=min(200, len(df) - 1)).ema_indicator()

    res_zone, sup_zone = calculate_support_resistance(df)
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    live_price = df.iloc[-1]["close"]
    signals = []

    if ENABLE_TREND_CONTINUATION and len(df) >= 200:
        bull_alignment = (curr["ema_20"] > curr["ema_50"]) and (curr["ema_50"] > curr["ema_100"]) and (curr["ema_100"] > curr["ema_200"])
        near_support = abs(curr["close"] - sup_zone) / sup_zone < 0.005 or (curr["low"] <= sup_zone <= curr["high"])
        if bull_alignment and near_support:
            signals.append({"strategy": "Trend Continuation", "direction": "BUY"})

        bear_alignment = (curr["ema_20"] < curr["ema_50"]) and (curr["ema_50"] < curr["ema_100"]) and (curr["ema_100"] < curr["ema_200"])
        near_resistance = abs(curr["close"] - res_zone) / res_zone < 0.005 or (curr["low"] <= res_zone <= curr["high"])
        if bear_alignment and near_resistance:
            signals.append({"strategy": "Trend Continuation", "direction": "SELL"})

    if ENABLE_PHISON_20MA:
        bullish_close_cross = (prev["close"] < prev["ema_20"]) and (curr["close"] > curr["ema_20"])
        bearish_close_cross = (prev["close"] > prev["ema_20"]) and (curr["close"] < curr["ema_20"])
        if bullish_close_cross:
            signals.append({"strategy": "Phison 20 MA Structure-Shift", "direction": "BUY"})
        if bearish_close_cross:
            signals.append({"strategy": "Phison 20 MA Structure-Shift", "direction": "SELL"})

    return signals, live_price

async def main():
    print(f"Executing cloud market scan for {len(PAIRS)} assets on 4H timeframe...")
    for symbol in PAIRS:
        for tf in TIMEFRAMES:
            df = fetch_forex_data(symbol, tf)
            if df is None or df.empty:
                continue
            signals, price = check_strategies(df, symbol, tf)
            for sig in signals:
                msg = (
                    f"🚨 *AUTOMATED 4H SIGNAL* 🚨\n\n"
                    f"• *Asset:* `{symbol}`\n"
                    f"• *Timeframe:* `{tf}`\n"
                    f"• *Strategy:* {sig['strategy']}\n"
                    f"• *Signal Direction:* *{sig['direction']}*\n"
                    f"• *Current Price:* `{price:,.2f}`\n\n"
                    f"_Alert only. Manual confirmation required._"
                )
                await send_alert(msg)

if __name__ == "__main__":
    asyncio.run(main())
