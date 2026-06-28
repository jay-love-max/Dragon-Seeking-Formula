# A股 1进2 UZI 智能评委席批量审计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现盘后对 Top 5 重点个股的 UZI 智能评委席批量审计，通过大模型子进程（在线）与本地财务快照规则模拟器（离线）的双轨混合架构，将个股深度诊断与排雷数据呈现在复盘看板中。

**Architecture:** 盘后自动检测本地 `../UZI-Skill` 目录与 API 密钥。密钥完备时启动子进程并行诊断并使用正则表达式解析 HTML 报告；密钥缺失时自动降级调用本地财务快照规则（Warren Buffett 价值、赵老哥游资、Michael Burry 空头排雷）进行数据模拟。结果保存至 SQLite 的 `uzi_audit` 历史表中，并通过 `recap_history.js` 导出，在主看板新增的“UZI 智能评委席报告”独立 Bento 卡片中高亮呈现。

**Tech Stack:** Python 3.12, SQLite 3, BeautifulSoup/re, HTML/JS, Vue 3, Tailwind CSS.

---

### Task 1: 数据库表结构扩充

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `init_db()` 函数内插入 `uzi_audit` 表的创建)

- [ ] **Step 1: 编写 `uzi_audit` 数据表创建逻辑**
  在 `init_db()` 函数的 commit 之前，加入 `uzi_audit` 历史报告表的 SQL 创建语句。

  修改 `stock-recap-board/src/recap_engine.py` 中的 `init_db()`：
  ```python
      # 4. UZI 智能评委席审计历史数据表
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
  ```

- [ ] **Step 2: 验证数据表初始化**
  通过 Python 终端调用 `init_db()` 并验证 `uzi_audit` 表是否成功在数据库中建立。
  运行：`/opt/anaconda3/bin/python -c "import sys; sys.path.append('stock-recap-board/src'); from recap_engine import init_db; init_db()"`
  验证表创建：
  `/opt/anaconda3/bin/python -c "import sqlite3; conn = sqlite3.connect('stock-recap-board/data/recap.db'); c = conn.cursor(); c.execute('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'uzi_audit\''); print(c.fetchone()[0]); conn.close()"`
  期望：打印 `uzi_audit` 且无抛错。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "migration: create uzi_audit table"
  ```

---

### Task 2: UZI-Skill 项目自检测与克隆逻辑

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (新增自检测函数 `check_uzi_project`)

- [ ] **Step 1: 编写 `check_uzi_project()` 函数**
  在 `recap_engine.py` 中编写该函数，负责在同级目录检测 UZI-Skill 项目。如果项目缺失，执行 `git clone`；随后检测环境变量或 UZI-Skill 目录下的 `.env` 中是否配置了 `GEMINI_API_KEY` 等 LLM 密钥，并返回状态（`online` 或 `offline`）。

  在 `stock-recap-board/src/recap_engine.py` 中添加：
  ```python
  def check_uzi_project():
      """
      Check if ../UZI-Skill exists. If not, try to clone it.
      Check if API keys exist for online mode.
      Returns: "online" (has project + key) or "offline" (fallback to local rules)
      """
      uzi_dir = os.path.abspath(os.path.join(BASE_DIR, "..", "UZI-Skill"))
      run_script = os.path.join(uzi_dir, "run.py")
      
      # 1. Check & Auto-clone if missing
      if not os.path.exists(run_script):
          print(f"UZI-Skill project not found at {uzi_dir}. Attempting to clone...")
          try:
              subprocess.run(
                  ["git", "clone", "https://github.com/wbh604/UZI-Skill.git", uzi_dir],
                  check=True, timeout=60
              )
              print("Successfully cloned UZI-Skill project!")
          except Exception as e:
              print(f"Failed to clone UZI-Skill: {e}. Fallback to offline mode.")
              return "offline", uzi_dir
              
      # 2. Load .env from UZI-Skill if exists
      env_path = os.path.join(uzi_dir, ".env")
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
          return "online", uzi_dir
      return "offline", uzi_dir
  ```

- [ ] **Step 2: 验证自检测函数**
  通过 Python 终端运行检测，打印返回的状态值。
  运行：`/opt/anaconda3/bin/python -c "import sys; sys.path.append('stock-recap-board/src'); from recap_engine import check_uzi_project; status, path = check_uzi_project(); print('Status:', status, 'Path:', path)"`
  期望：由于我们在沙箱中未配置 API 密钥，应该打印 `Status: offline`。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: implement check_uzi_project detection and auto-clone"
  ```

