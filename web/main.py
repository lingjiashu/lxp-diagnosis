"""
FastAPI 后端 — LXP 逆变器故障诊断服务
"""

import os
import uuid
import shutil
from pathlib import Path
from tempfile import mkdtemp
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from engine.diagnosis import run_diagnosis


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

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


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
    """
    try:
        # Save uploaded files to temp directory
        session_id = uuid.uuid4().hex[:12]
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(exist_ok=True)
        
        historical_path = session_dir / historical.filename
        event_path = None
        settings_path = None
        
        # Save historical
        with open(historical_path, "wb") as f:
            content = await historical.read()
            f.write(content)
        
        # Save event if provided
        if event:
            event_path = session_dir / event.filename
            with open(event_path, "wb") as f:
                content = await event.read()
                f.write(content)
        
        # Save settings if provided
        if settings:
            settings_path = session_dir / settings.filename
            with open(settings_path, "wb") as f:
                content = await settings.read()
                f.write(content)
        
        # Run diagnosis
        result = run_diagnosis(
            historical_path=str(historical_path),
            event_path=str(event_path) if event_path else None,
            set_path=str(settings_path) if settings_path else None,
        )
        
        # Clean up temp files
        try:
            shutil.rmtree(session_dir)
        except Exception:
            pass
        
        # Build response: split report from data
        report = result.pop("report", "")
        all_violations = result.pop("all_violations", [])
        fault_transitions = result.pop("fault_transitions", [])
        correlated = result.pop("correlated", [])
        
        # Summary stats
        critical_count = sum(1 for v in all_violations if v["severity"] == "critical")
        warning_count = sum(1 for v in all_violations if v["severity"] == "warning")
        
        # Extract event list for display
        event_list = []
        if event_records_raw := result.get("event_records"):
            event_list_raw = event_records_raw.get("_raw_events", [])
        
        return JSONResponse({
            "success": True,
            "summary": {
                **result["historical"],
                "events": result.get("event_records"),
                "settings": result.get("set_records"),
                "violations_total": len(all_violations),
                "violations_critical": critical_count,
                "violations_warning": warning_count,
                "transitions_count": len(fault_transitions),
            },
            "violations": all_violations,
            "transitions": fault_transitions,
            "correlated": correlated,
            "report": report,
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=500)


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "1.0"}


# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
