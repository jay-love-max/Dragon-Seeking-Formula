# 财务排雷指标补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐财务排雷字段与判定规则，让复盘引擎能稳定输出商誉、应收、负债率驱动的 `risk_level` 和可解释摘要。

**Architecture:** 适配层继续负责“把财务快照读全、读准”，复盘层负责“把财务数据转成风险判定和摘要”。新增一个纯函数式的排雷评估助手，专门把 `finance_dict + 股票简称` 归一成风险等级、风险标记和说明文本，避免规则散落在多个分支里。测试分成两层：适配层验证字段归一，复盘层验证风险规则与摘要文案。

**Tech Stack:** Python 3.11、`pandas`、现有 `akshare` / `mootdx` / `sqlite3`、`unittest`。

---

### Task 1: Normalize finance snapshot fields in the adapter

**Files:**
- Modify: `src/data_adapters/a_stock_adapter.py`
- Test: `tests/test_data_adapters.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_a_stock_adapter_finance_fields(self):
        import tempfile
        from pathlib import Path
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fin_dir = root / "financials"
            (fin_dir / "metrics").mkdir(parents=True, exist_ok=True)
            (fin_dir / "income").mkdir(parents=True, exist_ok=True)
            (fin_dir / "balance_sheet").mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "roe_waa": [18.5],
                    "eps_basic": [2.45],
                }
            ).to_parquet(str(fin_dir / "metrics" / "part.parquet"), engine="pyarrow")

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "net_profit": [185.0],
                    "revenue": [1000.0],
                }
            ).to_parquet(str(fin_dir / "income" / "part.parquet"), engine="pyarrow")

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "total_equity": [1000.0],
                    "shares_total": [100.0],
                    "current_liability": [200.0],
                    "noncurrent_liability": [100.0],
                    "total_assets": [1500.0],
                    "goodwill": [60.0],
                    "accounts_receivable": [150.0],
                }
            ).to_parquet(str(fin_dir / "balance_sheet" / "part.parquet"), engine="pyarrow")

            os.environ["DATA_DIR"] = str(root)
            try:
                adapter = AStockDataAdapter()
                res = adapter.get_finance_data("600519")
            finally:
                del os.environ["DATA_DIR"]

            self.assertEqual(res["jinglirun"], 185.0)
            self.assertEqual(res["jingzichan"], 1000.0)
            self.assertEqual(res["zhuyingshouru"], 1000.0)
            self.assertEqual(res["zongguben"], 100.0)
            self.assertEqual(res["liudongfuzhai"], 200.0)
            self.assertEqual(res["changqifuzhai"], 100.0)
            self.assertEqual(res["zongzichan"], 1500.0)
            self.assertEqual(res["goodwill"], 60.0)
            self.assertEqual(res["accounts_receivable"], 150.0)
            self.assertEqual(res["asset_liability_ratio"], 20.0)
            self.assertEqual(res["goodwill_ratio"], 6.0)
            self.assertEqual(res["receivable_ratio"], 10.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_data_adapters.py -q`

Expected: fail because `get_finance_data()` does not yet return the new normalized fields and ratios.

- [ ] **Step 3: Write minimal implementation**

Update `src/data_adapters/a_stock_adapter.py` so `get_finance_data()` also reads and returns the extra balance-sheet fields and derived ratios:

```python
            goodwill = _pick(balance, "goodwill", "商誉", "goodwill_value")
            accounts_receivable = _pick(
                balance,
                "accounts_receivable",
                "应收账款",
                "ar",
                "receivable",
            )

            asset_liability_ratio = None
            goodwill_ratio = None
            receivable_ratio = None
            if zongzichan not in (None, 0):
                liabilities = (liudongfuzhai or 0.0) + (changqifuzhai or 0.0)
                asset_liability_ratio = liabilities / float(zongzichan) * 100
                if accounts_receivable is not None:
                    receivable_ratio = float(accounts_receivable) / float(zongzichan) * 100
            if jingzichan not in (None, 0) and goodwill is not None:
                goodwill_ratio = float(goodwill) / float(jingzichan) * 100

            if goodwill is not None:
                finance_dict["goodwill"] = float(goodwill)
            if accounts_receivable is not None:
                finance_dict["accounts_receivable"] = float(accounts_receivable)
            if asset_liability_ratio is not None:
                finance_dict["asset_liability_ratio"] = float(asset_liability_ratio)
            if goodwill_ratio is not None:
                finance_dict["goodwill_ratio"] = float(goodwill_ratio)
            if receivable_ratio is not None:
                finance_dict["receivable_ratio"] = float(receivable_ratio)
```

