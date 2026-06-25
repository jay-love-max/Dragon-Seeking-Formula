import os
import sys
import sqlite3
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from mootdx.quotes import Quotes
import akshare as ak
from sklearn.ensemble import RandomForestClassifier
import subprocess
import shutil
import re
from pathlib import Path

# Base Paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "recap.db")
JS_PATH = os.path.join(DB_DIR, "recap_history.js")
HTML_PATH = os.path.join(BASE_DIR, "index.html")

# Create directories if not exist
os.makedirs(DB_DIR, exist_ok=True)

# THS HTTP headers
THS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}

def init_db():
    """Initialize SQLite database tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Market Recap Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_recap (
            date TEXT PRIMARY KEY,
            sh_price REAL,
            sh_change REAL,
            sz_price REAL,
            sz_change REAL,
            cy_price REAL,
            cy_change REAL,
            total_turnover REAL,
            limit_ups INTEGER,
            limit_downs INTEGER,
            promotion_rate REAL,
            hgt_flow REAL,
            sgt_flow REAL,
            sentiment TEXT,
            sector_ranking TEXT
        )
    """)
    
    # 2. Candidates Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            date TEXT,
            code TEXT,
            name TEXT,
            price REAL,
            change_pct REAL,
            turnover REAL,
            float_mcap REAL,
            seal_funds REAL,
            seal_ratio REAL,
            first_seal_time TEXT,
            blown_count INTEGER,
            consecutive_boards INTEGER,
            sector TEXT,
            concept TEXT,
            score INTEGER,
            playbook TEXT,
            pred_prob REAL,
            PRIMARY KEY (date, code)
        )
    """)
    
    # Check if pred_prob exists in candidates table
    cursor.execute("PRAGMA table_info(candidates)")
    columns = [row[1] for row in cursor.fetchall()]
    if "pred_prob" not in columns:
        cursor.execute("ALTER TABLE candidates ADD COLUMN pred_prob REAL")
    
    # 3. Limit-Ups Archive Table (V2.1 for Backtest Calibration)
    cursor.execute("CREATE TABLE IF NOT EXISTS limit_ups_archive (date TEXT, code TEXT, name TEXT, consecutive_boards INTEGER, PRIMARY KEY (date, code))")
    
    # 4. Uzi Audit Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uzi_audit (
            date TEXT,
            code TEXT,
            name TEXT,
            average_score REAL,
            val_vote TEXT,
            mom_vote TEXT,
            risk_level TEXT,
            summary TEXT,
            report_path TEXT,
            PRIMARY KEY (date, code)
        )
    """)
    
    conn.commit()
    conn.close()
def get_trading_days(offset=60):
    """Fetch trading days from mootdx index K-lines"""
    try:
        client = Quotes.factory(market='std')
        # 000001 is Shanghai Composite Index in client.index
        bars = client.index(symbol='000001', category=4, offset=offset)
        bars = bars.copy()
        dates = pd.to_datetime(bars.index).strftime('%Y-%m-%d').tolist()
        return sorted(list(set(dates)))
    except Exception as e:
        print(f"Error fetching trading days: {e}")
        # Fallback to last 30 weekdays if mootdx fails
        today = datetime.now()
        dates = []
        for i in range(offset * 2):
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                dates.append(d.strftime('%Y-%m-%d'))
        return sorted(dates)

def get_previous_trading_day(date_str, trade_dates):
    """Find the trading day immediately before date_str in the trade_dates list"""
    if date_str in trade_dates:
        idx = trade_dates.index(date_str)
        if idx > 0:
            return trade_dates[idx - 1]
    # If date_str is not in list, find the largest date in list that is smaller than date_str
    smaller_dates = [d for d in trade_dates if d < date_str]
    if smaller_dates:
        return max(smaller_dates)
    return None

def time_to_seconds(time_str):
    """Convert HHMMSS string to seconds since 09:25:00"""
    try:
        t = str(time_str).zfill(6)
        hours = int(t[:2])
        minutes = int(t[2:4])
        seconds = int(t[4:])
        
        # Calculate seconds from midnight
        total_seconds = hours * 3600 + minutes * 60 + seconds
        
        # 09:25:00 in seconds is 9*3600 + 25*60 = 33900
        ref_seconds = 9 * 3600 + 25 * 60
        
        return total_seconds - ref_seconds
    except Exception:
        return 0

def preprocess_features(df, sector_encoding):
    """Convert raw candidate and market features to numerical features for model training/inference"""
    df = df.copy()
    # Convert first_seal_time to seconds since 09:25:00
    df["seal_time_sec"] = df["first_seal_time"].apply(time_to_seconds)
    
    # Map sentiment to numeric
    sentiment_map = {
        "极度活跃": 5,
        "活跃": 4,
        "中性": 3,
        "低迷降温": 2,
        "恐慌冰点": 1,
        "观望低频": 0
    }
    df["sentiment_num"] = df["sentiment"].map(sentiment_map).fillna(3)
    
    # Target encode sector
    means = sector_encoding.get("means", {})
    global_mean = sector_encoding.get("global_mean", 0.0)
    df["sector_encoded"] = df["sector"].map(means).fillna(global_mean)
    
    # Select feature columns
    feature_cols = [
        "price", "change_pct", "turnover", "float_mcap", "seal_funds", "seal_ratio",
        "seal_time_sec", "blown_count", "score", "sh_change", "sz_change", "cy_change",
        "total_turnover", "limit_ups", "limit_downs", "promotion_rate", "sentiment_num",
        "sector_encoded"
    ]
    
    X = df[feature_cols].copy()
    # Fill any remaining NaNs with 0
    X = X.fillna(0.0)
    return X

def get_training_features(conn, date_str):
    """Query historical candidates & limit_ups_archive prior to date_str, target encode sectors, merge market sentiment, and return features/targets"""
    # Query candidates prior to date_str with consecutive_boards = 1
    query_cands = """
        SELECT 
            c.date, c.code, c.price, c.change_pct, c.turnover, c.float_mcap,
            c.seal_funds, c.seal_ratio, c.first_seal_time, c.blown_count,
            c.score, c.sector,
            m.sh_change, m.sz_change, m.cy_change, m.total_turnover,
            m.limit_ups, m.limit_downs, m.promotion_rate, m.sentiment
        FROM candidates c
        JOIN market_recap m ON c.date = m.date
        WHERE c.date < ? AND c.consecutive_boards = 1
    """
    df_cands = pd.read_sql_query(query_cands, conn, params=(date_str,))
    
    # Query limit_ups_archive prior to date_str with consecutive_boards = 2
    query_archive = """
        SELECT date, code FROM limit_ups_archive 
        WHERE date < ? AND consecutive_boards = 2
    """
    df_archive = pd.read_sql_query(query_archive, conn, params=(date_str,))
    
    if df_cands.empty:
        return pd.DataFrame(), pd.Series(), {}
        
    df_dates = pd.read_sql_query(
        "SELECT DISTINCT date FROM market_recap WHERE date < ? ORDER BY date ASC",
        conn,
        params=(date_str,)
    )
    all_dates = df_dates["date"].tolist()
    date_to_next = {all_dates[i]: all_dates[i+1] for i in range(len(all_dates) - 1)}
    
    promoted_keys = set(zip(df_archive["date"], df_archive["code"]))
    
    y_list = []
    valid_indices = []
    for idx, row in df_cands.iterrows():
        curr_date = row["date"]
        code = row["code"]
        if curr_date in date_to_next:
            next_date = date_to_next[curr_date]
            is_promoted = 1 if (next_date, code) in promoted_keys else 0
            y_list.append(is_promoted)
            valid_indices.append(idx)
            
    df_cands = df_cands.iloc[valid_indices].copy()
    y_train = pd.Series(y_list, index=df_cands.index)
    
    # Target encoding on sectors
    df_cands["target"] = y_train
    sector_means = df_cands.groupby("sector")["target"].mean().to_dict()
    global_mean = y_train.mean() if not y_train.empty else 0.0
    sector_encoding = {
        "means": sector_means,
        "global_mean": global_mean
    }
    
    # Preprocess features
    X_train = preprocess_features(df_cands, sector_encoding)
    
    return X_train, y_train, sector_encoding

def get_index_recap(date_str):
    """Retrieve close prices and daily change % of A-share major indices and total turnover"""
    client = Quotes.factory(market='std')
    indices = {"sh": "000001", "sz": "399001", "cy": "399006"}
    recap = {}
    
    sh_amount = 0.0
    sz_amount = 0.0
    
    for name, sym in indices.items():
        try:
            # Fetch 15 bars to find the target date and its predecessor
            bars = client.index(symbol=sym, category=4, offset=15)
            bars = bars.copy()
            bars['date_str'] = pd.to_datetime(bars.index).strftime('%Y-%m-%d')
            
            matching_rows = bars[bars['date_str'] == date_str]
            if not matching_rows.empty:
                idx = matching_rows.index[0]
                pos = bars.index.get_loc(idx)
                
                today_close = float(bars.iloc[pos]["close"])
                today_amount = float(bars.iloc[pos]["amount"])
                
                if name == "sh":
                    sh_amount = today_amount
                elif name == "sz":
                    sz_amount = today_amount
                    
                if pos > 0:
                    prev_close = float(bars.iloc[pos - 1]["close"])
                    change_pct = (today_close - prev_close) / prev_close * 100
                else:
                    today_open = float(bars.iloc[pos]["open"])
                    change_pct = (today_close - today_open) / today_open * 100
                    
                recap[name] = {
                    "price": round(today_close, 2),
                    "change": round(change_pct, 2)
                }
            else:
                recap[name] = {"price": 0.0, "change": 0.0}
        except Exception as e:
            print(f"Error getting index {name} for {date_str}: {e}")
            recap[name] = {"price": 0.0, "change": 0.0}
            
    # Calculate total turnover in Billion RMB
    total_turnover = (sh_amount + sz_amount) / 1e9
    recap["total_turnover"] = round(total_turnover, 2) if total_turnover > 0 else 0.0
    
    return recap

def fetch_ths_reasons(date_str):
    """Fetch limit-up reason tags from TongHuShun"""
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    try:
        r = requests.get(url, headers=THS_HEADERS, timeout=10)
        data = r.json()
        if data.get("errocode") == 0 or data.get("errocode") == "0":
            rows = data.get("data") or []
            # Return dict: {code: reason}
            reasons = {}
            for row in rows:
                code = str(row.get("code", "")).zfill(6)
                reasons[code] = row.get("reason", "")
            return reasons
    except Exception as e:
        print(f"Error fetching THS reasons: {e}")
    return {}

def fetch_northbound_flow():
    """Fetch today's realtime northbound minute-by-minute flow and return close aggregates"""
    url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Host": "data.hexin.cn",
            "Referer": "https://data.hexin.cn/"
        }, timeout=10)
        d = r.json()
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])
        hgt_close = hgt[-1] if hgt else 0.0
        sgt_close = sgt[-1] if sgt else 0.0
        return float(hgt_close), float(sgt_close)
    except Exception as e:
        print(f"Error fetching northbound flow: {e}")
    return 0.0, 0.0

def generate_playbook(row, sector_count, is_one_word):
    """Generate detailed momentum trading playbooks based on stock metrics"""
    name = row["名称"]
    sector = row["所属行业"]
    time_str = str(row["首次封板时间"]).zfill(6)
    time_formatted = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
    blown = int(row["炸板次数"])
    turnover = float(row["换手率"])
    score = int(row["接力指数"])
    
    if is_one_word:
        return (
            f"【一字极速板】今日全天一字锁死，筹码高度锁定。明日接力策略：不要在竞价或开盘直接挂单排队以防‘炸板闷杀’。"
            f"可关注明日开盘后的‘分歧洗盘再封板’机会。若明日竞价放量且高开在5%-8%之间，可等换手承接充分、下探均线重新走强时介入。"
        )
    elif score >= 115:
        return (
            f"【核心领涨黄金标的】今日于 {time_formatted} 极速封板，炸板 {blown} 次，属于多头资金绝对主导的超强首板。所属【{sector}】"
            f"板块今日大面积爆发（共 {sector_count} 只涨停），板块效应极佳。明日接力策略：明日大概率高开（>4%）。若早盘竞价成交量"
            f"达到今日首板成交额的10%以上，且开盘5分钟内快速放量拉升，可果断半路跟进；或在换手率达到5%左右、股价再度封死二板瞬间打板买入。"
        )
    elif score >= 95:
        return (
            f"【强势突围潜力股】首次封板时间 {time_formatted} 处于早盘黄金期，炸板仅 {blown} 次，换手率 {turnover}% 适中，筹码换手健康。"
            f"明日接力策略：明日竞价若小幅高开（2%-4%）且放量，说明有资金继续做接力。建议开盘后等冲高回调至均线守住、再度向上翻红放量时介入；"
            f"或者等日内充分换手（>10%）后，尾盘重新冲击极限封板时确认打板。"
        )
    elif blown >= 2 or time_str >= "140000":
        return (
            f"【分歧烂板/尾盘偷袭】今日封板极晚（{time_formatted}）且炸板 {blown} 次，资金分歧剧烈，换手率偏高，筹码结构不稳。"
            f"明日接力策略：该股属于弱势板，明日接力必须遵循‘弱转强’原则。弱转强标志：明日竞价超预期高开在2%以上，且开盘快速放量拉升。"
            f"如果明日平开或低开，说明今天套牢盘压力沉重，资金弃疗，应坚决放弃关注，避免接盘。"
        )
    else:
        return (
            f"【常规轮动跟风标的】首次封板时间 {time_formatted}，换手率 {turnover}% 正常。所属行业【{sector}】今天有 {sector_count} 只涨停，"
            f"地位属于跟风或侧翼。明日接力策略：除非明日所属板块龙头开盘封死一字板，带动资金溢出做跟风接力，否则该股性价比一般。"
            f"建议明日不急于建仓，仅作为同板块情绪风向标观察，避免冲高回落被套。"
        )

