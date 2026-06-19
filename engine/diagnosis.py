"""
主诊断流程：解析 → 扫描 → 关联 → 报告
"""

from .parser import parse_historical_data, parse_event_records, parse_set_records
from .detector import scan_fault_signatures, find_fault_code_transitions
from .correlator import full_correlation
from .report import generate_report
from .timeline import extract_event_timeline, extract_field_changes
from typing import Optional


def run_diagnosis(
    historical_path: str,
    event_path: Optional[str] = None,
    set_path: Optional[str] = None,
) -> dict:
    # Step 1: Parse
    historical = parse_historical_data(historical_path)
    
    event_records = None
    if event_path:
        event_records = parse_event_records(event_path)
    
    set_records = None
    if set_path:
        set_records = parse_set_records(set_path)
    
    # Step 2: Scan for physical law violations
    all_violations = scan_fault_signatures(historical["rows"])
    
    # Step 2b: Event timeline and field changes
    event_timeline = extract_event_timeline(historical["rows"])
    bat_status_changes = extract_field_changes(historical["rows"], "batStatusInv")
    internal_fault_changes = extract_field_changes(historical["rows"], "internalFault")
    
    # Step 3: Find fault code transitions
    fault_transitions = find_fault_code_transitions(historical["rows"])
    
    # Step 4: Correlate with events and settings
    correlated = []
    if event_records or set_records:
        correlated = full_correlation(
            fault_transitions,
            event_records or {"events": []},
            set_records or {"records": []},
        )
    
    # Step 5: Generate report
    report = generate_report(
        historical,
        event_records,
        set_records,
        all_violations,
        fault_transitions,
        correlated,
    )
    
    return {
        "historical": {
            "serial_number": historical["serial_number"],
            "total_rows": historical["total_rows"],
            "time_range": {
                "start": str(historical["time_range"]["start"])[:19] if historical["time_range"]["start"] else None,
                "end": str(historical["time_range"]["end"])[:19] if historical["time_range"]["end"] else None,
            },
            "sheets": historical["sheets"],
        },
        "event_records": {
            "total_events": event_records["total_events"],
            "fault_count": len(event_records.get("fault_events", [])),
            "notice_count": len(event_records.get("notice_events", [])),
            "_raw_events": [
                {
                    "type": e["type"],
                    "event": e["event"],
                    "start_time": str(e["start_time"])[:19] if e["start_time"] else None,
                    "recovered_time": str(e["recovered_time"])[:19] if e.get("recovered_time") else None,
                }
                for e in event_records.get("events", [])
            ],
        } if event_records else None,
        "set_records": {
            "total_records": set_records["total_records"],
        } if set_records else None,
        "all_violations": all_violations,
        "fault_transitions": [
            {
                "transition_time": t["transition_time"],
                "from_code": t["from_code"],
                "to_code": t["to_code"],
                "violations_before_count": len(t.get("violations_before", [])),
                "violations_after_count": len(t.get("violations_after", [])),
            }
            for t in fault_transitions
        ],
        "correlated": correlated,
        "report": report,
        "event_timeline": event_timeline,
        "field_changes": {
            "batStatusInv": bat_status_changes,
            "internalFault": internal_fault_changes,
        },
    }
