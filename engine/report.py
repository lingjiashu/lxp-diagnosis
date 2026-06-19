"""
Markdown 故障分析报告生成器
"""

from datetime import datetime
from typing import Optional


def generate_report(
    historical: dict,
    event_records: Optional[dict],
    set_records: Optional[dict],
    all_violations: list,
    fault_transitions: list,
    correlated_results: list,
) -> str:
    """
    生成完整的故障分析 Markdown 报告。
    """
    lines = []
    
    # ── 标题 ──
    sn = historical.get("serial_number", "未知")
    time_range = historical.get("time_range", {})
    start_str = str(time_range.get("start", "?"))[:19] if time_range.get("start") else "?"
    end_str = str(time_range.get("end", "?"))[:19] if time_range.get("end") else "?"
    
    lines.append(f"# 🔬 LXP 逆变器故障分析报告")
    lines.append(f"")
    lines.append(f"**设备序列号**: `{sn}`")
    lines.append(f"**数据时间范围**: {start_str} → {end_str}")
    lines.append(f"**数据总行数**: {historical.get('total_rows', 0)}")
    lines.append(f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")
    
    # ── 事件概览 ──
    if event_records:
        lines.append(f"---")
        lines.append(f"## 📋 事件记录概览")
        lines.append(f"")
        lines.append(f"| # | 类型 | 事件 | 开始时间 | 恢复时间 |")
        lines.append(f"|---|------|------|----------|----------|")
        for i, evt in enumerate(event_records.get("events", [])):
            etype = "🔴" if evt["type"] == "Fault" else "🟡"
            st = str(evt["start_time"])[:19] if evt["start_time"] else "?"
            rt = str(evt["recovered_time"])[:19] if evt.get("recovered_time") else "未恢复"
            lines.append(f"| {i+1} | {etype} {evt['type']} | {evt['event']} | {st} | {rt} |")
        lines.append(f"")
    
    # ── 设置操作概览 ──
    if set_records:
        lines.append(f"---")
        lines.append(f"## ⚙️ 操作设置记录概览")
        lines.append(f"")
        lines.append(f"共 **{set_records.get('total_records', 0)}** 条操作记录")
        lines.append(f"")
        lines.append(f"| 时间 | 用户 | 参数 | 值 | 结果 |")
        lines.append(f"|------|------|------|-----|------|")
        for rec in set_records.get("records", []):
            t = str(rec["time"])[:19] if rec["time"] else "?"
            result_icon = "✅" if rec["result"] == "Success" else "❌"
            lines.append(f"| {t} | {rec['username']} | {rec['parameter']} | {rec['value']} | {result_icon} {rec['result']} |")
        lines.append(f"")
    
    # ── 物理判据违反汇总 ──
    lines.append(f"---")
    lines.append(f"## ⚡ 强故障特征扫描结果")
    lines.append(f"")
    lines.append(f"扫描规则：")
    lines.append(f"1. **vBat ≈ Vbat_Inv**（误差 ≤ 1V）")
    lines.append(f"2. **vBUS2 ≈ vBat × 6**（误差 ≤ 20V，Standby 状态下跳过）")
    lines.append(f"3. **vBusP × 2 ≈ vBus1**（误差 ≤ 6V）")
    lines.append(f"4. **Fault 状态直接触发**（Status 包含 fault 关键字即触发分析）")
    lines.append(f"")
    
    if not all_violations:
        lines.append(f"> ✅ **未发现物理判据违反，硬件状态正常。**")
        lines.append(f"")
    else:
        critical_count = sum(1 for v in all_violations if v["severity"] == "critical")
        warning_count = sum(1 for v in all_violations if v["severity"] == "warning")
        
        lines.append(f"| 统计 | 数量 |")
        lines.append(f"|------|------|")
        lines.append(f"| 🔴 严重违反（≥2条同时违反）| **{critical_count}** |")
        lines.append(f"| 🟡 警告（1条违反）| **{warning_count}** |")
        lines.append(f"| 📊 总计异常时间点 | **{len(all_violations)}** |")
        lines.append(f"")
        
        # Detail for each violation
        for i, v in enumerate(all_violations):
            t = str(v["time"])[:19] if v["time"] else "?"
            m = v["metrics"]
            sev = "🔴" if v["severity"] == "critical" else "🟡"
            rules = ", ".join([r["rule"].split(" (")[0] for r in v["violations"]])
            
            lines.append(f"### {sev} 异常 #{i+1}: {t}")
            lines.append(f"")
            lines.append(f"**状态**: {v['status']} | **Fault**: {v['fault_code']} | **Warn**: {v['warning_code']} | **违反**: {rules}")
            lines.append(f"")
            
            # Violation details
            for r in v["violations"]:
                line = f"- {r['detail']}"
                if r.get("inference"):
                    line += f"  ⚠️ **推断**: {r['inference']}"
                lines.append(line)
            lines.append(f"")
            
            # InternalFault parsing — always show for current row
            inf = v.get("internal_fault")
            if inf:
                lines.append(f"**Internal Fault 解析**: `{inf['hex']}` → `{inf['binary']}` → **{inf['fault_summary']}**")
                lines.append(f"")
                lines.append(f"| Bit | 名称 | 值 | 状态 |")
                lines.append(f"|-----|------|-----|------|")
                for bit_info in inf["active_bits"]:
                    state = "🔴 异常" if bit_info["value"] == 1 else "✅ 正常"
                    lines.append(f"| {bit_info['bit']} | {bit_info['name']} | {bit_info['value']} | {state} |")
                lines.append(f"")
            
            # Three-row data: prev / current / next
            lines.append(f"**异常时间点上下文数据（上一笔 → 当前 → 下一笔）**:")
            lines.append(f"")
            lines.append(f"| 字段 | ◀ 上一笔 | ⚡ 当前（异常） | ▶ 下一笔 |")
            lines.append(f"|------|----------|-----------------|----------|")
            
            prev = v.get("prev_row")
            curr = {
                "time": t,
                "status": v['status'],
                "fault_code": v['fault_code'],
                "warning_code": v['warning_code'],
                "SOC": m.get('SOC'),
                "BatCurrent": m.get('BatCurrent'),
                "pCharge": m.get('pCharge'),
                "pDisCharge": m.get('pDisCharge'),
                "vpv1": m.get('vpv1'),
                "vpv2": m.get('vpv2'),
                "vpv3": m.get('vpv3'),
                "ppv1": m.get('ppv1'),
                "ppv2": m.get('ppv2'),
                "ppv3": m.get('ppv3'),
                "vacr": m.get('vacr'),
                "fac": m.get('fac'),
                "pToGrid": m.get('pToGrid'),
                "pToUser": m.get('pToUser'),
                "pLoad": m.get('pLoad'),
                "vBusP": m.get('vBusP'),
                "vBus1": m.get('vBus1'),
                "vBus2": m.get('vBUS2'),
            }
            next_r = v.get("next_row")
            
            def _fmt(val, unit=""):
                if val is None:
                    return "—"
                if isinstance(val, float):
                    return f"{val:.1f}{unit}"
                return f"{val}{unit}"
            
            fields = [
                ("时间", "time", ""),
                ("Status", "status", ""),
                ("Fault Code", "fault_code", ""),
                ("Warn Code", "warning_code", ""),
                ("SOC", "SOC", "%"),
                ("BatCurrent", "BatCurrent", "A"),
                ("pCharge", "pCharge", "W"),
                ("pDisCharge", "pDisCharge", "W"),
                ("vpv1", "vpv1", "V"),
                ("vpv2", "vpv2", "V"),
                ("vpv3", "vpv3", "V"),
                ("ppv1 (Ppv1)", "ppv1", "W"),
                ("ppv2 (Ppv2)", "ppv2", "W"),
                ("ppv3 (Ppv3)", "ppv3", "W"),
                ("vacr", "vacr", "V"),
                ("fac", "fac", "Hz"),
                ("pToGrid", "pToGrid", "W"),
                ("pToUser", "pToUser", "W"),
                ("pLoad", "pLoad", "W"),
                ("vBusP", "vBusP", "V"),
                ("vBus1", "vBus1", "V"),
                ("vBus2", "vBus2", "V"),
                ("InternalFault (HEX→含义)", "internal_fault_hex", ""),
            ]
            
            for label, key, unit in fields:
                if key == "internal_fault_hex":
                    def _inf_hex(row_data):
                        if not row_data: return "—"
                        inf_r = row_data.get("internal_fault")
                        if not inf_r: return "—"
                        return f"{inf_r['hex']}→{inf_r['fault_summary']}"
                    pv = _inf_hex(prev)
                    cv = _inf_hex({"internal_fault": inf})
                    nv = _inf_hex(next_r)
                else:
                    pv = _fmt(prev.get(key) if prev else None, unit)
                    cv = _fmt(curr.get(key), unit)
                    nv = _fmt(next_r.get(key) if next_r else None, unit)
                lines.append(f"| {label} | {pv} | {cv} | {nv} |")
            
            lines.append(f"")
            
            # Show InternalFault for prev/next too — always show
            for label, row_data in [("上一笔", prev), ("下一笔", next_r)]:
                if row_data:
                    inf_r = row_data.get("internal_fault")
                    if inf_r:
                        lines.append(f"**{label} Internal Fault**: `{inf_r['hex']}` → `{inf_r['binary']}` → {inf_r['fault_summary']}")
                        lines.append(f"")
            
            lines.append(f"---")
            lines.append(f"")
    
    # ── Fault Code 突变分析 ──
    lines.append(f"---")
    lines.append(f"## 🔄 Fault Code 突变分析")
    lines.append(f"")
    
    if not fault_transitions:
        lines.append(f"> 未检测到 fault code 突变。")
        lines.append(f"")
    else:
        # Filter to only interesting transitions (0→non-zero or significant changes)
        interesting = [t for t in fault_transitions 
                       if t.get("violations_before") or t.get("violations_after")]
        
        lines.append(f"共检测到 **{len(fault_transitions)}** 次 fault code 变化，"
                    f"其中 **{len(interesting)}** 次伴随物理判据异常。")
        lines.append(f"")
        
        for i, trans in enumerate(fault_transitions):
            t = str(trans["transition_time"])[:19] if trans["transition_time"] else "?"
            has_violations = bool(trans.get("violations_before") or trans.get("violations_after"))
            marker = "⚡" if has_violations else "ℹ️"
            
            lines.append(f"### {marker} 突变 #{i+1}: {trans['from_code']} → {trans['to_code']}")
            lines.append(f"")
            lines.append(f"**时间**: {t}")
            lines.append(f"")
            
            # Violations around transition
            vb = trans.get("violations_before", [])
            va = trans.get("violations_after", [])
            
            if vb:
                lines.append(f"**突变前异常** ({len(vb)} 个时间点):")
                for v in vb:
                    lines.append(f"- {str(v['time'])[:19]}: {v['violation_count']} 条违反 "
                                f"(fault={v['fault_code']}, warn={v['warning_code']})")
                lines.append(f"")
            
            if va:
                lines.append(f"**突变后异常** ({len(va)} 个时间点):")
                for v in va:
                    lines.append(f"- {str(v['time'])[:19]}: {v['violation_count']} 条违反 "
                                f"(fault={v['fault_code']}, warn={v['warning_code']})")
                lines.append(f"")
            
            # Related events
            if trans.get("related_events"):
                lines.append(f"**关联事件**:")
                for evt in trans["related_events"][:5]:
                    direction = "←" if evt["direction"] == "before" else "→" if evt["direction"] == "after" else "⟷"
                    lines.append(f"- {direction} {abs(evt['time_diff_minutes']):.0f}min: "
                                f"{'🔴' if evt['type']=='Fault' else '🟡'} {evt['event']}")
                lines.append(f"")
            
            # Related settings
            if trans.get("related_settings"):
                lines.append(f"**关联操作设置**:")
                for s in trans["related_settings"][:5]:
                    direction = "←" if s["direction"] == "before" else "→" if s["direction"] == "after" else "⟷"
                    icon = "✅" if s["result"] == "Success" else "❌"
                    lines.append(f"- {direction} {abs(s['time_diff_minutes']):.0f}min: "
                                f"{icon} {s['parameter']} = {s['value']} ({s['username']})")
                lines.append(f"")
            
            # Data window table
            lines.append(f"**突变前后数据**:")
            lines.append(f"")
            lines.append(f"| 方向 | 时间 | Fault | Warn | vBat | Vbat_Inv | vBUS2 | vBus1 | vBusP | SOC |")
            lines.append(f"|------|------|-------|------|------|----------|-------|-------|-------|-----|")
            
            for row in trans.get("window_before", [])[-3:]:  # Last 3 before
                rt = str(row["time"])[:19] if row["time"] else "?"
                lines.append(f"| ◀ 前 | {rt} | {row.get('fault_code','')} | {row.get('warning_code','')} | "
                            f"{row.get('vBat','?')} | {row.get('Vbat_Inv','?')} | "
                            f"{row.get('vBUS2','?')} | {row.get('vBus1','?')} | {row.get('vBusP','?')} | "
                            f"{row.get('SOC','?')}% |")
            
            for row in trans.get("window_after", [])[:3]:  # First 3 after
                rt = str(row["time"])[:19] if row["time"] else "?"
                lines.append(f"| ▶ 后 | {rt} | {row.get('fault_code','')} | {row.get('warning_code','')} | "
                            f"{row.get('vBat','?')} | {row.get('Vbat_Inv','?')} | "
                            f"{row.get('vBUS2','?')} | {row.get('vBus1','?')} | {row.get('vBusP','?')} | "
                            f"{row.get('SOC','?')}% |")
            lines.append(f"")
    
    # ── 诊断结论 ──
    lines.append(f"---")
    lines.append(f"## 🎯 诊断结论")
    lines.append(f"")
    
    if not all_violations:
        lines.append(f"✅ **数据范围内未发现硬件物理判据异常。**")
        lines.append(f"")
        lines.append(f"逆变器电压关系（vBat→Vbat_Inv, vBUS2/vBat, vBusP/vBus1）均符合预期。")
    else:
        critical = [v for v in all_violations if v["severity"] == "critical"]
        
        # Check which rules are most violated
        rule_counts = {}
        for v in all_violations:
            for r in v["violations"]:
                rule_name = r["rule"].split(" (")[0]
                rule_counts[rule_name] = rule_counts.get(rule_name, 0) + 1
        
        lines.append(f"### 风险等级")
        lines.append(f"")
        if critical:
            lines.append(f"🔴 **高风险** — 发现 **{len(critical)}** 个严重违反时间点（≥2条判据同时违反）")
        else:
            lines.append(f"🟡 **注意** — 发现 {len(all_violations)} 个单条判据违反时间点")
        lines.append(f"")
        
        lines.append(f"### 判据违反统计")
        lines.append(f"")
        for rule, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- **{rule}**: {count} 次违反")
        lines.append(f"")
        
        lines.append(f"### 建议")
        lines.append(f"")
        
        if rule_counts.get("vBat一致性", 0) > 0:
            lines.append(f"- ⚠️ **vBat/Vbat_Inv 不一致**: 检查电池电压采样电路、ADC 校准、采样电阻分压网络。可能是 BMS 通讯异常或采样板故障。")
        if rule_counts.get("vBUS2比例", 0) > 0:
            lines.append(f"- ⚠️ **vBUS2/vBat 比例异常**: 检查 BUS 电容、DC-DC 变换器、BUS 电压采样电路。可能是 BUS 电容老化或 LLC 谐振参数偏移。")
        if rule_counts.get("vBusP半压", 0) > 0:
            lines.append(f"- ⚠️ **vBusP/vBus1 半压关系异常**: 检查 BUS 中点电压平衡、上下桥臂驱动对称性、母线电容均压电阻。")
        if rule_counts.get("充放电状态下BUS2异常低", 0) > 0:
            lines.append(f"- ⚠️ **充放电状态下BUS2异常低**: 在运行状态下BUS2无电压或极低，可能是BUS电容失效、LLC未启动、或BUS采样电路故障。")

        lines.append(f"")

    # ── 附录：判据说明 ──
    lines.append(f"---")
    lines.append(f"## 📐 附录：物理判据说明")
    lines.append(f"")
    lines.append(f"### 判据 1: vBat ≈ Vbat_Inv（≤1V）")
    lines.append(f"vBat 是电池端电压（由 BMS 上报），Vbat_Inv 是逆变器侧采集的电池电压。")
    lines.append(f"两者应基本一致。差异 >1V 说明采样偏差或线损异常。")
    lines.append(f"")
    lines.append(f"### 判据 2: vBUS2 ≈ vBat × 6（≤20V）")
    lines.append(f"LLC 谐振变换器将电池电压升压到 BUS 电压，升压比 ≈ 6:1。")
    lines.append(f"偏差 >20V 说明 BUS 电压异常或变压器匝比偏移。")
    lines.append(f"")
    lines.append(f"### 判据 3: vBusP × 2 ≈ vBus1（≤6V）")
    lines.append(f"BUS 采用双电容串联中点引出拓扑，vBusP 为半母线电压。")
    lines.append(f"正常时 vBusP × 2 ≈ vBus1。偏差 >6V 说明母线中点不平衡。")
    lines.append(f"")
    lines.append(f"### 判据 4: 充放电状态下 BUS2 异常低")
    lines.append(f"当逆变器处于 charge/discharge/fault 状态且电池电压 >40V 时，")
    lines.append(f"vBUS2 应不低于 vBat × 6 - 200V。若 vBUS2 极低，说明 LLC 未正常启动或 BUS 电容失效。")
    lines.append(f"")

    return "\n".join(lines)
