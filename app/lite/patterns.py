"""반복 업무 묶기 — 한 테넌트의 인계 기록에는 서로 다른 업무가 섞여 있다.

무엇을 요청받은 업무인지(업무 범주)가 묶음을 정한다. 범주가 같은 사례는 한 묶음이고,
그 안의 단계 차이(분기·병렬·반복·건너뜀)는 한 묶음의 변형으로 둔다.

  케이스 → 범주별 묶음 → 묶음마다 필수 단계(절반 이상에 나온 단계)와 옵션 단계

범주 판단은 여기서 하지 않는다. 부르는 쪽(Lite)이 사례마다 한 번 정해 넘긴다 — 그래야
같은 입력에 같은 묶음이 나온다. 이 모듈에는 무작위성도 LLM 도 없다.

관리자가 정식 등록·보류한 프로세스와 이미 보인 추천(decided, 경계)은 묶음 하나로 고정한다. 두
경계가 한 묶음으로 합쳐지지 않게 하려는 것이다. 범주가 같은 경계가 여럿이면 필수 단계를 더 많이
맞추는 쪽에 붙는다.

빈도는 초안이고 확정은 관리자가 한다(2026-11-10). 경계의 필수 단계는 받은 값을 그대로 쓰고, 빈도로
본 결과는 core_by_frequency 로 따로 준다. 경계에 관리자가 확인한 사례(case_ids)가 오면 묶음의 모양은
그 사례로만 만들고, 새로 붙은 사례는 new_case_ids · proposed 로 나눠 준다 — 부르는 쪽이 관리자
확인 없이 프로세스를 바꾸지 않게.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from . import eventlog

MIN_CASES = 3
MIN_CASE_LEN = 2

# 확인 필요 사유
NO_CATEGORY = "no_category"
NO_CORE_STEP = "no_core_step"


def pattern_key(core: list[str], category: str = "") -> str:
    """새 묶음의 키. 범주가 다르면 필수 단계가 같아도 다른 키다 (교육 일정표 · 다과 견적)."""
    body = "|".join(sorted(core))
    return hashlib.sha1((f"{category}#{body}" if category else body).encode("utf-8")).hexdigest()[:12]


def _core_of(traces: dict[str, list[str]], case_ids: list[str]) -> list[str]:
    """묶음의 필수 단계 — 사례의 절반을 넘는 수에 나온 단계.

    정확히 절반인 단계는 분기의 한쪽이다(넷 중 둘은 재무 검토, 둘은 계약 검토). 필수로 보면
    두 가지 분기가 모두 필수가 되어 어느 사례도 묶음의 모양과 맞지 않는다. 그래서 과반으로 본다.
    """
    if not case_ids:
        return []
    freq = Counter(a for c in case_ids for a in set(traces[c]))
    return [a for a, n in freq.items() if n * 2 > len(case_ids)]


def find(rows: list[dict], *, min_cases: int = MIN_CASES,
         categories: dict[str, str] | None = None,
         decided: list[dict] | None = None) -> dict:
    """반복 업무 묶음과 확인 필요 사례.

    categories: 사례 → 업무 범주. 없는 사례는 묶지 않고 확인 필요로 돌려준다.
    decided:    경계 목록. 각 항목은 key · category · core_activities, 선택으로 case_ids(관리자가 확인한
                사례 — 먼저 넣는다) · exclude(그 프로세스가 아니라고 한 사례). 결정 순서대로 준다.
    """
    categories = dict(categories or {})
    decided = list(decided or [])

    # 이미 정의된 프로세스에서 나온 기록이 있는 사례는 통째로 뺀다 (확인 필요에도 담지 않는다)
    defined_cases = {r.get("origin_room_id") or r.get("case_id") for r in rows if r.get("proc_def_id")}
    rows = [r for r in rows if (r.get("origin_room_id") or r.get("case_id")) not in defined_cases]
    events = eventlog.build_events(rows)
    traces = {c: t for c, t in eventlog.to_traces(events).items() if len(t) >= MIN_CASE_LEN}
    by_case: dict[str, list] = defaultdict(list)
    for e in events:
        if e.case_id in traces:
            by_case[e.case_id].append(e)

    # 사례 순서를 고정한다 — 처음 기록된 시각, 같으면 이름
    cases = sorted(traces, key=lambda c: (str(by_case[c][0].occurred_at), c))

    decided_cases: dict[str, list[str]] = {d["key"]: [] for d in decided}
    new_cases: dict[str, list[str]] = {d["key"]: [] for d in decided}
    by_category: dict[str, list[str]] = defaultdict(list)
    unclassified: list[dict] = []

    def unclear(case_id: str, reason: str) -> None:
        unclassified.append({"case_id": case_id, "trace": list(traces[case_id]), "reason": reason})

    # 관리자가 확인한 소속이 범주·필수 단계보다 앞선다 (한 사례는 먼저 나온 경계 하나에만)
    pinned: dict[str, str] = {}
    for d in decided:
        for c in d.get("case_ids") or []:
            if c in traces and c not in pinned:
                pinned[c] = d["key"]
    excluded = {d["key"]: set(d.get("exclude") or []) for d in decided}
    # case_ids 를 준 경계는 새로 붙은 사례를 제안으로 나눈다. 주지 않았으면 예전처럼 섞는다
    tracks = {d["key"]: d.get("case_ids") is not None for d in decided}

    for c in cases:
        if c in pinned:
            decided_cases[pinned[c]].append(c)
            continue
        category = categories.get(c)
        if not category:
            unclear(c, NO_CATEGORY)
            continue
        here = set(traces[c])
        # 범주가 같은 경계 중, 필수 단계를 더 많이 맞추는 쪽. 같으면 먼저 결정된 쪽
        best = None
        for i, d in enumerate(decided):
            if d.get("category") != category or c in excluded[d["key"]]:
                continue
            hit = len(here & set(d.get("core_activities") or []))
            if best is None or hit > best[0]:
                best = (hit, i, d)
        if best is None:
            by_category[category].append(c)
        elif best[0] == 0:
            unclear(c, NO_CORE_STEP)
        elif tracks[best[2]["key"]]:
            new_cases[best[2]["key"]].append(c)
        else:
            decided_cases[best[2]["key"]].append(c)

    groups: list[tuple[dict | None, str, list[str], list[str]]] = []
    for d in decided:
        ids = decided_cases[d["key"]]
        # 경계의 필수 단계는 관리자가 확정한 값이다 — 빈도로 다시 정하지 않는다 (빈 값일 때만 빈도)
        core = list(d.get("core_activities") or []) or _core_of(traces, ids)
        groups.append((d, d.get("category") or "", ids, core))
    for category in sorted(by_category):
        ids = by_category[category]
        core = _core_of(traces, ids)
        # 그 묶음의 필수 단계를 하나도 거치지 않은 사례는 범주가 틀렸을 수 있다 — 묻는다
        kept = [c for c in ids if set(traces[c]) & set(core)]
        for c in ids:
            if c not in kept:
                unclear(c, NO_CORE_STEP)
        if len(kept) < min_cases:
            continue
        groups.append((None, category, kept, core))

    def first_at(c: str) -> str:
        return str(by_case[c][0].occurred_at)

    def frequency(ids: list[str]) -> dict[str, int]:
        freq = Counter(a for c in ids for a in set(traces[c]))
        return {a: freq[a] for a in sorted(freq, key=lambda a: (-freq[a], a))}

    def variants_of(ids: list[str]) -> list[dict]:
        return [{"trace": list(t), "count": n} for t, n in Counter(tuple(traces[c]) for c in ids).most_common()]

    out: list[dict] = []
    for d, category, ids, core in groups:
        evs = [e for c in ids for e in by_case[c]]
        variants = Counter(tuple(traces[c]) for c in ids)
        main = list(variants.most_common(1)[0][0]) if variants else []
        seen = [a for c in ids for a in traces[c]]
        optional = sorted({a for a in seen} - set(core))
        steps = []
        for a in main:
            mine = [e for e in evs if e.activity == a]
            roles = Counter(e.role for e in mine if e.role)
            people = Counter(e.resource_name for e in mine if e.resource_name)
            steps.append({
                "activity": a,
                "cases": sum(1 for c in ids if a in traces[c]),
                "by_agent": sum(1 for e in mine if e.is_agent),
                "total": len(mine),
                "role": roles.most_common(1)[0][0] if roles else "",
                "performers": [n for n, _ in people.most_common(3)],
                "tools": [t for t, _ in Counter(t for e in mine for t in e.tools).most_common()],
                "skills": [k for k, _ in Counter(k for e in mine for k in e.skills).most_common()],
            })
        when = sorted(str(e.occurred_at) for e in evs)
        key = d["key"] if d else pattern_key(core, category)
        new = sorted(new_cases.get(d["key"], []) if d else [], key=first_at)
        both = sorted(ids + new, key=first_at)
        out.append({
            "key": key,
            "decided_key": d["key"] if d else "",
            "category": category,
            "process_id": f"mined_{key}",
            "case_ids": sorted(ids, key=first_at),
            "case_count": len(ids),
            "event_count": len(evs),
            "core_activities": sorted(core, key=main.index) if main and all(a in main for a in core) else sorted(core),
            "optional_activities": optional,
            "core_by_frequency": sorted(_core_of(traces, ids)),
            "frequency": frequency(ids),
            "new_case_ids": new,
            "proposed": {
                "case_ids": both,
                "case_count": len(both),
                "variants": variants_of(both),
                "frequency": frequency(both),
                "core_by_frequency": sorted(_core_of(traces, both)),
            } if new else None,
            "main_variant": main,
            "variants": variants_of(ids),
            "steps": steps,
            "first_seen": when[0] if when else None,
            "last_seen": when[-1] if when else None,
            "automation_rate": round(sum(1 for e in evs if e.is_agent) / len(evs), 3) if evs else 0,
        })
    out.sort(key=lambda p: (-p["case_count"], p["last_seen"] or ""))
    unclassified.sort(key=lambda u: u["case_id"])
    return {"patterns": out, "unclassified": unclassified}
