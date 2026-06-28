# A股 1进2 机器学习晋级预测模型实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 A股 1进2 首板股次日晋级率的机器学习预测，并在网页看板上以“双轨并行”方式与经验接力指数共同展示。

**Architecture:** 盘后动态读取 SQLite 数据库中历史数据并进行 Target Encoding 行业特征映射，构建包含个股筹码、行业热度及大盘情绪的多维特征矩阵。每次执行复盘时就地动态训练一个 Scikit-Learn 随机森林模型（ No Look-Ahead Bias，防数据泄露），预测并保存当前候选股的晋级概率，同步计算不同分值区间的历史晋级胜率。

**Tech Stack:** Python 3.12, SQLite 3, Scikit-Learn 1.7.2, Pandas, HTML/JS, Vue 3, Tailwind CSS.

---

### Task 1: 数据库结构平滑升级

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `init_db()` 函数内插入迁移逻辑)

- [ ] **Step 1: 编写数据库迁移及表创建逻辑**
  在 `init_db()` 函数中，在关闭连接前插入 candidates 表的列检测与 limit_ups_archive 表的创建逻辑。

  修改 `stock-recap-board/src/recap_engine.py` 中的 `init_db()`：
  ```python
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
              PRIMARY KEY (date, code)
          )
      """)
      
      # === V2.1 迁移与表结构升级 ===
      # 2.A 检查并补充 pred_prob 预测概率列
      cursor.pragma_table_info('candidates')
      cols = [col[1] for col in cursor.fetchall()]
      if "pred_prob" not in cols:
          print("[Migration] Adding pred_prob column to candidates table...")
          cursor.execute("ALTER TABLE candidates ADD COLUMN pred_prob REAL")
          
      # 3. 全量涨停股归档表，用于提取历史 Y 值（晋级率回测）
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS limit_ups_archive (
              date TEXT,
              code TEXT,
              name TEXT,
              consecutive_boards INTEGER,
              PRIMARY KEY (date, code)
          )
      """)
      
      conn.commit()
      conn.close()
  ```

