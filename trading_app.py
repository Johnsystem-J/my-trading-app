import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import copy
import yfinance as yf
import pandas_ta as ta
from scipy.signal import find_peaks

# --- ค่าคงที่และ Dictionaries ---
JOURNAL_FILE = Path("trading_journal.csv")
CONFIG_FILE = Path("config.json")
PAIRS_TO_ANALYZE = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
SL_ATR_MULTIPLIER = 2.0
RR_RATIO = 1.5

PIP_MULTIPLIERS = {"JPY": 100, "Default": 10000}
PIP_VALUE_USD_PER_LOT = {
    "EUR/USD": 10, "GBP/USD": 10, "USD/JPY": 6.8,
    "AUD/USD": 10, "USD/CAD": 7.2
}

# --- ฟังก์ชันจัดการไฟล์ ---
def save_config(settings_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings_data, f, indent=4, ensure_ascii=False)

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "global_settings" in data and "pair_settings" in data: return data
            else: return get_default_settings()
        except (json.JSONDecodeError, TypeError): return get_default_settings()
    else: return get_default_settings()

def get_default_settings():
    default_pair_settings = {
        "current_price": 1.08550, "ema_50_price": 1.08200, "rsi_14_value": 40.0,
        "raw_atr_value": 0.00150, "is_bullish_candle": False, "is_bearish_candle": False,
        "d1_trend": "ยังไม่ไดเช็ค", "near_key_level": False, "market_structure_ok": False
    }
    return {
        "global_settings": {"account_balance": 1000.0, "risk_percentage": 1.0},
        "pair_settings": {pair: default_pair_settings.copy() for pair in PAIRS_TO_ANALYZE}
    }

def load_journal():
    if not JOURNAL_FILE.exists(): return create_empty_journal_df()
    try:
        df = pd.read_csv(JOURNAL_FILE)
        required_columns = create_empty_journal_df().columns
        for col in required_columns:
            if col not in df.columns: df[col] = 0.0 if "P/L" in col or col == "Lot_Size" else ""
        return df
    except pd.errors.EmptyDataError: return create_empty_journal_df()

def save_journal(df):
    df.to_csv(JOURNAL_FILE, index=False)

def create_empty_journal_df():
     return pd.DataFrame(columns=[
            "Date", "Pair", "Direction", "Entry", "Exit", "SL", "TP", "Lot_Size",
            "P/L (Pips)", "P/L ($)", "Outcome", "Reason", "Review"
        ])

# --- ฟังก์ชันวิเคราะห์อัตโนมัติ (แก้ไขแล้ว) ---
@st.cache_data(ttl=600) # Cache a result for 10 minutes
def analyze_chart_data(pair, timeframe, period):
    ticker_name = f"{pair.replace('/', '')}=X"
    df = yf.download(ticker_name, period=period, interval=timeframe, progress=False)
    
    # --- ส่วนที่แก้ไข: จัดการกับ MultiIndex Columns ---
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel()
    df.columns = df.columns.str.lower()
    # --- จบส่วนที่แก้ไข ---

    if df.empty:
        return {"trend": "No Data", "structure_ok": False, "latest_ema": 0}

    # Calculate EMA
    df.ta.ema(length=50, append=True)
    latest_close = df['close'].iloc[-1]
    latest_ema = df['ema_50'].iloc[-1]
    
    # Analyze Trend
    trend = "ขาขึ้น (Uptrend)" if latest_close > latest_ema else "ขาลง (Downtrend)"

    # Analyze Market Structure
    high_peaks, _ = find_peaks(df['high'], distance=5, prominence=0.001)
    low_peaks, _ = find_peaks(-df['low'], distance=5, prominence=0.001)
    
    structure_ok = False
    if trend == "ขาขึ้น (Uptrend)" and len(high_peaks) >= 2 and len(low_peaks) >= 2:
        if df['high'].iloc[high_peaks[-1]] > df['high'].iloc[high_peaks[-2]] and \
           df['low'].iloc[low_peaks[-1]] > df['low'].iloc[low_peaks[-2]]:
            structure_ok = True
    elif trend == "ขาลง (Downtrend)" and len(high_peaks) >= 2 and len(low_peaks) >= 2:
        if df['high'].iloc[high_peaks[-1]] < df['high'].iloc[high_peaks[-2]] and \
           df['low'].iloc[low_peaks[-1]] < df['low'].iloc[low_peaks[-2]]:
            structure_ok = True
            
    return {"trend": trend, "structure_ok": structure_ok, "latest_ema": latest_ema}

# --- ฟังก์ชันผู้ช่วยอื่นๆ ---
def get_pip_multiplier(pair):
    return PIP_MULTIPLIERS["JPY"] if "JPY" in pair else PIP_MULTIPLIERS["Default"]

def calculate_position_size(balance, risk_pct, sl_pips, pair):
    if sl_pips <= 0: return 0, 0
    risk_amount = balance * (risk_pct / 100)
    pip_value = PIP_VALUE_USD_PER_LOT.get(pair, 10)
    lot_size = risk_amount / (sl_pips * pip_value)
    return lot_size, risk_amount

