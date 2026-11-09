"""업무 범주로 묶는다 — 단계 이름 겹침이 아니라 무엇을 요청받은 업무인지가 묶음을 정한다.

2026-11-06 회의: "식별의 기본 전략은 하나의 의도" · "너무 많이 쪼개 놓았다"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lite import patterns  # noqa: E402

INTAKE, QUOTE, REPLY = "요청 메일 접수", "견적서 작성", "고객 회신"
FINANCE, CONTRACT, DESIGN = "재무 검토", "계약 검토", "디자인 검토"
PLAN, PROPOSAL = "평면도 작성", "제안서 작성"


def _rows(case, acts, t0=0, proc=None):
    return [{"case_id": case, "origin_room_id": case, "source": "chat_handover", "norm_activity_label": a,
             "to_user_id": f"u-{a}", "to_user_name": a, "to_role": f"{a} 담당", "to_is_agent": False,
             "artifact_refs": [], "occurred_at": f"2026-11-{1 + t0:02d}T{i:02d}:00:00", "proc_def_id": proc}
            for i, a in enumerate(acts)]


def _find(cases, decided=None, min_cases=4):
    """cases: {case_id: (활동 목록, 범주)}"""
    rows, cats = [], {}
    for i, (cid, (acts, cat)) in enumerate(cases.items()):
        rows += _rows(cid, acts, t0=i)
        if cat:
            cats[cid] = cat
    return patterns.find(rows, min_cases=min_cases, categories=cats, decided=decided or [])


def _only(res):
    assert len(res["patterns"]) == 1, [p["category"] for p in res["patterns"]]
    return res["patterns"][0]


# --- 업무 범주가 묶음을 정한다 ---

def test_review_step_differs_stays_one_group():
    """검토 단계만 다른 업무 넷은 한 묶음이고, 검토는 옵션 단계다."""
    res = _find({
        "c1": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, CONTRACT, REPLY], "행사 견적"),
        "c4": ([INTAKE, QUOTE, CONTRACT, REPLY], "행사 견적"),
    })
    p = _only(res)
    assert p["case_count"] == 4
    assert set(p["core_activities"]) == {INTAKE, QUOTE, REPLY}
    assert set(p["optional_activities"]) == {FINANCE, CONTRACT}


def test_skipped_and_repeated_steps_stay_one_group():
    """건너뛴 업무와 검토를 두 번 거친 업무도 같은 범주면 한 묶음이다."""
    res = _find({
        "c1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, FINANCE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c4": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
    })
    assert _only(res)["case_count"] == 4


def test_same_steps_different_category_are_two_groups():
    """단계 이름이 모두 같아도 범주가 다르면 다른 묶음이다."""
    res = _find({
        "a1": ([INTAKE, QUOTE, DESIGN, REPLY], "매장 설계"),
        "a2": ([INTAKE, QUOTE, DESIGN, REPLY], "매장 설계"),
        "b1": ([INTAKE, QUOTE, DESIGN, REPLY], "워크숍 운영"),
        "b2": ([INTAKE, QUOTE, DESIGN, REPLY], "워크숍 운영"),
    }, min_cases=2)
    assert {p["category"] for p in res["patterns"]} == {"매장 설계", "워크숍 운영"}


def test_long_and_short_flows_of_one_category_stay_together():
    """단계 수가 크게 달라도 같은 범주면 갈라지지 않는다 (겹침 비율로는 갈라졌다)."""
    res = _find({
        "c1": ([INTAKE, PLAN, PROPOSAL, QUOTE, FINANCE, REPLY], "매장 설계"),
        "c2": ([INTAKE, PLAN, PROPOSAL, QUOTE, FINANCE, REPLY], "매장 설계"),
        "c3": ([INTAKE, QUOTE, REPLY], "매장 설계"),
        "c4": ([INTAKE, QUOTE, REPLY], "매장 설계"),
    })
    assert _only(res)["case_count"] == 4


# --- 결정된 프로세스의 경계를 지킨다 ---

DECIDED_A = {"key": "kA", "category": "다과 견적", "core_activities": [INTAKE, QUOTE, FINANCE, REPLY]}
DECIDED_B = {"key": "kB", "category": "매장 설계", "core_activities": [INTAKE, PLAN, QUOTE, DESIGN, REPLY]}


def test_two_decided_processes_do_not_merge():
    """두 결정 모두와 이름이 겹치는 업무가 들어와도 두 묶음은 그대로다."""
    res = _find({
        "a1": ([INTAKE, QUOTE, FINANCE, REPLY], "다과 견적"),
        "a2": ([INTAKE, QUOTE, FINANCE, REPLY], "다과 견적"),
        "b1": ([INTAKE, PLAN, QUOTE, DESIGN, REPLY], "매장 설계"),
        "b2": ([INTAKE, PLAN, QUOTE, DESIGN, REPLY], "매장 설계"),
        "x1": ([INTAKE, QUOTE, REPLY], "다과 견적"),
    }, decided=[DECIDED_A, DECIDED_B], min_cases=2)
    keys = {p["decided_key"] for p in res["patterns"]}
    assert keys == {"kA", "kB"}
    by = {p["decided_key"]: p for p in res["patterns"]}
    assert set(by["kA"]["case_ids"]) == {"a1", "a2", "x1"}
    assert set(by["kB"]["case_ids"]) == {"b1", "b2"}


def test_decided_group_keeps_its_key():
    res = _find({
        "a1": ([INTAKE, QUOTE, FINANCE, REPLY], "다과 견적"),
        "a2": ([INTAKE, QUOTE, FINANCE, REPLY], "다과 견적"),
    }, decided=[DECIDED_A], min_cases=2)
    assert _only(res)["key"] == "kA"


def test_decided_group_survives_below_min_cases():
    """결정된 프로세스의 묶음은 사례가 적어도 돌려준다."""
    res = _find({"a1": ([INTAKE, QUOTE, FINANCE, REPLY], "다과 견적")}, decided=[DECIDED_A], min_cases=4)
    assert _only(res)["decided_key"] == "kA"


def test_case_joins_the_decided_matching_more_core_steps():
    """범주가 같은 결정이 둘이면 필수 단계를 더 많이 맞추는 쪽에 붙는다."""
    short = {"key": "k1", "category": "견적", "core_activities": [INTAKE, QUOTE, REPLY]}
    long = {"key": "k2", "category": "견적", "core_activities": [INTAKE, PLAN, PROPOSAL, QUOTE, REPLY]}
    res = _find({"c1": ([INTAKE, PLAN, PROPOSAL, QUOTE, REPLY], "견적")},
                decided=[short, long], min_cases=1)
    by = {p["decided_key"]: p for p in res["patterns"]}
    assert by["k2"]["case_ids"] == ["c1"]
    assert by["k1"]["case_ids"] == []


# --- 확인 필요 ---

def test_case_without_category_is_unclassified():
    res = _find({
        "c1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, REPLY], None),
    }, min_cases=2)
    assert [u["case_id"] for u in res["unclassified"]] == ["c3"]
    assert res["unclassified"][0]["reason"] == "no_category"
    assert res["unclassified"][0]["trace"] == [INTAKE, QUOTE, REPLY]


def test_case_sharing_no_core_step_is_unclassified():
    """범주는 같지만 그 묶음의 필수 단계를 하나도 거치지 않은 업무는 묻는다."""
    res = _find({
        "c1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c4": ([PLAN, PROPOSAL], "행사 견적"),
    }, min_cases=3)
    assert [u["case_id"] for u in res["unclassified"]] == ["c4"]
    assert res["unclassified"][0]["reason"] == "no_core_step"
    assert _only(res)["case_count"] == 3


def test_defined_process_cases_are_not_unclassified():
    res = _find({"c1": ([INTAKE, QUOTE, REPLY], "행사 견적")}, min_cases=1)
    rows = [r for r in _rows("c1", [INTAKE, QUOTE, REPLY], proc="mined_x")]
    res2 = patterns.find(rows, min_cases=1, categories={"c1": "행사 견적"}, decided=[])
    assert res["patterns"] and not res2["patterns"] and not res2["unclassified"]


def test_without_categories_everything_is_unclassified():
    """범주를 주지 않으면 묶지 않고 모두 확인 필요로 돌려준다."""
    rows = _rows("c1", [INTAKE, QUOTE, REPLY]) + _rows("c2", [INTAKE, QUOTE, REPLY], t0=1)
    res = patterns.find(rows, min_cases=1)
    assert res["patterns"] == []
    assert {u["case_id"] for u in res["unclassified"]} == {"c1", "c2"}


# --- 재현성 ---

def test_same_input_gives_the_same_groups():
    cases = {
        "c1": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, CONTRACT, REPLY], "행사 견적"),
        "c3": ([INTAKE, PLAN, QUOTE, REPLY], "매장 설계"),
        "c4": ([INTAKE, PLAN, QUOTE, DESIGN, REPLY], "매장 설계"),
    }
    a, b = _find(cases, min_cases=2), _find(cases, min_cases=2)
    assert [(p["key"], p["case_ids"], p["core_activities"]) for p in a["patterns"]] \
        == [(p["key"], p["case_ids"], p["core_activities"]) for p in b["patterns"]]


def test_key_does_not_change_when_optional_steps_change():
    base = {f"c{i}": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적") for i in range(4)}
    k1 = _only(_find(base))["key"]
    base["c9"] = ([INTAKE, QUOTE, CONTRACT, REPLY], "행사 견적")
    assert _only(_find(base))["key"] == k1
