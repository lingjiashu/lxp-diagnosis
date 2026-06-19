"""
关联器：将故障时间点与事件记录、操作设置关联起来
"""

from datetime import datetime, timedelta
from typing import Optional


def parse_time(val) -> Optional[datetime]:
    """安全解析时间字符串"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        from pandas import to_datetime
        return to_datetime(str(val))
    except Exception:
        return None


def correlate_events_to_faults(
    fault_transitions: list,
    event_records: dict,
    time_window_hours: float = 24.0,
) -> list:
    """
    为每个故障突变点查找时间窗口内的事件记录。
    
    返回:
    [
        {
            "transition": {...},
            "related_events": [
                {"event": ..., "time_diff_minutes": float, "direction": "before"|"after"},
            ],
            "related_settings": [...],
        }
    ]
    """
    events = event_records.get("events", [])
    results = []
    
    for trans in fault_transitions:
        trans_time = parse_time(trans["transition_time"])
        if trans_time is None:
            results.append({**trans, "related_events": [], "related_settings": []})
            continue
        
        related = []
        for evt in events:
            evt_time = evt.get("start_time")
            if evt_time is None:
                continue
            
            diff = (trans_time - evt_time).total_seconds() / 60.0  # minutes
            
            if abs(diff) <= time_window_hours * 60:
                related.append({
                    "event": evt["event"],
                    "type": evt["type"],
                    "start_time": str(evt["start_time"]) if evt["start_time"] else None,
                    "recovered_time": str(evt["recovered_time"]) if evt.get("recovered_time") else None,
                    "time_diff_minutes": round(diff, 1),
                    "direction": "before" if diff > 0 else "after" if diff < 0 else "same",
                })
        
        # Sort by absolute time diff
        related.sort(key=lambda x: abs(x["time_diff_minutes"]))
        
        results.append({**trans, "related_events": related})
    
    return results


def correlate_settings_to_faults(
    fault_transitions: list,
    set_records: dict,
    time_window_hours: float = 24.0,
) -> list:
    """
    为每个故障突变点查找时间窗口内的设置操作记录。
    """
    records = set_records.get("records", [])
    results = []
    
    for trans in fault_transitions:
        trans_time = parse_time(trans["transition_time"])
        if trans_time is None:
            results.append({**trans, "related_settings": []})
            continue
        
        related = []
        for rec in records:
            rec_time = rec.get("time")
            if rec_time is None:
                continue
            rec_time = parse_time(rec_time)
            if rec_time is None:
                continue
            
            diff = (trans_time - rec_time).total_seconds() / 60.0
            
            if abs(diff) <= time_window_hours * 60:
                related.append({
                    "time": str(rec["time"]) if rec["time"] else None,
                    "username": rec["username"],
                    "parameter": rec["parameter"],
                    "value": rec["value"],
                    "result": rec["result"],
                    "time_diff_minutes": round(diff, 1),
                    "direction": "before" if diff > 0 else "after" if diff < 0 else "same",
                })
        
        related.sort(key=lambda x: abs(x["time_diff_minutes"]))
        results.append({**trans, "related_settings": related})
    
    return results


def full_correlation(
    fault_transitions: list,
    event_records: dict,
    set_records: dict,
    time_window_hours: float = 48.0,
) -> list:
    """
    完整关联：同时关联事件和设置操作。
    
    返回每个故障突变点的完整上下文：
    - 突变前后数据窗口
    - 关联的事件记录
    - 关联的设置操作
    - 物理判据违反情况
    """
    # First correlate events
    with_events = correlate_events_to_faults(
        fault_transitions, event_records, time_window_hours
    )
    
    # Then add settings
    full = []
    for item in with_events:
        trans = {
            "transition_index": item.get("transition_index"),
            "transition_time": item.get("transition_time"),
            "from_code": item.get("from_code"),
            "to_code": item.get("to_code"),
            "window_before": item.get("window_before", []),
            "window_after": item.get("window_after", []),
            "violations_before": item.get("violations_before", []),
            "violations_after": item.get("violations_after", []),
            "related_events": item.get("related_events", []),
            "related_settings": [],  # Will fill below
        }
        
        # Correlate settings for this transition
        trans_time = parse_time(item["transition_time"])
        if trans_time:
            related_settings = []
            for rec in set_records.get("records", []):
                rec_time = parse_time(rec.get("time"))
                if rec_time is None:
                    continue
                diff = (trans_time - rec_time).total_seconds() / 60.0
                if abs(diff) <= time_window_hours * 60:
                    related_settings.append({
                        "time": str(rec["time"]) if rec["time"] else None,
                        "username": rec["username"],
                        "parameter": rec["parameter"],
                        "value": rec["value"],
                        "result": rec["result"],
                        "time_diff_minutes": round(diff, 1),
                        "direction": "before" if diff > 0 else "after" if diff < 0 else "same",
                    })
            related_settings.sort(key=lambda x: abs(x["time_diff_minutes"]))
            trans["related_settings"] = related_settings
        
        full.append(trans)
    
    return full
