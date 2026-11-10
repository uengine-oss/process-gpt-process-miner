"""관리자가 확정한 경계 — 빈도는 초안이고, 확정은 관리자가 한다.

2026-11-10: 관리자가 정한 필수·옵션과 사례 소속을 사례 수가 덮지 않는다. 경계에 새로 붙은 사례는
묶음에 섞지 않고 제안으로 따로 돌려준다(부르는 쪽이 관리자에게 묻는다).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lite import patterns  # noqa: E402

INTAKE, QUOTE, REPLY = "요청 메일 접수", "견적서 작성", "고객 회신"
FINANCE, CONTRACT, DESIGN = "재무 검토", "계약 검토", "디자인 검토"
PLAN, PROPOSAL = "평면도 작성", "제안서 작성"


def _rows(case, acts, t0=0):
    return [{"case_id": case, "origin_room_id": case, "source": "chat_handover", "norm_activity_label": a,
             "to_user_id": f"u-{a}", "to_user_name": a, "to_role": f"{a} 담당", "to_is_agent": False,
             "artifact_refs": [], "occurred_at": f"2026-11-{1 + t0:02d}T{i:02d}:00:00", "proc_def_id": None}
            for i, a in enumerate(acts)]


def _find(cases, decided=None, min_cases=2):
    rows, cats = [], {}
    for i, (cid, (acts, cat)) in enumerate(cases.items()):
        rows += _rows(cid, acts, t0=i)
        if cat:
            cats[cid] = cat
    return patterns.find(rows, min_cases=min_cases, categories=cats, decided=decided or [])


def _by(res):
    return {p["decided_key"] or p["key"]: p for p in res["patterns"]}


# --- 빈도는 초안, 확정은 관리자 ---

def test_admin_core_is_not_overwritten_by_frequency():
    """관리자가 재무 검토를 옵션으로 정했으면, 재무 검토가 과반이 되어도 필수가 아니다."""
    kept = {"key": "kE", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY],
            "case_ids": ["c1", "c2", "c3"]}
    res = _find({
        "c1": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, REPLY], "행사 견적"),
    }, decided=[kept])
    p = _by(res)["kE"]
    assert FINANCE not in p["core_activities"]
    assert FINANCE in p["core_by_frequency"]
    assert p["frequency"][FINANCE] == 2 and p["frequency"][INTAKE] == 3


def test_admin_required_step_stays_required_even_when_rare():
    """관리자가 필수로 정한 단계는 드물게 나와도 필수로 남는다."""
    kept = {"key": "kE", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, CONTRACT, REPLY],
            "case_ids": ["c1", "c2", "c3"]}
    res = _find({
        "c1": ([INTAKE, QUOTE, CONTRACT, REPLY], "행사 견적"),
        "c2": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "c3": ([INTAKE, QUOTE, REPLY], "행사 견적"),
    }, decided=[kept])
    p = _by(res)["kE"]
    assert CONTRACT in p["core_activities"]
    assert CONTRACT not in p["core_by_frequency"]


# --- 관리자가 확인한 소속 ---

def test_moved_case_stays_where_the_admin_put_it():
    """관리자가 옮긴 사례는 범주가 원래 쪽과 같아도 옮긴 쪽에만 있다."""
    a = {"key": "kA", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY],
         "case_ids": ["a1", "a2"], "exclude": ["x1"]}
    b = {"key": "kB", "category": "교육 일정표", "core_activities": [INTAKE, PLAN, REPLY],
         "case_ids": ["b1", "b2", "x1"]}
    res = _find({
        "a1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "a2": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "b1": ([INTAKE, PLAN, REPLY], "교육 일정표"),
        "b2": ([INTAKE, PLAN, REPLY], "교육 일정표"),
        "x1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
    }, decided=[a, b])
    by = _by(res)
    assert by["kA"]["case_ids"] == ["a1", "a2"]
    assert set(by["kB"]["case_ids"]) == {"b1", "b2", "x1"}
    assert by["kA"]["new_case_ids"] == [] and by["kB"]["new_case_ids"] == []


def test_excluded_case_goes_elsewhere_not_back():
    """아니라고 한 사례는 그 경계에 다시 붙지 않는다."""
    a = {"key": "kA", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY],
         "case_ids": ["a1", "a2"], "exclude": ["x1"]}
    res = _find({
        "a1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "a2": ([INTAKE, QUOTE, REPLY], "행사 견적"),
        "x1": ([INTAKE, QUOTE, REPLY], "행사 견적"),
    }, decided=[a], min_cases=4)
    p = _by(res)["kA"]
    assert "x1" not in p["case_ids"] and "x1" not in p["new_case_ids"]


# --- 새 사례는 제안으로 ---

def test_new_cases_come_as_a_proposal_not_mixed_in():
    """확인한 사례 넷 위에 같은 업무 둘이 더 쌓이면, 묶음은 넷 그대로이고 둘은 제안으로 온다."""
    kept = {"key": "kE", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY],
            "case_ids": ["c1", "c2", "c3", "c4"]}
    cases = {f"c{i}": ([INTAKE, QUOTE, REPLY], "행사 견적") for i in range(1, 5)}
    cases["n1"] = ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적")
    cases["n2"] = ([INTAKE, QUOTE, FINANCE, REPLY], "행사 견적")
    p = _by(_find(cases, decided=[kept]))["kE"]
    assert p["case_ids"] == ["c1", "c2", "c3", "c4"]
    assert p["case_count"] == 4
    assert p["new_case_ids"] == ["n1", "n2"]
    assert FINANCE not in p["frequency"]
    assert set(p["proposed"]["case_ids"]) == {"c1", "c2", "c3", "c4", "n1", "n2"}
    assert p["proposed"]["frequency"][FINANCE] == 2
    assert [v["count"] for v in p["proposed"]["variants"]] == [4, 2]


def test_boundary_without_case_ids_behaves_as_before():
    """경계에 case_ids 가 없으면 붙은 사례가 모두 묶음에 든다 (배포 순서를 맞추지 않아도 된다)."""
    d = {"key": "kE", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY]}
    res = _find({"c1": ([INTAKE, QUOTE, REPLY], "행사 견적"), "c2": ([INTAKE, QUOTE, REPLY], "행사 견적")}, decided=[d])
    p = _by(res)["kE"]
    assert p["case_ids"] == ["c1", "c2"] and p["new_case_ids"] == []


# --- 키 ---

def test_same_core_different_category_have_different_keys():
    """교육 일정표와 다과 견적이 모두 '요청 메일 접수·견적서 작성'이어도 키가 다르다."""
    res = _find({
        "a1": ([INTAKE, QUOTE], "교육 일정표"),
        "a2": ([INTAKE, QUOTE], "교육 일정표"),
        "b1": ([INTAKE, QUOTE], "다과 견적"),
        "b2": ([INTAKE, QUOTE], "다과 견적"),
    })
    keys = [p["key"] for p in res["patterns"]]
    assert len(keys) == 2 and len(set(keys)) == 2


def test_same_input_same_proposal():
    kept = {"key": "kE", "category": "행사 견적", "core_activities": [INTAKE, QUOTE, REPLY], "case_ids": ["c1"]}
    cases = {"c1": ([INTAKE, QUOTE, REPLY], "행사 견적"), "n1": ([INTAKE, QUOTE, DESIGN, REPLY], "행사 견적")}
    a, b = _by(_find(cases, decided=[kept]))["kE"], _by(_find(cases, decided=[kept]))["kE"]
    assert (a["new_case_ids"], a["proposed"]) == (b["new_case_ids"], b["proposed"])


def test_request_model_keeps_case_ids_optional():
    """경계의 case_ids 는 빠지면 None 이어야 예전 동작이 된다."""
    from app.server import DecidedProcess
    assert DecidedProcess(key="k").model_dump()["case_ids"] is None
    assert DecidedProcess(key="k", case_ids=[], exclude=["x"]).model_dump()["case_ids"] == []
