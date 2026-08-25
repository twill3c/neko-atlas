"""L6 の成果物を生成する。

  data/zadan.json    — 座談ビュー(縮退版。応酬ネットワークは出荷しない — F-21 / SPEC §4)
  data/gendaku.json  — 衒学カタログ(F-22)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .gendaku import build as build_gendaku
from .gendaku import unclassified_candidates

DATA = Path("data")
WEB = Path("web")


def build_zadan() -> dict:
    """章 × 人物の発話量。**帰属できた発話のみの集計**であることを構造で明示する。

    応酬ネットワークは出荷しない(帰属率 16.5% では辺が引けず、交替既定も実測 0 件)。
    「不明」は第一級の項目として扱い、章ごとの帰属率を必ず併記する。
    """
    band = json.loads((DATA / "band.json").read_text(encoding="utf-8"))
    att = json.loads((DATA / "attribution.json").read_text(encoding="utf-8"))
    persons = json.loads((DATA / "persons.json").read_text(encoding="utf-8"))

    display = {p["id"]: p["display"] for p in persons["persons"]}
    display.update({u["id"]: u["display"] for u in persons["unresolved"]})

    chapters = {c["index"]: c for c in band["chapters"]}
    by_ch: dict[int, dict] = {
        i: {"chapter": i, "label": c["label"], "utterances": 0, "attributed": 0,
            "unknown": 0, "ambiguous": 0, "speakers": {}, "chars": {}}
        for i, c in chapters.items()
    }
    totals: dict[str, dict] = {}
    for a in att["attributions"]:
        e = by_ch[a["chapter"]]
        e["utterances"] += 1
        chars = a["end"] - a["start"]
        if a["speaker"]:
            e["attributed"] += 1
            e["speakers"][a["speaker"]] = e["speakers"].get(a["speaker"], 0) + 1
            e["chars"][a["speaker"]] = e["chars"].get(a["speaker"], 0) + chars
            t = totals.setdefault(a["speaker"], {"utterances": 0, "chars": 0})
            t["utterances"] += 1
            t["chars"] += chars
        else:
            e["unknown"] += 1
            if a["candidates"]:
                e["ambiguous"] += 1
    for e in by_ch.values():
        e["attribution_rate"] = round(e["attributed"] / max(1, e["utterances"]), 3)

    ranked = sorted(totals.items(), key=lambda kv: -kv[1]["utterances"])
    return {
        "note": "帰属できた発話だけの集計。帰属できなかった発話は「不明」として"
                "第一級の項目に置き、直前の話者などで埋めていない",
        "degraded": {
            "reason": "応酬ネットワークは出荷しない(SPEC §4 の縮退条件)",
            "attribution_rate": band["attribution"]["rate"],
            "adjacent_pair_probability": round(band["attribution"]["rate"] ** 2, 4),
            "runs_with_two_or_more_known": 0,
            "r4_filled": att["summary"].get("r4_filled", 0),
        },
        "precision": band["attribution"]["precision"],
        "gold_size": band["attribution"]["gold_size"],
        "persons": display,
        "totals": [{"id": k, "display": display.get(k, k), **v} for k, v in ranked],
        "by_chapter": [by_ch[i] for i in sorted(by_ch)],
        "overall": {
            "utterances": att["summary"]["utterances"],
            "attributed": att["summary"]["attributed"],
            "unattributed": att["summary"]["unattributed"],
            "ambiguous": att["summary"]["ambiguous"],
            "by_rule": att["summary"]["by_rule"],
        },
    }


def build() -> dict:
    band = json.loads((DATA / "band.json").read_text(encoding="utf-8"))
    persons = json.loads((DATA / "persons.json").read_text(encoding="utf-8"))
    alias = set()
    for p in persons["persons"] + persons["unresolved"]:
        alias |= set(p["aliases"])
    alias |= {"苦沙弥", "珍野", "迷亭", "寒月", "水島", "独仙", "八木", "東風", "越智",
              "鼻子", "金田", "富子", "鈴木", "藤十郎", "三平", "多々良", "雪江",
              "三毛子", "黒", "おさん", "吾輩", "細君", "妻君", "令嬢"}

    zadan = build_zadan()
    (DATA / "zadan.json").write_text(
        json.dumps(zadan, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    gendaku = build_gendaku(DATA, band["chapters"])
    gendaku["unclassified"] = unclassified_candidates(DATA, alias)
    (DATA / "gendaku.json").write_text(
        json.dumps(gendaku, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    wd = WEB / "data"
    wd.mkdir(parents=True, exist_ok=True)
    for n in ("zadan.json", "gendaku.json"):
        shutil.copy(DATA / n, wd / n)
    return {"zadan": zadan, "gendaku": gendaku}


if __name__ == "__main__":
    r = build()
    z, g = r["zadan"], r["gendaku"]
    print(f"座談: 発話 {z['overall']['utterances']:,}／帰属 {z['overall']['attributed']:,}"
          f"／不明 {z['overall']['unattributed']:,}／曖昧 {z['overall']['ambiguous']}")
    print("  話者上位:", "、".join(f"{t['display']} {t['utterances']}"
                                   for t in z["totals"][:6]))
    found = [e for e in g["entries"] if not e["needs_review"]]
    missing = [e for e in g["entries"] if e["needs_review"]]
    print(f"衒学: 統制語彙 {g['vocab_size']} 語／本文で確認 {len(found)}"
          f"／未確認 {len(missing)}")
    if missing:
        print("  未確認:", "、".join(e["surface"] for e in missing))
    for cls in g["classes"]:
        n = sum(e["total"] for e in found if e["class"] == cls)
        print(f"  {cls}: {sum(1 for e in found if e['class']==cls)} 語・延べ {n}")
    u = g["unclassified"]
    print(f"  未分類の候補: {u['candidates']} 種・延べ {u['occurrences']}")
