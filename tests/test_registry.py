    for n in low_risk:
        assert n in by_name, f"缺工具: {n}"
        assert by_name[n].risk == "low", f"{n} 风险等级应为 low，实际 {by_name[n].risk}"
    for n in high_risk:
        assert n in by_name, f"缺工具: {n}"
        assert by_name[n].risk == "high", f"{n} 风险等级应为 high，实际 {by_name[n].risk}"
