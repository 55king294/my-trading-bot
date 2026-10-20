import time
import pandas as pd
import numpy as np
from datetime import datetime
import MetaTrader5 as mt5

# ====== YAHAN APNI DEMO ACCOUNT DETAILS DALIYE ======
MT5_LOGIN = 345695737  
MT5_PASSWORD = "aA1Shahzad@"  
MT5_SERVER = "XMGlobal-MT5 10"  
# ====================================================

SYMBOLS = ["GOLD24-7", "BTCUSD"]
TIMEFRAME = mt5.TIMEFRAME_H4
CHECK_INTERVAL_MIN = 10
ACCOUNT_USD = 1000.0
RISK_PCT = 1.0
MAGIC_NUMBER = 123456

# Break Even Settings
BE_TRIGGER_POINTS = 50  # Kitne points profit par SL break even ho
BE_OFFSET_POINTS = 5    # Break even par SL ko entry se thoda upar/neeche rakhein

def connect_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"MT5 Connect nahi hua, error: {mt5.last_error()}")
        quit()
    print("MT5 se connect ho gaya!")

def fetch_data(symbol, count=2000):
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, count)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'tick_volume']].copy()
    df.columns = ["open", "high", "low", "close", "vol"]
    return df

def calculate_adx(df, period=14):
    df['up'] = df['high'] - df['high'].shift(1)
    df['down'] = df['low'].shift(1) - df['low']
    df['+dm'] = np.where((df['up'] > df['down']) & (df['up'] > 0), df['up'], 0.0)
    df['-dm'] = np.where((df['down'] > df['up']) & (df['down'] > 0), df['down'], 0.0)
    tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    df['+di'] = 100 * (df['+dm'].ewm(alpha=1/period, adjust=False).mean() / atr)
    df['-di'] = 100 * (df['-dm'].ewm(alpha=1/period, adjust=False).mean() / atr)
    dx = 100 * abs(df['+di'] - df['-di']) / (df['+di'] + df['-di'])
    return dx.ewm(alpha=1/period, adjust=False).mean()

def get_trend(df):
    ema50 = df['close'].ewm(span=50, adjust=False).mean()
    ema200 = df['close'].ewm(span=200, adjust=False).mean()
    adx = calculate_adx(df)
    trend = "NEUTRAL"
    if ema50.iloc[-1] > ema200.iloc[-1] and df['close'].iloc[-1] > ema50.iloc[-1]:
        trend = "UP"
    elif ema50.iloc[-1] < ema200.iloc[-1] and df['close'].iloc[-1] < ema50.iloc[-1]:
        trend = "DOWN"
    return trend, adx.iloc[-1], df.iloc[-1]

def calculate_lot_size(symbol, sl_distance):
    if sl_distance <= 0: return 0.01
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None: return 0.01
    risk_amount = ACCOUNT_USD * (RISK_PCT / 100.0)
    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    if tick_size == 0: return 0.01
    points = sl_distance / tick_size
    loss_per_lot = points * tick_value
    if loss_per_lot == 0: return 0.01
    lot_size = risk_amount / loss_per_lot
    lot_size = round(lot_size, 2)
    if lot_size < symbol_info.volume_min: lot_size = symbol_info.volume_min
    if lot_size > symbol_info.volume_max: lot_size = symbol_info.volume_max
    return lot_size

def place_trade(symbol, direction, price, sl_distance, tp_distance):
    lot = calculate_lot_size(symbol, sl_distance)
    if direction == "BUY":
        sl = price - sl_distance
        tp = price + tp_distance
        order_type = mt5.ORDER_TYPE_BUY
    else:
        sl = price + sl_distance
        tp = price - tp_distance
        order_type = mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": "Auto 4H Trend",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"? Trade fail hui {symbol}: {result.comment}")
    else:
        print(f"? {direction} Trade lag gayi {symbol} | Lot: {lot} | SL: {sl:.5f} | TP: {tp:.5f}")

def manage_break_even(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions: return

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None: return

    point = symbol_info.point
    tick = mt5.symbol_info_tick(symbol)

    for pos in positions:
        if pos.magic != MAGIC_NUMBER: continue

        # BUY position ke liye
        if pos.type == mt5.ORDER_TYPE_BUY:
            # Check karein ke profit trigger se zyada hai ya nahi
            if tick.bid - pos.price_open >= BE_TRIGGER_POINTS * point:
                # Check karein ke SL pehle se break even par nahi hai
                if pos.sl < pos.price_open:
                    new_sl = pos.price_open + (BE_OFFSET_POINTS * point)
                    modify_sl(pos, new_sl, pos.tp)
                    print(f"?? {symbol} BUY Trade ka SL Break Even par set ho gaya (Entry: {pos.price_open}, New SL: {new_sl})")

        # SELL position ke liye
        elif pos.type == mt5.ORDER_TYPE_SELL:
            # Check karein ke profit trigger se zyada hai ya nahi
            if pos.price_open - tick.ask >= BE_TRIGGER_POINTS * point:
                # Check karein ke SL pehle se break even par nahi hai
                if pos.sl > pos.price_open or pos.sl == 0:
                    new_sl = pos.price_open - (BE_OFFSET_POINTS * point)
                    modify_sl(pos, new_sl, pos.tp)
                    print(f"?? {symbol} SELL Trade ka SL Break Even par set ho gaya (Entry: {pos.price_open}, New SL: {new_sl})")

def modify_sl(pos, new_sl, tp):
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": pos.ticket,
        "symbol": pos.symbol,
        "sl": new_sl,
        "tp": tp,
    }
    mt5.order_send(request)

def main():
    connect_mt5()
    print(f"?? Auto Trade Bot Chalu | Break Even ON")
    
    while True:
        try:
            print(f"\n? Waqt: {datetime.now().strftime('%H:%M')}")
            
            # Break Even Check (har 10 minute baad)
            for symbol in SYMBOLS:
                manage_break_even(symbol)

            for symbol in SYMBOLS:
                positions = mt5.positions_get(symbol=symbol)
                if positions and len(positions) > 0:
                    print(f"[{symbol}] Pehle se trade khuli hai, skip kar rahe hain.")
                    continue

                df = fetch_data(symbol)
                if df is not None:
                    trend, adx, last_candle = get_trend(df)
                    
                    if adx > 20:
                        price = last_candle['close']
                        sl_distance = price * 0.01 
                        tp_distance = price * 0.02
                        
                        if trend == "UP":
                            place_trade(symbol, "BUY", mt5.symbol_info_tick(symbol).ask, sl_distance, tp_distance)
                        elif trend == "DOWN":
                            place_trade(symbol, "SELL", mt5.symbol_info_tick(symbol).bid, sl_distance, tp_distance)
                        else:
                            print(f"[{symbol}] Trend NEUTRAL | Koi trade nahi")
                    else:
                        print(f"[{symbol}] ADX kam hai ({adx:.1f}) | Koi trade nahi")
                        
            print(f"? Agli jaanch {CHECK_INTERVAL_MIN} minute baad...")
            time.sleep(CHECK_INTERVAL_MIN * 60)
            
        except KeyboardInterrupt:
            print("\n?? Bot band kiya gaya.")
            break
        except Exception as e:
            print(f"?? Error aya: {e}")
            time.sleep(60)

    mt5.shutdown()

if __name__ == "__main__":
    main()