def display_trade_plan(action, entry, sl, tp, sl_pips, tp_pips, lot_size, risk_amount):
    st.subheader(f"แผนการเทรด: {action}")
    c1, c2, c3 = st.columns(3)
    c1.metric("ราคาเข้า (Entry)", f"{entry:.5f}")
    c2.metric("Stop Loss (SL)", f"{sl:.5f}", delta=f"-{sl_pips:.1f} Pips", delta_color="inverse")
    c3.metric("Take Profit (TP)", f"{tp:.5f}", delta=f"+{tp_pips:.1f} Pips")
    st.info(f"**ขนาด Position ที่แนะนำ: {lot_size:.2f} lots** (ความเสี่ยง: ${risk_amount:.2f})")

# --- ส่วนหลักของแอป ---
st.set_page_config(layout="wide", page_title="Trading Dashboard Pro+")

if 'app_state' not in st.session_state: st.session_state.app_state = load_config()
if 'active_mode' not in st.session_state: st.session_state.active_mode = "วางแผนเทรด (Dashboard)"
if 'edit_index' not in st.session_state: st.session_state.edit_index = None

previous_state = copy.deepcopy(st.session_state.app_state)

with st.sidebar:
    if st.button("📈 วางแผนเทรด", use_container_width=True, type="primary" if st.session_state.active_mode == "วางแผนเทรด (Dashboard)" else "secondary"):
        st.session_state.active_mode = "วางแผนเทรด (Dashboard)"
        st.rerun()
    if st.button("📓 บันทึกและวิเคราะห์ผล", use_container_width=True, type="primary" if "Journal" in st.session_state.active_mode else "secondary"):
        st.session_state.active_mode = "Journal"
        st.rerun()
    st.divider()
    st.header("⚙️ ตั้งค่าส่วนกลาง")
    st.session_state.app_state["global_settings"]["account_balance"] = st.number_input("ยอดเงินในบัญชี ($)", value=st.session_state.app_state["global_settings"].get("account_balance", 1000.0), format="%.2f")
    st.session_state.app_state["global_settings"]["risk_percentage"] = st.slider("ความเสี่ยงที่ยอมรับได้ (%)", 0.5, 5.0, value=st.session_state.app_state["global_settings"].get("risk_percentage", 1.0), step=0.1)

