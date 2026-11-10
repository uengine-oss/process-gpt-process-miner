"""마이닝 알고리즘 단위 테스트 — LLM 없이 결정론적으로 돈다.

알려진 로그를 넣어 기대한 구조가 나오는지 본다. 이 테스트가 마이너 품질의 기준선이다.
실행: cd services/process-miner && python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lite.discovery.dfg import build_dfg, filter_noise  # noqa: E402
from app.lite.discovery.inductive import discover, discover_from_traces  # noqa: E402
from app.discovery.process_tree import AND, LOOP, SEQ, XOR  # noqa: E402


def test_pure_sequence():
    """모든 케이스가 같은 순서 → 순차 구조."""
    traces = [["접수", "검토", "승인", "통보"]] * 5
    tree = discover_from_traces(traces)
    assert tree.kind == SEQ
    assert tree.activities() == ["접수", "검토", "승인", "통보"]


def test_exclusive_choice():
    """승인/반려로 갈리는 배타 분기."""
    traces = [["접수", "검토", "승인", "통보"]] * 4 + [["접수", "검토", "반려", "통보"]] * 3
    tree = discover_from_traces(traces)
    assert tree.kind == SEQ
    kinds = [c.kind for c in tree.children]
    assert XOR in kinds, f"XOR 분기를 찾지 못함: {tree}"
    xor = tree.children[kinds.index(XOR)]
    assert set(xor.activities()) == {"승인", "반려"}


def test_parallel():
    """두 활동이 서로 다른 순서로 번갈아 나타나면 병렬."""
    traces = [
        ["시작", "법무검토", "재무검토", "종료"],
        ["시작", "재무검토", "법무검토", "종료"],
    ] * 4
    tree = discover_from_traces(traces)
    assert tree.kind == SEQ
    kinds = [c.kind for c in tree.children]
    assert AND in kinds, f"병렬 분기를 찾지 못함: {tree}"
    par = tree.children[kinds.index(AND)]
    assert set(par.activities()) == {"법무검토", "재무검토"}


def test_self_loop_becomes_loop():
    """같은 활동이 연달아 반복되면 반복 구조."""
    traces = [
        ["접수", "보완", "보완", "승인"],
        ["접수", "보완", "승인"],
    ] * 3
    tree = discover_from_traces(traces)
    assert LOOP in repr(tree), f"반복 구조를 찾지 못함: {tree}"


def test_noise_filter_drops_rare_edge():
    """한 번뿐인 이상 경로는 min_freq 로 걷어낸다."""
    traces = [["접수", "검토", "승인"]] * 10 + [["접수", "승인"]]
    kept = filter_noise(build_dfg(traces), min_freq=2)
    assert ("접수", "승인") not in kept.edges
    assert ("접수", "검토") in kept.edges


def test_soundness_no_duplicate_activities():
    """도출된 트리에 같은 활동이 두 번 나오면 안 된다(BPMN 변환이 깨진다)."""
    traces = [
        ["A", "B", "C"],
        ["A", "C", "B"],
        ["A", "B", "D"],
        ["A", "D", "B"],
    ]
    tree = discover_from_traces(traces)
    acts = tree.activities()
    assert len(acts) == len(set(acts)), f"활동 중복: {acts}"


def test_single_activity():
    tree = discover_from_traces([["단일"]])
    assert tree.activities() == ["단일"]


def test_empty_log():
    tree = discover(build_dfg([]))
    assert tree.activities() == []


def test_optional_step_is_skippable():
    """일부 케이스에만 있는 단계는 건너뛸 수 있어야 한다(xor 에 τ 포함)."""
    traces = [["산출", "검토", "발송"]] * 5 + [["산출", "검토", "재산출", "발송"]] * 3
    tree = discover_from_traces(traces)
    assert "τ" in repr(tree), f"선택적 단계가 표현되지 않음: {tree}"
    # 필수 단계는 선택적으로 만들지 않는다
    assert repr(tree).count("τ") == 1, f"필수 단계까지 선택적이 됨: {tree}"


def test_always_present_steps_stay_mandatory():
    traces = [["A", "B", "C"]] * 4
    tree = discover_from_traces(traces)
    assert "τ" not in repr(tree), f"필수 단계가 선택적이 됨: {tree}"


def test_agent_delegation_without_label_is_excluded():
    """암묵 위임은 정규화 라벨이 없으면 활동으로 쓰지 않는다(대화 원문 유입 방지)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.lite.eventlog import pick_label

    assert pick_label({"source": "agent_delegation", "activity_label": "이거 견적 좀 뽑아줘 " * 10}) == ""
    assert pick_label({"source": "agent_delegation", "norm_activity_label": "견적 산출"}) == "견적 산출"
    assert pick_label({"source": "chat_handover", "next_activity_label": "견적서 검토"}) == "견적서 검토"
    # 너무 긴 라벨은 활동명이 아니다
    assert pick_label({"source": "chat_handover", "next_activity_label": "가" * 80}) == ""


def test_repeated_start_keeps_order_as_loop():
    """한 흐름 안에 시작 단계가 다시 나오면(접수 → 작성 → 접수) 컷이 없다.
    이때 모든 단계를 배타 분기로 묶으면 '접수가 늘 먼저' 라는 순서를 잃는다(2026-11-10 '요청 메일·견적서 작성').
    IM 의 fall-through(strict tau loop)대로 반복 단위로 끊어 본체를 찾는다."""
    traces = ([["접수", "제안서 작성", "접수"]] * 9 + [["접수", "견적서 작성"]] * 8 + [["접수", "제안서 작성"]] * 4
              + [["접수", "견적서 작성", "접수"]] * 4 + [["접수", "견적서 작성", "견적서 검토"]])
    tree = discover_from_traces(traces)
    assert tree.kind == SEQ, tree
    loop = tree.children[0]
    assert loop.kind == LOOP, f"반복으로 보지 않음: {tree}"
    body = loop.children[0]
    assert body.kind == SEQ and body.children[0].activities() == ["접수"], f"접수가 맨 앞이 아님: {tree}"
    assert set(body.children[1].activities()) == {"견적서 작성", "제안서 작성"}
    assert tree.children[1].kind == XOR and "τ" in repr(tree.children[1]), "견적서 검토는 건너뛸 수 있다"


def test_tau_loop_when_no_end_start_pair():
    """끝 단계 뒤에 시작 단계가 바로 오지 않아도, 시작 단계가 다시 나오는 곳에서 끊는다(tau loop)."""
    traces = [["A", "B", "A", "C"], ["A", "C"], ["A", "B", "A", "B", "A", "C"]]
    tree = discover_from_traces(traces)
    assert LOOP in repr(tree), tree
    acts = tree.activities()
    assert len(acts) == len(set(acts)), f"활동 중복: {acts}"


def test_branch_step_is_not_optional_within_its_branch():
    """배타 분기 갈래 안의 단계는 그 갈래로 간 사례로 센다. 견적서 갈래로 간 사례는 모두 견적서를 썼으니
    견적서 작성은 그 갈래에서 필수다(전체로 세면 건너뛸 수 있게 돼, 아무 일도 안 하는 경로가 생긴다)."""
    traces = [["접수", "제안서 작성"]] * 13 + [["접수", "견적서 작성"]] * 12 + [["접수", "견적서 작성", "견적서 검토"]]
    tree = discover_from_traces(traces)
    assert repr(tree) == "seq('접수', xor(seq('견적서 작성', xor('견적서 검토', τ)), '제안서 작성'))", tree
