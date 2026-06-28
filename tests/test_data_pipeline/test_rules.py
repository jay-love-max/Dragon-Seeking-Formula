from data_pipeline.rules import RULES, _rate_limited, check_rules


class MockRow:
    pass


def test_blown_alert_rule():
    rule = [r for r in RULES if r.name == "blown_alert"][0]
    row = MockRow()
    row.blown_count = 2
    row.name = "测试"
    row.code = "000001"
    assert rule.condition(row)


def test_blown_alert_no_fire():
    rule = [r for r in RULES if r.name == "blown_alert"][0]
    row = MockRow()
    row.blown_count = 1
    assert not rule.condition(row)


def test_sector_heat_rule():
    rule = [r for r in RULES if r.name == "sector_heat"][0]
    row = MockRow()
    row.sector_limit_ups = 5
    assert rule.condition(row)


def test_check_rules_matches():
    row = MockRow()
    row.code = "000001"
    row.name = "测试"
    row.blown_count = 2
    row.sector = "计算机"
    row.sector_limit_ups = 1
    matches = check_rules(row)
    names = [r.name for r in matches]
    assert "blown_alert" in names


def test_rate_limit():
    assert not _rate_limited("blown_alert", "999999")
    assert _rate_limited("blown_alert", "999999")
    assert not _rate_limited("sector_heat", "999999")


def test_sector_heat_dedupes_by_sector():
    row = MockRow()
    row.code = "000001"
    row.name = "测试"
    row.blown_count = 0
    row.sector = "计算机"
    row.sector_limit_ups = 5
    first = check_rules(row)
    second = check_rules(row)
    assert any(r.name == "sector_heat" for r in first)
    assert not any(r.name == "sector_heat" for r in second)


def test_opportunity_alert_fires_on_score_jump():
    row = MockRow()
    row.code = "000001"
    row.name = "测试"
    row.blown_count = 1
    row.sector = "计算机"
    row.sector_limit_ups = 6
    row.score_intraday_prev = 90
    row.score_intraday = 95
    matches = check_rules(row)
    names = [r.name for r in matches]
    assert "opportunity_alert" in names
