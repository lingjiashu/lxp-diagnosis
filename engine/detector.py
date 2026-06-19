"""
强故障特征检测器

三条物理定律 (硬件故障判据):
1. vBat ≈ Vbat_Inv   (误差 ≤ 1V)
2. vBUS2 ≈ vBat × 6  (误差 ≤ 10V)
3. vBusP × 2 ≈ vBus1 (误差 ≤ 6V)

违反任一条 = 硬件异常时间点
"""

from datetime import datetime
from typing import Optional
from .parser import safe_float, safe_int


# ─── 大小写不敏感的列名查找 ───

# 列名映射：常用变体 → 统一键
_COLUMN_ALIASES = {
    'vbat': 'vbat',
    'vbat_inv': 'vbat_inv',
    'vbus1': 'vbus1',
    'vbus2': 'vbus2',
    'vbusp': 'vbusp',
    'faultcode': 'faultcode',
    'warningcode': 'warningcode',
    'soc': 'soc',
    'batcurrent': 'batcurrent',
    'pcharge': 'pcharge',
    'pdischarge': 'pdischarge',
    'status': 'status',
    'serial number': 'serial_number',
    'time': 'time',
}

def _lookup(row: dict, *keys: str) -> Optional[float]:
    """大小写不敏感地从 row 中查找值"""
    for key in keys:
        # Direct match
        if key in row:
            return safe_float(row[key])
        # Case-insensitive match
        key_lower = key.lower().replace(' ', '_').replace('-', '_')
        for col_name in row:
            col_lower = col_name.lower().replace(' ', '_').replace('-', '_')
            if col_lower == key_lower:
                return safe_float(row[col_name])
    return None

def _lookup_str(row: dict, *keys: str) -> str:
    """大小写不敏感地查找字符串值"""
    for key in keys:
        if key in row:
            return str(row[key])
        key_lower = key.lower()
        for col_name in row:
            if col_name.lower() == key_lower:
                return str(row[col_name])
    return ''


# ─── 三条强故障判据 ───

def check_vbat_consistency(vBat: Optional[float], Vbat_Inv: Optional[float]) -> dict:
    """
    判据1: vBat ≈ Vbat_Inv, 误差 ≤ 1V
    """
    if vBat is None or Vbat_Inv is None:
        return {"passed": None, "error": None, "detail": "数据缺失"}
    
    error = abs(vBat - Vbat_Inv)
    passed = error <= 1.0
    
    return {
        "passed": passed,
        "error": round(error, 2),
        "detail": f"vBat={vBat:.1f}V, Vbat_Inv={Vbat_Inv:.1f}V, 误差={error:.2f}V {'✓' if passed else '✗ 超标'}"
    }


def check_vbus_ratio(vBat: Optional[float], vBUS2: Optional[float]) -> dict:
    """
    判据2: vBUS2 ≈ vBat × 6, 误差 ≤ 20V
    """
    if vBat is None or vBUS2 is None:
        return {"passed": None, "error": None, "detail": "数据缺失"}
    
    if vBat == 0:
        return {"passed": None, "error": None, "detail": "vBat=0, 无法计算"}
    
    expected = vBat * 6
    error = abs(vBUS2 - expected)
    passed = error <= 20.0
    
    return {
        "passed": passed,
        "error": round(error, 2),
        "detail": f"vBUS2={vBUS2:.1f}V, vBat×6={expected:.1f}V, 误差={error:.2f}V {'✓' if passed else '✗ 超标'}"
    }


def check_vbus_half_ratio(vBusP: Optional[float], vBus1: Optional[float]) -> dict:
    """
    判据3: vBusP × 2 ≈ vBus1, 误差 ≤ 6V
    """
    if vBusP is None or vBus1 is None:
        return {"passed": None, "error": None, "detail": "数据缺失"}
    
    expected = vBusP * 2
    error = abs(vBus1 - expected)
    passed = error <= 6.0
    
    return {
        "passed": passed,
        "error": round(error, 2),
        "detail": f"vBus1={vBus1:.1f}V, vBusP×2={expected:.1f}V, 误差={error:.2f}V {'✓' if passed else '✗ 超标'}"
    }