- [ ] **Step 2: 验证数据库迁移正常运行**
  通过 Python 终端调用 `init_db()` 并验证数据库表结构升级。
  运行：`/opt/anaconda3/bin/python -c "import sys; sys.path.append('stock-recap-board/src'); from recap_engine import init_db; init_db()"`
  期望：控制台打印 `[Migration] Adding pred_prob column to candidates table...`（若是首次执行该命令）且无任何抛错退出。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "migration: add pred_prob column and limit_ups_archive table"
  ```

---

### Task 2: 每日全量涨停股盘后归档

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `run_recap()` 核心保存逻辑前添加归档保存)

- [ ] **Step 1: 在 `run_recap()` 中插入归档插入逻辑**
  在 `run_recap` 写入 `market_recap` 之前，将当天获取的 `df_zt`（全市场涨停池）全部存入 `limit_ups_archive` 中。

  修改 `stock-recap-board/src/recap_engine.py` 的 `run_recap` 保存节：
  ```python
      # 8.A 写入全量涨停归档（为回测晋级率提供 T+1 的 Y 值）
      print("Archiving all limit-ups for backtest...")
      cursor.execute("DELETE FROM limit_ups_archive WHERE date = ?", (date_str,))
      for idx, row in df_zt.iterrows():
          cursor.execute("""
              INSERT OR REPLACE INTO limit_ups_archive (date, code, name, consecutive_boards)
              VALUES (?, ?, ?, ?)
          """, (
              date_str,
              row["代码"],
              row["名称"],
              int(row["连板数"])
          ))
  ```

- [ ] **Step 2: 手动测试单日复盘归档**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py --date 2026-06-24` （在 `stock-recap-board` 目录下）
  验证数据库中已写入归档数据：
  `/opt/anaconda3/bin/python -c "import sqlite3; conn = sqlite3.connect('stock-recap-board/data/recap.db'); c = conn.cursor(); c.execute('SELECT count(*) FROM limit_ups_archive WHERE date=\'2026-06-24\''); print('Archive count:', c.fetchone()[0]); conn.close()"`
  期望：打印 `Archive count: 98` (或当天实际涨停数)。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: archive all limit ups in run_recap"
  ```

---

### Task 3: 机器学习特征工程与预处理逻辑

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `run_recap` 前定义预处理及特征提取函数)

- [ ] **Step 1: 编写时间转换为秒、及特征工程抽取逻辑**
  编写 `time_to_seconds` 函数，将 `首次封板时间`（HHMMSS）转换为距离 `09:25:00` 的累计秒数。
  编写 `get_training_features` 函数，安全提取日期 $T$ 之前的所有历史首板数据，构建训练特征 $X$（包含个股、行业 Target Encoding、大盘环境）及 $Y$（比对 T+1 是否晋级成功）。

  在 `stock-recap-board/src/recap_engine.py` 中添加：
  ```python
  def time_to_seconds(time_str):
      """Convert HHMMSS string to seconds from 09:25:00"""
      try:
          t = str(time_str).zfill(6)
          h, m, s = int(t[:2]), int(t[2:4]), int(t[4:])
          total_sec = h * 3600 + m * 60 + s
          # 09:25:00 in seconds is 9*3600 + 25*60 = 33900
          diff = total_sec - 33900
          return max(0, diff)
      except Exception:
          return 1800  # Default to 30 mins after open on error
          
  def get_training_features(conn, date_str):
      """
      Extract features and labels for dates < date_str.
      Returns: X_train, y_train, sector_means (dict for encoding)
      """
      cursor = conn.cursor()
      
      # 1. Load candidates (1-board) prior to date_str
      df_cands = pd.read_sql_query(
          "SELECT date, code, turnover, float_mcap, seal_ratio, first_seal_time, blown_count, sector FROM candidates WHERE date < ? AND consecutive_boards = 1",
          conn, params=(date_str,)
      )
      
      # 2. Load promoted list (2-board)
      df_promoted = pd.read_sql_query(
          "SELECT date, code FROM limit_ups_archive WHERE consecutive_boards = 2", conn
      )
      
      if df_cands.empty:
          return pd.DataFrame(), pd.Series(), {}
          
      # Get trading calendar to map date T to T+1 (next day)
      dates_sorted = sorted(df_cands["date"].unique())
      date_to_next = {dates_sorted[i]: dates_sorted[i+1] for i in range(len(dates_sorted) - 1)}
      
      # Store promoted as set for fast lookup: (date_of_2b, code)
      promoted_keys = set(zip(df_promoted["date"], df_promoted["code"]))
      
      # Generate Y labels
      y_list = []
      for _, row in df_cands.iterrows():
          curr_date = row["date"]
          next_date = date_to_next.get(curr_date)
          code = row["code"]
          if next_date and (next_date, code) in promoted_keys:
              y_list.append(1)
          else:
              y_list.append(0)
      df_cands["success"] = y_list
      
      # 3. Target Encode the Sectors
      # Calculate historical success rate per sector
      sector_means = df_cands.groupby("sector")["success"].mean().to_dict()
      global_mean = df_cands["success"].mean() if not df_cands.empty else 0.12
      
      df_cands["sector_target_enc"] = df_cands["sector"].map(sector_means).fillna(global_mean)
      
      # 4. Convert seal time to seconds
      df_cands["first_seal_time_seconds"] = df_cands["first_seal_time"].apply(time_to_seconds)
      
      # 5. Merge with market sentiment features
      df_market = pd.read_sql_query(
          "SELECT date, limit_ups, limit_downs, total_turnover, promotion_rate FROM market_recap", conn
      )
      df_train = pd.merge(df_cands, df_market, on="date", how="left")
      df_train = df_train.fillna(0.0)
      
      # Feature columns
      feature_cols = [
          "first_seal_time_seconds", "blown_count", "turnover", "float_mcap", "seal_ratio",
          "sector_target_enc", "limit_ups", "limit_downs", "total_turnover", "promotion_rate"
      ]
      
      X = df_train[feature_cols]
      y = df_train["success"]
      
      return X, y, {"means": sector_means, "global": global_mean}
  ```

- [ ] **Step 2: 验证特征提取逻辑无数据泄露**
  运行：`/opt/anaconda3/bin/python -c "import sqlite3; import sys; sys.path.append('stock-recap-board/src'); from recap_engine import get_training_features; conn=sqlite3.connect('stock-recap-board/data/recap.db'); X, y, sec = get_training_features(conn, '2026-06-24'); print('X shape:', X.shape, 'y sum:', y.sum()); conn.close()"`
  期望：打印特征矩阵的行列数及成功晋级样本总数，无任何空值或数据报错。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: implement ML feature engineering and target encoding"
  ```

