"""반복 업무 묶기 — 한 테넌트의 인계 기록에는 서로 다른 업무가 섞여 있다.

무엇을 요청받은 업무인지(업무 범주)가 묶음을 정한다. 범주가 같은 사례는 한 묶음이고,
그 안의 단계 차이(분기·병렬·반복·건너뜀)는 한 묶음의 변형으로 둔다.

  케이스 → 범주별 묶음 → 묶음마다 필수 단계(절반 이상에 나온 단계)와 옵션 단계

범주 판단은 여기서 하지 않는다. 부르는 쪽(Lite)이 사례마다 한 번 정해 넘긴다 — 그래야
같은 입력에 같은 묶음이 나온다. 이 모듈에는 무작위성도 LLM 도 없다.

관리자가 정식 등록·보류한 프로세스(decided)는 묶음 하나로 고정한다. 두 결정이 한 묶음으로
합쳐지지 않게 하려는 것이다. 범주가 같은 결정이 여럿이면 필수 단계를 더 많이 맞추는 쪽에 붙는다.
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


def pattern_key(core: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(core)).encode("utf-8")).hexdigest()[:12]


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
    decided:    결정된 프로세스 목록. 각 항목은 key · category · core_activities. 결정 순서대로 준다.
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
    by_category: dict[str, list[str]] = defaultdict(list)
    unclassified: list[dict] = []

    def unclear(case_id: str, reason: str) -> None:
        unclassified.append({"case_id": case_id, "trace": list(traces[case_id]), "reason": reason})

    for c in cases:
        category = categories.get(c)
        if not category:
            unclear(c, NO_CATEGORY)
            continue
        here = set(traces[c])
        # 범주가 같은 결정 중, 필수 단계를 더 많이 맞추는 쪽. 같으면 먼저 결정된 쪽
        best = None
        for i, d in enumerate(decided):
            if d.get("category") != category:
                continue
            hit = len(here & set(d.get("core_activities") or []))
            if best is None or hit > best[0]:
                best = (hit, i, d)
        if best is None:
            by_category[category].append(c)
        elif best[0] == 0:
            unclear(c, NO_CORE_STEP)
        else:
            decided_cases[best[2]["key"]].append(c)

    groups: list[tuple[dict | None, str, list[str], list[str]]] = []
    for d in decided:
        ids = decided_cases[d["key"]]
        core = _core_of(traces, ids) or list(d.get("core_activities") or [])
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
        key = d["key"] if d else pattern_key(core)
        out.append({
            "key": key,
            "decided_key": d["key"] if d else "",
            "category": category,
            "process_id": f"mined_{key}",
            "case_ids": sorted(ids, key=lambda x: str(by_case[x][0].occurred_at)),
            "case_count": len(ids),
            "event_count": len(evs),
            "core_activities": sorted(core, key=main.index) if main and all(a in main for a in core) else sorted(core),
            "optional_activities": optional,
            "main_variant": main,
            "variants": [{"trace": list(t), "count": n} for t, n in variants.most_common()],
            "steps": steps,
            "first_seen": when[0] if when else None,
            "last_seen": when[-1] if when else None,
            "automation_rate": round(sum(1 for e in evs if e.is_agent) / len(evs), 3) if evs else 0,
        })
    out.sort(key=lambda p: (-p["case_count"], p["last_seen"] or ""))
    unclassified.sort(key=lambda u: u["case_id"])
    return {"patterns": out, "unclassified": unclassified}