def check_bus_under_voltage(status: str, vBat: Optional[float], Vbat_Inv: Optional[float], vBUS2: Optional[float]) -> dict:
    """
    判据4: 在 charge/discharge/fault 状态下，电池有电压(>40V)但 BUS2 异常低
    vBUS2 < vBat × 6 - 200V
    """
    if not status:
        return {"passed": None, "error": None, "detail": "状态未知"}
    
    status_lower = str(status).lower()
    has_active_state = any(kw in status_lower for kw in ['charge', 'discharge', 'fault'])
    
    if not has_active_state:
        return {"passed": None, "error": None, "detail": "非充/放电/故障状态，跳过"}
    
    bat_voltage = vBat if vBat is not None else Vbat_Inv
    if bat_voltage is None:
        return {"passed": None, "error": None, "detail": "电池电压数据缺失"}
    
    if bat_voltage <= 40:
        return {"passed": None, "error": None, "detail": f"电池电压={bat_voltage:.1f}V ≤ 40V，跳过"}
    
    if vBUS2 is None:
        return {"passed": False, "error": None, "detail": f"状态={status}，电池={bat_voltage:.1f}V，但 vBUS2 数据缺失 ⚠️"}
    
    threshold = bat_voltage * 6 - 200
    passed = vBUS2 >= threshold
    
    return {
        "passed": passed,
        "error": round(threshold - vBUS2, 2) if not passed else 0,
        "detail": f"状态={status}，电池={bat_voltage:.1f}V，vBUS2={vBUS2:.1f}V，阈值={threshold:.1f}V {'✓' if passed else '✗ 异常低'}"
    }


# ─── InternalFault 位解析 ───

INTERNAL_FAULT_BITS = {
    0: "GFCI故障",
    1: "硬件过流",
    2: "逆变过流",
    3: "Boost过流",
    4: "BDC过流",
    5: "BUS短路",
    6: "Bypass继电器故障",
}


def parse_internal_fault(value) -> dict:
    """
    解析 internalFault 寄存器的位含义。
    支持 hex string (0x504) 或 decimal。
    
    返回:
    {
        "raw": str,
        "hex": str,
        "decimal": int,
        "binary": str,       # 16位二进制
        "active_bits": [{"bit": int, "name": str, "value": 1|0}, ...],
        "fault_summary": str,  # 中文摘要
    }
    """
    if value is None:
        return None
    
    # Parse value
    if isinstance(value, (int, float)):
        dec_val = int(value)
    else:
        s = str(value).strip()
        if s.startswith('0x') or s.startswith('0X'):
            dec_val = int(s, 16)
        else:
            try:
                dec_val = int(s)
            except ValueError:
                try:
                    dec_val = int(float(s))
                except ValueError:
                    return None
    
    hex_str = f"0x{dec_val:04X}"
    binary_str = f"{dec_val:016b}"  # 16-bit binary
    
    active_bits = []
    fault_parts = []
    for bit in range(16):
        bit_val = (dec_val >> bit) & 1
        name = INTERNAL_FAULT_BITS.get(bit)
        if name:
            active_bits.append({"bit": bit, "name": name, "value": bit_val})
            if bit_val == 1:
                fault_parts.append(name)
    
    return {
        "raw": str(value),
        "hex": hex_str,
        "decimal": dec_val,
        "binary": binary_str,
        "active_bits": active_bits,
        "fault_summary": "、".join(fault_parts) if fault_parts else "无异常",
    }


# ─── 主扫描函数 ───