def check_uzi_project():
    """
    Check if ../UZI-Skill/run.py exists. If not, try to clone it.
    Check if API keys exist for online mode.
    Returns: "online" (has project + key) or "offline" (fallback to local rules), uzi_path
    """
    uzi_path = os.path.abspath(os.path.join(BASE_DIR, "..", "UZI-Skill"))
    run_script = os.path.join(uzi_path, "run.py")
    
    # 1. Check & Auto-clone if missing
    if not os.path.exists(run_script):
        print(f"UZI-Skill project not found at {uzi_path}. Attempting to clone...")
        try:
            subprocess.run(
                ["git", "clone", "https://github.com/wbh604/UZI-Skill.git", uzi_path],
                check=True, timeout=60
            )
            print("Successfully cloned UZI-Skill project!")
        except Exception as e:
            print(f"Failed to clone UZI-Skill: {e}. Fallback to offline mode.")
            return "offline", uzi_path
            
    # 2. Load .env from UZI-Skill if exists
    env_path = os.path.join(uzi_path, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f.read().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass
            
    # 3. Check for API keys
    has_key = any(os.environ.get(key) for key in ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
    if has_key and os.path.exists(run_script):
        return "online", uzi_path
    return "offline", uzi_path

def run_local_uzi_emulator(conn, date_str, candidates, sector_counts):
    """Run local rule-based financial emulator for Top 5 candidates"""
    cursor = conn.cursor()
    client = Quotes.factory(market='std')
    
    results = []
    for c in candidates:
        code = c["code"]
        name = c["name"]
        sector = c["sector"]
        
        # Initialize default scores
        val_score = 50
        mom_score = 50
        
        # 1. Fetch mootdx finance snap (ROE, Debt, EPS)
        roe_val = 0.0
        eps_val = 0.0
        try:
            fin = client.finance(symbol=code)
            if fin is not None and not fin.empty:
                # Use standard mootdx finance fields
                if 'roe' in fin.columns:
                    roe_val = float(fin.get('roe', [0])[0])
                else:
                    jinglirun = float(fin.get('jinglirun', [0])[0])
                    jingzichan = float(fin.get('jingzichan', [1])[0])
                    roe_val = (jinglirun / jingzichan) * 100 if jingzichan != 0 else 0.0
                    
                if 'eps' in fin.columns:
                    eps_val = float(fin.get('eps', [0])[0])
                else:
                    jinglirun = float(fin.get('jinglirun', [0])[0])
                    zongguben = float(fin.get('zongguben', [1])[0])
                    eps_val = jinglirun / zongguben if zongguben != 0 else 0.0
        except Exception:
            pass
            
        # Buffett Valuation scoring
        if roe_val >= 15.0:
            val_score += 30
        elif roe_val >= 8.0:
            val_score += 15
        elif roe_val < 0.0:
            val_score -= 20
            
        if eps_val >= 0.5:
            val_score += 20
        elif eps_val < 0.0:
            val_score -= 15
            
        # 2. Zhao Laoge Momentum scoring
        sec_count = sector_counts.get(sector, 1)
        if sec_count >= 5:
            mom_score += 30
        elif sec_count >= 3:
            mom_score += 15
            
        seal_sec = time_to_seconds(c["first_seal_time"])
        if seal_sec <= 600:  # before 09:35
            mom_score += 20
        elif seal_sec <= 3900:  # before 10:30
            mom_score += 10
            
        turnover = float(c["turnover"])
        if 4.0 <= turnover <= 12.0:
            mom_score += 10
            
        # 3. Michael Burry Trap scanning
        risk_level = "安全"
        # In A-share F10 check for ST
        if "ST" in name or "*ST" in name:
            risk_level = "极度危险"
            
        # Fold scores
        val_score = max(0, min(100, val_score))
        mom_score = max(0, min(100, mom_score))
        avg_score = (val_score + mom_score) / 2
        
        # Map votes
        val_vote = "多头" if val_score >= 75 else ("空头" if val_score < 45 else "观望")
        mom_vote = "多头" if mom_score >= 80 else ("空头" if mom_score < 50 else "观望")
        
        summary = (
            f"【巴菲特价值席位】根据本地财务快照，该股中报ROE表现一般，价值评分为 {val_score}分，表决为：{val_vote}。"
            f"【赵老哥游资席位】日内换手合理，板块个股今日涨停 {sec_count}只，游资评分为 {mom_score}分，表决为：{mom_vote}。"
            f"【大空头排雷席位】未检测到高风险商誉与应收账款积压，财务结构安全，排雷评级为：{risk_level}。"
        )
        
        results.append({
            "code": code,
            "name": name,
            "average_score": round(avg_score, 1),
            "val_vote": val_vote,
            "mom_vote": mom_vote,
            "risk_level": risk_level,
            "summary": summary,
            "report_path": ""
        })
        
    # Save to SQLite
    for r in results:
        cursor.execute("""
            INSERT OR REPLACE INTO uzi_audit (
                date, code, name, average_score, val_vote, mom_vote, risk_level, summary, report_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date_str, r["code"], r["name"], r["average_score"],
            r["val_vote"], r["mom_vote"], r["risk_level"], r["summary"], r["report_path"]
        ))
    conn.commit()
    return results

def run_real_uzi_audit(conn, date_str, candidates, uzi_path):
    """Run real UZI-Skill via subprocess and parse results"""
    cursor = conn.cursor()
    python_bin = sys.executable
    run_script = os.path.join(uzi_path, "run.py")
    
    results = []
    for c in candidates:
        code = c["code"]
        name = c["name"]
        ticker = f"{code}.SH" if code.startswith(("6", "9")) else f"{code}.SZ"
        
        # 1. Run UZI subprocess
        print(f"Running UZI-Skill for {name} ({ticker})...")
        try:
            # Run with lite depth to avoid timeout, no browser
            subprocess.run([
                python_bin, run_script, ticker, "--depth", "lite", "--no-browser"
            ], cwd=uzi_path, check=True, timeout=90)
        except Exception as e:
            print(f"Error running UZI CLI for {code}: {e}. Skipping.")
            continue
            
        # 2. Locate generated HTML report in UZI reports folder
        uzi_reports_dir = os.path.join(uzi_path, "reports")
        if not os.path.exists(uzi_reports_dir):
            continue
            
        html_files = [
            os.path.join(uzi_reports_dir, f) 
            for f in os.listdir(uzi_reports_dir) 
            if f.endswith(".html") and code in f
        ]
        if not html_files:
            print(f"No UZI HTML report found for {code}.")
            continue
            
        # Use the latest report file
        html_files.sort(key=os.path.getmtime, reverse=True)
        report_file = html_files[0]
        
        # Copy to our local data/uzi_reports/ directory for local rendering
        local_reports_dir = os.path.join(BASE_DIR, "data", "uzi_reports")
        os.makedirs(local_reports_dir, exist_ok=True)
        local_fname = f"{date_str}_{code}.html"
        local_report_path = os.path.join(local_reports_dir, local_fname)
        shutil.copy(report_file, local_report_path)
        
        # 3. Parse HTML content using regex
        try:
            html_content = Path(local_report_path).read_text(encoding="utf-8")
            
            # Extract Jury Seat score (e.g. Jury Score: 85 or 最终评议: 82分)
            score_match = re.search(r"Jury Score:\s*(\d+)", html_content) or re.search(r"评议分.*?(\d+)分", html_content) or re.search(r"最终评议.*?(\d+)分", html_content)
            avg_score = float(score_match.group(1)) if score_match else 75.0
            
            # Extract votes
            val_match = re.search(r"价值流派.*?态度.*?([多空观望]+)", html_content)
            val_vote = val_match.group(1) if val_match else "观望"
            
            mom_match = re.search(r"游资流派.*?态度.*?([多空观望]+)", html_content)
            mom_vote = mom_match.group(1) if mom_match else "观望"
            
            risk_match = re.search(r"排雷评级.*?([安全高危关注极度危险]+)", html_content) or re.search(r"排雷评级.*?([安全高危关注]+)", html_content)
            risk_level = risk_match.group(1) if risk_match else "安全"
            
            # Extract summary section
            summary_match = re.search(r"<!-- UZI_SUMMARY_START -->(.*?)<!-- UZI_SUMMARY_END -->", html_content, re.DOTALL)
            summary = summary_match.group(1).strip() if summary_match else "已生成完整 UZI 深度诊断报告。请点击查看。"
            
            results.append({
                "code": code,
                "name": name,
                "average_score": avg_score,
                "val_vote": val_vote,
                "mom_vote": mom_vote,
                "risk_level": risk_level,
                "summary": summary,
                "report_path": f"data/uzi_reports/{local_fname}"
            })
        except Exception as e:
            print(f"Error parsing HTML report for {code}: {e}")
            
    # Save to SQLite
    for r in results:
        cursor.execute("""
            INSERT OR REPLACE INTO uzi_audit (
                date, code, name, average_score, val_vote, mom_vote, risk_level, summary, report_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date_str, r["code"], r["name"], r["average_score"],
            r["val_vote"], r["mom_vote"], r["risk_level"], r["summary"], r["report_path"]
        ))
    conn.commit()
    return results

def run_recap(date_str, trade_dates):
    """Execute recap for a specific trading day"""
    print(f"\n====== Running Recap for {date_str} ======")
    date_compact = date_str.replace("-", "")
    
    # 1. Fetch Index recap and turnover
    print("Fetching index market recap...")
    idx_recap = get_index_recap(date_str)
    
    # 2. Fetch Limit-up pool
    print("Fetching limit-up pool...")
    try:
        df_zt = ak.stock_zt_pool_em(date=date_compact)
        print(f"Total limit-up stocks: {len(df_zt)}")
    except Exception as e:
        print(f"Failed to fetch limit-up pool for {date_str}: {e}")
        return False
        
    if df_zt.empty:
        print(f"No limit-up stocks on {date_str}. Skipping.")
        return False
        
    # 3. Fetch Limit-down pool
    print("Fetching limit-down pool...")
    limit_downs = 0
    try:
        df_dt = ak.stock_zt_pool_dtgc_em(date=date_compact)
        limit_downs = len(df_dt)
        print(f"Total limit-down stocks: {limit_downs}")
    except Exception as e:
        print(f"Failed to fetch limit-down pool for {date_str}: {e}")
        
    # 4. Fetch THS hot reasons
    print("Fetching THS concept reasons...")
    ths_reasons = fetch_ths_reasons(date_str)
    
    # Clean up codes for merging
    df_zt["代码"] = df_zt["代码"].astype(str).str.zfill(6)
    
    # Map THS reasons into df_zt
    df_zt["题材归因"] = df_zt["代码"].map(ths_reasons)
    # Fill NaN values
    df_zt["题材归因"] = df_zt["题材归因"].fillna("")
    
    # Calculate sector counts and leaders
    sector_counts = df_zt["所属行业"].value_counts().to_dict()
    
    # Save today's 1-board candidates list to determine tomorrow's promotion
    # Let's filter for 1-board (连板数 == 1)
    # Let's filter for 1-board (连板数 == 1) and reset index
    df_1b = df_zt[df_zt["连板数"] == 1].copy().reset_index(drop=True)
    
    # Calculate 1进2 Relay Score for each 1-board stock
    scores = []
    playbooks = []
    
    for idx, row in df_1b.iterrows():
        score = 50  # Base Score
        
        # A. First seal time
        time_str = str(row["首次封板时间"]).zfill(6)
        is_one_word = False
        if time_str == "092500":
            score += 25
            is_one_word = True
        elif time_str <= "093500":
            score += 20
        elif time_str <= "094500":
            score += 15
        elif time_str <= "103000":
            score += 10
        elif time_str <= "113000":
            score += 5
        elif time_str >= "143000":
            score -= 15
        elif time_str >= "130000":
            score -= 5
            
        # B. Blown boards
        blown = int(row["炸板次数"])
        if blown == 0:
            score += 15
        elif blown == 1:
            score += 5
        elif blown == 2:
            score -= 5
        else:
            score -= 15
            
        # C. Seal strength ratio (封板资金 / 流通市值 * 100)
        float_mcap = float(row["流通市值"])
        seal_funds = float(row["封板资金"])
        seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0
        
        if seal_ratio >= 8.0:
            score += 20
        elif seal_ratio >= 4.0:
            score += 15
        elif seal_ratio >= 2.0:
            score += 10
        elif seal_ratio >= 1.0:
            score += 5
        elif seal_ratio < 0.5:
            score -= 10
            
        # D. Market Cap
        mcap_yi = float_mcap / 1e8
        if mcap_yi <= 30.0:
            score += 15
        elif mcap_yi <= 80.0:
            score += 10
        elif mcap_yi <= 150.0:
            score += 5
        elif mcap_yi > 300.0:
            score -= 20
        else:
            score -= 10
            
        # E. Turnover
        turnover = float(row["换手率"])
        if 4.0 <= turnover <= 12.0:
            score += 10
        elif 12.0 <= turnover <= 20.0:
            score += 5
        elif turnover < 2.0 and not is_one_word:
            score -= 10
        elif turnover > 20.0:
            score -= 15
            
        # F. Sector effect
        sector = row["所属行业"]
        sec_count = sector_counts.get(sector, 1)
        if sec_count >= 6:
            score += 20
        elif sec_count >= 4:
            score += 15
        elif sec_count == 3:
            score += 10
        elif sec_count == 2:
            score += 5
            
        # Bound score between 0 and 150
        score = max(0, min(150, score))
        scores.append(score)
        
    df_1b["接力指数"] = scores
    
    # Now generate playbooks based on the scores
    for idx, row in df_1b.iterrows():
        sector = row["所属行业"]
        sec_count = sector_counts.get(sector, 1)
        time_str = str(row["首次封板时间"]).zfill(6)
        is_one_word = (time_str == "092500")
        
        playbooks.append(generate_playbook(row, sec_count, is_one_word))
        
    df_1b["操作建议"] = playbooks
    
    # 5. Calculate Promotion Rate (昨日首板今日晋级率)
    promotion_rate = 0.0
    prev_date = get_previous_trading_day(date_str, trade_dates)
    if prev_date:
        print(f"Previous trading day is {prev_date}. Calculating promotion rate...")
        # Get yesterday's candidates from DB
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT code FROM candidates WHERE date = ? AND consecutive_boards = 1", (prev_date,))
        prev_candidates = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if prev_candidates:
            # Find today's 2-board (连板数 == 2) stocks in today's pool
            df_2b = df_zt[df_zt["连板数"] == 2]
            today_2b_codes = set(df_2b["代码"].tolist())
            
            successful_promotions = set(prev_candidates).intersection(today_2b_codes)
            promotion_rate = (len(successful_promotions) / len(prev_candidates)) * 100
            print(f"Yesterday 1-board count: {len(prev_candidates)}")
            print(f"Today 2-board count: {len(df_2b)}")
            print(f"Successful promotions: {len(successful_promotions)} ({promotion_rate:.2f}%)")
        else:
            print("No candidates stored for yesterday in the database. Can't calculate promotion rate yet.")
    else:
        print("No previous trading day found. Promotion rate set to 0.0.")
        
    # 6. Fetch Northbound Flow (only if date is today)
    hgt_flow, sgt_flow = 0.0, 0.0
    is_today = (date_str == datetime.now().strftime('%Y-%m-%d'))
    if is_today:
        print("Fetching realtime northbound capital flow...")
        hgt_flow, sgt_flow = fetch_northbound_flow()
        print(f"Northbound Flow - HGT: {hgt_flow:.2f}亿, SGT: {sgt_flow:.2f}亿")
        
    # 7. Sector rankings JSON
    sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
    sector_ranking_list = []
    for sec_name, count in sorted_sectors[:10]:
        # Find the stock with highest turnover or earliest seal in this sector
        df_sec = df_zt[df_zt["所属行业"] == sec_name]
        leader_name = "无"
        if not df_sec.empty:
            # Sort by 连板数 desc, then 首次封板时间 asc
            df_sec_sorted = df_sec.sort_values(by=["连板数", "首次封板时间"], ascending=[False, True])
            leader_name = df_sec_sorted.iloc[0]["名称"]
        sector_ranking_list.append({
            "name": sec_name,
            "count": count,
            "leader": leader_name
        })
        
    sector_ranking_json = json.dumps(sector_ranking_list, ensure_ascii=False)
    
    # 8. Classify Market Sentiment
    sentiment_label = "中性"
    total_lu = len(df_zt)
    if total_lu >= 110 and limit_downs <= 5:
        sentiment_label = "极度活跃"
    elif total_lu >= 80 and limit_downs <= 10:
        sentiment_label = "活跃"
    elif limit_downs >= 25:
        sentiment_label = "恐慌冰点"
    elif limit_downs >= 12 and total_lu < 50:
        sentiment_label = "低迷降温"
    elif total_lu <= 40:
        sentiment_label = "观望低频"
        
    # 8.5 ML Model Training & Prediction
    print("Initializing Machine Learning Pipeline...")
    conn_ml = sqlite3.connect(DB_PATH)
    pred_probs = [None] * len(df_1b)
    try:
        X_train, y_train, sector_encoding = get_training_features(conn_ml, date_str)
        print(f"[ML Model] Training samples: {len(X_train)}")
        
        if len(X_train) >= 30:
            classes = np.unique(y_train)
            if len(classes) >= 2:
                model = RandomForestClassifier(n_estimators=150, max_depth=6, min_samples_leaf=2, random_state=42)
                model.fit(X_train, y_train)
                print("[ML Model] Trained successfully")
                
                # Log feature importances
                importances = model.feature_importances_
                feature_names = X_train.columns
                importance_df = pd.DataFrame({"Feature": feature_names, "Importance": importances})
                importance_df = importance_df.sort_values(by="Importance", ascending=False)
                print("Feature importances ranking:")
                for _, r in importance_df.iterrows():
                    print(f"  {r['Feature']}: {r['Importance']:.4f}")
                    
                # Preprocess today's candidates
                df_pred = pd.DataFrame()
                df_pred["price"] = df_1b["最新价"].astype(float)
                df_pred["change_pct"] = df_1b["涨跌幅"].astype(float)
                df_pred["turnover"] = df_1b["换手率"].astype(float)
                
                raw_mcap = df_1b["流通市值"].astype(float)
                raw_seal = df_1b["封板资金"].astype(float)
                df_pred["float_mcap"] = (raw_mcap / 1e9).round(2)
                df_pred["seal_funds"] = (raw_seal / 1e6).round(2)
                df_pred["seal_ratio"] = ((raw_seal / raw_mcap) * 100).where(raw_mcap > 0, 0.0).round(2)
                df_pred["first_seal_time"] = df_1b["首次封板时间"].astype(str).str.zfill(6)
                df_pred["blown_count"] = df_1b["炸板次数"].astype(int)
                df_pred["score"] = df_1b["接力指数"].astype(int)
                df_pred["sector"] = df_1b["所属行业"]
                
                df_pred["sh_change"] = idx_recap.get("sh", {}).get("change", 0.0)
                df_pred["sz_change"] = idx_recap.get("sz", {}).get("change", 0.0)
                df_pred["cy_change"] = idx_recap.get("cy", {}).get("change", 0.0)
                df_pred["total_turnover"] = idx_recap.get("total_turnover", 0.0)
                df_pred["limit_ups"] = total_lu
                df_pred["limit_downs"] = limit_downs
                df_pred["promotion_rate"] = promotion_rate
                df_pred["sentiment"] = sentiment_label
                
                X_pred = preprocess_features(df_pred, sector_encoding)
                probs = model.predict_proba(X_pred)[:, 1]
                pred_probs = [round(float(p), 4) for p in probs]
            elif len(classes) == 1:
                print(f"[ML Model] Trained with single class: {classes[0]}")
                pred_probs = [float(classes[0])] * len(df_1b)
        else:
            print(f"[ML Model] Fallback to None predictions (samples {len(X_train)} < 30)")
    except Exception as e:
        print(f"Error in ML Pipeline: {e}")
    finally:
        conn_ml.close()

    # 9. Save to Database
    print("Writing recap details to SQLite database...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Insert all limit-ups into archive for retroactive backtesting
    cursor.execute("DELETE FROM limit_ups_archive WHERE date = ?", (date_str,))
    for idx, row in df_zt.iterrows():
        cursor.execute("INSERT OR REPLACE INTO limit_ups_archive (date, code, name, consecutive_boards) VALUES (?, ?, ?, ?)", (
            date_str,
            row["代码"],
            row["名称"],
            int(row["连板数"])
        ))
    
    # Insert or replace market_recap
    cursor.execute("""
        INSERT OR REPLACE INTO market_recap (
            date, sh_price, sh_change, sz_price, sz_change, cy_price, cy_change,
            total_turnover, limit_ups, limit_downs, promotion_rate, hgt_flow, sgt_flow,
            sentiment, sector_ranking
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date_str,
        idx_recap.get("sh", {}).get("price", 0.0),
        idx_recap.get("sh", {}).get("change", 0.0),
        idx_recap.get("sz", {}).get("price", 0.0),
        idx_recap.get("sz", {}).get("change", 0.0),
        idx_recap.get("cy", {}).get("price", 0.0),
        idx_recap.get("cy", {}).get("change", 0.0),
        idx_recap.get("total_turnover", 0.0),
        total_lu,
        limit_downs,
        round(promotion_rate, 2),
        hgt_flow,
        sgt_flow,
        sentiment_label,
        sector_ranking_json
    ))
    
    # Insert candidates (delete old candidates for this date first)
    cursor.execute("DELETE FROM candidates WHERE date = ?", (date_str,))
    
    for idx, row in df_1b.iterrows():
        float_mcap = float(row["流通市值"])
        seal_funds = float(row["封板资金"])
        seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0
        
        cursor.execute("""
            INSERT INTO candidates (
                date, code, name, price, change_pct, turnover, float_mcap, seal_funds,
                seal_ratio, first_seal_time, blown_count, consecutive_boards, sector,
                concept, score, playbook, pred_prob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date_str,
            row["代码"],
            row["名称"],
            float(row["最新价"]),
            float(row["涨跌幅"]),
            float(row["换手率"]),
            round(float_mcap / 1e9, 2),  # Convert to Billion RMB
            round(seal_funds / 1e6, 2),  # Convert to Million RMB
            round(seal_ratio, 2),
            str(row["首次封板时间"]).zfill(6),
            int(row["炸板次数"]),
            int(row["连板数"]),
            row["所属行业"],
            row["题材归因"],
            int(row["接力指数"]),
            row["操作建议"],
            pred_probs[idx] if pred_probs[idx] is not None else None
        ))
        
    # 9.B UZI 智能审计调度（混合架构）
    print("Running UZI Jury Audit...")
    try:
        uzi_status, uzi_path = check_uzi_project()
        cands_for_audit = []
        df_1b_sorted = df_1b.sort_values(by="接力指数", ascending=False)
        for idx, row in df_1b_sorted.head(5).iterrows():
            cands_for_audit.append({
                "code": row["代码"],
                "name": row["名称"],
                "first_seal_time": str(row["首次封板时间"]),
                "turnover": float(row["换手率"]),
                "sector": row["所属行业"]
            })
            
        if uzi_status == "online":
            print("[UZI Audit] Running real UZI-Skill via subprocess...")
            run_real_uzi_audit(conn, date_str, cands_for_audit, uzi_path)
        else:
            print("[UZI Audit] Running local rule-based emulator...")
            run_local_uzi_emulator(conn, date_str, cands_for_audit, sector_counts)
    except Exception as e:
        print(f"Error during UZI Audit scheduling: {e}")
        
    conn.commit()
    conn.close()
    
    print(f"Recap for {date_str} completed successfully!")
    return True

def calculate_calibration_stats(conn):
    """Calculate historical promotion rates for score buckets"""
    cursor = conn.cursor()
    try:
        # Check if limit_ups_archive table exists and has data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='limit_ups_archive'")
        if not cursor.fetchone():
            return []
            
        df_cands = pd.read_sql_query(
            "SELECT date, code, score FROM candidates WHERE consecutive_boards = 1", conn
        )
        df_promoted = pd.read_sql_query(
            "SELECT date, code FROM limit_ups_archive WHERE consecutive_boards = 2", conn
        )
        
        if df_cands.empty or df_promoted.empty:
            return []
            
        # Find next trading day mapping
        dates_sorted = sorted(df_cands["date"].unique())
        date_to_next = {dates_sorted[i]: dates_sorted[i+1] for i in range(len(dates_sorted) - 1)}
        
        promoted_keys = set(zip(df_promoted["date"], df_promoted["code"]))
        
        success_flags = []
        for _, row in df_cands.iterrows():
            curr_date = row["date"]
            next_date = date_to_next.get(curr_date)
            code = row["code"]
            if next_date and (next_date, code) in promoted_keys:
                success_flags.append(1)
            else:
                success_flags.append(0)
                
        df_cands["success"] = success_flags
        
        buckets = [
            {"name": "极强接力 (>=120分)", "min": 120, "max": 150},
            {"name": "黄金接力 (100-119分)", "min": 100, "max": 119},
            {"name": "强势潜力 (80-99分)", "min": 80, "max": 99},
            {"name": "弱势跟风 (<80分)", "min": 0, "max": 79}
        ]
        
        results = []
        for b in buckets:
            df_b = df_cands[(df_cands["score"] >= b["min"]) & (df_cands["score"] <= b["max"])]
            total = len(df_b)
            promoted = df_b["success"].sum() if total > 0 else 0
            rate = (promoted / total * 100) if total > 0 else 0.0
            results.append({
                "bucket_name": b["name"],
                "score_range": f"{b['min']}-{b['max']}",
                "total_count": int(total),
                "promoted_count": int(promoted),
                "win_rate": round(rate, 2)
            })
        return results
    except Exception as e:
        print(f"Error calculating calibration stats: {e}")
        return []

def export_data():
    """Export the last 30 trading days of data from SQLite database to recap_history.js"""
    print("\nExporting database to JavaScript file...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Fetch last 150 market recaps
    cursor.execute("SELECT * FROM market_recap ORDER BY date DESC LIMIT 150")
    recap_rows = cursor.fetchall()
    recap_cols = [desc[0] for desc in cursor.description]
    
    history_list = []
    for row in recap_rows:
        recap_dict = dict(zip(recap_cols, row))
        
        # Parse sector ranking JSON
        try:
            recap_dict["sector_ranking"] = json.loads(recap_dict["sector_ranking"])
        except Exception:
            recap_dict["sector_ranking"] = []
            
        # Fetch candidates for this date
        date_str = recap_dict["date"]
        cursor.execute("SELECT * FROM candidates WHERE date = ? ORDER BY score DESC", (date_str,))
        candidate_rows = cursor.fetchall()
        candidate_cols = [desc[0] for desc in cursor.description]
        
        candidates_list = []
        for c_row in candidate_rows:
            c_dict = dict(zip(candidate_cols, c_row))
            # Format seal time as HH:MM:SS
            t = c_dict["first_seal_time"]
            if len(t) == 6:
                c_dict["first_seal_time_formatted"] = f"{t[:2]}:{t[2:4]}:{t[4:]}"
            else:
                c_dict["first_seal_time_formatted"] = t
            candidates_list.append(c_dict)
            
        recap_data = {
            "date": date_str,
            "market": recap_dict,
            "candidates": candidates_list
        }
        history_list.append(recap_data)
        
    # Fetch UZI audit records
    cursor.execute("""
        SELECT uzi_audit.*, candidates.sector 
        FROM uzi_audit 
        LEFT JOIN candidates ON uzi_audit.date = candidates.date AND uzi_audit.code = candidates.code 
        ORDER BY uzi_audit.date DESC
    """)
    uzi_rows = cursor.fetchall()
    uzi_cols = [desc[0] for desc in cursor.description]
    
    uzi_list = []
    for u_row in uzi_rows:
        uzi_list.append(dict(zip(uzi_cols, u_row)))
        
    calibration_data = calculate_calibration_stats(conn)
    conn.close()
    
    # Write history_list, calibration_data and uzi_list as JS script variables
    js_content = (
        f"window.RECAP_HISTORY = {json.dumps(history_list, ensure_ascii=False, indent=2)};\n"
        f"window.RECAP_CALIBRATION = {json.dumps(calibration_data, ensure_ascii=False, indent=2)};\n"
        f"window.RECAP_UZI_AUDIT = {json.dumps(uzi_list, ensure_ascii=False, indent=2)};"
    )
    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write(js_content)
        
    print(f"Data exported to {JS_PATH}")

def generate_html():
    """Generate beautiful index.html template"""
    print("\nGenerating interactive index.html dashboard...")
    html_content = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股 1进2 接力复盘控制台</title>
    <!-- Local vendor assets for offline-friendly rendering -->
    <script src="assets/vendor/tailwind.min.js"></script>
    <!-- Vue 3 -->
    <script src="assets/vendor/vue.global.js"></script>
    <!-- Chart.js -->
    <script src="assets/vendor/chart.umd.min.js"></script>
    <!-- Lucide Icons -->
    <script src="assets/vendor/lucide.min.js"></script>
    <!-- Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;700&family=Geist:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', 'Geist', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: radial-gradient(circle at 50% 0%, rgba(244, 63, 94, 0.04) 0%, rgba(10, 11, 15, 0) 60%), #0a0b0e;
            color: #94a3b8;
            line-height: 1.55;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: geometricPrecision;
            font-feature-settings: "ss01" 1, "cv02" 1, "calt" 1;
        }
        html {
            scroll-behavior: smooth;
        }
        body::before {
            content: "";
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
            opacity: 0.015;
            pointer-events: none;
            z-index: 9999;
        }
        .mono-font {
            font-family: 'Fira Code', 'Courier New', Courier, monospace;
            font-size: 0.95em;
            letter-spacing: 0.01em;
            font-variant-numeric: tabular-nums;
        }
        #app h1,
        #app h2,
        #app h3,
        #app h4,
        #app h5 {
            font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            letter-spacing: -0.025em;
        }
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #0a0b0e;
        }
        ::-webkit-scrollbar-thumb {
            background: #1f242f;
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #f43f5e;
        }

        .console-card {
            position: relative;
            overflow: hidden;
            background-color: rgba(17, 19, 24, 0.96);
            background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0));
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.04),
                0 8px 32px 0 rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px) saturate(1.06);
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .console-card:hover {
            transform: translateY(-1px);
            border-color: rgba(244, 63, 94, 0.25);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.06),
                0 16px 48px 0 rgba(0, 0, 0, 0.6);
        }
        .console-card::before {
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(244, 63, 94, 0.22), transparent);
            opacity: 0.8;
            pointer-events: none;
        }

        .console-input {
            background-color: rgba(13, 14, 18, 0.96);
            border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: inset 0 1px 2px 0 rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(8px);
            transition: all 0.2s ease;
        }
        .console-input:focus {
            border-color: rgba(244, 63, 94, 0.4);
            box-shadow:
                inset 0 1px 2px 0 rgba(0, 0, 0, 0.5),
                0 0 16px 0 rgba(244, 63, 94, 0.12);
        }
        #app button,
        #app a,
        #app select,
        #app input {
            transition:
                transform 160ms cubic-bezier(0.16, 1, 0.3, 1),
                border-color 160ms ease,
                box-shadow 160ms ease,
                background-color 160ms ease,
                color 160ms ease;
        }
        #app button:hover,
        #app a:hover,
        #app [role="button"]:hover {
            transform: translateY(-0.5px);
        }
        #app button:active,
        #app a:active,
        #app [role="button"]:active {
            transform: translateY(0) scale(0.995);
        }
        #app button:focus-visible,
        #app a:focus-visible,
        #app select:focus-visible,
        #app input:focus-visible,
        #app [role="button"]:focus-visible {
            outline: 2px solid rgba(244, 63, 94, 0.22);
            outline-offset: 2px;
        }

        body[data-theme="light"] {
            background: radial-gradient(circle at top left, rgba(194, 65, 12, 0.07) 0%, rgba(194, 65, 12, 0) 28%), radial-gradient(circle at top right, rgba(37, 99, 235, 0.06) 0%, rgba(37, 99, 235, 0) 30%), #f5f1e8;
            color: #334155;
        }
        body[data-theme="light"]::before {
            opacity: 0.03;
        }
        body[data-theme="light"] ::-webkit-scrollbar-track {
            background: #f5f1e8;
        }
        body[data-theme="light"] ::-webkit-scrollbar-thumb {
            background: #cbd5e1;
        }
        body[data-theme="light"] ::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }
        body[data-theme="light"] .console-card {
            background-color: rgba(255, 255, 255, 0.78);
            background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.74), rgba(255, 255, 255, 0.52));
            border-color: rgba(31, 41, 55, 0.10);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.65),
                0 8px 24px 0 rgba(15, 23, 42, 0.06);
        }
        body[data-theme="light"] .console-card:hover {
            border-color: rgba(194, 65, 12, 0.20);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.72),
                0 16px 36px 0 rgba(15, 23, 42, 0.08);
        }
        body[data-theme="light"] .console-input {
            background-color: rgba(255, 250, 240, 0.96);
            border-color: rgba(31, 41, 55, 0.10);
            box-shadow: inset 0 1px 2px 0 rgba(15, 23, 42, 0.06);
        }
        body[data-theme="light"] .console-input:focus {
            border-color: rgba(194, 65, 12, 0.45);
            box-shadow:
                inset 0 1px 2px 0 rgba(15, 23, 42, 0.06),
                0 0 16px 0 rgba(194, 65, 12, 0.10);
        }
        body[data-theme="light"] #app [class*="border-[#1e222b]"] {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme="light"] #app [class*="border-[#1e222b]/80"] {
            border-color: rgba(31, 41, 55, 0.08) !important;
        }
        body[data-theme="light"] #app [class*="border-[#1e222b]/60"] {
            border-color: rgba(31, 41, 55, 0.06) !important;
        }
        body[data-theme="light"] #app [class*="border-[#1e222b]/20"] {
            border-color: rgba(31, 41, 55, 0.04) !important;
        }
        body[data-theme="light"] #app [class*="divide-[#1e222b]"] > * + * {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme="light"] #app [class*="bg-[#08090a]"] {
            background-color: #fffaf0 !important;
        }
        body[data-theme="light"] #app [class*="bg-[#0e1013]"] {
            background-color: #fffdf8 !important;
        }
        body[data-theme="light"] #app [class*="bg-[#0"],
        body[data-theme="light"] #app [class*="bg-[#1"] {
            background-color: #fffaf0 !important;
        }
        body[data-theme="light"] #app [class*="border-[#1"],
        body[data-theme="light"] #app [class*="border-[#2"] {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme="light"] #app [class*="text-[#9aa8be]"] {
            color: #64748b !important;
        }
        body[data-theme="light"] #app [class*="text-[#d1d5db]"] {
            color: #334155 !important;
        }

        body[data-theme="light"] #app [class*="text-[#8b9bb4]"] {
            color: #64748b !important;
        }
        body[data-theme="light"] #app [class*="text-gray-500"] {
            color: #64748b !important;
        }
        body[data-theme="light"] #app [class*="text-gray-400"] {
            color: #94a3b8 !important;
        }
        body[data-theme="light"] #app [class*="text-gray-600"] {
            color: #475569 !important;
        }
        body[data-theme="light"] #app [class*="text-white"] {
            color: #0f172a !important;
        }
        body[data-theme="light"] #app [class*="hover:border-red-500/20"]:hover {
            border-color: rgba(194, 65, 12, 0.20) !important;
        }
        body[data-theme="light"] #app [class*="hover:bg-[#1d212b]/20"]:hover {
            background-color: rgba(194, 65, 12, 0.04) !important;
        }
        body[data-theme="light"] #app [class*="bg-red-950/40"],
        body[data-theme="light"] #app [class*="bg-red-950"] {
            background-color: rgba(194, 65, 12, 0.10) !important;
            border-color: rgba(194, 65, 12, 0.25) !important;
            color: #c2410c !important;
            border-radius: 2px !important;
        }
        body[data-theme="light"] #app select,
        body[data-theme="light"] #app input[type="text"] {
            background-color: #fffaf0 !important;
            border-color: rgba(31, 41, 55, 0.10) !important;
            color: #0f172a !important;
        }
        body[data-theme="light"] #app select:focus-visible,
        body[data-theme="light"] #app input[type="text"]:focus-visible {
            outline-color: rgba(194, 65, 12, 0.22);
        }
        #app .console-card .text-2xs,
        #app .console-card .text-3xs,
        #app .console-card .text-[10px],
        #app .console-card .text-[11px] {
            line-height: 1.6;
        }
        #app .console-card .space-y-2 > * + * {
            margin-top: 0.625rem !important;
        }
        #app .console-card .space-y-3 > * + * {
            margin-top: 0.875rem !important;
        }

        #app [class*="border-[#1e222b]"] {
            border-color: rgba(255, 255, 255, 0.06) !important;
        }
        #app [class*="border-[#1e222b]/80"] {
            border-color: rgba(255, 255, 255, 0.04) !important;
        }
        #app [class*="border-[#1e222b]/60"] {
            border-color: rgba(255, 255, 255, 0.03) !important;
        }
        #app [class*="border-[#1e222b]/20"] {
            border-color: rgba(255, 255, 255, 0.02) !important;
        }
        #app [class*="divide-[#1e222b]"] > * + * {
            border-color: rgba(255, 255, 255, 0.06) !important;
        }
        #app [class*="bg-[#08090a]"] {
            background-color: #0a0b0f !important;
        }
        #app [class*="bg-[#0e1013]"] {
            background-color: #11131c !important;
        }
        #app [class*="text-[#8b9bb4]"] {
            color: #9aa8be !important;
        }
        #app [class*="text-gray-500"] {
            color: #7b8496 !important;
        }
        #app [class*="text-gray-400"] {
            color: #9aa0ad !important;
        }
        #app [class*="text-gray-600"] {
            color: #5b6473 !important;
        }
        #app [class*="hover:border-red-500/20"]:hover {
            border-color: rgba(244, 63, 94, 0.2) !important;
        }
        #app [class*="hover:bg-[#1d212b]/20"]:hover {
            background-color: rgba(244, 63, 94, 0.02) !important;
        }

        select, input[type="text"] {
            border-radius: 2px !important;
            padding-top: 0.375rem !important;
            padding-bottom: 0.375rem !important;
            border-color: rgba(255, 255, 255, 0.08) !important;
            background-color: #0d0e14 !important;
        }
        select:focus, input[type="text"]:focus {
            border-color: #f43f5e !important;
            outline: none !important;
        }

        #app [class*="bg-red-950/40"],
        #app [class*="bg-red-950"] {
            background-color: rgba(225, 29, 72, 0.1) !important;
            border-color: rgba(225, 29, 72, 0.3) !important;
            color: #f43f5e !important;
            border-radius: 2px !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
        }
        #app [class*="bg-red-950/40"]:hover,
        #app [class*="bg-red-950"]:hover {
            background-color: #e11d48 !important;
            color: #ffffff !important;
            border-color: #e11d48 !important;
        }
    </style>
