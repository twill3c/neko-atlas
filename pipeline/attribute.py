"""F-12 / F-13 — 規則ベースの話者帰属。

規律:
- 帰属した発話には**どの規則で決まったか**(rule_id)を必ず付ける
- 規則が発火しなかった発話は `speaker=null` のまま残す。
  **直前話者・既定話者で埋める実装を書いてはならない**(帰属率が上がって見えるだけで、
  座談ビュー・声の帯・配置ビューが同時に壊れる)
- 複数人物が候補になったら帰属しない(推定で 1 人に絞らない)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

#: 言表動詞。語幹で持ち、活用は後続の任意文字で吸収する
SPEECH_VERBS = (
    "云", "言", "答", "聞", "問", "訊", "叫", "話", "述", "呟", "囁", "怒鳴",
    "call", "口を切", "相槌", "返事", "promise",
)
SPEECH_RE = re.compile("|".join(re.escape(v) for v in SPEECH_VERBS))

#: 敬称。異名の直後に付きうる
HONORIFIC = r"(?:君|氏|先生|さん|様|子|夫人|嬢|の方)?"
#: 主語を示す助詞
SUBJECT_PARTICLE = r"(?:は|が|も)"

NL = "\r\n"


@dataclass
class Attribution:
    utterance_index: int      # 発話の通し番号
    segment_index: int        # segments 上の位置
    start: int                # body_raw 上の開始
    end: int
    chapter: int
    speaker: str | None       # 人物 id。決まらなければ None のまま
    rule_id: str | None       # 帰属根拠の規則
    evidence: str | None      # 判断に使った地の文の断片
    candidates: list[str]     # 候補が複数出たときの記録(帰属はしない)


def build_alias_table(persons_json: dict) -> list[tuple[str, str]]:
    """(異名, 人物 id) を長い順に並べた表。長一致優先で誤帰属を防ぐ。"""
    table: list[tuple[str, str]] = []
    for p in persons_json["persons"] + persons_json.get("unresolved", []):
        for alias in p["aliases"]:
            table.append((alias, p["id"]))
    table.sort(key=lambda kv: -len(kv[0]))
    return table


def _subject_matches(span: str, table: list[tuple[str, str]]) -> list[tuple[str, int]]:
    """span 中で「異名 + 敬称 + は/が/も」の形で現れる人物を、出現順に返す。"""
    found: list[tuple[str, int]] = []
    taken: list[tuple[int, int]] = []
    for alias, pid in table:
        for m in re.finditer(re.escape(alias) + HONORIFIC + SUBJECT_PARTICLE, span):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue  # 長一致で既に取られた範囲
            taken.append((m.start(), m.end()))
            found.append((pid, m.start()))
    found.sort(key=lambda kv: kv[1])
    # 同一人物の重複は 1 つに畳む(順序は保つ)
    seen, out = set(), []
    for pid, pos in found:
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, pos))
    return out


def _clause(text: str) -> str:
    """地の文の先頭から、最初の句点または改行までを言表節として切り出す。"""
    end = len(text)
    for mark in ("。", NL):
        i = text.find(mark)
        if i >= 0:
            end = min(end, i + len(mark))
    return text[:end]


def _tail_clause(text: str) -> str:
    """地の文の末尾から、直前の句点または改行以降を切り出す。"""
    start = 0
    for mark in ("。", NL):
        i = text.rfind(mark)
        if i >= 0:
            start = max(start, i + len(mark))
    return text[start:]


def attribute(segments, chapters, table: list[tuple[str, str]]) -> list[Attribution]:
    """R1(後置言表節)と R2(前置言表節)で帰属する。決まらなければ None。"""
    out: list[Attribution] = []
    u = 0
    for i, seg in enumerate(segments):
        if seg.kind != "kaiwa":
            continue
        u += 1
        ch = next((c.index for c in chapters if c.start <= seg.start < c.end), 0)
        speaker = rule = evidence = None
        candidates: list[str] = []

        # R1: 「…」と{人物}{は/が}…{言表動詞}
        if i + 1 < len(segments) and segments[i + 1].kind == "jinomon":
            span = _clause(segments[i + 1].text.lstrip("　"))
            # 引用の「と」自体が言表の標識である。言表動詞は必須にしない —
            # 「と主人は無暗に感心している」型の言表節を落とすため(L3 実測)
            if span.startswith("と"):
                subs = _subject_matches(span, table)
                if len(subs) == 1:
                    speaker = subs[0][0]
                    rule = "R1" if SPEECH_RE.search(span) else "R1b"
                    evidence = span.strip()
                elif len(subs) > 1:
                    candidates = [s[0] for s in subs]
                    evidence = span.strip()

        # R2: {人物}{は/が}…{言表動詞}「…」
        if speaker is None and not candidates and i > 0 and segments[i - 1].kind == "jinomon":
            span = _tail_clause(segments[i - 1].text.rstrip())
            if SPEECH_RE.search(span):
                subs = _subject_matches(span, table)
                if len(subs) == 1:
                    speaker, rule, evidence = subs[0][0], "R2", span.strip()
                elif len(subs) > 1:
                    candidates = [s[0] for s in subs]
                    evidence = span.strip()

        out.append(
            Attribution(u, i, seg.start, seg.end, ch, speaker, rule, evidence, candidates)
        )
    return out


def _is_gap(seg) -> bool:
    """発話と発話の間が「地の文なし」(改行と空白だけ)かどうか。"""
    return seg.kind == "jinomon" and not seg.text.strip().strip("　")


def apply_alternation(segments, attributions: list[Attribution]) -> int:
    """R4 交替既定 — 地の文を挟まない連続発話の塊で、話者が 2 人に確定し、
    既知の帰属がすべて厳密交替と整合するときだけ、残りを parity で埋める。

    **既定話者・直前話者で埋める規則ではない。** 2 人以外・矛盾がある塊には触らない。
    埋めた発話には rule_id="R4" を付け、根拠を残す。戻り値は補完した件数。
    """
    by_seg = {a.segment_index: a for a in attributions}
    runs: list[list[int]] = []
    current: list[int] = []
    for i, seg in enumerate(segments):
        if seg.kind == "kaiwa":
            current.append(i)
        elif _is_gap(seg):
            continue  # 塊は続く
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)

    filled = 0
    for run in runs:
        known = [(k, by_seg[i].speaker) for k, i in enumerate(run) if by_seg[i].speaker]
        speakers = {s for _, s in known}
        if len(speakers) != 2 or len(known) < 2:
            continue
        # 既知の帰属が厳密交替(位置の偶奇で話者が決まる)と整合するか
        parity: dict[int, str] = {}
        ok = True
        for k, sp in known:
            if parity.setdefault(k % 2, sp) != sp:
                ok = False
                break
        if not ok or len(parity) != 2:
            continue
        for k, i in enumerate(run):
            a = by_seg[i]
            if a.speaker or a.candidates:
                continue
            a.speaker = parity[k % 2]
            a.rule_id = "R4"
            a.evidence = f"地の文を挟まない連続発話 {len(run)} 件の交替既定(既知 {len(known)} 件と整合)"
            filled += 1
    return filled


def summarize(attributions: list[Attribution]) -> dict:
    total = len(attributions)
    attributed = sum(1 for a in attributions if a.speaker)
    by_rule: dict[str, int] = {}
    by_speaker: dict[str, int] = {}
    for a in attributions:
        if a.rule_id:
            by_rule[a.rule_id] = by_rule.get(a.rule_id, 0) + 1
        if a.speaker:
            by_speaker[a.speaker] = by_speaker.get(a.speaker, 0) + 1
    return {
        "utterances": total,
        "attributed": attributed,
        "unattributed": total - attributed,
        "attribution_rate": round(attributed / total, 4) if total else 0.0,
        "ambiguous": sum(1 for a in attributions if a.candidates),
        "by_rule": dict(sorted(by_rule.items())),
        "by_speaker": dict(sorted(by_speaker.items(), key=lambda kv: -kv[1])),
    }


def save(attributions: list[Attribution], summary: dict, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "summary": summary,
                "note": "speaker=null は帰属不能。直前話者や既定話者で埋めていない(F-13)",
                "attributions": [asdict(a) for a in attributions],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