def scan_fault_signatures(rows: list) -> list:
    """
    扫描所有数据行，找出违反物理定律的时间点。
    
    返回:
    [
        {
            "index": int,           # 行索引
            "time": datetime,
            "status": str,
            "fault_code": str,
            "warning_code": str,
            "violations": [         # 哪些判据被违反
                {"rule": "vBat一致性", "passed": False, ...},
                ...
            ],
            "metrics": {            # 当前行的关键数据
                "vBat": float, "Vbat_Inv": float,
                "vBUS2": float, "vBus1": float, "vBusP": float,
                "SOC": float, "BatCurrent": float,
                "pCharge": float, "pDisCharge": float,
            },
            "severity": "critical" | "warning",  # 严重程度
        }
    ]
    """
    violations_list = []
    
    for i, row in enumerate(rows):
        vBat = _lookup(row, 'vBat', 'vbat')
        Vbat_Inv = _lookup(row, 'Vbat_Inv', 'vbat_inv')
        vBUS2 = _lookup(row, 'vBus2', 'vbus2')
        vBus1 = _lookup(row, 'vBus1', 'vbus1')
        vBusP = _lookup(row, 'vBusP', 'vbusp')
        status = _lookup_str(row, 'Status', 'status')
        status_lower = str(status).lower() if status else ''
        
        # 四条触发条件
        r1 = check_vbat_consistency(vBat, Vbat_Inv)
        
        # 规则2: Standby 状态下不判断
        is_standby = 'standby' in status_lower
        r2 = check_vbus_ratio(vBat, vBUS2) if not is_standby else {"passed": None, "error": None, "detail": "Standby状态，跳过"}
        
        r3 = check_vbus_half_ratio(vBusP, vBus1)
        
        # 规则4: Fault 状态 → 直接触发；Charge/Discharge 状态 → 检查 BUS2
        is_fault_status = 'fault' in status_lower
        r4 = check_bus_under_voltage(status, vBat, Vbat_Inv, vBUS2)
        
        # Gather violations
        viols = []
        for rule_name, result in [("vBat一致性 (vBat≈Vbat_Inv, ≤1V)", r1),
                                   ("vBUS2比例 (vBUS2≈vBat×6, ≤20V)", r2),
                                   ("vBusP半压 (vBusP×2≈vBus1, ≤6V)", r3),
                                   ("充放电状态下BUS2异常低 (vBUS2 < vBat×6-200V)", r4)]:
            if result["passed"] is False:
                inference = ""
                if "vBat一致性" in rule_name:
                    bat_v = vBat if vBat is not None else Vbat_Inv
                    if bat_v and 40 <= bat_v <= 60:
                        inference = "可能电池开关断开，内部DCDC过流或者短路"
                    else:
                        inference = "电池采样失效"
                elif "vBUS2比例" in rule_name:
                    inference = "DCDC板或者HV板出现故障（损坏）"
                elif "vBusP半压" in rule_name:
                    inference = "主板逆变侧或者BUS平衡回路出现半BUS短路，同时也会引起vBus2异常"
                elif "BUS2异常低" in rule_name:
                    inference = "LLC未正常启动（Fault状态下LLC不启动属正常，需结合其他判据判断）"
                
                viols.append({
                    "rule": rule_name,
                    "passed": False,
                    "error": result["error"],
                    "detail": result["detail"],
                    "inference": inference,
                })
        
        # Fault 状态单独作为触发条件
        if is_fault_status:
            viols.append({
                "rule": "Fault状态触发",
                "passed": False,
                "error": None,
                "detail": f"Status包含fault: {status}",
                "inference": "",
            })
        
        if viols:
            # Determine severity
            severity = "critical" if len(viols) >= 2 else "warning"
            
            time_val = row.get('_parsed_time') or _lookup_str(row, 'Time', 'time')
            
            fault_code = _lookup_str(row, 'faultCode', 'faultcode')
            warning_code = _lookup_str(row, 'warningCode', 'warningcode')
            internal_fault_raw = _lookup_str(row, 'internalFault', 'internalfault')
            internal_fault = parse_internal_fault(internal_fault_raw)
            
            # Get prev/next row data for context
            prev_row = rows[i - 1] if i > 0 else None
            next_row = rows[i + 1] if i < len(rows) - 1 else None
            
            violations_list.append({
                "index": i,
                "time": str(time_val) if time_val else None,
                "status": status,
                "fault_code": fault_code,
                "warning_code": warning_code,
                "internal_fault": internal_fault,
                "violations": viols,
                "violation_count": len(viols),
                "metrics": {
                    "vBat": vBat,
                    "Vbat_Inv": Vbat_Inv,
                    "vBUS2": vBUS2,
                    "vBus1": vBus1,
                    "vBusP": vBusP,
                    "SOC": _lookup(row, 'SOC', 'soc'),
                    "BatCurrent": _lookup(row, 'BatCurrent', 'batcurrent'),
                    "pCharge": _lookup(row, 'pCharge', 'pcharge'),
                    "pDisCharge": _lookup(row, 'pDisCharge', 'pdischarge'),
                    "vpv1": _lookup(row, 'vpv1'),
                    "vpv2": _lookup(row, 'vpv2'),
                    "vpv3": _lookup(row, 'vpv3'),
                    "ppv1": _lookup(row, 'ppv1'),
                    "ppv2": _lookup(row, 'ppv2'),
                    "ppv3": _lookup(row, 'ppv3'),
                    "vacr": _lookup(row, 'vacr'),
                    "fac": _lookup(row, 'fac'),
                    "pToGrid": _lookup(row, 'pToGrid', 'ptogrid'),
                    "pToUser": _lookup(row, 'pToUser', 'ptouser'),
                    "pLoad": _lookup(row, 'pLoad', 'pload'),
                    "tinner": _lookup(row, 'tinner'),
                    "tBat": _lookup(row, 'tBat'),
                },
                "prev_row": _row_snapshot(prev_row) if prev_row else None,
                "next_row": _row_snapshot(next_row) if next_row else None,
                "severity": severity,
            })
    
    return violations_list