---

### Task 4: 随机森林模型动态训练与概率预测

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `run_recap` 中整合模型训练、预测及数据库保存)

- [ ] **Step 1: 引入 sklearn 依赖并开发训练/预测流程**
  在 `recap_engine.py` 中引入 `RandomForestClassifier`，并在 `run_recap` 中获取特征矩阵、执行模型训练、输出特征权重排名，并计算当日候选股的 `pred_prob` 保存至数据库。

  修改 `stock-recap-board/src/recap_engine.py` 头部：
  ```python
  from sklearn.ensemble import RandomForestClassifier
  ```

  修改 `stock-recap-board/src/recap_engine.py` 的 `run_recap`（在计算指数得分的 `for idx, row in df_1b.iterrows():` 循环前插入训练逻辑）：
  ```python
      # === 集合竞价 & 1进2 随机森林模型动态训练与预测 ===
      print("Training RandomForest model on historical data...")
      conn_ml = sqlite3.connect(DB_PATH)
      X_train, y_train, sector_encoding = get_training_features(conn_ml, date_str)
      
      model = None
      global_mean = 0.12
      if not X_train.empty and len(X_train) >= 30:
          try:
              model = RandomForestClassifier(n_estimators=150, max_depth=6, min_samples_leaf=2, random_state=42)
              model.fit(X_train, y_train)
              print(f"[ML Model] Trained successfully on {len(X_train)} samples.")
              
              # 打印特征重要性
              importances = model.feature_importances_
              indices = np.argsort(importances)[::-1]
              print("[ML Model] Feature importances ranking:")
              for rank, ind in enumerate(indices[:5]):
                  print(f"  {rank+1}. {X_train.columns[ind]}: {importances[ind]*100:.1f}%")
          except Exception as e:
              print(f"[ML Model] Training failed: {e}")
              model = None
      else:
          print(f"[ML Model] Not enough training samples ({len(X_train)}/30 required). Fallback to empty predictions.")
          if not X_train.empty:
              global_mean = X_train["sector_target_enc"].mean()
              
      # Pre-calculate today's market sentiment indicators for prediction
      today_market_turnover = idx_recap.get("total_turnover", 0.0)
      today_market_promo = promotion_rate
  ```

  修改 `run_recap` 内部计算 `df_1b` 的循环，加入个股特征生成、模型预测概率并存储：
  ```python
      scores = []
      playbooks = []
      probs = []
      
      for idx, row in df_1b.iterrows():
          # ... [原有打分卡算分逻辑] ...
          score = max(0, min(150, score))
          scores.append(score)
          
          # 计算个股机器学习预测特征
          if model:
              # Get sector target encoding
              sec = row["所属行业"]
              sec_val = sector_encoding["means"].get(sec, sector_encoding["global"])
              sec_sec = time_to_seconds(row["首次封板时间"])
              float_mcap = float(row["流通市值"])
              seal_funds = float(row["封板资金"])
              seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0
              
              X_today = pd.DataFrame([{
                  "first_seal_time_seconds": sec_sec,
                  "blown_count": int(row["炸板次数"]),
                  "turnover": float(row["换手率"]),
                  "float_mcap": float_mcap / 1e9,
                  "seal_ratio": seal_ratio,
                  "sector_target_enc": sec_val,
                  "limit_ups": total_lu,
                  "limit_downs": limit_downs,
                  "total_turnover": today_market_turnover,
                  "promotion_rate": today_market_promo
              }])
              
              try:
                  prob = float(model.predict_proba(X_today)[0][1])
                  probs.append(prob)
              except Exception:
                  probs.append(None)
          else:
              probs.append(None)
              
      df_1b["接力指数"] = scores
      df_1b["预测概率"] = probs
  ```

  修改 `run_recap` 写入 `candidates` 数据库的字段，存入 `pred_prob`：
  ```python
      # Insert candidates (delete old candidates for this date first)
      cursor.execute("DELETE FROM candidates WHERE date = ?", (date_str,))
      
      for idx, row in df_1b.iterrows():
          float_mcap = float(row["流通市值"])
          seal_funds = float(row["封板资金"])
          seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0
          
          # Handle None values for DB insertion
          pred_prob_val = float(row["预测概率"]) if row["预测概率"] is not None else None
          
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
              pred_prob_val
          ))
  ```