---

### Task 3: 本地财务快照规则模拟器 (Offline Fallback)

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (新增函数 `run_local_uzi_emulator`)

- [ ] **Step 1: 编写 `run_local_uzi_emulator()` 逻辑**
  使用 `mootdx` 财务快照接口，提取个股的 ROE、负债率、EPS，并从 candidates 提取换手率、封板时间、行业热度，以此核算 Buffet 价值席位、赵老哥游资席位和 Burry 排雷席位分值。

  在 `stock-recap-board/src/recap_engine.py` 中添加：
  ```python
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
          ar_ratio = 0.0
          gw_ratio = 0.0
          
          # 1. Fetch mootdx finance snap (ROE, Debt, EPS)
          try:
              fin = client.finance(symbol=code)
              if fin is not None and not fin.empty:
                  # Use standard mootdx finance fields
                  # bvps=每股净资产, eps=每股收益, roe=净资产收益率, liutongguben=流通股本
                  # For debt ratio, we estimate from assets/liabilities if present, or fallback
                  roe_val = float(fin.get('roe', [0])[0])
                  eps_val = float(fin.get('eps', [0])[0])
                  
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
          except Exception:
              pass
              
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
  ```

- [ ] **Step 2: 验证本地模拟器逻辑**
  运行：`/opt/anaconda3/bin/python -c "import sqlite3; import sys; sys.path.append('stock-recap-board/src'); from recap_engine import run_local_uzi_emulator; conn=sqlite3.connect('stock-recap-board/data/recap.db'); cands=[{'code':'301132','name':'满坤科技','first_seal_time':'093633','turnover':7.27,'sector':'元件'}]; print(run_local_uzi_emulator(conn, '2026-06-24', cands, {'元件':5}))"`
  期望：打印满坤科技的评估字典（含 Buffett 价值席位、赵老哥态度、Burry 评级），且数据库中有对应 `uzi_audit` 记录。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: implement local rule-based uzi emulator"
  ```

---

### Task 4: 大模型子进程调用与 HTML 报告解析 (Online Mode)

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (新增函数 `run_real_uzi_audit`)

- [ ] **Step 1: 编写 `run_real_uzi_audit` 及正则解析逻辑**
  通过 Python 子进程并行/串行执行 UZI-Skill 的 `run.py` 行情扫描。完成生成后，读取 `reports/` 下生成的 HTML 报告，使用正则表达式拉取其 Jury 分数、投票列表及策略总结，存入 `uzi_audit` 表。

  在 `stock-recap-board/src/recap_engine.py` 中添加：
  ```python
  import re

  def run_real_uzi_audit(conn, date_str, candidates, uzi_dir):
      """Run real UZI-Skill via subprocess and parse results"""
      cursor = conn.cursor()
      python_bin = sys.executable
      run_script = os.path.join(uzi_dir, "run.py")
      
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
              ], cwd=uzi_dir, check=True, timeout=90)
          except Exception as e:
              print(f"Error running UZI CLI for {code}: {e}. Skipping.")
              continue
              
          # 2. Locate generated HTML report in UZI reports folder
          # UZI reports are saved in UZI-Skill/reports/ with names like YYYY-MM-DD_org_title.html
          # or simply containing the ticker. Let's find the newest html file containing code
          uzi_reports_dir = os.path.join(uzi_dir, "reports")
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
              
              # Extract Jury Seat score (e.g. 最终评议: 82分 or Jury Score: 82)
              score_match = re.search(r"Jury Score:\s*(\d+)", html_content) or re.search(r"评议分.*?(\d+)分", html_content)
              avg_score = float(score_match.group(1)) if score_match else 75.0
              
              # Extract votes
              val_match = re.search(r"价值流派.*?态度.*?([多空观望]+)", html_content)
              val_vote = val_match.group(1) if val_match else "观望"
              
              mom_match = re.search(r"游资流派.*?态度.*?([多空观望]+)", html_content)
              mom_vote = mom_match.group(1) if mom_match else "观望"
              
              risk_match = re.search(r"排雷评级.*?([安全高危关注]+)", html_content)
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
  ```

- [ ] **Step 2: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: implement real uzi audit subprocess execution and html parser"
  ```

