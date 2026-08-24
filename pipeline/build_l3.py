"""L3 の成果物を生成する。

  data/persons.json              — 人物の統制語彙と異名の根拠(F-11)
  data/attribution.json          — 発話ごとの話者・規則 ID・根拠(F-12 / F-13)
  docs/attribution_calibration.md — gold 300 に対する較正結果(F-14)
"""
from __future__ import annotations

import collections
import io
import json
from pathlib import Path

from .aozora import split_document
from .attribute import (
    _is_gap,
    apply_alternation,
    attribute,
    build_alias_table,
    save,
    summarize,
)
from .chapters import find_chapters
from .gold import evaluate
from .persons import build as build_persons
from .persons import save as save_persons
from .persons import to_json as persons_to_json
from .voices import split_voices

DATA = Path("data")
DOCS = Path("docs")


def load():
    card_id = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))["card_id"]
    raw = (DATA / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8")
    doc = split_document(raw)
    return doc, find_chapters(doc)[0], split_voices(doc)


def run_stats(segments, attributions) -> dict:
    """地の文を挟まない連続発話の塊の統計(R4 が成立しうるかの実測)。"""
    by_seg = {a.segment_index: a for a in attributions}
    runs, current = [], []
    for i, seg in enumerate(segments):
        if seg.kind == "kaiwa":
            current.append(i)
        elif _is_gap(seg):
            continue
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    known = collections.Counter(
        sum(1 for i in r if by_seg[i].speaker) for r in runs
    )
    return {
        "runs": len(runs),
        "utterances_in_runs": sum(len(r) for r in runs),
        "known_per_run": dict(sorted(known.items())),
        "runs_with_two_or_more_known": sum(v for k, v in known.items() if k >= 2),
    }


def build() -> dict:
    doc, chapters, voices = load()
    flat = "".join(s.text for s in voices["segments"])

    persons = build_persons(flat)
    save_persons(persons, DATA / "persons.json")
    pj = persons_to_json(persons)

    table = build_alias_table(pj)
    atts = attribute(voices["segments"], chapters, table)
    runs = run_stats(voices["segments"], atts)
    filled = apply_alternation(voices["segments"], atts)

    summary = summarize(atts)
    summary["r4_filled"] = filled
    summary["runs"] = runs
    save(atts, summary, DATA / "attribution.json")

    gold_path = DATA / "speaker_gold.json"
    ev = None
    if gold_path.exists():
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        ev = evaluate(gold, atts)
        write_calibration(pj, summary, ev, runs)
    return {"persons": pj, "summary": summary, "eval": ev}


def write_calibration(pj: dict, summary: dict, ev: dict, runs: dict) -> None:
    errors = ev.get("errors", [])
    lines = [
        "# attribution_calibration — 話者帰属の較正(O-3 / F-14)",
        "",
        "**このファイルは実測の出力であり、手で書かない。**",
        "",
        "gold は評価専用(T-305)。文脈のみを読んで人手で付与し、規則の出力は参照していない。",
        "**この結果を見て規則を調整してはならない** — 調整するなら新しい標本を取り直す。",
        "",
        "## 人物の統制語彙(F-11)",
        "",
        "| 人物 | 異名 | 統合の根拠 |",
        "|---|---|---|",
    ]
    for p in pj["persons"]:
        ev_txt = "、".join(
            f"{a}: {d['hits'][0]['kind']}(@{d['hits'][0]['offset']}, via {d['via']})"
            for a, d in p["evidence"].items()
        ) or "—(代表形のみ)"
        lines.append(f"| {p['display']} | {' / '.join(p['aliases'])} | {ev_txt} |")
    if pj["unresolved"]:
        lines += [
            "",
            "### 統合しなかった呼称(未解決実体)",
            "",
            "根拠が取れないまま短い異名に前方一致させると別人の発話になる。"
            "推定で束ねない代わりに、**独立した未解決実体**として可視化する。",
            "",
            "| 呼称 | 候補 | 理由 |",
            "|---|---|---|",
        ]
        lines += [
            f"| {u['canonical']} | {u['candidate_of']} | {u['reason']} |"
            for u in pj["unresolved"]
        ]

    lines += [
        "",
        "## 規則の帰属(F-12)",
        "",
        "| 規則 | 内容 | 件数 |",
        "|---|---|---|",
        f"| R1 | 「…」と{{人物}}{{は/が/も}}…{{言表動詞}} | {summary['by_rule'].get('R1', 0):,} |",
        f"| R1b | 「…」と{{人物}}{{は/が/も}}…(言表動詞なし。引用の「と」を標識とする) | {summary['by_rule'].get('R1b', 0):,} |",
        f"| R2 | {{人物}}{{は/が/も}}…{{言表動詞}}「…」 | {summary['by_rule'].get('R2', 0):,} |",
        f"| R4 | 地の文を挟まない連続発話の交替既定 | {summary['by_rule'].get('R4', 0):,} |",
        "",
        f"- 発話 **{summary['utterances']:,}** 件中、帰属できたのは **{summary['attributed']:,}** 件"
        f"(帰属率 **{summary['attribution_rate']:.1%}**)",
        f"- 候補が複数出て**帰属しなかった**発話: {summary['ambiguous']:,} 件(推定で 1 人に絞らない)",
        f"- 残り **{summary['unattributed']:,}** 件は `speaker=null`。"
        "直前話者・既定話者で埋めていない(F-13)",
        "",
        "### R4(交替既定)が成立しない理由 — 実測",
        "",
        "地の文を挟まない連続発話の塊を数えると:",
        "",
        f"- 塊 **{runs['runs']:,}** 個・塊内の発話 **{runs['utterances_in_runs']:,}** 件"
        f"(全発話の {runs['utterances_in_runs'] / summary['utterances']:.0%})",
        f"- 塊内の既知帰属数の分布: {runs['known_per_run']}",
        f"- **既知が 2 件以上ある塊は {runs['runs_with_two_or_more_known']} 個**",
        "",
        "R1/R2 は塊の**外側**の地の文にしか届かないので、帰属は塊の端に 1 件しか付かない。",
        "交替の位相を決めるには最低 2 件の既知が要るため、この規則は構造的に発火しない。",
        "実装は残すが、この本文では 0 件である。",
        "",
        "## gold 300 に対する評価(O-3)",
        "",
        "| 指標 | 値 |",
        "|---|---|",
        f"| gold 標本 | {ev['gold_size']} 件(seed 固定・章横断の一様無作為) |",
        f"| 判定可能 | {ev['decidable']} 件 |",
        f"| 判定不能(unknown / not_speech) | {ev['undecidable']} 件 |",
        f"| うち統制語彙の外の話者(`other:…`) | {ev['out_of_vocabulary']} 件 |",
        f"| 規則が帰属した数 | {ev['predicted']} 件 |",
        f"| 正解 | {ev['true_positive']} 件 |",
        f"| 誤帰属 | {ev['false_positive']} 件 |",
        f"| 取りこぼし | {ev['false_negative']} 件 |",
        f"| **適合率** | **{ev['precision']:.3f}** |",
        f"| **再現率** | **{ev['recall']:.3f}** |",
        f"| gold 上の帰属率 | {ev['attribution_rate_on_gold']:.3f} |",
        f"| 判定不能なのに帰属した数 | {ev['over_attributed_on_unknown']} 件 |",
        "",
        "### 誤帰属の全件",
        "",
        "| # | gold | 規則の答え | 規則 | 根拠にした地の文 |",
        "|---|---|---|---|---|",
    ]
    for e in errors:
        lines.append(
            f"| {e['utterance']} | {e['gold']} | {e['pred']} | {e['rule']} | "
            f"{(e['evidence'] or '').replace('|', '/')[:60]} |"
        )
    lines += [
        "",
        "誤りは 5 件とも同型で、**「と」節が言表を越えて次の主語まで伸びている**。",
        "「…と意味不明な語を連ねているところへ例のごとく迷亭が這入って来る」では、",
        "迷亭は話者ではなく**入って来た人**である。",
        "",
        "**この観察をもとに規則を直すことはしない**(T-305)。直すなら新しい gold を取り直し、",
        "そちらで評価する。",
        "",
        "## 統制語彙の限界(実測)",
        "",
        f"gold の判定可能 {ev['decidable']} 件のうち **{ev['out_of_vocabulary']} 件"
        f"({ev['out_of_vocabulary'] / ev['decidable']:.0%})** は統制語彙の外の話者だった",
        "(甘木先生・二絃琴の御師匠とその下女・迷亭の伯父・古井武右衛門・落雲館の生徒・",
        "湯屋の客・巡査・倫理の先生・車屋の神さん・小供)。",
        "規則がどれだけ良くなっても、この分は現在の人物表では帰属できない。",
        "",
    ]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "attribution_calibration.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    r = build()
    s = r["summary"]
    print(f"帰属率 {s['attribution_rate']:.1%}({s['attributed']:,}/{s['utterances']:,})"
          f" ／ 曖昧 {s['ambiguous']} ／ R4 補完 {s['r4_filled']}")
    if r["eval"]:
        e = r["eval"]
        print(f"gold 評価: 適合率 {e['precision']:.3f} ／ 再現率 {e['recall']:.3f}"
              f" ／ 語彙外 {e['out_of_vocabulary']}/{e['decidable']}")