- [ ] **Step 2: 手动测试动态模型预测输出**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py --date 2026-06-24`
  期望：终端成功打印 `[ML Model] Trained successfully on 1220 samples.`，显示 `Feature importances ranking:`。验证数据库中已存入 `pred_prob`：
  `/opt/anaconda3/bin/python -c "import sqlite3; conn = sqlite3.connect('stock-recap-board/data/recap.db'); c = conn.cursor(); c.execute('SELECT name, score, pred_prob FROM candidates WHERE date=\'2026-06-24\' ORDER BY score DESC LIMIT 3'); print(c.fetchall()); conn.close()"`
  期望：输出前 3 个标的，其 `pred_prob` 字段为合理的浮点数概率值（例如 `0.2312`）。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: implement random forest classifier training and prediction pipeline"
  ```

---

### Task 5: 历史得分胜率回测与 JSON/JS 导出

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (编写 `calculate_calibration_stats()`，并在 `export_data()` 中调用它，导出 `window.RECAP_CALIBRATION`)

- [ ] **Step 1: 编写 `calculate_calibration_stats` 统计方法**
  在 `export_data()` 前编写该函数，读取 SQLite 数据库的历史 candidates 及 limit_ups_archive 成功晋级归档，核算 4 个接力得分桶的真实晋级成功概率。

  修改 `stock-recap-board/src/recap_engine.py`：
  ```python
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
  ```

- [ ] **Step 2: 修改 `export_data()` 以导出 JS 变量**
  读取 `pred_prob` 字段，并在保存 JS 数据文件时，增加导出 `window.RECAP_CALIBRATION` 变量。

  修改 `export_data()` 中获取 candidate_cols 的 SQL 查询及 JS 写入节：
  ```python
          # Fetch candidates for this date
          date_str = recap_dict["date"]
          cursor.execute("SELECT * FROM candidates WHERE date = ? ORDER BY score DESC", (date_str,))
          candidate_rows = cursor.fetchall()
          
          candidate_cols = [
              "date", "code", "name", "price", "change_pct", "turnover", "float_mcap",
              "seal_funds", "seal_ratio", "first_seal_time", "blown_count", "consecutive_boards",
              "sector", "concept", "score", "playbook", "pred_prob"
          ]
  ```

  修改 `export_data` 最后的 JS 写入部分：
  ```python
      calibration_data = calculate_calibration_stats(conn)
      conn.close()
      
      # Write history_list and calibration_data as JS script variables
      js_content = (
          f"window.RECAP_HISTORY = {json.dumps(history_list, ensure_ascii=False, indent=2)};\n"
          f"window.RECAP_CALIBRATION = {json.dumps(calibration_data, ensure_ascii=False, indent=2)};"
      )
      with open(JS_PATH, "w", encoding="utf-8") as f:
          f.write(js_content)
  ```

- [ ] **Step 3: 验证 JS 导出的完整性**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py` (重构全量导出)
  验证 `recap_history.js` 是否包含 `window.RECAP_CALIBRATION` 和 `pred_prob` 数据：
  `tail -n 15 stock-recap-board/data/recap_history.js`
  期望：尾部成功导出 `window.RECAP_CALIBRATION = [...]` 的 JSON 数据且无语法破坏。

- [ ] **Step 4: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: export backtest calibration statistics to recap_history.js"
  ```

---

### Task 6: 前端双轨展示与 UI 集成

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `generate_html()` 的 `html_content` 模板中进行界面重塑)