def create_analysis_panel(pair_name):
    pair_settings = st.session_state.app_state["pair_settings"].get(pair_name, get_default_settings()["pair_settings"][pair_name])
    global_settings = st.session_state.app_state["global_settings"]

    st.header(f"ข้อมูลตลาดของ {pair_name}")
    
    if st.button(f"🔍 วิเคราะห์กราฟ {pair_name} อัตโนมัติ", key=f"analyze_{pair_name}", use_container_width=True):
        with st.spinner("กำลังดึงและวิเคราะห์ข้อมูล D1 และ H4..."):
            st.session_state[f"{pair_name}_d1_analysis"] = analyze_chart_data(pair_name, "1d", "1y")
            st.session_state[f"{pair_name}_h4_analysis"] = analyze_chart_data(pair_name, "4h", "6mo")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Indicators (H1)")
        current_price = st.number_input("ราคาปัจจุบัน", key=f"curr_{pair_name}", format="%.5f", step=0.00001, value=pair_settings.get("current_price", 1.0))
        rsi_14_value = st.number_input("ค่า RSI (14)", key=f"rsi_{pair_name}", min_value=0.0, max_value=100.0, step=0.1, value=float(pair_settings.get("rsi_14_value", 50.0)))
        raw_atr_value = st.number_input("ค่า ATR (14)", key=f"atr_{pair_name}", format="%.5f", step=0.00001, value=pair_settings.get("raw_atr_value", 0.0015))
    with c2:
        st.subheader("การยืนยันด้วยตนเอง")
        near_key_level = st.checkbox("จุดเข้าเทรดอยู่ใกล้แนวรับ/แนวต้านสำคัญ", key=f"keylevel_{pair_name}", value=pair_settings.get("near_key_level", False))
        is_bullish_candle = st.checkbox("พบแท่งเทียนกลับตัวฝั่ง 'ซื้อ'", key=f"bull_candle_{pair_name}", value=pair_settings.get("is_bullish_candle", False))
        is_bearish_candle = st.checkbox("พบแท่งเทียนกลับตัวฝั่ง 'ขาย'", key=f"bear_candle_{pair_name}", value=pair_settings.get("is_bearish_candle", False))

    st.session_state.app_state["pair_settings"][pair_name] = {
        "current_price": current_price, "rsi_14_value": rsi_14_value, 
        "raw_atr_value": raw_atr_value, "is_bullish_candle": is_bullish_candle, "is_bearish_candle": is_bearish_candle,
        "near_key_level": near_key_level,
        "d1_trend": st.session_state.app_state["pair_settings"].get(pair_name, {}).get("d1_trend", "ยังไม่ไดเช็ค"),
        "market_structure_ok": st.session_state.app_state["pair_settings"].get(pair_name, {}).get("market_structure_ok", False)
    }

    st.divider()
    with st.container(border=True):
        st.subheader("บทวิเคราะห์และแผนการเทรด")
        
        d1_analysis = st.session_state.get(f"{pair_name}_d1_analysis")
        h4_analysis = st.session_state.get(f"{pair_name}_h4_analysis")

        if not d1_analysis or not h4_analysis:
            st.info("กรุณากดปุ่ม 'วิเคราะห์กราฟอัตโนมัติ' เพื่อเริ่ม")
        else:
            d1_trend = d1_analysis["trend"]
            h4_trend = h4_analysis["trend"]
            h4_structure_ok = h4_analysis["structure_ok"]
            
            buy_d1_ok, buy_h4_ok, buy_structure_ok, buy_keylevel_ok, buy_rsi_ok, buy_candle_ok = (d1_trend == "ขาขึ้น (Uptrend)"), (h4_trend == "ขาขึ้น (Uptrend)"), h4_structure_ok, near_key_level, (30 < rsi_14_value <= 45), is_bullish_candle
            sell_d1_ok, sell_h4_ok, sell_structure_ok, sell_keylevel_ok, sell_rsi_ok, sell_candle_ok = (d1_trend == "ขาลง (Downtrend)"), (h4_trend == "ขาลง (Downtrend)"), h4_structure_ok, near_key_level, (55 <= rsi_14_value < 70), is_bearish_candle
            
            st.markdown("**Checklist สัญญาณ:**")
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"{'✅' if buy_d1_ok or sell_d1_ok else '❌'} **D1 Trend:** {d1_trend}")
            c1.markdown(f"{'✅' if buy_h4_ok or sell_h4_ok else '❌'} **H4 Trend:** {h4_trend}")
            c2.markdown(f"{'✅' if buy_structure_ok or sell_structure_ok else '❌'} **H4 Market Structure:** {'สอดคล้อง' if h4_structure_ok else 'ไม่สอดคล้อง'}")
            c2.markdown(f"{'✅' if buy_keylevel_ok or sell_keylevel_ok else '...'} **Key Level:** {'ใกล้โซนสำคัญ' if near_key_level else 'ยังไม่เช็ค'}")
            c3.markdown(f"{'✅' if buy_rsi_ok or sell_rsi_ok else '❌'} **H1 Pullback (RSI):** {rsi_14_value:.1f}")
            c3.markdown(f"{'✅' if buy_candle_ok or sell_candle_ok else '❌'} **H1 Confirmation:** {'พบสัญญาณ' if buy_candle_ok or sell_candle_ok else 'รอแท่งเทียน'}")
            st.divider()

            is_strong_buy = all([buy_d1_ok, buy_h4_ok, buy_structure_ok, buy_keylevel_ok, buy_rsi_ok, buy_candle_ok])
            is_strong_sell = all([sell_d1_ok, sell_h4_ok, sell_structure_ok, sell_keylevel_ok, sell_rsi_ok, sell_candle_ok])
            
            pip_multiplier = get_pip_multiplier(pair_name)
            atr_pips = raw_atr_value * pip_multiplier

            if is_strong_buy:
                st.success("**Action: สัญญาณซื้อคุณภาพสูง (High-Probability Buy Signal)**")
                # ... (โค้ดแสดงแผนและปุ่มยืนยันเหมือนเดิม)
            elif is_strong_sell:
                st.error("**Action: สัญญาณขายคุณภาพสูง (High-Probability Sell Signal)**")
                # ... (โค้ดแสดงแผนและปุ่มยืนยันเหมือนเดิม)
            else:
                st.warning("**Action: รอต่อไป (Wait / Stay Flat)**")
                # ... (โค้ดคำแนะนำแบบละเอียดเหมือนเดิม)

# --- โหมดที่ 1: วางแผนเทรด ---
if st.session_state.active_mode == "วางแผนเทรด (Dashboard)":
    st.title("📈 Trading Dashboard Pro+")
    st.caption("แดชบอร์ดวิเคราะห์แนวโน้มและโครงสร้างตลาดอัตโนมัติ")
    tabs = st.tabs(PAIRS_TO_ANALYZE)
    for i, pair_name in enumerate(PAIRS_TO_ANALYZE):
        with tabs[i]:
            create_analysis_panel(pair_name)

# --- โหมดที่ 2: บันทึกและวิเคราะห์ผล ---
elif "Journal" in st.session_state.active_mode:
    st.title("📓 Trading Journal & Performance")
    # ... (โค้ดหน้า Journal ทั้งหมดเหมือนเดิม) ...

# --- ตรรกะการบันทึกอัตโนมัติ ---
if previous_state != st.session_state.app_state:
    save_config(st.session_state.app_state)
    st.toast('บันทึกการเปลี่ยนแปลงอัตโนมัติ!', icon='💾')