Keep the existing `mootdx` fallback unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_data_adapters.py::TestDataAdapters::test_a_stock_adapter_finance_fields -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data_adapters/a_stock_adapter.py tests/test_data_adapters.py
git commit -m "feat: normalize finance trap fields"
```

---

### Task 2: Add a dedicated finance trap evaluator in the recap engine

**Files:**
- Modify: `src/recap_engine.py`
- Test: `tests/test_recap_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_finance_trap_evaluator(self):
        safe = {
            "jinglirun": 185.0,
            "jingzichan": 1000.0,
            "zongguben": 100.0,
            "liudongfuzhai": 200.0,
            "changqifuzhai": 100.0,
            "zongzichan": 1500.0,
            "goodwill": 20.0,
            "accounts_receivable": 40.0,
        }
        safe_result = recap_engine._evaluate_finance_trap("贵州茅台", safe)
        self.assertEqual(safe_result["risk_level"], "安全")
        self.assertEqual(safe_result["risk_flags"], [])
        self.assertEqual(safe_result["asset_liability_ratio"], 20.0)

        risky = {
            "jinglirun": 50.0,
            "jingzichan": 100.0,
            "zongguben": 10.0,
            "liudongfuzhai": 80.0,
            "changqifuzhai": 30.0,
            "zongzichan": 100.0,
            "goodwill": 40.0,
            "accounts_receivable": 60.0,
        }
        risky_result = recap_engine._evaluate_finance_trap("某股", risky)
        self.assertEqual(risky_result["risk_level"], "极度危险")
        self.assertIn("high_liability", risky_result["risk_flags"])
        self.assertIn("high_goodwill", risky_result["risk_flags"])
        self.assertIn("high_receivable", risky_result["risk_flags"])

        st_result = recap_engine._evaluate_finance_trap("*ST测试", safe)
        self.assertEqual(st_result["risk_level"], "极度危险")
        self.assertIn("st", st_result["risk_flags"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_recap_pipeline.py::TestRecapPipeline::test_finance_trap_evaluator -q`

Expected: fail because `_evaluate_finance_trap()` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add a private helper near the existing analysis helpers in `src/recap_engine.py`:

```python
def _evaluate_finance_trap(name, finance):
    finance = finance or {}
    risk_flags = []
    risk_notes = []

    st_name = str(name or "")
    if "ST" in st_name or "*ST" in st_name:
        return {
            "risk_level": "极度危险",
            "risk_flags": ["st"],
            "risk_notes": ["简称命中 ST / *ST"],
            "asset_liability_ratio": _safe_float(finance.get("asset_liability_ratio")),
            "goodwill_ratio": _safe_float(finance.get("goodwill_ratio")),
            "receivable_ratio": _safe_float(finance.get("receivable_ratio")),
        }

    jingzichan = _safe_float(finance.get("jingzichan"))
    zongzichan = _safe_float(finance.get("zongzichan"))
    liudongfuzhai = _safe_float(finance.get("liudongfuzhai")) or 0.0
    changqifuzhai = _safe_float(finance.get("changqifuzhai")) or 0.0
    goodwill = _safe_float(finance.get("goodwill"))
    accounts_receivable = _safe_float(finance.get("accounts_receivable"))

    asset_liability_ratio = None
    goodwill_ratio = None
    receivable_ratio = None

    if zongzichan not in (None, 0):
        liabilities = liudongfuzhai + changqifuzhai
        asset_liability_ratio = liabilities / zongzichan * 100
        if asset_liability_ratio >= 75:
            risk_flags.append("high_liability")
            risk_notes.append(f"资产负债率 {asset_liability_ratio:.1f}% >= 75%")
        if accounts_receivable is not None:
            receivable_ratio = accounts_receivable / zongzichan * 100
            if receivable_ratio >= 50:
                risk_flags.append("high_receivable")
                risk_notes.append(f"应收账款占总资产比 {receivable_ratio:.1f}% >= 50%")

    if jingzichan not in (None, 0) and goodwill is not None:
        goodwill_ratio = goodwill / jingzichan * 100
        if goodwill_ratio >= 30:
            risk_flags.append("high_goodwill")
            risk_notes.append(f"商誉占净资产比 {goodwill_ratio:.1f}% >= 30%")

    if len(risk_flags) >= 2:
        risk_level = "极度危险"
    elif len(risk_flags) == 1:
        risk_level = "危险"
    else:
        risk_level = "安全"

    return {
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "risk_notes": risk_notes,
        "asset_liability_ratio": asset_liability_ratio,
        "goodwill_ratio": goodwill_ratio,
        "receivable_ratio": receivable_ratio,
    }
```

Then thread the returned dict into the local audit path so the candidate payload carries `risk_level`, `risk_flags`, `risk_notes`, and the derived ratios.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_recap_pipeline.py::TestRecapPipeline::test_finance_trap_evaluator -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recap_engine.py tests/test_recap_pipeline.py
git commit -m "feat: add finance trap evaluator"
```

---

### Task 3: Reword audit summaries and add regression coverage

**Files:**
- Modify: `src/recap_engine.py`
- Modify: `tests/test_recap_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add a regression test that forces the local UZI path to use a redline-heavy finance snapshot and checks the stored summary and `analysis_json` text:

```python
    def test_local_uzi_summary_mentions_specific_trap_reasons(self):
        recap_engine.init_db()
        original_get_finance_data = recap_engine.ADAPTER.get_finance_data
        recap_engine.ADAPTER.get_finance_data = lambda code: {
            "jinglirun": 50.0,
            "jingzichan": 100.0,
            "zongguben": 10.0,
            "liudongfuzhai": 80.0,
            "changqifuzhai": 30.0,
            "zongzichan": 100.0,
            "goodwill": 40.0,
            "accounts_receivable": 60.0,
        }
        conn = sqlite3.connect(str(self.db_path))
        try:
            results = recap_engine.run_real_uzi_audit(
                conn,
                "2026-06-26",
                [
                    {
                        "code": "600519",
                        "name": "测试股份",
                        "first_seal_time": "093000",
                        "turnover": 6.2,
                        "sector": "白酒",
                    },
                ],
                uzi_path="/nonexistent/UZI-Skill",
            )
            self.assertEqual(results[0]["risk_level"], "极度危险")
            self.assertIn("资产负债率", results[0]["summary"])
            self.assertIn("商誉", results[0]["summary"])

            cur = conn.cursor()
            cur.execute(
                "SELECT analysis_json FROM uzi_audit WHERE date = ? AND code = ?",
                ("2026-06-26", "600519"),
            )
            stored = cur.fetchone()
            analysis = json.loads(stored[0])
            self.assertIn("18_trap", analysis["dim_commentary"])
            self.assertIn("资产负债率", analysis["dim_commentary"]["18_trap"])
        finally:
            conn.close()
            recap_engine.ADAPTER.get_finance_data = original_get_finance_data
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_recap_pipeline.py::TestRecapPipeline::test_local_uzi_summary_mentions_specific_trap_reasons -q`

Expected: fail because the current summary still uses the old blanket phrase and the analysis text does not carry the explicit trap reasons.

- [ ] **Step 3: Write minimal implementation**

Update the local audit summary and payload wiring in `src/recap_engine.py`:

```python
        trap_info = _evaluate_finance_trap(name, finance_dict)
        candidate_payload["risk_level"] = trap_info["risk_level"]
        candidate_payload["risk_flags"] = trap_info["risk_flags"]
        candidate_payload["risk_notes"] = trap_info["risk_notes"]
        candidate_payload["asset_liability_ratio"] = trap_info["asset_liability_ratio"]
        candidate_payload["goodwill_ratio"] = trap_info["goodwill_ratio"]
        candidate_payload["receivable_ratio"] = trap_info["receivable_ratio"]

        risk_note_text = "；".join(trap_info["risk_notes"]) if trap_info["risk_notes"] else "当前财务快照未触发明确排雷红线"
        summary = (
            f"【巴菲特价值席位】根据本地财务快照，该股中报ROE表现一般，价值评分为 {val_score}分，表决为：{val_vote}。"
            f"【赵老哥游资席位】日内换手合理，板块个股今日涨停 {sector_count}只，游资评分为 {mom_score}分，表决为：{mom_vote}。"
            f"【大空头排雷席位】{risk_note_text}，排雷评级为：{risk_level}。"
            f"【结构化覆盖】{analysis_payload['coverage']['label']}。"
        )
```

Also update `_build_uzi_analysis_payload()` so `dim_commentary["18_trap"]` uses `candidate["risk_notes"]` when present and falls back to the neutral sentence when it is not.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_recap_pipeline.py::TestRecapPipeline::test_local_uzi_summary_mentions_specific_trap_reasons -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recap_engine.py tests/test_recap_pipeline.py
git commit -m "fix: explain finance trap summaries"
```

---

### Task 4: Run the focused regression suite

**Files:**
- No code changes
- Test: `tests/test_data_adapters.py`, `tests/test_recap_pipeline.py`

- [ ] **Step 1: Run the focused tests**

Run:

```bash
pytest tests/test_data_adapters.py tests/test_recap_pipeline.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Spot-check the audit payload**

Run a narrow smoke check if needed:

```bash
python -m pytest tests/test_recap_pipeline.py::TestRecapPipeline::test_database_initialization -q
```

Expected: PASS, and `uzi_audit` still has `analysis_json`.

- [ ] **Step 3: Commit**

```bash
git add src/data_adapters/a_stock_adapter.py src/recap_engine.py tests/test_data_adapters.py tests/test_recap_pipeline.py
git commit -m "test: cover finance trap scoring"
```