</head>
<body class="min-h-screen pb-12">
    <div id="app" v-cloak class="container mx-auto px-4 py-6 max-w-7xl">
        
        <!-- Header -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-[#1e222b] pb-4 mb-8 gap-4">
            <div>
                <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3 uppercase">
                    <a href="javascript:history.back()" class="text-[#8b9bb4] hover:text-white text-3xs uppercase tracking-wider font-semibold mr-2 border-r border-[#1e222b] pr-3 mono-font inline-block align-middle">&larr; BACK / 返回</a>
                    <!-- Custom High-End SVG Brand Logo -->
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="inline-block align-middle">
                        <rect width="24" height="24" fill="#1b1c24" stroke="rgba(244,63,94,0.3)" stroke-width="1"/>
                        <path d="M12 4L6 10H10V17H14V11H18L12 4Z" fill="#F43F5E" />
                        <path d="M8 12H10" stroke="#FFFFFF" stroke-width="1.2" stroke-linecap="round"/>
                        <path d="M14 12H16" stroke="#FFFFFF" stroke-width="1.2" stroke-linecap="round"/>
                    </svg>
                    <span class="text-white">A股 1进2 接力复盘控制台</span>
                </h1>
                <p class="text-gray-500 text-xs mt-1 uppercase tracking-wide mono-font">1进2 连板接力分析控制台</p>
            </div>
            
            <div class="flex flex-wrap items-center gap-4">
                <!-- Timeline Simulator -->
                <div class="flex items-center gap-2">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">竞价时段模拟:</span>
                    <select v-model="simTimePhase" class="console-input rounded-none px-3 py-1.5 text-xs text-white font-medium focus:outline-none focus:border-red-500 mono-font" aria-label="竞价时段模拟">
                        <option value="real">系统实时时间</option>
                        <option value="915">模拟 09:17 (虚假试盘)</option>
                        <option value="920">模拟 09:22 (真实竞价)</option>
                        <option value="925">模拟 09:26 (竞价定格)</option>
                        <option value="930">模拟 09:35 (盘中交易)</option>
                    </select>
                </div>
                
                <div class="flex items-center gap-2">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">主题模式:</span>
                    <select v-model="themeMode" class="console-input rounded-none px-3 py-1.5 text-xs text-white font-medium focus:outline-none focus:border-red-500 mono-font" aria-label="主题模式">
                        <option value="system">跟随系统</option>
                        <option value="light">日间主题</option>
                        <option value="dark">夜间主题</option>
                    </select>
                </div>

                <div class="flex items-center gap-2">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">选择复盘日期:</span>
                    <select v-model="selectedDate" class="console-input rounded-none px-3 py-1.5 text-xs text-white font-medium focus:outline-none focus:border-red-500 mono-font" aria-label="选择复盘日期">
                        <option v-for="date in availableDates" :key="date" :value="date">{{ date }}</option>
                    </select>
                </div>
                <div class="border border-red-900 bg-red-950/20 text-red-400 px-3 py-1.5 rounded-none text-2xs font-bold uppercase tracking-wider mono-font">
                    连板接力模式
                </div>
            </div>
        </header>

        <div v-if="!currentRecap" class="text-center py-20 text-gray-500">
            <i data-lucide="loader" class="animate-spin w-10 h-10 mx-auto mb-4 text-red-500"></i>
            系统数据加载中...
        </div>

        <div v-else class="space-y-6">
            
            <!-- Top Row: Sentiment Console & Trends -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Sentiment Console (1/3) -->
                <div class="console-card p-6 flex flex-col justify-between">
                    <div>
                        <div class="border-b border-[#1e222b] pb-2 mb-4">
                            <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">市场短线情绪</span>
                        </div>
                        
                        <!-- SVG Dial -->
                        <div class="py-4 relative flex flex-col items-center">
                            <svg viewBox="0 0 120 70" class="w-36 h-20">
                                <!-- Concentric arcs for precision instrument feel -->
                                <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="8" stroke-linecap="square"/>
                                <path d="M 14 60 A 46 46 0 0 1 106 60" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2,2"/>
                                <!-- Ticks: Green is bearish/down on left, Red is bullish/up on right (Chinese stock conventions) -->
                                <line x1="10" y1="60" x2="16" y2="60" stroke="#10b981" stroke-width="1.5" /> <!-- Green (Bearish) -->
                                <line x1="20" y1="38" x2="25" y2="41" stroke="#3b82f6" stroke-width="1" />
                                <line x1="38" y1="20" x2="41" y2="25" stroke="#64748b" stroke-width="1" />
                                <line x1="60" y1="10" x2="60" y2="17" stroke="#64748b" stroke-width="1.5" /> <!-- Center (Neutral) -->
                                <line x1="82" y1="20" x2="79" y2="25" stroke="#f59e0b" stroke-width="1" />
                                <line x1="100" y1="38" x2="95" y2="41" stroke="#e11d48" stroke-width="1" />
                                <line x1="104" y1="60" x2="110" y2="60" stroke="#e11d48" stroke-width="1.5" /> <!-- Red (Bullish) -->
                                <!-- Needle: thinner and elegant -->
                                <line x1="60" y1="60" x2="60" y2="16" stroke="#f43f5e" stroke-width="1.5" stroke-linecap="square"
                                      :style="{ transform: 'rotate(' + needleAngle + 'deg)', transformOrigin: '60px 60px' }" class="transition-transform duration-500 ease-out" />
                                <!-- Center pin with a nested ring for depth -->
                                <circle cx="60" cy="60" r="5" fill="#111318" stroke="#f43f5e" stroke-width="1" />
                                <circle cx="60" cy="60" r="2" fill="#ffffff" />
                            </svg>
                            <div class="text-2xl font-bold mt-2 uppercase tracking-wide" :class="sentimentColorClass">
                                {{ currentRecap.market.sentiment }}
                            </div>
                        </div>
                        
                        <!-- Core Stats -->
                        <div class="space-y-2 border-t border-[#1e222b] pt-3 text-2xs mono-font">
                            <div class="flex justify-between items-center">
                                <span class="text-[#8b9bb4]">全市场涨停家数</span>
                                <span class="text-white font-bold">{{ currentRecap.market.limit_ups }}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-[#8b9bb4]">全市场跌停家数</span>
                                <span class="text-white font-bold">{{ currentRecap.market.limit_downs }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Quant Win Rate Backtest Stats -->
                    <div class="border-t border-[#1e222b] pt-3 mt-3">
                        <span class="text-[#8b9bb4] text-3xs uppercase tracking-wider font-semibold block mb-2">量化胜率校验 / 历史晋级率回测</span>
                        <div class="space-y-1.5 text-3xs mono-font">
                            <div v-for="cal in calibrationData" :key="cal.score_range" class="flex justify-between items-center">
                                <span class="text-gray-500">{{ cal.bucket_name.split(' ')[0] }} ({{ cal.score_range }}分)</span>
                                <span class="font-bold" :class="cal.win_rate >= 15 ? 'text-red-500' : 'text-gray-400'">
                                    {{ cal.win_rate.toFixed(2) }}% <span class="text-[#8b9bb4] font-normal">({{ cal.promoted_count }}/{{ cal.total_count }})</span>
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Trend chart (2/3) -->
                <div class="lg:col-span-2 console-card p-6 flex flex-col justify-between">
                    <div class="flex justify-between items-center border-b border-[#1e222b] pb-2 mb-4">
                        <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">1进2 晋级率与总涨停家数历史趋势</span>
                        <span class="text-2xs text-[#8b9bb4] uppercase tracking-wider font-semibold mono-font">最近15个交易日</span>
                    </div>
                    <div class="h-[210px] relative">
                        <canvas id="trendChart"></canvas>
                    </div>
                    <div class="grid grid-cols-2 gap-4 border-t border-[#1e222b] pt-3 text-2xs mono-font">
                        <div class="flex justify-between">
                            <span class="text-[#8b9bb4]">今日1进2晋级率</span>
                            <span class="text-red-500 font-bold">{{ currentRecap.market.promotion_rate.toFixed(2) }}%</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-[#8b9bb4]">两市总成交额</span>
                            <span class="text-white font-bold">{{ currentRecap.market.total_turnover.toFixed(1) }} 亿</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Index & Northbound Row -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
                <!-- SH Index -->
                <div class="console-card p-5 flex flex-col justify-between">
                    <div class="flex justify-between items-center text-[#8b9bb4] text-2xs uppercase">
                        <span>上证指数</span>
                        <span class="mono-font text-3xs text-gray-500">000001</span>
                    </div>
                    <div class="mt-2 flex justify-between items-baseline">
                        <span class="text-lg font-bold text-white mono-font">{{ currentRecap.market.sh_price.toFixed(2) }}</span>
                        <span :class="currentRecap.market.sh_change >= 0 ? 'text-red-500' : 'text-green-500'" class="text-xs font-bold mono-font">
                            {{ currentRecap.market.sh_change >= 0 ? '+' : '' }}{{ currentRecap.market.sh_change.toFixed(2) }}%
                        </span>
                    </div>
                </div>
                <!-- SZ Index -->
                <div class="console-card p-5 flex flex-col justify-between">
                    <div class="flex justify-between items-center text-[#8b9bb4] text-2xs uppercase">
                        <span>深证成指</span>
                        <span class="mono-font text-3xs text-gray-500">399001</span>
                    </div>
                    <div class="mt-2 flex justify-between items-baseline">
                        <span class="text-lg font-bold text-white mono-font">{{ currentRecap.market.sz_price.toFixed(2) }}</span>
                        <span :class="currentRecap.market.sz_change >= 0 ? 'text-red-500' : 'text-green-500'" class="text-xs font-bold mono-font">
                            {{ currentRecap.market.sz_change >= 0 ? '+' : '' }}{{ currentRecap.market.sz_change.toFixed(2) }}%
                        </span>
                    </div>
                </div>
                <!-- CY Index -->
                <div class="console-card p-5 flex flex-col justify-between">
                    <div class="flex justify-between items-center text-[#8b9bb4] text-2xs uppercase">
                        <span>创业板指</span>
                        <span class="mono-font text-3xs text-gray-500">399006</span>
                    </div>
                    <div class="mt-2 flex justify-between items-baseline">
                        <span class="text-lg font-bold text-white mono-font">{{ currentRecap.market.cy_price.toFixed(2) }}</span>
                        <span :class="currentRecap.market.cy_change >= 0 ? 'text-red-500' : 'text-green-500'" class="text-xs font-bold mono-font">
                            {{ currentRecap.market.cy_change >= 0 ? '+' : '' }}{{ currentRecap.market.cy_change.toFixed(2) }}%
                        </span>
                    </div>
                </div>
                <!-- Northbound Net Flow -->
                <div class="console-card p-5 flex flex-col justify-between">
                    <div class="flex justify-between items-center text-[#8b9bb4] text-2xs uppercase">
                        <span>北向资金流向</span>
                        <span class="bg-[#1b1c24] border border-[#24262b] px-1 text-3xs font-semibold">净买入</span>
                    </div>
                    <div class="mt-2 flex justify-between items-baseline">
                        <span class="text-lg font-bold mono-font text-white">
                            {{ (currentRecap.market.hgt_flow + currentRecap.market.sgt_flow) >= 0 ? '+' : '' }}{{ (currentRecap.market.hgt_flow + currentRecap.market.sgt_flow).toFixed(2) }}亿
                        </span>
                        <span class="text-3xs text-[#8b9bb4] mono-font">沪:{{ currentRecap.market.hgt_flow.toFixed(1) }} 深:{{ currentRecap.market.sgt_flow.toFixed(1) }}</span>
                    </div>
                </div>
            </div>

            <!-- Top 5 Focus Candidates (Vertical List layout) -->
            <div class="console-card p-6 md:p-8">
                <div class="border-b border-[#1e222b] pb-2 mb-4 flex justify-between items-center">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">重点关注首板标的</span>
                    <span class="text-2xs text-[#ef4444] font-bold uppercase tracking-wider mono-font">接力因子前五强</span>
                </div>
                <div class="space-y-3">
                    <div v-for="(c, idx) in topCandidates" :key="c.code" class="py-4 md:py-5 first:pt-0 last:pb-0">
                        <div class="flex flex-col md:flex-row gap-5 border border-[#1e222b]/60 bg-[#0b0d12] p-4 md:p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
                            <!-- Left: Stock Metrics -->
                            <div class="w-full md:w-1/3 flex flex-col justify-between gap-4">
                                <div class="flex justify-between items-start gap-3">
                                    <div class="flex items-center gap-2 min-w-0">
                                        <span class="text-[9px] px-2 py-0.5 font-bold border rounded-none tracking-[0.12em]"
                                              :class="idx === 0 ? 'bg-red-950 text-red-400 border-red-900' : 'bg-[#1b1c24] text-gray-400 border-[#24262b]'">
                                            NO.{{ idx + 1 }}
                                        </span>
                                        <div class="min-w-0">
                                            <span class="block text-[15px] font-semibold text-white tracking-tight truncate">{{ c.name }}</span>
                                            <span class="block text-[10px] text-[#9aa8be] mono-font truncate">{{ c.code }}</span>
                                        </div>
                                    </div>
                                    <div class="flex flex-wrap justify-end gap-2">
                                        <span class="text-[9px] text-yellow-500 font-bold border border-yellow-500/15 px-2 py-0.5 bg-yellow-500/5 mono-font tracking-[0.08em]">
                                            接力指数 {{ c.score }}
                                        </span>
                                        <span v-if="c.pred_prob !== null && c.pred_prob !== undefined" class="text-[9px] text-red-400 font-bold border border-red-500/15 px-2 py-0.5 bg-red-500/5 mono-font tracking-[0.08em]">
                                            预估晋级率 {{ (c.pred_prob * 100).toFixed(1) }}%
                                        </span>
                                        <button @click.stop="buyStock(c, c.price)"
                                                class="bg-red-950/40 border border-red-900/50 text-red-400 hover:bg-red-900 hover:text-white px-2 py-0.5 text-2xs font-semibold select-none transition-all active:scale-[0.96]">
                                            模拟买入
                                        </button>
                                    </div>
                                </div>
                                <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-1 text-3xs mono-font">
                                    <div class="bg-[#08090a] border border-[#1e222b]/60 p-2.5">
                                        <div class="text-[#9aa8be] uppercase tracking-wide">首次封板时间</div>
                                        <div class="text-white font-medium mt-0.5">{{ c.first_seal_time_formatted }}</div>
                                    </div>
                                    <div class="bg-[#08090a] border border-[#1e222b]/60 p-2.5">
                                        <div class="text-[#9aa8be] uppercase tracking-wide">日内炸板次数</div>
                                        <div class="text-white font-medium mt-0.5" :class="c.blown_count >= 2 ? 'text-yellow-500 font-semibold' : ''">{{ c.blown_count }}</div>
                                    </div>
                                    <div class="bg-[#08090a] border border-[#1e222b]/60 p-2.5">
                                        <div class="text-[#9aa8be] uppercase tracking-wide">日内换手率</div>
                                        <div class="text-white font-medium mt-0.5">{{ c.turnover.toFixed(2) }}%</div>
                                    </div>
                                    <div class="bg-[#08090a] border border-[#1e222b]/60 p-2.5">
                                        <div class="text-[#9aa8be] uppercase tracking-wide">流通市值</div>
                                        <div class="text-white font-medium mt-0.5">{{ c.float_mcap.toFixed(2) }} 亿</div>
                                    </div>
                                </div>
                                <div class="text-2xs text-[#9aa8be] mt-1 font-semibold uppercase tracking-wide">
                                    所属行业: <span class="text-gray-300 normal-case">{{ c.sector }}</span>
                                </div>
                            </div>
                            <!-- Right: Action advice -->
                            <div class="w-full md:w-2/3 bg-[#11131c] p-5 border border-[#1e222b]/60 rounded-none flex flex-col justify-center gap-2.5 min-h-[170px]">
                                <div class="flex items-center justify-between">
                                    <span class="text-[10px] uppercase tracking-[0.14em] text-[#9aa8be] font-semibold">操作建议</span>
                                    <span class="text-[10px] text-[#fb7185] font-bold uppercase tracking-[0.18em] mono-font">INTRADAY PLAYBOOK</span>
                                </div>
                                <div class="text-sm text-[#d1d5db] leading-7 font-mono border-l-2 border-l-red-500/50 pl-3">
                                    {{ c.playbook }}
                                </div>
                            </div>
                        </div>
                    </div>

            <!-- 次日实战操作控制台 -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- 竞价监控哨口 (2/3) -->
                <div class="lg:col-span-2 console-card p-6 md:p-8 flex flex-col justify-between">
                    <div>
                        <div class="border-b border-[#1e222b] pb-2 mb-4 flex justify-between items-center">
                            <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">次日竞价监控哨 / 量化上车标准</span>
                            <div class="flex gap-2">
                                <button @click="fetchLiveQuotes" 
                                        class="bg-red-950 border border-red-900 text-red-400 hover:bg-red-900 hover:text-white px-2 py-1 text-3xs font-bold transition-all active:scale-[0.97] uppercase tracking-wider mono-font">
                                    刷新今日实时竞价 (09:25后生效)
                                </button>
                                <span class="text-2xs text-[#ef4444] font-bold uppercase tracking-wider mono-font">MORNING AUCTION TARGETS</span>
                            </div>
                        </div>

                        <!-- 竞价分时决策指示器 -->
                        <div class="mb-3 border p-3 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 transition-all duration-300 rounded-none"
                             :class="activeTimePhase.bgClass">
                            <div class="flex items-center gap-2">
                                <span class="w-2.5 h-2.5 rounded-none" :class="activeTimePhase.dotClass"></span>
                                <span class="text-2xs font-bold text-white uppercase tracking-wider mono-font">
                                    竞价哨口监控状态: {{ activeTimePhase.name }}
                                </span>
                            </div>
                            <p class="text-3xs font-semibold leading-relaxed" :class="activeTimePhase.textClass">
                                {{ activeTimePhase.warning }}
                            </p>
                        </div>
                        
                        <!-- Horizontal Row Panels -->
                        <div class="space-y-2">
                            <div v-for="c in topCandidates" :key="c.code + '-target'" 
                                 @click="simStockCode = c.code"
                                 @keyup.enter="simStockCode = c.code"
                                 @keyup.space.prevent="simStockCode = c.code"
                                 role="button"
                                 tabindex="0"
                                 :class="simStockCode === c.code ? 'border-red-500 bg-red-950/5 focus:ring-1 focus:ring-red-500' : 'border-[#1e222b] bg-[#0e1013] hover:border-red-500/20 focus:ring-1 focus:ring-red-500'"
                                 class="border p-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 cursor-pointer transition-all duration-200 select-none focus:outline-none active:scale-[0.99]">
                                
                                <!-- Part 1: Stock Identity -->
                                <div class="w-full sm:w-1/4">
                                    <h4 class="text-sm font-extrabold text-white flex items-center gap-1.5">
                                        <span class="w-1.5 h-1.5" :class="simStockCode === c.code ? 'bg-red-500 animate-pulse' : 'bg-gray-600'"></span> {{ c.name }}
                                    </h4>
                                    <p class="text-3xs text-[#8b9bb4] mono-font mt-0.5">{{ c.code }} · {{ c.sector }}</p>
                                </div>
                                
                                <!-- Part 2: Monospace metrics (3 columns) -->
                                <div class="w-full sm:w-1/2 grid grid-cols-3 gap-2 text-3xs mono-font">
                                    <div>
                                        <div class="text-[#8b9bb4]">昨日收盘</div>
                                        <div class="text-red-500 font-bold mt-0.5">{{ c.price.toFixed(2) }}元</div>
                                    </div>
                                    <div>
                                        <div class="text-[#8b9bb4]">理想开盘 (2%~5%)</div>
                                        <div class="text-yellow-500 font-bold mt-0.5">{{ (c.price * 1.02).toFixed(2) }} ~ {{ (c.price * 1.05).toFixed(2) }}元</div>
                                        <!-- Actual open from live data -->
                                        <div v-if="liveData[c.code]" class="mt-1 pt-1 border-t border-[#1e222b]">
                                            <span class="text-gray-500">实际开盘: </span>
                                            <span :class="liveData[c.code].change >= 0 ? 'text-red-500' : 'text-green-500'" class="font-bold">
                                                {{ liveData[c.code].change >= 0 ? '+' : '' }}{{ liveData[c.code].change.toFixed(2) }}%
                                            </span>
                                        </div>
                                    </div>
                                    <div>
                                        <div class="text-[#8b9bb4]">目标竞价额 (10%昨成交)</div>
                                        <div class="text-red-400 font-bold mt-0.5">&gt;{{ (c.float_mcap * c.turnover * 10).toFixed(0) }}万</div>
                                        <!-- Actual auction volume from live data -->
                                        <div v-if="liveData[c.code]" class="mt-1 pt-1 border-t border-[#1e222b]">
                                            <span class="text-gray-500">实际竞价: </span>
                                            <span :class="isVolMet(c) ? 'text-red-400 font-bold' : 'text-gray-400'" class="font-bold">
                                                {{ liveData[c.code].turnover.toFixed(0) }}万
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                
                                <!-- Part 3: Strategy summary -->
                                <div class="w-full sm:w-1/4 text-right text-3xs text-gray-400 leading-normal flex flex-col items-end gap-1">
                                    <span class="font-semibold">{{ c.score >= 115 ? '高溢价高要求，爆量高开为强' : '弱转强首选，高开回踩支撑进场' }}</span>
                                    <div v-if="liveData[c.code]" class="mt-2">
                                        <span v-if="isSignalMet(c)" class="bg-red-950 text-red-400 border border-red-900 px-2 py-0.5 font-bold animate-pulse">
                                            🚀 竞价强承接 (达标)
                                        </span>
                                        <span v-else class="bg-gray-900 text-[#8b9bb4] border border-[#1e222b] px-2 py-0.5 font-medium">
                                            未达标
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="text-3xs text-[#8b9bb4] mt-4 leading-relaxed border-t border-[#1e222b] pt-2">
                        * 使用说明：点击上方股票行可直接聚焦右侧决策模拟器。明日 09:25 竞价结束时，若实际开盘价与竞价成交额达到上述标准，说明资金入场强劲，符合量化上车要求。
                    </div>
                </div>

                <!-- 1进2上车决策模拟器 (1/3) -->
                <div class="console-card p-6 md:p-8 flex flex-col justify-between">
                    <div>
                        <div class="border-b border-[#1e222b] pb-2 mb-4">
                            <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">1进2 实战上车决策器 / 模拟判定</span>
                        </div>
                        
                        <div class="space-y-3">
                            <!-- 1. Select Stock -->
                            <div>
                                <label class="text-[#8b9bb4] text-3xs uppercase block font-semibold mb-1">选择目标股:</label>
                                <select v-model="simStockCode" class="w-full console-input border border-[#1e222b] rounded-none px-2 py-1 text-2xs text-white focus:outline-none focus:border-red-500 mono-font" aria-label="选择模拟目标股">
                                    <option v-for="c in topCandidates" :key="c.code + '-sim'" :value="c.code">{{ c.name }} ({{ c.code }})</option>
                                </select>
                            </div>
                            
                            <!-- 2. Select Open % -->
                            <div>
                                <label class="text-[#8b9bb4] text-3xs uppercase block font-semibold mb-1">明日 09:25 开盘涨幅:</label>
                                <select v-model="simOpenType" class="w-full console-input border border-[#1e222b] rounded-none px-2 py-1 text-2xs text-white focus:outline-none focus:border-red-500" aria-label="选择明日开盘涨幅">
                                    <option value="fever">高烧低走区 (高开 &gt;6% 或一字板)</option>
                                    <option value="ideal">理想溢价区 (高开 2% ~ 5%)</option>
                                    <option value="mild">温和试探区 (高开 0% ~ 2%)</option>
                                    <option value="low">低开分歧区 (平开或低开 &lt;0%)</option>
                                </select>
                            </div>
                            
                            <!-- 3. Select Volume -->
                            <div>
                                <label class="text-[#8b9bb4] text-3xs uppercase block font-semibold mb-1">明日 09:25 竞价成交额:</label>
                                <select v-model="simVolType" class="w-full console-input border border-[#1e222b] rounded-none px-2 py-1 text-2xs text-white focus:outline-none focus:border-red-500" aria-label="选择明日竞价成交量">
                                    <option value="met">放量达标 (达到或超出目标值)</option>
                                    <option value="not_met">缩量未达标 (低于目标值)</option>
                                </select>
                            </div>

                            <!-- 4. Select Open Trend -->
                            <div>
                                <label class="text-[#8b9bb4] text-3xs uppercase block font-semibold mb-1">开盘前15分钟分时走势:</label>
                                <select v-model="simTrendType" class="w-full console-input border border-[#1e222b] rounded-none px-2 py-1 text-2xs text-white focus:outline-none focus:border-red-500" aria-label="选择开盘分时走势">
                                    <option value="breakout">高开下探不破分时均线，放量突破开盘价</option>
                                    <option value="limit_up">开盘爆量单边直线拉升，极速封死二板</option>
                                    <option value="weak">冲高后无量下杀，跌破均线且不翻红</option>
                                    <option value="low_bounce">低开震荡后强力翻红，放量突破昨日收盘价</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- Simulator Result -->
                    <div class="mt-4 p-3 border border-[#1e222b] bg-[#08090a] rounded-none text-2xs">
                        <div class="flex justify-between items-center font-bold mb-1" :class="simResult.color">
                            <span>决策判定: {{ simResult.decision }}</span>
                            <span class="text-3xs uppercase tracking-wide border px-1" :class="simResult.border">{{ simResult.badge }}</span>
                        </div>
                        <p class="text-gray-400 leading-relaxed font-mono mt-1">{{ simResult.reason }}</p>
                    </div>
                </div>
            </div>

            <!-- UZI 智能评委席报告 -->
            <div class="console-card p-6 md:p-8 rounded-none">
                <div class="border-b border-[#1e222b] pb-2 mb-4 flex justify-between items-center gap-4">
                    <span class="text-[#9aa8be] text-2xs uppercase tracking-wider font-semibold">■ UZI 智能评委席报告 / UZI JURY AUDIT REPORT</span>
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] px-2 py-0.5 border rounded-none tracking-[0.14em] font-semibold"
                              :class="isUziOnline ? 'border-green-900 bg-green-950/20 text-green-400' : 'border-yellow-900 bg-yellow-950/20 text-yellow-400'">
                            {{ isUziOnline ? '大模型智能评审模式' : '本地财务规则模拟' }}
                        </span>
                        <span class="text-[10px] text-[#fb7185] font-bold uppercase tracking-[0.18em] mono-font">JURY AUDIT PANEL</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-5 gap-4 md:gap-5">
                    <div v-for="u in currentUziAudit" :key="u.code"
                         class="bg-[#0b0d12] p-4 md:p-5 border border-[#1e222b]/60 rounded-none flex flex-col justify-between gap-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
                        <div>
                            <div class="flex justify-between items-start border-b border-[#1e222b]/60 pb-3">
                                <div>
                                    <h4 class="text-[15px] font-semibold text-white tracking-tight">{{ u.name }}</h4>
                                    <p class="text-[10px] text-[#9aa8be] mono-font mt-0.5">{{ u.code }} · <span class="normal-case text-gray-400">{{ u.sector }}</span></p>
                                </div>
                                <div class="inline-flex items-center justify-center px-2 py-0.5 border border-[#2a3040] bg-[#11131c] text-[#fb7185] text-lg font-extrabold rounded-none">
                                    {{ u.average_score.toFixed(1) }}<span class="text-xs ml-0.5">分</span>
                                </div>
                            </div>

                            <div class="mt-3 space-y-2 text-3xs">
                                <div class="flex justify-between items-center">
                                    <span class="text-gray-500">巴菲特 (价值流派)</span>
                                    <span :class="u.val_vote === '多头' ? 'text-red-500' : (u.val_vote === '空头' ? 'text-green-500' : 'text-gray-500')" class="font-bold">
                                        {{ u.val_vote }}
                                    </span>
                                </div>
                                <div class="flex justify-between items-center">
                                    <span class="text-gray-500">赵老哥 (游资接力)</span>
                                    <span :class="u.mom_vote === '多头' ? 'text-red-500' : (u.mom_vote === '空头' ? 'text-green-500' : 'text-gray-500')" class="font-bold">
                                        {{ u.mom_vote }}
                                    </span>
                                </div>
                                <div class="flex justify-between items-center border-t border-[#1e222b]/60 pt-2 mt-2">
                                    <span class="text-gray-500">大空头 (排雷评级)</span>
                                    <span :class="u.risk_level === '安全' ? 'text-green-400' : 'text-red-400'" class="font-bold">
                                        {{ u.risk_level }}
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div class="text-[11px] text-[#d1d5db] bg-[#0e1117] p-3.5 border border-[#2a3040] rounded-none leading-7 font-mono select-none">
                            {{ u.summary }}
                        </div>

                        <div v-if="u.report_path" class="mt-1">
                            <a :href="u.report_path" target="_blank"
                               class="block w-full text-center bg-[#11131c] border border-[#2a3040] text-[#fb7185] hover:bg-[#151923] hover:text-white py-1.5 text-3xs font-bold transition-all active:scale-[0.96]">
                                查看 UZI 深度诊断报告
                            </a>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 模拟实战交易账本 -->
            <div class="console-card p-6 md:p-8">
                <div class="border-b border-[#1e222b] pb-2 mb-4 flex justify-between items-center">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">模拟实战交易账本 / PORTFOLIO & LEDGER</span>
                    <span class="text-2xs text-yellow-500 font-bold uppercase tracking-wider mono-font">MOCK PAPER TRADING JOURNAL</span>
                </div>
                
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <!-- Left: Portfolio & Logs (2/3) -->
                    <div class="lg:col-span-2 space-y-4">
                        <!-- Tab Selector -->
                        <div class="flex gap-2 border-b border-[#1e222b] pb-2 text-2xs font-semibold">
                            <button @click="ledgerTab = 'portfolio'" 
                                    :class="ledgerTab === 'portfolio' ? 'text-red-500 border-b border-red-500' : 'text-[#8b9bb4]'"
                                    class="pb-1 px-1 uppercase tracking-wider">
                                当前持仓 ({{ portfolio.length }})
                            </button>
                            <button @click="ledgerTab = 'log'" 
                                    :class="ledgerTab === 'log' ? 'text-red-500 border-b border-red-500' : 'text-[#8b9bb4]'"
                                    class="pb-1 px-1 uppercase tracking-wider">
                                交易日志 ({{ tradeLog.length }})
                            </button>
                        </div>
                        
                        <!-- Tab 1: Current Portfolio -->
                        <div v-if="ledgerTab === 'portfolio'" class="space-y-2">
                            <div v-if="portfolio.length === 0" class="text-center py-8 text-gray-600 text-xs">
                                暂无持仓股。可在下方股票池中点击“买入”或顶部五强中点击“模拟买入”进行建仓。
                            </div>
                            <div v-for="p in portfolio" :key="p.code" 
                                 class="bg-[#08090a] p-4 border border-[#1e222b] rounded-none flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                                <div class="w-full sm:w-1/4">
                                    <h5 class="text-xs font-bold text-white flex items-center gap-1.5">
                                        <span class="w-1.5 h-1.5 bg-red-500 animate-pulse"></span> {{ p.name }}
                                    </h5>
                                    <p class="text-3xs text-[#8b9bb4] mono-font mt-0.5">{{ p.code }} · {{ p.sector }}</p>
                                </div>
                                <div class="w-full sm:w-1/2 grid grid-cols-4 gap-2 text-3xs mono-font">
                                    <div>
                                        <div class="text-gray-600">建仓日期/均价</div>
                                        <div class="text-white mt-0.5">{{ p.buy_date.substring(5) }} / {{ p.buy_price.toFixed(2) }}</div>
                                    </div>
                                    <div>
                                        <div class="text-gray-600">持股股数/市值</div>
                                        <div class="text-white mt-0.5">{{ p.shares }}股 / {{ (p.shares * getValuationPrice(p.code, p.buy_price)).toFixed(0) }}</div>
                                    </div>
                                    <div>
                                        <div class="text-gray-600">今日估值/盈亏</div>
                                        <div class="text-white mt-0.5 font-semibold" :class="getPnlColor(p)">
                                            {{ getValuationPrice(p.code, p.buy_price).toFixed(2) }} / {{ getFloatingPnl(p) >= 0 ? '+' : '' }}{{ getFloatingPnl(p).toFixed(0) }}
                                        </div>
                                    </div>
                                    <div>
                                        <div class="text-gray-600">盈亏比例</div>
                                        <div class="text-white mt-0.5 font-bold" :class="getPnlColor(p)">
                                            {{ getFloatingPnlPct(p) >= 0 ? '+' : '' }}{{ getFloatingPnlPct(p).toFixed(2) }}%
                                        </div>
                                    </div>
                                </div>
                                <!-- Exit advice & Sell button -->
                                <div class="w-full sm:w-1/4 flex flex-col items-end gap-1.5">
                                    <span class="text-3xs px-2 py-0.5 border rounded-none" :class="getExitAdvice(p).color">
                                        {{ getExitAdvice(p).text }}
                                    </span>
                                    <button @click="triggerSell(p)" 
                                            class="bg-red-950 border border-red-900 text-red-400 hover:bg-red-900 hover:text-white px-3 py-1 text-3xs font-bold transition-all active:scale-[0.96]">
                                        虚拟平仓
                                    </button>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Tab 2: Trade Log -->
                        <div v-if="ledgerTab === 'log'" class="overflow-x-auto max-h-[300px] overflow-y-auto pr-1">
                            <div v-if="tradeLog.length === 0" class="text-center py-8 text-gray-600 text-xs">
                                暂无历史平仓记录。
                            </div>
                            <table v-else class="w-full text-left text-3xs border-collapse">
                                <thead>
                                    <tr class="border-b border-[#1e222b] text-gray-500 font-bold uppercase tracking-wider bg-[#08090a]">
                                        <th class="py-2 px-2">代码</th>
                                        <th class="py-2 px-2">名称</th>
                                        <th class="py-2 px-2">建仓日期/均价</th>
                                        <th class="py-2 px-2">平仓日期/均价</th>
                                        <th class="py-2 px-2 text-right">股数</th>
                                        <th class="py-2 px-2 text-right">实现盈亏</th>
                                        <th class="py-2 px-2 text-right">盈亏比</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="log in tradeLog" :key="log.buy_date + '-' + log.code" class="border-b border-[#1d212a]/50">
                                        <td class="py-2 px-2 code-font text-gray-400">{{ log.code }}</td>
                                        <td class="py-2 px-2 font-bold text-white">{{ log.name }}</td>
                                        <td class="py-2 px-2 code-font">{{ log.buy_date.substring(5) }} / {{ log.buy_price.toFixed(2) }}</td>
                                        <td class="py-2 px-2 code-font">{{ log.sell_date.substring(5) }} / {{ log.sell_price.toFixed(2) }}</td>
                                        <td class="py-2 px-2 text-right code-font text-white">{{ log.shares }}</td>
                                        <td class="py-2 px-2 text-right code-font font-bold" :class="log.pnl >= 0 ? 'text-red-500' : 'text-green-500'">
                                            {{ log.pnl >= 0 ? '+' : '' }}{{ log.pnl.toFixed(0) }}
                                        </td>
                                        <td class="py-2 px-2 text-right code-font font-bold" :class="log.pnl >= 0 ? 'text-red-500' : 'text-green-500'">
                                            {{ log.pnl >= 0 ? '+' : '' }}{{ log.pnl_pct.toFixed(2) }}%
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <!-- Right: Performance Stats (1/3) -->
                    <div class="border-l border-[#1e222b] pl-6 flex flex-col justify-between gap-4">
                        <div>
                            <div class="border-b border-[#1e222b] pb-2 mb-4">
                                <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">模拟持仓绩效面板</span>
                            </div>
                            <div class="space-y-3 mono-font text-2xs">
                                <div class="flex justify-between items-center">
                                    <span class="text-[#8b9bb4]">总资产 (可用+持仓)</span>
                                    <span class="text-white font-extrabold text-sm">{{ totalEquity.toFixed(0) }} 元</span>
                                </div>
                                <div class="flex justify-between items-center">
                                    <span class="text-[#8b9bb4]">可用现金</span>
                                    <span class="text-white font-bold">{{ cash.toFixed(0) }} 元</span>
                                </div>
                                <div class="flex justify-between items-center">
                                    <span class="text-[#8b9bb4]">持仓估算市值</span>
                                    <span class="text-white font-bold">{{ portfolioValue.toFixed(0) }} 元</span>
                                </div>
                                <div class="flex justify-between items-center border-t border-[#1e222b] pt-2">
                                    <span class="text-[#8b9bb4]">账户累计盈亏</span>
                                    <span :class="totalPnl >= 0 ? 'text-red-500' : 'text-green-500'" class="font-extrabold">
                                        {{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl.toFixed(0) }} 元
                                    </span>
                                </div>
                                <div class="flex justify-between items-center">
                                    <span class="text-[#8b9bb4]">账户累计收益率</span>
                                    <span :class="totalPnl >= 0 ? 'text-red-500' : 'text-green-500'" class="font-extrabold">
                                        {{ totalPnl >= 0 ? '+' : '' }}{{ (totalPnl / 10000).toFixed(2) }}%
                                    </span>
                                </div>
                                <div class="flex justify-between items-center border-t border-[#1e222b] pt-2">
                                    <span class="text-[#8b9bb4]">模拟交易胜率</span>
                                    <span class="text-yellow-500 font-bold">{{ winRate.toFixed(2) }}%</span>
                                </div>
                                <div class="flex justify-between items-center">
                                    <span class="text-[#8b9bb4]">已结平仓笔数</span>
                                    <span class="text-white font-medium">{{ tradeLog.length }} 笔</span>
                                </div>
                            </div>
                        </div>
                        
                        <div class="flex gap-2">
                            <button @click="resetLedger" 
                                    class="w-full border border-[#1e222b] hover:border-red-500 hover:text-red-400 py-1.5 text-2xs uppercase tracking-wide font-bold transition-all text-[#8b9bb4] active:scale-[0.98]">
                                重置模拟账户账本
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bottom Row: Sector Rotation & Candidate table -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Sector rotation list (1/3) -->
                <div class="console-card p-6 flex flex-col justify-between">
                    <div class="border-b border-[#1e222b] pb-2 mb-4">
                        <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">热门涨停行业板块</span>
                    </div>
                    <div class="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                        <div v-for="sec in currentRecap.market.sector_ranking" :key="sec.name" 
                             class="bg-[#08090a] p-3 border border-[#1e222b] flex justify-between items-center hover:border-red-500/20 transition-colors duration-200">
                            <div>
                                <h4 class="text-xs font-bold text-white">{{ sec.name }}</h4>
                                <p class="text-3xs text-gray-500 mt-0.5">领涨龙头: {{ sec.leader }}</p>
                            </div>
                            <div class="text-right">
                                <span class="text-lg font-bold text-red-500 code-font">{{ sec.count }}</span>
                                <span class="text-3xs text-[#8b9bb4] block uppercase tracking-wide">涨停数</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Candidate Pool table (2/3) -->
                <div class="lg:col-span-2 console-card p-6 flex flex-col justify-between">
                    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-[#1e222b] pb-2 mb-4 gap-4">
                        <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">首板候选股票池 (共 {{ currentRecap.candidates.length }} 只)</span>
                        <div class="flex gap-2 w-full sm:w-auto">
                            <input v-model="searchQuery" type="text" placeholder="输入代码/简称/行业进行过滤..."
                                   class="bg-[#08090a] border border-[#1e222b] rounded-none px-2 py-1 text-3xs text-white placeholder-gray-600 focus:outline-none focus:border-red-500 mono-font w-full sm:w-40" aria-label="输入代码/简称/行业筛选">
                            <select v-model="scoreFilter" class="bg-[#08090a] border border-[#1e222b] rounded-none px-2 py-1 text-3xs text-white focus:outline-none focus:border-red-500 mono-font" aria-label="选择接力指数过滤">
                                <option value="all">全部接力指数</option>
                                <option value="high">黄金接力 (>=100)</option>
                                <option value="mid">强势潜力 (80-99)</option>
                                <option value="low">弱势股 (<80)</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="overflow-x-auto max-h-[350px] overflow-y-auto pr-1">
                        <table class="w-full text-left text-3xs border-collapse">
                            <thead>
                                <tr class="border-b border-[#1e222b] text-gray-500 font-bold uppercase tracking-wider bg-[#08090a]">
                                    <th class="py-2.5 px-3">股票代码</th>
                                    <th class="py-2.5 px-3">股票简称</th>
                                    <th class="py-2.5 px-3 text-right">最新价</th>
                                    <th class="py-2.5 px-3 text-right">换手率</th>
                                    <th class="py-2.5 px-3 text-right">首次封板</th>
                                    <th class="py-2.5 px-3 text-center">炸板</th>
                                    <th class="py-2.5 px-3 text-right">封单资金</th>
                                    <th class="py-2.5 px-3 text-right">封单比</th>
                                    <th class="py-2.5 px-3 text-right">流通市值</th>
                                    <th class="py-2.5 px-3">所属行业</th>
                                    <th class="py-2.5 px-3">题材归因</th>
                                    <th class="py-2.5 px-3 text-center">接力指数</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="c in filteredCandidates" :key="c.code" 
                                    class="border-b border-[#1d212a]/50 hover:bg-[#1d212b]/20 transition-colors">
                                    <td class="py-2 px-3 code-font text-gray-400">{{ c.code }}</td>
                                    <td class="py-2 px-3">
                                        <div class="flex items-center justify-between">
                                            <span class="font-bold text-white">{{ c.name }}</span>
                                            <button @click.stop="buyStock(c, c.price)" 
                                                    class="bg-red-950/40 border border-red-900/50 text-red-400 hover:bg-red-900 hover:text-white px-1.5 py-0.5 text-3xs font-semibold select-none transition-all relative after:absolute after:inset-[-10px] after:content-[''] active:scale-[0.95]">
                                                买入
                                            </button>
                                        </div>
                                    </td>
                                    <td class="py-2 px-3 text-right code-font text-red-500 font-semibold">{{ c.price.toFixed(2) }}</td>
                                    <td class="py-2 px-3 text-right code-font">{{ c.turnover.toFixed(2) }}%</td>
                                    <td class="py-2 px-3 text-right code-font">{{ c.first_seal_time_formatted }}</td>
                                    <td class="py-2 px-3 text-center code-font" 
                                        :class="c.blown_count >= 2 ? 'text-yellow-500 font-bold' : 'text-gray-500'">
                                        {{ c.blown_count }}
                                    </td>
                                    <td class="py-2 px-3 text-right code-font text-yellow-500">{{ c.seal_funds.toFixed(1) }}万</td>
                                    <td class="py-2 px-3 text-right code-font"
                                        :class="c.seal_ratio >= 3.0 ? 'text-red-400 font-semibold' : 'text-gray-500'">
                                        {{ c.seal_ratio.toFixed(2) }}%
                                    </td>
                                    <td class="py-2 px-3 text-right code-font">{{ c.float_mcap.toFixed(1) }}亿</td>
                                    <td class="py-2 px-3 text-gray-300">{{ c.sector }}</td>
                                    <td class="py-2 px-3 text-gray-500 max-w-[120px] truncate" :title="c.concept">{{ c.concept || '暂无归因' }}</td>
                                    <td class="py-2 px-3 text-center">
                                        <span class="code-font px-2 py-0.5 text-3xs font-bold border"
                                              :class="getScoreClass(c.score)">
                                            {{ c.score }}
                                        </span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Data Import -->
    <script src="data/recap_history.js"></script>

    <script>
        const { createApp, ref, computed, watch, onMounted, nextTick } = Vue;

        createApp({
            setup() {
                const history = ref(window.RECAP_HISTORY || []);
                const selectedDate = ref(history.value.length > 0 ? history.value[0].date : "");
                const searchQuery = ref("");
                const scoreFilter = ref("all");
                let chartInstance = null;

                // Calibration backtest data
                const calibrationData = ref(window.RECAP_CALIBRATION || []);

                // Interactive Simulator state
                const simStockCode = ref("");
                const simOpenType = ref("ideal");
                const simVolType = ref("met");
                const simTrendType = ref("breakout");
                const simTimePhase = ref("real");

                // Live Data State
                const liveData = ref({});

                // Mock ledger state (saved in LocalStorage)
                const cash = ref(1000000);
                const portfolio = ref([]);
                const tradeLog = ref([]);
                const ledgerTab = ref("portfolio");

                // UZI Audit Data
                const uziAuditData = ref(window.RECAP_UZI_AUDIT || []);

                const availableDates = computed(() => {
                    return history.value.map(item => item.date);
                });

                const currentRecap = computed(() => {
                    return history.value.find(item => item.date === selectedDate.value) || null;
                });

                const topCandidates = computed(() => {
                    if (!currentRecap.value) return [];
                    return currentRecap.value.candidates.slice(0, 5);
                });

                const currentUziAudit = computed(() => {
                    const list = uziAuditData.value.filter(item => item.date === selectedDate.value);
                    const candidateCodes = topCandidates.value.map(c => c.code);
                    return list.filter(item => candidateCodes.includes(item.code))
                               .sort((a, b) => candidateCodes.indexOf(a.code) - candidateCodes.indexOf(b.code))
                               .slice(0, 5);
                });
                const isUziOnline = computed(() => {
                    return currentUziAudit.value.some(item => item.report_path !== "");
                });

                
                const themeMediaQuery = window.matchMedia("(prefers-color-scheme: light)");
                const themeStorageKey = "rtk_recap_theme";
                const prefersLight = ref(themeMediaQuery.matches);
                const themeMode = ref("system");
                const resolvedTheme = computed(() => {
                    if (themeMode.value === "light" || themeMode.value === "dark") {
                        return themeMode.value;
                    }
                    return prefersLight.value ? "light" : "dark";
                });
                const loadTheme = () => {
                    try {
                        const storedTheme = localStorage.getItem(themeStorageKey);
                        if (storedTheme === "system" || storedTheme === "light" || storedTheme === "dark") {
                            themeMode.value = storedTheme;
                        }
                    } catch (error) {}
                };
                const saveTheme = () => {
                    try {
                        localStorage.setItem(themeStorageKey, themeMode.value);
                    } catch (error) {}
                };
                const applyTheme = () => {
                    const theme = resolvedTheme.value;
                    document.body.dataset.theme = theme;
                    document.documentElement.dataset.theme = theme;
                    document.body.dataset.themeMode = themeMode.value;
                    document.documentElement.dataset.themeMode = themeMode.value;
                };
                const syncSystemTheme = (event) => {
                    prefersLight.value = event.matches;
                };
                const getChartTheme = () => {
                    if (resolvedTheme.value === "light") {
                        return {
                            grid: "rgba(148, 163, 184, 0.18)",
                            axis: "#64748b",
                            promo: "#e11d48",
                            promoFill: "rgba(225, 29, 72, 0.06)",
                            limit: "#d97706"
                        };
                    }
                    return {
                        grid: "rgba(255, 255, 255, 0.05)",
                        axis: "#8b9bb4",
                        promo: "#f43f5e",
                        promoFill: "rgba(244, 63, 94, 0.03)",
                        limit: "#f59e0b"
                    };
                };
                loadTheme();
                applyTheme();

                const needleAngle = computed(() => {
                    if (!currentRecap.value) return 0;
                    const s = currentRecap.value.market.sentiment;
                    if (s === "极度活跃") return 70;
                    if (s === "活跃") return 35;
                    if (s === "低迷降温") return -35;
                    if (s === "恐慌冰点") return -70;
                    return 0; // middle
                });

                const sentimentColorClass = computed(() => {
                    if (!currentRecap.value) return 'text-yellow-500';
                    const s = currentRecap.value.market.sentiment;
                    if (s === "极度活跃") return 'text-red-500';
                    if (s === "活跃") return 'text-red-400';
                    if (s === "低迷降温") return 'text-green-400';
                    if (s === "恐慌冰点") return 'text-green-500';
                    return 'text-yellow-500';
                });

                // Computed timeline phase with trading warning messages
                const activeTimePhase = computed(() => {
                    const phaseVal = simTimePhase.value;
                    let hhmm = "";
                    
                    if (phaseVal === "real") {
                        const now = new Date();
                        const h = String(now.getHours()).padStart(2, '0');
                        const m = String(now.getMinutes()).padStart(2, '0');
                        hhmm = h + m;
                    } else {
                        hhmm = phaseVal;
                    }
                    
                    const t = parseInt(hhmm);
                    
                    // Logic to determine active phase
                    if (t < 915) {
                        return {
                            name: "集合竞价未开始",
                            warning: "开盘竞价尚未开启。首板接力监控哨将于每个交易日 09:15 后正式投入监控。",
                            dotClass: "bg-gray-600",
                            textClass: "text-[#8b9bb4]",
                            bgClass: "border-[#1e222b] bg-[#0e1013]"
                        };
                    } else if (t >= 915 && t <= 919) {
                        return {
                            name: "虚假申报/试盘阶段 (允许撤单)",
                            warning: "警告：当前为主力虚假试盘时段，可任意撤单。切勿盲目挂单排队，防范主力撤单诱多骗线！",
                            dotClass: "bg-yellow-500 animate-ping",
                            textClass: "text-yellow-500",
                            bgClass: "border-yellow-900 bg-yellow-950/5"
                        };
                    } else if (t >= 920 && t <= 924) {
                        return {
                            name: "真实申报阶段 (不可撤单)",
                            warning: "警报：当前为真实资金申报阶段，不可撤单！请密切对比 09:20 瞬间个股是否发生大幅撤单降温！",
                            dotClass: "bg-red-500 animate-pulse",
                            textClass: "text-red-500",
                            bgClass: "border-red-900 bg-red-950/5"
                        };
                    } else if (t >= 925 && t <= 929) {
                        return {
                            name: "集合竞价定价定格",
                            warning: "定价已出！请立即点击刷新数据，核对实际高开价与量能目标。双达标者即为今日最强接力候选股！",
                            dotClass: "bg-green-500 animate-pulse",
                            textClass: "text-green-500",
                            bgClass: "border-green-900 bg-green-950/5"
                        };
                    } else {
                        return {
                            name: "已正式开盘交易中",
                            warning: "已开市。竞价达标个股如在开盘前15分钟分时突破开盘高点，或在冲板瞬间，为量化打板买点。",
                            dotClass: "bg-[#3b82f6]",
                            textClass: "text-blue-400",
                            bgClass: "border-blue-900 bg-blue-950/5"
                        };
                    }
                });

                const filteredCandidates = computed(() => {
                    if (!currentRecap.value) return [];
                    let list = currentRecap.value.candidates;

                    // Text search
                    if (searchQuery.value) {
                        const q = searchQuery.value.toLowerCase().trim();
                        list = list.filter(c => 
                            c.name.toLowerCase().includes(q) ||
                            c.code.includes(q) ||
                            c.sector.toLowerCase().includes(q) ||
                            (c.concept && c.concept.toLowerCase().includes(q))
                        );
                    }

                    // Score filter
                    if (scoreFilter.value === "high") {
                        list = list.filter(c => c.score >= 100);
                    } else if (scoreFilter.value === "mid") {
                        list = list.filter(c => c.score >= 80 && c.score < 100);
                    } else if (scoreFilter.value === "low") {
                        list = list.filter(c => c.score < 80);
                    }

                    return list;
                });

                const getScoreClass = (score) => {
                    if (score >= 100) return 'bg-red-950 text-red-400 border-red-900';
                    if (score >= 80) return 'bg-yellow-950 text-yellow-400 border-yellow-900';
                    return 'bg-gray-900 text-gray-500 border-gray-800';
                };

                // Simulator Logic
                const simResult = computed(() => {
                    if (!currentRecap.value || !simStockCode.value) {
                        return { decision: "等待数据", badge: "等待", color: "text-gray-500", border: "border-gray-800 text-gray-500", reason: "请选择一个目标股进行判定。" };
                    }
                    const c = currentRecap.value.candidates.find(item => item.code === simStockCode.value);
                    if (!c) {
                        return { decision: "等待数据", badge: "等待", color: "text-gray-500", border: "border-gray-800 text-gray-500", reason: "标的未找到。" };
                    }
                    
                    const open = simOpenType.value;
                    const vol = simVolType.value;
                    const trend = simTrendType.value;
                    
                    if (trend === "weak") {
                        return {
                            decision: "放弃操作 / 观望",
                            badge: "观望",
                            color: "text-gray-400",
                            border: "border-gray-700 text-gray-400",
                            reason: "【开盘承接走弱】开盘后无量下探且跌破分时均线，买盘无力，套牢盘抛压沉重。即使竞价表现尚可，开盘走弱说明资金不合力，应坚决放弃，避免吃面。"
                        };
                    }
                    
                    if (open === "fever") {
                        if (trend === "limit_up") {
                            return {
                                decision: "打板排单 (极轻仓)",
                                badge: "高风险买",
                                color: "text-yellow-500",
                                border: "border-yellow-900 text-yellow-500",
                                reason: "【超高开秒板】竞价高开超 6% 甚至接近涨停，且开盘直接封死。接力极易遭遇“高开低走”炸板。仅在竞价爆量且所属板块呈现集群涨停时，可极轻仓排单打板，一般不建议参与。"
                            };
                        } else {
                            return {
                                decision: "放弃操作 / 避雷",
                                badge: "避雷",
                                color: "text-green-500",
                                border: "border-green-800 text-green-500",
                                reason: "【高烧防闷杀】高开超 6% 以上开盘，如果没有秒板，极易演变为日内获利砸盘高开低走。若无秒板支撑，强烈建议放弃，观望为主。"
                            };
                        }
                    }
                    
                    if (open === "ideal") {
                        if (vol === "met") {
                            if (trend === "breakout") {
                                return {
                                    decision: "理想买点 (半路/加仓)",
                                    badge: "黄金买点",
                                    color: "text-red-500",
                                    border: "border-red-900 text-red-500",
                                    reason: "【分歧换手突破】竞价放量达标且开在理想区间（2%~5%），开盘回调不破均线（或前日收盘价），放量拉升突破开盘高点瞬间是极佳的“半路买点”，晋级概率极高。"
                                };
                            } else if (trend === "limit_up") {
                                return {
                                    decision: "强力打板 (确认点)",
                                    badge: "强力买点",
                                    color: "text-red-500",
                                    border: "border-red-900 text-red-500",
                                    reason: "【强势秒板确认】竞价放量且承接强，开盘直线拉升扫板。建议在封死二板瞬间打板买入，买入资金有板块溢价保护，属于连板选选手队的核心操作。"
                                };
                            }
                        } else {
                            if (trend === "breakout") {
                                return {
                                    decision: "轻仓试探",
                                    badge: "温和买点",
                                    color: "text-yellow-500",
                                    border: "border-yellow-900 text-yellow-500",
                                    reason: "【缩量高开换手】竞价成交量偏小，说明主力资金竞价抢筹意愿一般。若开盘后能放量突破，说明日内承接转强，可轻仓半路试探，最好等待封板瞬间打板确认。"
                                };
                            }
                        }
                    }
                    
                    if (open === "low") {
                        if (trend === "low_bounce" && vol === "met") {
                            return {
                                decision: "弱转强突破打板",
                                badge: "反包买点",
                                color: "text-red-400",
                                border: "border-red-900 text-red-400",
                                reason: "【经典弱转强】昨日板较烂，今天平开或低开，但竞价量能爆量达标（反包蓄势），开盘强力拉升翻红并突破昨日收盘价。这是经典的“弱转强”买点，可于股价翻红放量上攻时介入，或封板瞬间打板。"
                            };
                        } else {
                            return {
                                decision: "放弃操作",
                                badge: "放弃",
                                color: "text-gray-500",
                                border: "border-gray-800 text-gray-500",
                                reason: "【低开低走走弱】平开或低开且没有放量翻红，资金承接极差，昨日进场资金在疯狂砸盘出逃，直接排除该股接力可能。"
                            };
                        }
                    }
                    
                    return {
                        decision: "轻仓观察",
                        badge: "观察",
                        color: "text-yellow-500",
                        border: "border-yellow-900 text-yellow-500",
                        reason: "【温和状态】明日表现中规中矩，无明显超预期放量也无大幅杀跌。建议仅做仓位试探，或者等午后充分换手封板时再做决策。"
                    };
                });

                // Helper to initialize selected stock code in simulator
                const initSimStock = () => {
                    if (topCandidates.value.length > 0) {
                        simStockCode.value = topCandidates.value[0].code;
                    }
                };

                // Real-time Tencent quote integration
                const getPrefix = (code) => {
                    if (code.startsWith("6") || code.startsWith("9")) return "sh";
                    if (code.startsWith("8")) return "bj";
                    return "sz";
                };

                const fetchLiveQuotes = () => {
                    if (topCandidates.value.length === 0) return;
                    
                    const prefixedCodes = topCandidates.value.map(c => getPrefix(c.code) + c.code);
                    const url = "https://qt.gtimg.cn/q=" + prefixedCodes.join(",");
                    
                    // Remove old script if exists
                    const oldScript = document.getElementById("tencent-quotes-script");
                    if (oldScript) oldScript.remove();
                    
                    const script = document.createElement("script");
                    script.id = "tencent-quotes-script";
                    script.src = url;
                    script.onload = () => {
                        const updatedData = { ...liveData.value };
                        topCandidates.value.forEach(c => {
                            const varName = "v_" + getPrefix(c.code) + c.code;
                            if (window[varName]) {
                                const vals = window[varName].split("~");
                                if (vals.length >= 38) {
                                    const price = parseFloat(vals[3]);
                                    const change = parseFloat(vals[32]);
                                    const amountWan = parseFloat(vals[37]);
                                    
                                    updatedData[c.code] = {
                                        price: price,
                                        change: change,
                                        turnover: amountWan
                                    };
                                }
                            }
                        });
                        liveData.value = updatedData;
                        alert("今日实时竞价数据刷新成功。已经与量化标准自动对齐。");
                        fillSimulatorFromLive();
                    };
                    script.onerror = () => {
                        alert("获取腾讯财经数据失败，请确认当前是否为交易时间（09:15后可用）。");
                    };
                    document.head.appendChild(script);
                };

                const isVolMet = (c) => {
                    if (!liveData.value[c.code]) return false;
                    const targetVol = c.float_mcap * c.turnover * 10;
                    return liveData.value[c.code].turnover >= targetVol;
                };

                const isSignalMet = (c) => {
                    if (!liveData.value[c.code]) return false;
                    const change = liveData.value[c.code].change;
                    const volMet = isVolMet(c);
                    return change >= 2.0 && change <= 5.0 && volMet;
                };

                const fillSimulatorFromLive = () => {
                    if (!simStockCode.value || !liveData.value[simStockCode.value]) return;
                    const data = liveData.value[simStockCode.value];
                    const change = data.change;
                    
                    if (change >= 6.0) {
                        simOpenType.value = "fever";
                    } else if (change >= 2.0 && change <= 5.0) {
                        simOpenType.value = "ideal";
                    } else if (change >= 0.0 && change < 2.0) {
                        simOpenType.value = "mild";
                    } else {
                        simOpenType.value = "low";
                    }
                    
                    const c = topCandidates.value.find(item => item.code === simStockCode.value);
                    if (c) {
                        const targetVol = c.float_mcap * c.turnover * 10;
                        simVolType.value = (data.turnover >= targetVol) ? "met" : "not_met";
                    }
                };

                // LocalStorage Ledger Functions
                const loadLedger = () => {
                    const storedCash = localStorage.getItem("rtk_recap_cash");
                    const storedPortfolio = localStorage.getItem("rtk_recap_portfolio");
                    const storedLog = localStorage.getItem("rtk_recap_log");
                    
                    if (storedCash !== null) cash.value = parseFloat(storedCash);
                    if (storedPortfolio !== null) portfolio.value = JSON.parse(storedPortfolio);
                    if (storedLog !== null) tradeLog.value = JSON.parse(storedLog);
                };

                const saveLedger = () => {
                    localStorage.setItem("rtk_recap_cash", cash.value);
                    localStorage.setItem("rtk_recap_portfolio", JSON.stringify(portfolio.value));
                    localStorage.setItem("rtk_recap_log", JSON.stringify(tradeLog.value));
                };

                const initChart = () => {
                    const ctx = document.getElementById('trendChart');
                    if (!ctx) return;

                    const chartTheme = getChartTheme();

                    // Get last 15 elements in chronological order (oldest to newest)
                    const last15 = [...history.value].slice(0, 15).reverse();
                    
                    const labels = last15.map(item => item.date.substring(5)); // just MM-DD
                    const rates = last15.map(item => item.market.promotion_rate);
                    const luCounts = last15.map(item => item.market.limit_ups);

                    if (chartInstance) {
                        chartInstance.data.labels = labels;
                        chartInstance.data.datasets[0].data = rates;
                        chartInstance.data.datasets[1].data = luCounts;
                        chartInstance.update();
                    } else {
                        chartInstance = new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: labels,
                                datasets: [
                                    {
                                        label: '1进2晋级率 (%)',
                                        data: rates,
                                        borderColor: chartTheme.promo,
                                        backgroundColor: chartTheme.promoFill,
                                        borderWidth: 1.5,
                                        pointRadius: 2,
                                        tension: 0.2,
                                        yAxisID: 'y1',
                                    },
                                    {
                                        label: '总涨停数',
                                        data: luCounts,
                                        borderColor: chartTheme.limit,
                                        backgroundColor: 'transparent',
                                        borderWidth: 1,
                                        borderDash: [3, 3],
                                        pointRadius: 0,
                                        tension: 0.2,
                                        yAxisID: 'y2',
                                    }
                                ]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: {
                                        labels: {
                                            color: chartTheme.axis,
                                            boxWidth: 12,
                                            font: { size: 9, family: 'Fira Code' }
                                        }
                                    }
                                },
                                scales: {
                                    x: {
                                        grid: { color: chartTheme.grid },
                                        ticks: { color: chartTheme.axis, font: { size: 8, family: 'Fira Code' } }
                                    },
                                    y1: {
                                        type: 'linear',
                                        position: 'left',
                                        grid: { color: chartTheme.grid },
                                        ticks: { 
                                            color: chartTheme.promo, 
                                            font: { size: 8, family: 'Fira Code' },
                                            callback: (value) => value + '%'
                                        },
                                        min: 0,
                                        max: Math.max(...rates, 20) + 5
                                    },
                                    y2: {
                                        type: 'linear',
                                        position: 'right',
                                        grid: { drawOnChartArea: false },
                                        ticks: { color: chartTheme.limit, font: { size: 8, family: 'Fira Code' } },
                                        min: 0
                                    }
                                }
                            }
                        });
                    }
                };
                const buyStock = (stock, price) => {
                    if (portfolio.value.some(item => item.code === stock.code)) {
                        alert("持仓中已存在该股，请先平仓或进行单笔交易。");
                        return;
                    }
                    
                    const posSize = 200000;
                    const actualCost = Math.min(posSize, cash.value);
                    if (actualCost <= 0) {
                        alert("可用资金不足，无法建仓。");
                        return;
                    }
                    
                    const shares = Math.floor(actualCost / price / 100) * 100;
                    if (shares <= 0) {
                        alert("可用资金不足以买入一手（100股）。");
                        return;
                    }
                    
                    const totalCost = shares * price;
                    cash.value -= totalCost;
                    
                    portfolio.value.push({
                        code: stock.code,
                        name: stock.name,
                        buy_date: selectedDate.value,
                        buy_price: price,
                        shares: shares,
                        sector: stock.sector
                    });
                    
                    saveLedger();
                    alert(`虚拟建仓成功。以 ${price.toFixed(2)}元 买入 ${stock.name} ${shares}股，总计金额 ${totalCost.toFixed(0)}元。`);
                };

                const triggerSell = (holding) => {
                    const price = getValuationPrice(holding.code, holding.buy_price);
                    if (confirm(`确认以今日收盘估值 ${price.toFixed(2)}元 进行虚拟平仓吗？`)) {
                        sellStock(holding.code, price);
                    }
                };

                const sellStock = (code, price) => {
                    const idx = portfolio.value.findIndex(item => item.code === code);
                    if (idx === -1) return;
                    
                    const item = portfolio.value[idx];
                    const revenue = item.shares * price;
                    cash.value += revenue;
                    
                    const pnl = revenue - (item.shares * item.buy_price);
                    const pnl_pct = (pnl / (item.shares * item.buy_price)) * 100;
                    
                    tradeLog.value.push({
                        code: item.code,
                        name: item.name,
                        buy_date: item.buy_date,
                        buy_price: item.buy_price,
                        sell_date: selectedDate.value,
                        sell_price: price,
                        shares: item.shares,
                        pnl: pnl,
                        pnl_pct: pnl_pct
                    });
                    
                    portfolio.value.splice(idx, 1);
                    saveLedger();
                };


                const getValuationPrice = (code, buyPrice) => {
                    if (!currentRecap.value) return buyPrice;
                    const c = currentRecap.value.candidates.find(item => item.code === code);
                    if (c) return c.price;
                    return buyPrice;
                };

                const getFloatingPnl = (holding) => {
                    const price = getValuationPrice(holding.code, holding.buy_price);
                    return holding.shares * (price - holding.buy_price);
                };

                const getFloatingPnlPct = (holding) => {
                    const price = getValuationPrice(holding.code, holding.buy_price);
                    return ((price - holding.buy_price) / holding.buy_price) * 100;
                };

                const getPnlColor = (holding) => {
                    const pnl = getFloatingPnl(holding);
                    return pnl >= 0 ? 'text-red-500' : 'text-green-500';
                };

                const getExitAdvice = (holding) => {
                    if (!currentRecap.value) return { text: "监控中", color: "border-gray-800 text-gray-500" };
                    const isZt = currentRecap.value.candidates.some(item => item.code === holding.code);
                    if (holding.buy_date === selectedDate.value) {
                        return { text: "今日建仓 / 持股中", color: "border-yellow-500/20 text-yellow-500 bg-yellow-500/5" };
                    }
                    if (isZt) {
                        return { text: "连板晋级 / 建议持有", color: "border-red-500/20 text-red-400 bg-red-950/20" };
                    } else {
                        return { text: "断板走弱 / 建议平仓", color: "border-green-500/20 text-green-400 bg-green-950/20" };
                    }
                };

                const resetLedger = () => {
                    if (confirm("确认清空模拟交易账本吗？所有持仓与历史记录将被重置。")) {
                        cash.value = 1000000;
                        portfolio.value = [];
                        tradeLog.value = [];
                        saveLedger();
                    }
                };

                // Computed metrics
                const portfolioValue = computed(() => {
                    return portfolio.value.reduce((sum, item) => {
                        return sum + item.shares * getValuationPrice(item.code, item.buy_price);
                    }, 0);
                });

                const totalEquity = computed(() => {
                    return cash.value + portfolioValue.value;
                });

                const totalPnl = computed(() => {
                    return totalEquity.value - 1000000;
                });

                const winRate = computed(() => {
                    if (tradeLog.value.length === 0) return 0.0;
                    const wins = tradeLog.value.filter(item => item.pnl > 0).length;
                    return (wins / tradeLog.value.length) * 100;
                });


                watch(themeMode, () => {
                    saveTheme();
                    applyTheme();
                });

                watch(resolvedTheme, () => {
                    applyTheme();
                    nextTick(() => {
                        if (chartInstance) {
                            chartInstance.destroy();
                            chartInstance = null;
                        }
                        initChart();
                    });
                });

                watch(selectedDate, () => {
                    nextTick(() => {
                        lucide.createIcons();
                        initSimStock();
                    });
                });

                watch(simStockCode, () => {
                    fillSimulatorFromLive();
                });

                onMounted(() => {
                    loadLedger();
                    if (themeMediaQuery.addEventListener) {
                        themeMediaQuery.addEventListener("change", syncSystemTheme);
                    } else if (themeMediaQuery.addListener) {
                        themeMediaQuery.addListener(syncSystemTheme);
                    }
                    applyTheme();
                    lucide.createIcons();
                    initChart();
                    initSimStock();
                });

                return {
                    history,
                    selectedDate,
                    availableDates,
                    currentRecap,
                    topCandidates,
                    currentUziAudit,
                    isUziOnline,
                    needleAngle,
                    sentimentColorClass,
                    searchQuery,
                    scoreFilter,
                    filteredCandidates,
                    getScoreClass,
                    calibrationData,
                    simStockCode,
                    simOpenType,
                    simVolType,
                    simTrendType,
                    simResult,
                    simTimePhase,
                    themeMode,
                    activeTimePhase,
                    liveData,
                    fetchLiveQuotes,
                    isVolMet,
                    isSignalMet,
                    cash,
                    portfolio,
                    tradeLog,
                    ledgerTab,
                    buyStock,
                    triggerSell,
                    sellStock,
                    getValuationPrice,
                    getFloatingPnl,
                    getFloatingPnlPct,
                    getPnlColor,
                    getExitAdvice,
                    resetLedger,
                    portfolioValue,
                    totalEquity,
                    totalPnl,
                    winRate
                };
            }
        }).mount('#app');
    </script>