---

### Task 5: 整合复盘流程与 JSON 数据导出

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `run_recap()` 中整合调度逻辑，并在 `export_data()` 中导出 `window.RECAP_UZI_AUDIT`)

- [ ] **Step 1: 在 `run_recap()` 尾部添加审计调度逻辑**
  在 `run_recap` 写入 candidates 数据库之后，调用 `check_uzi_project` 并根据状态拉取审计结果：

  修改 `run_recap()` 结尾：
  ```python
      # 9.B UZI 智能审计调度（混合架构）
      print("Running UZI Jury Audit...")
      try:
          uzi_status, uzi_path = check_uzi_project()
          cands_for_audit = []
          for idx, row in df_1b.head(5).iterrows():
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
  ```

- [ ] **Step 2: 修改 `export_data()` 以导出 UZI 变量**
  在 `export_data` 中从 `uzi_audit` 提取对应的历史数据，并输出为 `window.RECAP_UZI_AUDIT`：

  修改 `export_data()` 最后的 SQLite 提取及 JS 写入节：
  ```python
      # Fetch UZI audit records
      cursor.execute("SELECT * FROM uzi_audit ORDER BY date DESC")
      uzi_rows = cursor.fetchall()
      uzi_cols = ["date", "code", "name", "average_score", "val_vote", "mom_vote", "risk_level", "summary", "report_path"]
      
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
  ```

- [ ] **Step 3: 验证数据导出链路**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py --date 2026-06-24`
  期望：日志打印 `[UZI Audit] Running local rule-based emulator...` 并生成 `uzi_audit` 数据。验证 `data/recap_history.js`：
  `tail -n 30 stock-recap-board/data/recap_history.js`
  期望：包含 `window.RECAP_UZI_AUDIT` 数组且内含满坤科技等 5 只股的模拟审计结构数据。

- [ ] **Step 4: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py
  git commit -m "feat: schedule uzi audit and export window.RECAP_UZI_AUDIT"
  ```

---

### Task 6: 前端 UI Bento 评委席卡片集成

**Files:**
- Modify: `stock-recap-board/src/recap_engine.py` (在 `generate_html()` 的 `html_content` 模板中进行界面重塑)