def _row_snapshot(row: dict) -> dict:
    """提取一行的关键数据快照，用于报告"""
    if row is None:
        return None
    return {
        "time": str(row.get('_parsed_time') or _lookup_str(row, 'Time', 'time')),
        "status": _lookup_str(row, 'Status', 'status'),
        "fault_code": _lookup_str(row, 'faultCode', 'faultcode'),
        "warning_code": _lookup_str(row, 'warningCode', 'warningcode'),
        "internal_fault": parse_internal_fault(_lookup_str(row, 'internalFault', 'internalfault')),
        "SOC": _lookup(row, 'SOC', 'soc'),
        "BatCurrent": _lookup(row, 'BatCurrent', 'batcurrent'),
        "pCharge": _lookup(row, 'pCharge', 'pcharge'),
        "pDisCharge": _lookup(row, 'pDisCharge', 'pdischarge'),
        "vpv1": _lookup(row, 'vpv1'),
        "vpv2": _lookup(row, 'vpv2'),
        "vpv3": _lookup(row, 'vpv3'),
        "ppv1": _lookup(row, 'ppv1'),
        "ppv2": _lookup(row, 'ppv2'),
        "ppv3": _lookup(row, 'ppv3'),
        "vacr": _lookup(row, 'vacr'),
        "fac": _lookup(row, 'fac'),
        "pToGrid": _lookup(row, 'pToGrid', 'ptogrid'),
        "pToUser": _lookup(row, 'pToUser', 'ptouser'),
        "pLoad": _lookup(row, 'pLoad', 'pload'),
        "vBusP": _lookup(row, 'vBusP', 'vbusp'),
        "vBus1": _lookup(row, 'vBus1', 'vbus1'),
        "vBus2": _lookup(row, 'vBus2', 'vbus2'),
    }


def find_fault_code_transitions(rows: list, window_before: int = 3, window_after: int = 5) -> list:
    """
    找出 fault code 突变点（0→非0 或 非0→非0变化），
    并提取突变前后的数据窗口用于分析。
    
    返回:
    [
        {
            "transition_index": int,
            "transition_time": datetime,
            "from_code": str,
            "to_code": str,
            "window_before": [rows],   # 突变前 N 行
            "window_after": [rows],    # 突变后 N 行
            "violations_before": [...],  # 前窗口的物理判据违反
            "violations_after": [...],   # 后窗口的物理判据违反
        }
    ]
    """
    transitions = []
    prev_fault = None
    
    for i, row in enumerate(rows):
        current_fault = safe_int(_lookup_str(row, 'faultCode', 'faultcode'))
        if current_fault is None:
            current_fault = 0
        
        if prev_fault is not None and current_fault != prev_fault:
            # Fault code transition detected
            start_idx = max(0, i - window_before)
            end_idx = min(len(rows), i + window_after)
            
            window_data = rows[start_idx:end_idx]
            
            # Check violations in the window
            violations_before = scan_fault_signatures(rows[max(0, i - window_before):i])
            violations_after = scan_fault_signatures(rows[i:min(len(rows), i + window_after)])
            
            transitions.append({
                "transition_index": i,
                "transition_time": str(row.get('_parsed_time') or row.get('Time', '')),
                "from_code": f"0x{prev_fault:X}" if prev_fault else "0x0",
                "to_code": f"0x{current_fault:X}" if current_fault else "0x0",
                "window_before": [
                    {
                        "time": str(r.get('_parsed_time') or _lookup_str(r, 'Time', 'time')),
                        "fault_code": _lookup_str(r, 'faultCode', 'faultcode'),
                        "warning_code": _lookup_str(r, 'warningCode', 'warningcode'),
                        "status": _lookup_str(r, 'Status', 'status'),
                        "vBat": _lookup(r, 'vBat', 'vbat'),
                        "Vbat_Inv": _lookup(r, 'Vbat_Inv', 'vbat_inv'),
                        "vBUS2": _lookup(r, 'vBus2', 'vbus2'),
                        "vBus1": _lookup(r, 'vBus1', 'vbus1'),
                        "vBusP": _lookup(r, 'vBusP', 'vbusp'),
                        "SOC": _lookup(r, 'SOC', 'soc'),
                    }
                    for r in rows[max(0, i - window_before):i]
                ],
                "window_after": [
                    {
                        "time": str(r.get('_parsed_time') or _lookup_str(r, 'Time', 'time')),
                        "fault_code": _lookup_str(r, 'faultCode', 'faultcode'),
                        "warning_code": _lookup_str(r, 'warningCode', 'warningcode'),
                        "status": _lookup_str(r, 'Status', 'status'),
                        "vBat": _lookup(r, 'vBat', 'vbat'),
                        "Vbat_Inv": _lookup(r, 'Vbat_Inv', 'vbat_inv'),
                        "vBUS2": _lookup(r, 'vBus2', 'vbus2'),
                        "vBus1": _lookup(r, 'vBus1', 'vbus1'),
                        "vBusP": _lookup(r, 'vBusP', 'vbusp'),
                        "SOC": _lookup(r, 'SOC', 'soc'),
                    }
                    for r in rows[i:min(len(rows), i + window_after)]
                ],
                "violations_before": violations_before,
                "violations_after": violations_after,
            })
        
        prev_fault = current_fault
    
    return transitions