- [ ] **Step 1: 在 HTML 模板中新增量化回测及晋级率 Badge/Column**
  * 在左侧 `市场短线情绪` 卡片底部，插入一个用于渲染 `量化胜率校验 / 历史晋级率回测` 的面板。
  * 在 Top 5 卡片头部，并在原有经验接力指数右侧，增加一个 `预估晋级率` 红色 Badge。
  * 在下方候选股票池表格中，新增一列 `预估晋级率`（位于“日内换手率”与“首次封板”之间，或“接力指数”之前）。
  * 在 Vue 实例中，添加 `calibrationData` 初始化，并在返回对象中暴露它们。

  修改 `generate_html()` 内部 `html_content` 模板：
  *在顶层 Sentiment Console 卡片内添加回测展示面板：*
  ```html
                    <!-- 量化胜率校验 / 历史晋级率回测 -->
                    <div class="border-t border-[#1e222b] pt-3 mt-3">
                        <span class="text-[#8b9bb4] text-3xs uppercase tracking-wider font-semibold block mb-2">量化胜率校验 / 历史晋级率回测</span>
                        <div class="space-y-1.5 text-3xs mono-font">
                            <div v-for="cal in calibrationData" :key="cal.score_range" class="flex justify-between items-center">
                                <span class="text-gray-500">{{ cal.bucket_name.split(' ')[0] }} ({{ cal.score_range }}分)</span>
                                <span class="font-bold" :class="cal.win_rate >= 15 ? 'text-red-500' : 'text-gray-400'">
                                    {{ cal.win_rate.toFixed(2) }}% <span class="text-gray-600 font-normal">({{ cal.promoted_count }}/{{ cal.total_count }})</span>
                                </span>
                            </div>
                        </div>
                    </div>
  ```

  *在前五强卡片的指数右侧增加晋级率 Badge：*
  ```html
                            <div class="flex justify-between items-start">
                                <div class="flex items-center gap-2">
                                    <span class="text-xs px-2 py-0.5 font-bold border" :class="idx === 0 ? 'bg-red-950 text-red-400 border-red-900' : 'bg-[#1b1c24] text-gray-400 border-[#24262b]'">
                                        NO.{{ idx + 1 }}
                                    </span>
                                    <span class="text-base font-bold text-white tracking-tight">{{ c.name }}</span>
                                    <span class="text-xs font-semibold text-gray-500 mono-font">{{ c.code }}</span>
                                </div>
                                <div class="flex gap-2">
                                    <span class="text-xs text-yellow-500 font-bold border border-yellow-500/20 px-2 py-0.5 bg-yellow-500/5 mono-font">
                                        接力指数: {{ c.score }}
                                    </span>
                                    <span v-if="c.pred_prob !== null && c.pred_prob !== undefined" class="text-xs text-red-400 font-bold border border-red-500/20 px-2 py-0.5 bg-red-500/5 mono-font">
                                        预估晋级率: {{ (c.pred_prob * 100).toFixed(1) }}%
                                    </span>
                                    <button @click.stop="buyStock(c, c.price)" 
                                            class="bg-red-950/40 border border-red-900/50 text-red-400 hover:bg-red-900 hover:text-white px-2 py-0.5 text-2xs font-semibold select-none transition-all">
                                        模拟买入
                                    </button>
                                </div>
                            </div>
  ```

  *在底部表格中新增预估晋级率列：*
  在 `<thead>` 行中增加：
  ```html
                                    <th class="py-2.5 px-3 text-right">预估晋级率</th>
  ```
  在 `<tbody>` 循环的 `接力指数` 列之前增加：
  ```html
                                    <td class="py-2 px-3 text-right code-font"
                                        :class="c.pred_prob && c.pred_prob >= 0.15 ? 'text-red-400 font-semibold' : 'text-gray-400'">
                                        {{ c.pred_prob !== null && c.pred_prob !== undefined ? (c.pred_prob * 100).toFixed(1) + '%' : 'N/A' }}
                                    </td>
  ```

  *在 Vue script 实例 setup 中注册变量：*
  ```javascript
                // Calibration backtest data
                const calibrationData = ref(window.RECAP_CALIBRATION || []);
  ```
  并在 `return` 对象中将 `calibrationData` 暴露出去。

- [ ] **Step 2: 重新编译生成网页看板**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py`
  期望：`index.html` 成功更新，并在控制台无报错输出。

- [ ] **Step 3: 运行自动化测试以确认 UI 无障碍及渲染表现**
  利用 Chromium 进行页面 console 日志诊断，确认 `index.html` 正常挂载。
  期望：控制台打印 `Vue app mounted successfully!` 且无报错。

- [ ] **Step 4: 提交代码并关闭临时文件**
  ```bash
  git add stock-recap-board/src/recap_engine.py stock-recap-board/index.html
  git commit -m "feat: complete UI integration for paper trading ledger and ML prediction"
  ```
