from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from app.config import settings

router = APIRouter(prefix="/api/recap", tags=["recap"])


from app.api._uzi_shared import build_uzi_analysis_payload  # noqa: E402


def get_recap_db_path() -> Path:
    # 1. Environment variable override
    env_path = os.getenv("RECAP_DB_PATH")
    if env_path:
        return Path(env_path)

    # 2. Local development path: project root data/recap.db
    # settings.data_dir is at <root>/vendor/tickflow-stock-panel/data
    dev_path = settings.data_dir.parent.parent.parent / "data" / "recap.db"
    if dev_path.exists():
        return dev_path

    # Fallback to older parent.parent just in case layout changes
    alt_path = settings.data_dir.parent.parent / "data" / "recap.db"
    if alt_path.exists():
        return alt_path

    # 3. Inside container/production fallback (same directory as data_dir or mapped volume)
    container_path = settings.data_dir / "recap.db"
    if container_path.exists():
        return container_path

    # Fallback to dev path
    return dev_path


def _recap_run_lock_path() -> Path:
    return settings.data_dir / ".recap_run.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_recap_run_lock() -> bool:
    lock_path = _recap_run_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            pid_str = lock_path.read_text(encoding="utf-8").strip()
            pid = int(pid_str) if pid_str.isdigit() else None
        except Exception:
            pid = None
        if pid is not None and _pid_alive(pid):
            return False
        lock_path.unlink(missing_ok=True)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def _release_recap_run_lock() -> None:
    try:
        _recap_run_lock_path().unlink(missing_ok=True)
    except Exception:
        pass


