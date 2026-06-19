"""
事件时间线 & 诊断字段变化追踪
"""

from datetime import datetime
from typing import Optional
from .parser import safe_float, safe_int


def extract_event_timeline(rows: list) -> list:
    """
    从历史数据中提取事件时间线：
    - 状态切换
    - Fault Code 出现/清除
    - Warning Code 出现/清除
    """
    events = []
    prev = None
    
    for i, row in enumerate(rows):
        status = str(row.get('Status', '')) if row.get('Status') else ''
        fault_code = str(row.get('faultCode', '')) if row.get('faultCode') else ''
        warning_code = str(row.get('warningCode', '')) if row.get('warningCode') else ''
        time_val = row.get('_parsed_time') or row.get('Time', '')
        
        if prev is None:
            prev = {'status': status, 'fault': fault_code, 'warn': warning_code}
            continue
        
        # Status change
        if status != prev['status']:
            events.append({
                'time': str(time_val)[:19] if time_val else '?',
                'type': 'status_change',
                'detail': f"{prev['status']} → {status}",
                'from': prev['status'],
                'to': status,
            })
        
        # Fault code appear
        if prev['fault'] == '0x0' and fault_code != '0x0' and fault_code != '0':
            events.append({
                'time': str(time_val)[:19] if time_val else '?',
                'type': 'fault_appear',
                'detail': f"故障出现: {fault_code}",
                'code': fault_code,
            })
        # Fault code cleared
        elif prev['fault'] != '0x0' and prev['fault'] != '0' and (fault_code == '0x0' or fault_code == '0'):
            events.append({
                'time': str(time_val)[:19] if time_val else '?',
                'type': 'fault_clear',
                'detail': "故障清除",
            })
        
        # Warning code appear
        if (prev['warn'] == '0x0' or prev['warn'] == '0') and warning_code != '0x0' and warning_code != '0':
            events.append({
                'time': str(time_val)[:19] if time_val else '?',
                'type': 'warning_appear',
                'detail': f"告警出现: {warning_code}",
                'code': warning_code,
            })
        # Warning code cleared
        elif prev['warn'] != '0x0' and prev['warn'] != '0' and (warning_code == '0x0' or warning_code == '0'):
            events.append({
                'time': str(time_val)[:19] if time_val else '?',
                'type': 'warning_clear',
                'detail': "告警清除",
            })
        
        prev = {'status': status, 'fault': fault_code, 'warn': warning_code}
    
    return events


# ─── 诊断字段定义 ───

DIAGNOSTIC_FIELDS = {
    'batStatusInv': {
        'label': '逆变器电池状态',
        'bits': {
            0: ('ChargeEnable', '0=禁止充电, 1=允许'),
            1: ('DischgEnable', '0=禁止放电, 1=允许'),
            2: ('DischgLimited', '1=放电限流'),
            3: ('ChargeLimited', '1=充电限流'),
            4: ('ForceChg', '1=强充使能'),
            5: ('FullChg', '1=满充使能'),
            6: ('DischgMosOff', '1=放电MOS关断'),
            7: ('BatSleep', '1=电池休眠'),
        }
    },
    'internalFault': {
        'label': '内部异常',
        'bits': {
            0: ('GFCI故障', 'GFCI模块异常'),
            1: ('硬件过流', '硬件过流保护'),
            2: ('逆变过流', '逆变过流保护'),
            3: ('Boost过流', 'Boost过流保护'),
            4: ('BDC过流', 'BDC过流保护'),
            5: ('BUS短路', 'BUS短路'),
            6: ('Bypass继电器', 'Bypass继电器故障'),
        }
    },
}


def _lookup_field(row: dict, *keys: str) -> Optional[str]:
    """大小写不敏感查找字段值"""
    for key in keys:
        if key in row:
            return str(row[key])
        key_lower = key.lower()
        for col in row:
            if col.lower() == key_lower:
                return str(row[col])
    return None


def parse_field_value(raw_val, field_bits: dict) -> dict:
    """解析字段值为 hex 和 bit 信息"""
    if raw_val is None:
        return None
    try:
        s = str(raw_val).strip()
        if s.startswith('0x') or s.startswith('0X'):
            dec = int(s, 16)
        else:
            dec = int(float(s))
    except (ValueError, TypeError):
        return {'hex': str(raw_val), 'binary': '?', 'bits': [], 'summary': str(raw_val)}
    
    hex_str = f"0x{dec:04X}"
    binary_str = f"{dec:016b}"
    
    bits = []
    active = []
    for bit_num, (name, desc) in field_bits.items():
        val = (dec >> bit_num) & 1
        bits.append({'bit': bit_num, 'name': name, 'desc': desc, 'value': val})
        if val:
            active.append(name)
    
    return {
        'hex': hex_str,
        'binary': binary_str,
        'bits': bits,
        'summary': '、'.join(active) if active else '无异常',
    }


def extract_field_changes(rows: list, field_name: str) -> list:
    """
    追踪指定字段的所有变化点。
    返回每次变化的时间、前后值、bit 级差异。
    """
    field_def = DIAGNOSTIC_FIELDS.get(field_name)
    if not field_def:
        return []
    
    changes = []
    prev_val = None
    prev_time = None
    
    for row in rows:
        raw = _lookup_field(row, field_name)
        time_val = row.get('_parsed_time') or row.get('Time', '')
        
        if raw is None:
            continue
        
        if prev_val is None:
            prev_val = raw
            prev_time = time_val
            continue
        
        if raw != prev_val:
            prev_parsed = parse_field_value(prev_val, field_def['bits'])
            curr_parsed = parse_field_value(raw, field_def['bits'])
            
            if prev_parsed and curr_parsed:
                # Find which bits changed
                changed_bits = []
                prev_bits = {b['bit']: b['value'] for b in prev_parsed['bits']}
                curr_bits = {b['bit']: b['value'] for b in curr_parsed['bits']}
                for b in curr_parsed['bits']:
                    if b['bit'] in prev_bits and b['value'] != prev_bits[b['bit']]:
                        changed_bits.append({
                            'bit': b['bit'],
                            'name': b['name'],
                            'from': prev_bits[b['bit']],
                            'to': b['value'],
                        })
                
                changes.append({
                    'time': str(time_val)[:19] if time_val else '?',
                    'prev_time': str(prev_time)[:19] if prev_time else '?',
                    'prev_hex': prev_parsed['hex'],
                    'prev_summary': prev_parsed['summary'],
                    'curr_hex': curr_parsed['hex'],
                    'curr_summary': curr_parsed['summary'],
                    'curr_binary': curr_parsed['binary'],
                    'prev_binary': prev_parsed['binary'],
                    'curr_bits': curr_parsed['bits'],
                    'changed_bits': changed_bits,
                })
            
            prev_val = raw
            prev_time = time_val
    
    return changes
