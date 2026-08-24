"""F-11 — 人物の統制語彙と異名の統合。

規律: **推定で異名を束ねない。** 本文中に同定の根拠がある対のみ統合し、
根拠(種別・オフセット・引用)を全件記録する。根拠が取れなかった異名は統合せず落とす。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

WINDOW = 60  # 近接共起とみなす文字幅(片側)

#: 候補。先頭が代表形。ここは「候補の提示」であって統合の決定ではない —
#: 各異名は本文の根拠が取れて初めて統合される(verify_aliases)。
CANDIDATES: list[dict] = [
    {"id": "kushami", "display": "苦沙弥(主人)", "kind": "human",
     "aliases": ["主人", "苦沙弥", "珍野"]},
    {"id": "meitei", "display": "迷亭", "kind": "human", "aliases": ["迷亭"]},
    {"id": "kangetsu", "display": "寒月", "kind": "human", "aliases": ["寒月", "水島"]},
    {"id": "dokusen", "display": "独仙", "kind": "human", "aliases": ["独仙", "八木"]},
    {"id": "tofu", "display": "東風", "kind": "human", "aliases": ["東風", "越智"]},
    {"id": "saikun", "display": "細君", "kind": "human", "aliases": ["細君", "妻君"]},
    {"id": "hanako", "display": "鼻子(金田夫人)", "kind": "human",
     "aliases": ["鼻子", "金田夫人"]},
    {"id": "kaneda", "display": "金田", "kind": "human", "aliases": ["金田"]},
    {"id": "tomiko", "display": "富子(令嬢)", "kind": "human", "aliases": ["富子", "令嬢"]},
    {"id": "suzuki", "display": "鈴木", "kind": "human", "aliases": ["鈴木", "藤十郎"]},
    {"id": "sanpei", "display": "多々良三平", "kind": "human", "aliases": ["三平", "多々良"]},
    {"id": "yukie", "display": "雪江", "kind": "human", "aliases": ["雪江"]},
    {"id": "osan", "display": "おさん", "kind": "human", "aliases": ["おさん"]},
    {"id": "wagahai", "display": "吾輩(猫)", "kind": "cat", "aliases": ["吾輩"]},
    {"id": "kuro", "display": "黒", "kind": "cat", "aliases": ["黒"]},
    {"id": "mikeko", "display": "三毛子", "kind": "cat", "aliases": ["三毛子"]},
]

#: 語り手が明示的に命名する箇所を拾う型(例: 「以来はこの女を称して鼻子鼻子と呼ぶつもりである」)
NAMING_RE = re.compile(r"(?:称して|名づけて|呼ぶ|呼んで|と云う名)")


@dataclass
class Evidence:
    kind: str      # adjacency / naming / window
    offset: int
    snippet: str


@dataclass
class Person:
    id: str
    display: str
    kind: str
    canonical: str
    aliases: list[str] = field(default_factory=list)
    evidence: dict[str, list[Evidence]] = field(default_factory=dict)
    evidence_via: dict[str, str] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


def find_evidence(flat: str, a: str, b: str) -> list[Evidence]:
    """異名 a と b が同一人物であることの本文中の根拠を探す。

    adjacency(連結形。例「水島寒月」)が最も強い。次に naming(語り手による命名)、
    最後に window(近接共起)。**どれも取れなければ統合しない。**
    """
    out: list[Evidence] = []
    for pat in (a + b, b + a):
        m = re.search(re.escape(pat), flat)
        if m:
            out.append(Evidence("adjacency", m.start(),
                                flat[max(0, m.start() - 25): m.start() + 35]))
            break
    for m in re.finditer(re.escape(a), flat):
        lo, hi = max(0, m.start() - WINDOW), m.start() + WINDOW
        win = flat[lo:hi]
        if b not in win:
            continue
        kind = "naming" if NAMING_RE.search(win) else "window"
        out.append(Evidence(kind, m.start(), win))
        if kind == "naming":
            break
        if sum(1 for e in out if e.kind == "window") >= 2:
            break
    # 強い順に並べる
    order = {"adjacency": 0, "naming": 1, "window": 2}
    out.sort(key=lambda e: order[e.kind])
    return out[:3]


def build(flat: str) -> list[Person]:
    persons: list[Person] = []
    for cand in CANDIDATES:
        canonical = cand["aliases"][0]
        p = Person(cand["id"], cand["display"], cand["kind"], canonical, [canonical])
        if canonical not in flat:
            p.rejected[canonical] = "本文に出現しない"
            persons.append(p)
            continue
        for alias in cand["aliases"][1:]:
            if alias not in flat:
                p.rejected[alias] = "本文に出現しない"
                continue
            # 部分文字列の関係にある対は「異名」ではなく表記変種。
            # 窓に両方が入るのが自明になり、根拠にならない
            container = next(
                (c for c in p.aliases if alias in c or c in alias), None
            )
            if container:
                p.rejected[alias] = f"「{container}」の表記変種であり異名ではない(部分文字列)"
                continue
            # 既に確定した異名のどれとでも結べればよい(推移的に同一人物と決まる)
            ev: list[Evidence] = []
            via = None
            for confirmed in p.aliases:
                ev = find_evidence(flat, confirmed, alias)
                if ev:
                    via = confirmed
                    break
            if not ev:
                p.rejected[alias] = "同定の根拠が本文に無いため統合しない"
                continue  # 未解決実体として別に立てる(unresolved_entities)
            p.aliases.append(alias)
            p.evidence[alias] = ev
            p.evidence_via[alias] = via
        persons.append(p)
    return persons


def unresolved_entities(persons: list[Person]) -> list[dict]:
    """根拠が取れず統合できなかった呼称を、**独立した未解決実体**として立てる。

    統合しないまま放置すると、より短い異名(例「金田」)に前方一致して
    別人の発話になる。推定で束ねない代わりに、曖昧なまま可視化する。
    """
    out: list[dict] = []
    for p in persons:
        for alias, reason in p.rejected.items():
            if "部分文字列" in reason or "出現しない" in reason:
                continue
            out.append(
                {
                    "id": f"unresolved:{alias}",
                    "display": f"{alias}(未解決)",
                    "kind": "unresolved",
                    "canonical": alias,
                    "aliases": [alias],
                    "needs_review": True,
                    "candidate_of": p.id,
                    "reason": reason,
                }
            )
    return out


def to_json(persons: list[Person]) -> dict:
    return {
        "window": WINDOW,
        "note": "異名の統合は本文中の根拠がある対のみ。根拠は種別・オフセット・引用で残す",
        "unresolved": unresolved_entities(persons),
        "persons": [
            {
                "id": p.id,
                "display": p.display,
                "kind": p.kind,
                "canonical": p.canonical,
                "aliases": p.aliases,
                "evidence": {
                    a: {
                        "via": p.evidence_via.get(a),
                        "hits": [
                            {"kind": e.kind, "offset": e.offset, "snippet": e.snippet}
                            for e in evs
                        ],
                    }
                    for a, evs in p.evidence.items()
                },
                "rejected": p.rejected,
            }
            for p in persons
        ],
    }


def save(persons: list[Person], path: Path) -> None:
    path.write_text(
        json.dumps(to_json(persons), ensure_ascii=False, indent=1), encoding="utf-8"
    )
