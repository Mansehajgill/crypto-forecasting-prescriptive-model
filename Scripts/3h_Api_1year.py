import requests
import pandas as pd
import time
from datetime import datetime, timedelta

def fetch_binance_ohlcv(symbol, interval='1h', days=365):
    """
    Page through Binance's 1h klines (max 1000 per request)
    to cover the last `days` days.
    """
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - days * 24 * 3600 * 1000
    all_bars = []

    while True:
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': start_ts,
            'limit': 1000
        }
        try:
            resp = requests.get("https://api.binance.com/api/v3/klines", params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_bars.extend(batch)
            start_ts = batch[-1][0] + 1
            if len(batch) < 1000:
                break
            time.sleep(0.3)
        except requests.RequestException as e:
            print(f"❌ Error fetching {symbol}: {e}")
            return pd.DataFrame()

    if not all_bars:
        print(f"⚠️ No OHLC data fetched for {symbol}.")
        return pd.DataFrame()

    df = pd.DataFrame(all_bars, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_vol', 'taker_buy_quote_vol', 'ignore'
    ])[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df

def fetch_market_caps_daily(coin_id, days=365):
    """
    Fetches 365 days of daily market caps from CoinGecko.
    Returns a DataFrame with timestamp, market_cap_usd.
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {'vs_currency': 'usd', 'days': days, 'interval': 'daily'}
    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        mc = pd.DataFrame(resp.json()['market_caps'], columns=['timestamp', 'market_cap_usd'])
        mc['timestamp'] = pd.to_datetime(mc['timestamp'], unit='ms')
        return mc.set_index('timestamp')
    except Exception as e:
        print(f"❌ Error fetching market cap for {coin_id}: {e}")
        return pd.DataFrame().set_index('timestamp', errors='ignore')

def main():
    coin_map = {
        'BTCUSDT': {'id': 'bitcoin', 'name': 'Bitcoin'},
        'ETHUSDT': {'id': 'ethereum', 'name': 'Ethereum'}
    }

    interval = '3h'
    days = 365
    all_coins = []

    print(f"📥 Fetching {interval} OHLC + daily market caps for {days} days...")

    for i, (sym, info) in enumerate(coin_map.items()):
        print(f"\n🔹 {sym} - {info['name']}")
        ohlc_1h = fetch_binance_ohlcv(sym, '1h', days=days)
        print(f"  OHLC rows fetched: {len(ohlc_1h)}")
        if not ohlc_1h.empty:
            print(f"  OHLC Date Range: {ohlc_1h['timestamp'].min()} to {ohlc_1h['timestamp'].max()}")

        if ohlc_1h.empty:
            print(f"⚠️ Skipping {sym} due to missing OHLC data.")
            continue

        # Resample to 3h
        ohlc_3h = (
            ohlc_1h
            .set_index('timestamp')
            .resample('3h')
            .agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            })
            .dropna()
            .reset_index()
        )

        time.sleep(1)  # Sleep between API calls

        mc_daily = fetch_market_caps_daily(info['id'], days=days)
        print(f"  Market cap rows fetched: {len(mc_daily)}")
        if not mc_daily.empty:
            print(f"  Market cap Date Range: {mc_daily.index.min()} to {mc_daily.index.max()}")

        if mc_daily.empty:
            print(f"⚠️ Skipping {sym} due to missing market cap data.")
            continue

        mc_3h = mc_daily.resample('3h').ffill().reset_index()

        df = pd.merge(ohlc_3h, mc_3h, on='timestamp', how='inner')
        print(f"  Merged 3-hour data rows: {len(df)}")
        if df.empty:
            print(f"⚠️ No overlapping timestamps for {sym}, skipping.")
            continue

        df['symbol'] = sym
        df['coin_name'] = info['name']
        df['price_change'] = df['close'] - df['open']
        df['price_pct_change'] = df['price_change'] / df['open'] * 100
        df['rolling_volatility'] = df['close'].rolling(window=8).std()  # 8x3h = 24h

        all_coins.append(df)
        time.sleep(8 + i)  # Sleep between coins

    if not all_coins:
        print("❌ No data fetched.")
        return

    print("🚀 Combining and computing dominance...")
    combined = pd.concat(all_coins)
    total_mc = combined.groupby('timestamp')['market_cap_usd'] \
                       .sum() \
                       .rename('total_market_cap_usd')
    combined = combined.join(total_mc, on='timestamp')
    combined['dominance_pct'] = combined['market_cap_usd'] / combined['total_market_cap_usd'] * 100

    out = combined[[
        'timestamp', 'symbol', 'coin_name', 'open', 'high', 'low', 'close', 'volume',
        'market_cap_usd', 'total_market_cap_usd', 'dominance_pct',
        'price_change', 'price_pct_change', 'rolling_volatility'
    ]].sort_values(['timestamp', 'dominance_pct'], ascending=[True, False])

    out.to_csv("crypto_dashboard_3h_1year.csv", index=False)
    print(f"\n✅ Saved crypto_dashboard_3h_1year.csv")

if __name__ == "__main__":
    main()