def calculate_calibration_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Calculate historical promotion rates for score buckets."""
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
        # Fallback empty list on error
        return []




@router.get("/intraday-execution")
def get_intraday_execution():
    db_path = get_recap_db_path()
    if not db_path.exists():
        return {"date": None, "candidates": [], "snapshot_ts": None, "market_brief": None}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM candidates
            WHERE date = (SELECT max(date) FROM candidates)
            ORDER BY score DESC
            LIMIT 5
        """)
        candidate_cols = [desc[0] for desc in cursor.description] if cursor.description else []
        candidate_rows = cursor.fetchall()

        if not candidate_rows:
            conn.close()
            return {"date": None, "candidates": [], "snapshot_ts": None, "market_brief": None}

        latest_date = candidate_rows[0]["date"]
        codes = [row["code"] for row in candidate_rows]

        rs_map = {}
        snapshot_ts = None
        try:
            placeholders = ", ".join("?" for _ in codes)
            cursor.execute(f"""
                SELECT code, price, change_pct, score_intraday, seal_funds, ts
                FROM realtime_snapshot
                WHERE code IN ({placeholders})
            """, codes)
            rs_rows = cursor.fetchall()
            rs_map = {row["code"]: dict(row) for row in rs_rows}
            for rs in rs_map.values():
                if rs.get("ts"):
                    snapshot_ts = rs["ts"]
        except Exception:
            pass

        candidates_list = []
        for row in candidate_rows:
            c = dict(row)
            code = c["code"]
            rs = rs_map.get(code, {})
            c["score_intraday"] = rs.get("score_intraday")
            c["price"] = rs.get("price")
            c["change_pct"] = rs.get("change_pct")
            c["seal_funds"] = rs.get("seal_funds")
            candidates_list.append(c)

        try:
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN change_pct >= 9.8 THEN 1 ELSE 0 END) AS limit_up,
                    SUM(CASE WHEN blown_count > 0 THEN 1 ELSE 0 END) AS broken,
                    SUM(CASE WHEN change_pct <= -9.8 THEN 1 ELSE 0 END) AS limit_down
                FROM realtime_snapshot
            """)
            brief_row = cursor.fetchone()
            market_brief = dict(brief_row) if brief_row else None
        except Exception:
            market_brief = None

        conn.close()

        return {
            "date": latest_date,
            "candidates": candidates_list,
            "snapshot_ts": snapshot_ts,
            "market_brief": market_brief,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query intraday execution data: {str(e)}")


@router.post("/run")
def trigger_recap_run():
    """Manually trigger the recap engine via run_daily.sh."""
    if os.getenv("RECAP_MANUAL_RUN_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Manual recap run is disabled")

    project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    script = project_root / "run_daily.sh"
    if not script.exists():
        raise HTTPException(status_code=404, detail=f"run_daily.sh not found at {script}")

    if not _acquire_recap_run_lock():
        return {"ok": False, "returncode": 409, "stdout": "", "stderr": "Recap engine already running"}

    try:
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PYTHONPATH": str(project_root / "src"), "PATH": os.environ.get("PATH", "")},
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Recap engine timed out (180s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run recap engine: {e}")
    finally:
        _release_recap_run_lock()


@router.get("/all")
def get_all_recap_data():
    db_path = get_recap_db_path()
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Recap database not found at {db_path}. Please run recap engine daily task first."
        )

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Fetch last 150 market recaps
        cursor.execute("SELECT * FROM market_recap ORDER BY date DESC LIMIT 150")
        recap_rows = cursor.fetchall()
        recap_cols = [desc[0] for desc in cursor.description]

        history_list = []
        history_lookup = {}
        for row in recap_rows:
            recap_dict = dict(zip(recap_cols, row))

            try:
                recap_dict["sector_ranking"] = json.loads(recap_dict["sector_ranking"])
            except Exception:
                recap_dict["sector_ranking"] = []

            date_str = recap_dict["date"]
            cursor.execute("SELECT * FROM candidates WHERE date = ? ORDER BY score DESC", (date_str,))
            candidate_rows = cursor.fetchall()
            candidate_cols = [desc[0] for desc in cursor.description]

            candidates_list = []
            for c_row in candidate_rows:
                c_dict = dict(zip(candidate_cols, c_row))
                dims = c_dict.get("personality_dims")
                if isinstance(dims, str):
                    try:
                        c_dict["personality_dims"] = json.loads(dims)
                    except Exception:
                        c_dict["personality_dims"] = None
                t = c_dict["first_seal_time"]
                if len(t) == 6:
                    c_dict["first_seal_time_formatted"] = f"{t[:2]}:{t[2:4]}:{t[4:]}"
                else:
                    c_dict["first_seal_time_formatted"] = t
                # 补充 execution_plans(条件买入 + 防守计划)
                # 尝试表存在时才查,否则崩溃(方案 11.2/14.2 表由 migration 003 创建)
                c_dict["buy_plan"] = None
                c_dict["defensive_plans"] = []
                try:
                    cursor.execute(
                        "SELECT action, trigger_price, precondition, trigger_type "
                        "FROM execution_plans "
                        "WHERE trade_date = ? AND code = ?",
                        (date_str, c_dict["code"])
                    )
                    plan_rows = cursor.fetchall()
                    plan_cols = [desc[0] for desc in cursor.description]
                    for pr in plan_rows:
                        p = dict(zip(plan_cols, pr))
                        if p["action"] == "CONDITIONAL_BUY":
                            c_dict["buy_plan"] = p
                        elif p["action"] in ("EXIT", "HOLD", "WATCH", "REDUCE"):
                            c_dict["defensive_plans"].append(p)
                except Exception:
                    pass  # graceful degrade:表不存在时保持默认 None/[]
                candidates_list.append(c_dict)

            # 补充 market_risk 字段(one_to_two_*→f18_* 是 DB→API 命名转换)
            try:
                cursor.execute(
                    "SELECT market_regime, one_to_two_numerator, one_to_two_denominator, one_to_two_rate, f18_policy, f18_risk_budget "
                    "FROM market_risk WHERE trade_date = ?",
                    (date_str,)
                )
                risk_row = cursor.fetchone()
                if risk_row:
                    recap_dict["market_regime"] = risk_row[0]
                    recap_dict["f18_numerator"] = risk_row[1]
                    recap_dict["f18_denominator"] = risk_row[2]
                    recap_dict["f18_rate"] = risk_row[3]
                    recap_dict["f18_policy"] = risk_row[4]
                    recap_dict["f18_risk_budget"] = risk_row[5]
                else:
                    raise Exception("no row")
            except Exception:
                recap_dict["market_regime"] = None
                recap_dict["f18_numerator"] = None
                recap_dict["f18_denominator"] = None
                recap_dict["f18_rate"] = None
                recap_dict["f18_policy"] = None
                recap_dict["f18_risk_budget"] = None

            recap_data = {
                "date": date_str,
                "market": recap_dict,
                "candidates": candidates_list
            }
            history_lookup[date_str] = recap_data
            history_list.append(recap_data)

        # 2. Fetch UZI audit records
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
            uzi_dict = dict(zip(uzi_cols, u_row))
            if not uzi_dict.get("analysis_json"):
                recap = history_lookup.get(uzi_dict.get("date"))
                market = recap.get("market", {}) if recap else {}
                candidate = {}
                if recap:
                    candidate = next((item for item in recap.get("candidates", []) if item.get("code") == uzi_dict.get("code")), {})
                uzi_dict["analysis_json"] = json.dumps(
                    build_uzi_analysis_payload(candidate, market=market),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            uzi_list.append(uzi_dict)

        # 3. Calculate calibration stats
        calibration_data = calculate_calibration_stats(conn)
        conn.close()

        return {
            "history": history_list,
            "calibration": calibration_data,
            "uzi_audit": uzi_list
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query recap database: {str(e)}"
        )
