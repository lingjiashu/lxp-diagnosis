"""
FastAPI 后端 — LXP 逆变器故障诊断服务
"""

import os
import uuid
import shutil
import json
import time
import glob
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from engine.diagnosis import run_diagnosis


class BatchLocalRequest(BaseModel):
    folder_path: str
    file_pattern: str = "*.xls*"


app = FastAPI(title="LXP Diagnosis", version="1.0")

# 增加文件上传大小限制（逆变器历史数据 Excel 可能 5MB+）
from fastapi import Request
from starlette.datastructures import UploadFile as StarletteUploadFile
import asyncio

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=500)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 结果保留时长（秒），超时自动清理
RESULT_MAX_AGE = 86400  # 24 hours
_last_cleanup = 0
CLEANUP_INTERVAL = 3600  # 每小时最多清理一次


def _cleanup_old_sessions():
    """清理过期 session 目录（带频率限制）。"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    for sd in UPLOAD_DIR.iterdir():
        if sd.is_dir():
            try:
                mtime = sd.stat().st_mtime
                if now - mtime > RESULT_MAX_AGE:
                    shutil.rmtree(sd)
            except Exception:
                pass


def _strip_heavy_fields(response: dict) -> dict:
    """移除 violations 中的大字段（prev_row/next_row），但 critical 违规保留。"""
    for v in response.get("violations", []):
        if v.get("severity") != "critical":
            v.pop("prev_row", None)
            v.pop("next_row", None)
    # 截断超大 report（保留头部 + 前200个违规详情）
    report = response.get("report", "")
    if len(report) > 500_000:
        lines = report.split("\n")
        header_end = 0
        violation_count = 0
        for i, line in enumerate(lines):
            if line.startswith("### 🟡 异常 #") or line.startswith("### 🔴 异常 #"):
                violation_count += 1
                if violation_count > 200:
                    header_end = i
                    break
            else:
                header_end = i + 1
        if header_end > 0 and header_end < len(lines):
            remaining = len([l for l in lines[header_end:] if l.startswith("### ")])
            response["report"] = "\n".join(lines[:header_end]) + (
                f"\n\n---\n> ⚠️ 已截断，省略剩余 {remaining} 个违规详情。"
                f"\n> 完整报告请通过异常时间点/事件时间线/字段变化 Tab 查看。\n"
            )
    return response


def _build_response(result: dict) -> dict:
    """从 run_diagnosis 原始返回构建前端兼容的响应。"""
    report = result.pop("report", "")
    all_violations = result.pop("all_violations", [])
    fault_transitions = result.pop("fault_transitions", [])
    correlated = result.pop("correlated", [])
    event_timeline = result.pop("event_timeline", [])
    field_changes = result.pop("field_changes", {})

    critical_count = sum(1 for v in all_violations if v["severity"] == "critical")
    warning_count = sum(1 for v in all_violations if v["severity"] == "warning")

    # 统计触犯的物理条件
    rules_set = set()
    for v in all_violations:
        for sv in v.get("violations", []):
            rn = sv.get("rule", "")
            if rn:
                short = rn.split("(")[0].strip() if "(" in rn else rn
                rules_set.add(short)

    return {
        "success": True,
        "summary": {
            **result.get("historical", {}),
            "events": result.get("event_records"),
            "settings": result.get("set_records"),
            "violations_total": len(all_violations),
            "violations_critical": critical_count,
            "violations_warning": warning_count,
            "transitions_count": len(fault_transitions),
            "violated_rules": sorted(rules_set),
        },
        "violations": all_violations,
        "transitions": fault_transitions,
        "correlated": correlated,
        "event_timeline": event_timeline,
        "field_changes": field_changes,
        "report": report,
    }


@app.get("/")
async def index():
    """返回前端页面"""
    html_path = BASE_DIR / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>LXP Diagnosis API Running</h1>")


@app.post("/api/diagnose")
async def diagnose(
    historical: UploadFile = File(...),
    event: UploadFile = File(None),
    settings: UploadFile = File(None),
):
    """
    上传文件并运行诊断。
    
    - historical: 历史运行数据 Excel（必填）
    - event: 事件记录 Excel（可选）
    - settings: 操作设置记录 Excel（可选）
    
    返回 session_id，可用于 /api/result/{session_id} 重新获取结果。
    """
    try:
        # 清理过期 session
        _cleanup_old_sessions()

        session_id = uuid.uuid4().hex[:12]
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(exist_ok=True)
        
        historical_path = session_dir / os.path.basename(historical.filename or "data.xls")
        event_path = None
        settings_path = None
        
        # Save historical
        with open(historical_path, "wb") as f:
            content = await historical.read()
            f.write(content)
        
        # Save event if provided
        if event:
            event_path = session_dir / os.path.basename(event.filename or "event.xls")
            with open(event_path, "wb") as f:
                content = await event.read()
                f.write(content)
        
        # Save settings if provided
        if settings:
            settings_path = session_dir / os.path.basename(settings.filename or "settings.xls")
            with open(settings_path, "wb") as f:
                content = await settings.read()
                f.write(content)
        
        # Run diagnosis
        raw_result = run_diagnosis(
            historical_path=str(historical_path),
            event_path=str(event_path) if event_path else None,
            set_path=str(settings_path) if settings_path else None,
        )
        
        # Build response
        response = _build_response(dict(raw_result))
        response["session_id"] = session_id

        # 精简存储（去掉 prev_row/next_row）
        _strip_heavy_fields(response)

        # 保存结果到磁盘，供后续 /api/result/ 查询
        result_file = session_dir / "result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, default=str)
        
        return JSONResponse(response)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=500)


@app.get("/api/result/{session_id}")
async def get_result(session_id: str):
    """根据 session_id 获取之前诊断的完整结果。"""
    result_file = UPLOAD_DIR / session_id / "result.json"
    if not result_file.exists():
        return JSONResponse({"success": False, "error": "结果不存在或已过期"}, status_code=404)
    
    # Check age
    try:
        mtime = result_file.stat().st_mtime
        if time.time() - mtime > RESULT_MAX_AGE:
            shutil.rmtree(UPLOAD_DIR / session_id, ignore_errors=True)
            return JSONResponse({"success": False, "error": "结果已过期"}, status_code=404)
    except Exception:
        pass

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"success": False, "error": f"读取失败: {e}"}, status_code=500)


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "1.0"}


@app.get("/api/batch-cached")
async def batch_cached():
    """返回最近一次批量分析的缓存结果（serveo 友好，GET 即取）。"""
    cache_file = BASE_DIR / "static" / "batch_cache.json"
    if cache_file.exists():
        try:
            import json as _json
            with open(cache_file, "r") as fh:
                return JSONResponse(_json.load(fh))
        except Exception:
            pass
    return JSONResponse({"success": False, "error": "无缓存，请先通过 POST /api/batch-diagnose-local 运行批量分析"})


# ═══════════════════════════════════════════
# 批量诊断 API
# ═══════════════════════════════════════════

def _diagnose_one(historical_path: str) -> dict:
    """对单个文件运行诊断，返回精简结果（含 session_id）。"""
    session_id = uuid.uuid4().hex[:12]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    raw_result = run_diagnosis(historical_path=historical_path)
    response = _build_response(dict(raw_result))
    response["session_id"] = session_id

    _strip_heavy_fields(response)

    # 只对严重异常文件保存完整 result.json，其他只存轻量版
    violations = raw_result.get("all_violations", [])
    critical = sum(1 for v in violations if v.get("severity") == "critical")
    warning = sum(1 for v in violations if v.get("severity") == "warning")
    
    result_file = session_dir / "result.json"
    if critical > 0:
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, default=str)
    else:
        # 无严重异常：只存摘要，丢弃 violations/report 大字段
        light = {
            "success": True,
            "session_id": session_id,
            "summary": response.get("summary", {}),
            "violations": [],
            "event_timeline": [],
            "field_changes": {},
            "report": "(无严重异常，完整报告省略)",
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(light, f, ensure_ascii=False, default=str)

    # 统计触犯的物理条件（去重排序）
    rules_set = set()
    for v in violations:
        for sv in v.get("violations", []):
            rule_name = sv.get("rule", "")
            if rule_name:
                # 取规则简称（括号前部分）
                short = rule_name.split("(")[0].strip() if "(" in rule_name else rule_name
                rules_set.add(short)
    violated_rules = sorted(rules_set)

    # 构建异常数据快照（取最后一个异常点的关键指标）
    data_snapshot = ""
    if violations:
        last_v = violations[-1]  # 最后一个异常点
        m = last_v.get("metrics", {})
        if m:
            fields = []
            # 按用户要求的顺序
            for key in ["SOC", "BatCurrent", "pCharge", "pDisCharge", "pinv", "prec",
                         "vBat", "Vbat_Inv", "vpv1", "vpv2", "vpv3",
                         "ppv1", "ppv2", "ppv3",
                         "vacr", "fac", "pToGrid", "pToUser", "pLoad",
                         "vBusP", "vBus1", "vBUS2"]:
                val = m.get(key)
                if val is not None:
                    if key == "SOC":
                        fields.append(f"SOC: {val}%")
                    elif key in ("BatCurrent",):
                        fields.append(f"BatCurrent: {val}A")
                    elif key in ("fac",):
                        fields.append(f"fac: {val}Hz")
                    elif key in ("vBat", "Vbat_Inv", "vpv1", "vpv2", "vpv3",
                                 "vacr", "vBusP", "vBus1", "vBUS2"):
                        fields.append(f"{key}: {val}V")
                    elif key in ("pCharge", "pDisCharge", "pinv", "prec",
                                 "ppv1", "ppv2", "ppv3", "pToGrid", "pToUser", "pLoad"):
                        fields.append(f"{key}: {val}W")
                    else:
                        fields.append(f"{key}: {val}")
            data_snapshot = " | ".join(fields)

    return {
        "session_id": session_id,
        "filename": os.path.basename(historical_path),
        "serial_number": raw_result["historical"]["serial_number"],
        "total_rows": raw_result["historical"]["total_rows"],
        "time_start": raw_result["historical"]["time_range"]["start"],
        "time_end": raw_result["historical"]["time_range"]["end"],
        "violations_total": len(violations),
        "violations_critical": critical,
        "violations_warning": warning,
        "transitions_count": len(raw_result.get("fault_transitions", [])),
        "violated_rules": violated_rules,
        "data_snapshot": data_snapshot,
        # ⚠️ 不包含完整 result，需要时通过 /api/result/{session_id} 获取
    }


@app.post("/api/batch-diagnose-local")
async def batch_diagnose_local(req: BatchLocalRequest):
    """
    批量诊断 — 服务器本地文件夹模式。
    扫描 folder_path 中的 Excel 文件，逐个诊断。
    """
    try:
        folder = Path(req.folder_path)
        if not folder.exists():
            return JSONResponse({"success": False, "error": f"文件夹不存在: {req.folder_path}"}, status_code=400)
        if not folder.is_dir():
            return JSONResponse({"success": False, "error": f"路径不是文件夹: {req.folder_path}"}, status_code=400)

        # 扫描 Excel 文件（去重、排序）
        patterns = [p.strip() for p in req.file_pattern.split(",")]
        files_set = set()
        for pat in patterns:
            for f in folder.glob(pat):
                if f.is_file() and f.suffix.lower() in (".xls", ".xlsx"):
                    files_set.add(f)
        file_list = sorted(files_set, key=lambda x: x.name)

        if not file_list:
            return JSONResponse({
                "success": False,
                "error": f"文件夹中未找到 Excel 文件 (pattern: {req.file_pattern})",
            }, status_code=400)

        results = []
        errors = []
        for fp in file_list:
            try:
                r = _diagnose_one(str(fp))
                results.append(r)
            except Exception as e:
                import traceback
                errors.append({
                    "filename": fp.name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        result = {
            "success": True,
            "total_files": len(file_list),
            "succeeded": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }
        # 自动缓存到 static/
        import json as _json
        cache_file = BASE_DIR / "static" / "batch_cache.json"
        with open(cache_file, "w") as fh:
            _json.dump(result, fh, ensure_ascii=False)
        return JSONResponse(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/batch-diagnose-upload")
async def batch_diagnose_upload(files: List[UploadFile] = File(...)):
    """
    批量诊断 — 浏览器多文件上传模式。
    接受多个 Excel 文件，逐个诊断。
    """
    try:
        if not files:
            return JSONResponse({"success": False, "error": "未选择文件"}, status_code=400)

        results = []
        errors = []
        for upload_file in files:
            try:
                # 保存临时文件
                session_id = uuid.uuid4().hex[:12]
                session_dir = UPLOAD_DIR / session_id
                session_dir.mkdir(parents=True, exist_ok=True)
                file_path = session_dir / os.path.basename(upload_file.filename or "unknown.xlsx")
                content = await upload_file.read()
                with open(file_path, "wb") as f:
                    f.write(content)

                r = _diagnose_one(str(file_path))
                results.append(r)

                # 清理临时文件（result.json 已由 _diagnose_one 保存到另一个 session_dir）
                try:
                    shutil.rmtree(session_dir)
                except Exception:
                    pass
            except Exception as e:
                import traceback
                errors.append({
                    "filename": upload_file.filename,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        return JSONResponse({
            "success": True,
            "total_files": len(files),
            "succeeded": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