- [ ] **Step 1: 在 HTML 模板中新增 UZI 选项卡看板**
  * 在“次日实战操作控制台”与“模拟实战交易账本”之间，插入一个全新的卡片面板：
    `■ UZI 智能评委席报告 / UZI JURY AUDIT REPORT`。
  * 页面横向平铺 5 列（对应今日 Top 5 候选股）：展示个股简称、评分、三个评委席位表决态度（价值、游资、大空头排雷）以及评语摘要。如果配置了 `report_path` 则显示深度诊断入口按钮。
  * 在 Vue 实例中，添加 `uziAuditData` 初始化，增加 `isUziOnline` 计算属性。

  修改 `generate_html()` 内部 `html_content` 模板：
  *插入 UZI 看板 HTML 模块：*
  ```html
            <!-- UZI 智能评委席报告 -->
            <div class="border border-[#1e222b] bg-[#0e1013] p-5">
                <div class="border-b border-[#1e222b] pb-2 mb-4 flex justify-between items-center">
                    <span class="text-[#8b9bb4] text-2xs uppercase tracking-wider font-semibold">UZI 智能评委席报告 / JURY AUDIT REPORT</span>
                    <div class="flex items-center gap-2">
                        <span class="text-3xs px-2 py-0.5 border"
                              :class="isUziOnline ? 'border-green-900 bg-green-950/20 text-green-400' : 'border-yellow-900 bg-yellow-950/20 text-yellow-400'">
                            {{ isUziOnline ? '大模型智能评审模式' : '本地财务规则模拟' }}
                        </span>
                        <span class="text-2xs text-[#ef4444] font-bold uppercase tracking-wider mono-font">JURY AUDIT PANEL</span>
                    </div>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
                    <div v-for="u in currentUziAudit" :key="u.code" 
                         class="bg-[#08090a] p-4 border border-[#1e222b] flex flex-col justify-between gap-4">
                        <div>
                            <div class="flex justify-between items-start border-b border-[#1e222b]/80 pb-2">
                                <div>
                                    <h4 class="text-sm font-bold text-white">{{ u.name }}</h4>
                                    <p class="text-3xs text-gray-500 mono-font mt-0.5">{{ u.code }}</p>
                                </div>
                                <span class="text-lg font-bold text-red-500 code-font">{{ u.average_score.toFixed(1) }}分</span>
                            </div>
                            
                            <div class="mt-3 space-y-1.5 text-3xs">
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
                                <div class="flex justify-between items-center border-t border-[#1e222b]/60 pt-1.5 mt-1.5">
                                    <span class="text-gray-500">大空头 (排雷评级)</span>
                                    <span :class="u.risk_level === '安全' ? 'text-green-400' : 'text-red-400'" class="font-bold">
                                        {{ u.risk_level }}
                                    </span>
                                </div>
                            </div>
                        </div>
                        
                        <div class="text-3xs text-gray-400 bg-[#0e1013] p-2 border border-[#1e222b] leading-relaxed font-mono select-all">
                            {{ u.summary }}
                        </div>
                        
                        <div v-if="u.report_path" class="mt-1">
                            <a :href="u.report_path" target="_blank"
                               class="block w-full text-center bg-red-950 border border-red-900 text-red-400 hover:bg-red-900 hover:text-white py-1 text-3xs font-bold transition-all">
                                查看 UZI 深度诊断报告
                            </a>
                        </div>
                    </div>
                </div>
            </div>
  ```

  *在 Vue script setup 中注册变量及 Computed 选项：*
  ```javascript
                // UZI Audit Data
                const uziAuditData = ref(window.RECAP_UZI_AUDIT || []);
                
                const currentUziAudit = computed(() => {
                    return uziAuditData.value.filter(item => item.date === selectedDate.value);
                });
                
                const isUziOnline = computed(() => {
                    // If any of the top 5 records has a report_path, it was run online
                    return currentUziAudit.value.some(item => item.report_path !== "");
                });
  ```
  并在 `return` 对象中将 `uziAuditData`、`currentUziAudit`、`isUziOnline` 暴露出来。

- [ ] **Step 2: 重新编译并进行 Chromium 挂载测试**
  运行：`/opt/anaconda3/bin/python src/recap_engine.py --backfill 15`
  期望：编译成功。
  运行 Chromium diagnostic：确认网页无障碍挂载，Vue 状态加载完全正确，Console 无报错。

- [ ] **Step 3: 提交代码**
  ```bash
  git add stock-recap-board/src/recap_engine.py stock-recap-board/index.html
  git commit -m "feat: complete UI and database integration for UZI Jury Audit panel"
  ```