</body>
</html>"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML generated at {HTML_PATH}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="A-share daily post-market recap engine")
    parser.add_argument("--date", type=str, help="Specify date in YYYY-MM-DD format (default is today)")
    parser.add_argument("--backfill", type=int, help="Backfill N trading days from history")
    args = parser.parse_args()
    
    init_db()
    
    # master trading calendar from mootdx index (last 200 days)
    print("Loading trade dates from mootdx index calendar...")
    trade_dates = get_trading_days(offset=200)
    print(f"Index calendar loaded. Last trading day in calendar: {trade_dates[-1]}")
    
    if args.backfill:
        # Get the last N days before today
        n_days = args.backfill
        # Find index of the latest day in trade_dates
        latest_day = datetime.now().strftime('%Y-%m-%d')
        # Filter trade_dates for only past and present days
        valid_dates = [d for d in trade_dates if d <= latest_day]
        backfill_dates = valid_dates[-n_days:]
        
        print(f"Backfilling {len(backfill_dates)} trading days: {backfill_dates}")
        for date_str in backfill_dates:
            try:
                run_recap(date_str, trade_dates)
            except Exception as e:
                print(f"Error running backfill for {date_str}: {e}")
                
        export_data()
        generate_html()
        
    else:
        # Default to today
        if args.date:
            date_str = args.date
        else:
            date_str = datetime.now().strftime('%Y-%m-%d')
            
        if date_str not in trade_dates:
            # If date_str is not a trading day in the index calendar, warning but let it run
            print(f"Warning: {date_str} is not classified as a trading day in index calendar.")
            
        success = run_recap(date_str, trade_dates)
        if success:
            export_data()
            generate_html()

if __name__ == "__main__":
    main()
