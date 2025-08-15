import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import copy
import yfinance as yf

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

# --- ฟังก์ชันผู้ช่วย ---
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
st.set_page_config(layout="wide", page_title="Trading Dashboard & Journal")

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
    
    if st.button(f"🔄 ดึงราคา {pair_name} ล่าสุด", key=f"refresh_{pair_name}"):
        try:
            ticker_name = f"{pair_name.replace('/', '')}=X"
            ticker = yf.Ticker(ticker_name)
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                latest_price = data['Close'].iloc[-1]
                st.session_state.app_state["pair_settings"][pair_name]["current_price"] = latest_price
                st.toast(f"อัปเดตราคา {pair_name} เป็น {latest_price:.5f} สำเร็จ!", icon="✅")
                st.rerun()
            else:
                st.error("ไม่สามารถดึงข้อมูลได้ ลองใหม่อีกครั้ง")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("ราคาและ Indicators พื้นฐาน")
        current_price = st.number_input("ราคาปัจจุบัน", key=f"curr_{pair_name}", format="%.5f", step=0.00001, value=pair_settings.get("current_price", 1.0))
        ema_50_price = st.number_input("ราคา EMA 50 (H4)", key=f"ema_{pair_name}", format="%.5f", step=0.00001, value=pair_settings.get("ema_50_price", 1.0))
        rsi_14_value = st.number_input("ค่า RSI (H1)", key=f"rsi_{pair_name}", min_value=0.0, max_value=100.0, step=0.1, value=float(pair_settings.get("rsi_14_value", 50.0)))
        raw_atr_value = st.number_input("ค่า ATR (H1)", key=f"atr_{pair_name}", format="%.5f", step=0.00001, value=pair_settings.get("raw_atr_value", 0.0015))
    
    with c2:
        st.subheader("การวิเคราะห์ขั้นสูง (Advanced Analysis)")
        d1_trend_options = ["ยังไม่ไดเช็ค", "ขาขึ้น (Uptrend)", "ขาลง (Downtrend)", "ไม่ชัดเจน (Sideways)"]
        d1_trend = st.selectbox("แนวโน้มกราฟรายวัน (D1)", options=d1_trend_options, key=f"d1_{pair_name}", index=d1_trend_options.index(pair_settings.get("d1_trend", "ยังไม่ไดเช็ค")))
        near_key_level = st.checkbox("จุดเข้าเทรดอยู่ใกล้แนวรับ/แนวต้านสำคัญ", key=f"keylevel_{pair_name}", value=pair_settings.get("near_key_level", False))
        market_structure_ok = st.checkbox("โครงสร้างตลาด (HH/HL หรือ LH/LL) สอดคล้อง", key=f"structure_{pair_name}", value=pair_settings.get("market_structure_ok", False))
        
        st.subheader("สัญญาณยืนยัน (Confirmation - H1)")
        is_bullish_candle = st.checkbox("พบแท่งเทียนกลับตัวฝั่ง 'ซื้อ'", key=f"bull_candle_{pair_name}", value=pair_settings.get("is_bullish_candle", False))
        is_bearish_candle = st.checkbox("พบแท่งเทียนกลับตัวฝั่ง 'ขาย'", key=f"bear_candle_{pair_name}", value=pair_settings.get("is_bearish_candle", False))

    st.session_state.app_state["pair_settings"][pair_name] = {
        "current_price": current_price, "ema_50_price": ema_50_price, "rsi_14_value": rsi_14_value, 
        "raw_atr_value": raw_atr_value, "is_bullish_candle": is_bullish_candle, "is_bearish_candle": is_bearish_candle,
        "d1_trend": d1_trend, "near_key_level": near_key_level, "market_structure_ok": market_structure_ok
    }

    st.divider()
    with st.container(border=True):
        st.subheader("บทวิเคราะห์และแผนการเทรด")
        h4_trend = "ขาขึ้น (Uptrend)" if current_price > ema_50_price else "ขาลง (Downtrend)"
        
        buy_d1_ok = (d1_trend == "ขาขึ้น (Uptrend)")
        buy_h4_ok = (h4_trend == "ขาขึ้น (Uptrend)")
        buy_structure_ok = market_structure_ok
        buy_keylevel_ok = near_key_level
        buy_rsi_ok = (30 < rsi_14_value <= 45)
        buy_candle_ok = is_bullish_candle
        
        sell_d1_ok = (d1_trend == "ขาลง (Downtrend)")
        sell_h4_ok = (h4_trend == "ขาลง (Downtrend)")
        sell_structure_ok = market_structure_ok
        sell_keylevel_ok = near_key_level
        sell_rsi_ok = (55 <= rsi_14_value < 70)
        sell_candle_ok = is_bearish_candle

        is_strong_buy = all([buy_d1_ok, buy_h4_ok, buy_structure_ok, buy_keylevel_ok, buy_rsi_ok, buy_candle_ok])
        is_strong_sell = all([sell_d1_ok, sell_h4_ok, sell_structure_ok, sell_keylevel_ok, sell_rsi_ok, sell_candle_ok])

        if is_strong_buy:
            st.success("**Action: สัญญาณซื้อคุณภาพสูง (High-Probability Buy Signal)**")
            reason = "D1/H4/Structure Uptrend, Pullback to Key Level, RSI OK, Bullish Candle"
            pip_multiplier = get_pip_multiplier(pair_name)
            atr_pips = raw_atr_value * pip_multiplier
            entry, sl_pips = current_price, atr_pips * SL_ATR_MULTIPLIER
            sl, tp = entry - (sl_pips / pip_multiplier), entry + ((sl_pips * RR_RATIO) / pip_multiplier)
            lot_size, risk_amount = calculate_position_size(global_settings["account_balance"], global_settings["risk_percentage"], sl_pips, pair_name)
            display_trade_plan("ซื้อ ณ ราคาตลาด", entry, sl, tp, sl_pips, sl_pips * RR_RATIO, lot_size, risk_amount)

            if st.button("✅ ยืนยันเข้าเทรด Buy นี้", key=f"confirm_buy_{pair_name}", use_container_width=True):
                new_trade = {"Date": datetime.now().strftime("%Y-%m-%d"), "Pair": pair_name, "Direction": "Buy", "Entry": entry, "Exit": 0.0, "SL": sl, "TP": tp, "Lot_Size": round(lot_size, 2), "P/L (Pips)": 0.0, "P/L ($)": 0.0, "Outcome": "Pending", "Reason": reason, "Review": ""}
                df = load_journal()
                df_new = pd.concat([pd.DataFrame([new_trade]), df], ignore_index=True)
                save_journal(df_new)
                st.session_state.active_mode = "Journal"
                st.rerun()
        
        elif is_strong_sell:
            st.error("**Action: สัญญาณขายคุณภาพสูง (High-Probability Sell Signal)**")
            reason = "D1/H4/Structure Downtrend, Rally to Key Level, RSI OK, Bearish Candle"
            pip_multiplier = get_pip_multiplier(pair_name)
            atr_pips = raw_atr_value * pip_multiplier
            entry, sl_pips = current_price, atr_pips * SL_ATR_MULTIPLIER
            sl, tp = entry + (sl_pips / pip_multiplier), entry - ((sl_pips * RR_RATIO) / pip_multiplier)
            lot_size, risk_amount = calculate_position_size(global_settings["account_balance"], global_settings["risk_percentage"], sl_pips, pair_name)
            display_trade_plan("ขาย ณ ราคาตลาด", entry, sl, tp, sl_pips, sl_pips * RR_RATIO, lot_size, risk_amount)
            
            if st.button("❌ ยืนยันเข้าเทรด Sell นี้", key=f"confirm_sell_{pair_name}", use_container_width=True):
                new_trade = {"Date": datetime.now().strftime("%Y-%m-%d"), "Pair": pair_name, "Direction": "Sell", "Entry": entry, "Exit": 0.0, "SL": sl, "TP": tp, "Lot_Size": round(lot_size, 2), "P/L (Pips)": 0.0, "P/L ($)": 0.0, "Outcome": "Pending", "Reason": reason, "Review": ""}
                df = load_journal()
                df_new = pd.concat([pd.DataFrame([new_trade]), df], ignore_index=True)
                save_journal(df_new)
                st.session_state.active_mode = "Journal"
                st.rerun()
        else:
            st.warning("**Action: รอต่อไป (Wait / Stay Flat)**")

# --- โหมดที่ 1: วางแผนเทรด ---
if st.session_state.active_mode == "วางแผนเทรด (Dashboard)":
    st.title("📈 Trading Dashboard")
    tabs = st.tabs(PAIRS_TO_ANALYZE)
    for i, pair_name in enumerate(PAIRS_TO_ANALYZE):
        with tabs[i]:
            create_analysis_panel(pair_name)

# --- โหมดที่ 2: บันทึกและวิเคราะห์ผล ---
elif "Journal" in st.session_state.active_mode:
    st.title("📓 Trading Journal & Performance")
    df = load_journal()

    if st.session_state.edit_index is not None:
        st.subheader(f"✏️ แก้ไขการเทรดลำดับที่ {st.session_state.edit_index}")
        try: initial_data = df.loc[st.session_state.edit_index].to_dict()
        except KeyError:
            st.error("ไม่พบข้อมูลเทรดที่ต้องการแก้ไข อาจถูกลบไปแล้ว")
            st.session_state.edit_index = None
            st.rerun()

        with st.form("edit_form", border=True):
            st.info("กรอกข้อมูลเมื่อเทรดจบแล้ว หรือแก้ไข SL/TP ที่ใช้จริง")
            st.markdown(f"**เหตุผลที่เข้าเทรด:** `{initial_data.get('Reason', '')}`")
            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            entry_price = c1.number_input("ราคาเข้าจริง", value=float(initial_data.get("Entry", 0.0)), format="%.5f")
            sl_price = c2.number_input("SL จริง", value=float(initial_data.get("SL", 0.0)), format="%.5f")
            tp_price = c3.number_input("TP จริง", value=float(initial_data.get("TP", 0.0)), format="%.5f")
            exit_price = c4.number_input("ราคาออกจริง", value=float(initial_data.get("Exit", 0.0)), format="%.5f")
            outcome = st.radio("ผลลัพธ์สุดท้าย", ["Pending", "Win", "Loss"], index=["Pending", "Win", "Loss"].index(initial_data.get("Outcome", "Pending")), horizontal=True)
            review_notes = st.text_area("บทเรียนที่ได้จากเทรดนี้", value=str(initial_data.get("Review", "")))
            
            submitted = st.form_submit_button("💾 บันทึกการแก้ไข")
            if submitted:
                old_pl_usd = initial_data.get("P/L ($)", 0.0)
                p_multiplier = get_pip_multiplier(initial_data["Pair"])
                pips = ((exit_price - entry_price) * p_multiplier) if initial_data["Direction"] == "Buy" else ((entry_price - exit_price) * p_multiplier)
                lot_size = initial_data.get("Lot_Size", 0.01)
                pip_value = PIP_VALUE_USD_PER_LOT.get(initial_data["Pair"], 10)
                pl_usd_new = round(pips * pip_value * lot_size, 2) if outcome != "Pending" else 0.0
                balance_change = pl_usd_new - old_pl_usd
                current_balance = st.session_state.app_state["global_settings"]["account_balance"]
                new_balance = current_balance + balance_change
                st.session_state.app_state["global_settings"]["account_balance"] = new_balance
                
                df.loc[st.session_state.edit_index, "Entry"] = entry_price
                df.loc[st.session_state.edit_index, "SL"] = sl_price
                df.loc[st.session_state.edit_index, "TP"] = tp_price
                df.loc[st.session_state.edit_index, "Exit"] = exit_price
                df.loc[st.session_state.edit_index, "Outcome"] = outcome
                df.loc[st.session_state.edit_index, "P/L (Pips)"] = round(pips, 1) if outcome != "Pending" else 0.0
                df.loc[st.session_state.edit_index, "P/L ($)"] = pl_usd_new
                df.loc[st.session_state.edit_index, "Review"] = review_notes
                
                save_journal(df)
                st.success("แก้ไขข้อมูลเรียบร้อย! ยอดเงินในบัญชีถูกอัปเดตแล้ว")
                st.session_state.edit_index = None
                st.rerun()

    st.divider()
    st.subheader("ประวัติการเทรดทั้งหมด")
    if not df.empty:
        for index, row in df.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 1, 1, 2])
                outcome_color = "normal" if row["Outcome"] in ["Win", "Loss"] else "off"
                direction_color = "green" if row["Direction"] == "Buy" else "red"
                c1.markdown(f"""**{row.get('Date', '')}** | **{row.get('Pair', '')}** | <span style='color:{direction_color}; font-weight: bold;'>{row.get('Direction', '')}</span>""", unsafe_allow_html=True)
                c2.metric("Entry", f"{row.get('Entry', 0.0):.4f}")
                c3.metric("Exit", f"{row.get('Exit', 0.0):.4f}")
                c4.metric("P/L (Pips)", f"{row.get('P/L (Pips)', 0.0):.1f}", delta_color=outcome_color)
                c5.metric("P/L ($)", f"{row.get('P/L ($)', 0.0):.2f}", delta_color=outcome_color)
                
                action_col, review_col = c6.columns([1, 4])
                if action_col.button("✏️", key=f"edit_{index}", help="แก้ไขเทรดนี้"):
                    st.session_state.edit_index = index
                    st.rerun()
                if action_col.button("🗑️", key=f"delete_{index}", help="ลบเทรดนี้"):
                    pl_to_reverse = row.get("P/L ($)", 0.0)
                    st.session_state.app_state["global_settings"]["account_balance"] -= pl_to_reverse
                    
                    df = df.drop(index).reset_index(drop=True)
                    save_journal(df)
                    st.toast(f"ลบเทรดและปรับ Balance คืนแล้ว")
                    st.rerun()
                
                with review_col.expander("เหตุผลและบทเรียน"):
                    st.write(f"**เหตุผลที่เข้า:** {row.get('Reason', '')}")
                    st.write(f"**บทเรียน:** {row.get('Review', '')}")
        
        st.divider()
        st.subheader("สรุปประสิทธิภาพโดยรวม")
        df_finished = df[df['Outcome'] != 'Pending']
        total_trades = len(df_finished)
        wins = df_finished[df_finished['Outcome'] == 'Win']
        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("จำนวนเทรดที่จบแล้ว", f"{total_trades} ครั้ง")
        kpi2.metric("อัตราการชนะ (Win Rate)", f"{win_rate:.2f}%")
        kpi3.metric("P/L ทั้งหมด ($)", f"${df_finished['P/L ($)'].sum():.2f}")
    else:
        st.info("ยังไม่มีข้อมูลการเทรดที่ถูกบันทึกไว้")

# --- ตรรกะการบันทึกอัตโนมัติ (ท้ายสุด) ---
if previous_state != st.session_state.app_state:
    save_config(st.session_state.app_state)
    st.toast('บันทึกการเปลี่ยนแปลงอัตโนมัติ!', icon='💾')
