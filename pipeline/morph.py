"""F-09 — 二辞書による形態素解析と差分の全件列挙(O-5)。

現代書き言葉 UniDic(unidic-lite)と 近代文語 UniDic の**両方**で解析する。
漢文訓読調が混在するため、片方の辞書に結論を依存させない。
差分率に閾値は課さない — 差分そのものがこの作品の混成性の測定値である。

近代文語 UniDic は CC BY-NC-SA 4.0。**辞書そのものを再配布しない**(.dict/ は git 管理外)。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

#: 語種フィールドが取りうる値。列位置は辞書ごとに実測で特定する(定数で書かない)
GOSHU_VALUES = {"和", "漢", "外", "混", "固", "記号", "不明", "他"}

KINDAI_DIR = Path(".dict/kindai-bungo")


@dataclass
class Token:
    surface: str
    pos1: str
    pos2: str
    lemma: str
    goshu: str
    cform: str


@dataclass
class DictSpec:
    name: str
    label: str
    version: str
    license: str


class Analyzer:
    """辞書 1 本ぶんの解析器。語種の列位置は起動時に実測で確定する。"""

    def __init__(self, spec: DictSpec, tagger):
        self.spec = spec
        self._tagger = tagger
        self._goshu_col = self._detect_goshu_col()

    def _detect_goshu_col(self) -> int:
        """語種の列を実測で特定する。辞書ごとに素性数が違うため位置を仮定しない。"""
        probe = "吾輩は猫である。ビールを飲む。天下の秀才。"
        hits: dict[int, int] = {}
        for word in self._tagger(probe):
            for i, v in enumerate(tuple(word.feature)):
                if v in GOSHU_VALUES:
                    hits[i] = hits.get(i, 0) + 1
        if not hits:
            raise RuntimeError(f"{self.spec.name}: 語種の列を特定できない")
        col, _ = max(hits.items(), key=lambda kv: kv[1])
        return col

    @property
    def goshu_col(self) -> int:
        return self._goshu_col

    def tokenize(self, text: str) -> list[Token]:
        out: list[Token] = []
        for word in self._tagger(text):
            f = tuple(word.feature)

            def g(i: int) -> str:
                return f[i] if i < len(f) and f[i] not in ("*", "") else ""

            out.append(
                Token(
                    surface=word.surface,
                    pos1=g(0),
                    pos2=g(1),
                    lemma=g(7) or word.surface,
                    goshu=g(self._goshu_col),
                    cform=g(5),
                )
            )
        return out


def load_analyzers() -> list[Analyzer]:
    """2 本の辞書を読み込む。どちらか欠けたら失敗させる(片方だけで進めない)。"""
    import fugashi
    import unidic_lite

    gendai = Analyzer(
        DictSpec("gendai", "現代書き言葉 UniDic (unidic-lite)", unidic_lite.__version__
                 if hasattr(unidic_lite, "__version__") else "unidic-lite", "BSD/GPL/LGPL"),
        fugashi.Tagger(),
    )

    if not (KINDAI_DIR / "sys.dic").exists():
        raise RuntimeError(
            f"近代文語 UniDic が {KINDAI_DIR} に無い。"
            "https://clrd.ninjal.ac.jp/unidic/download_all.html から取得すること"
        )
    d = str(KINDAI_DIR.resolve()).replace(os.sep, "/")
    kindai = Analyzer(
        DictSpec("kindai", "近代文語 UniDic v202512", "v202512", "CC BY-NC-SA 4.0"),
        fugashi.GenericTagger(f"-d {d} -r {d}/dicrc"),
    )
    return [gendai, kindai]


def boundaries(tokens: list[Token]) -> set[int]:
    """トークン境界の集合(文字オフセット)。分割の一致・不一致はこれで見る。"""
    out: set[int] = set()
    pos = 0
    for t in tokens:
        pos += len(t.surface)
        out.add(pos)
    return out


def diff_segmentation(text: str, a: list[Token], b: list[Token]) -> list[dict]:
    """2 辞書の分割が食い違う区間を全件返す。

    共通境界で区切り、区間内のトークン列が異なるものだけを拾う。
    """
    common = sorted(boundaries(a) & boundaries(b) | {0})
    if common[-1] != len(text):
        common.append(len(text))

    def slice_tokens(tokens: list[Token], lo: int, hi: int) -> list[Token]:
        out, pos = [], 0
        for t in tokens:
            if pos >= hi:
                break
            if pos >= lo:
                out.append(t)
            pos += len(t.surface)
        return out

    diffs: list[dict] = []
    for lo, hi in zip(common, common[1:]):
        ta, tb = slice_tokens(a, lo, hi), slice_tokens(b, lo, hi)
        sa = [t.surface for t in ta]
        sb = [t.surface for t in tb]
        pa = [t.pos1 for t in ta]
        pb = [t.pos1 for t in tb]
        if sa != sb or pa != pb:
            diffs.append(
                {
                    "text": text[lo:hi],
                    "offset": lo,
                    "gendai": [{"s": t.surface, "pos": t.pos1, "goshu": t.goshu} for t in ta],
                    "kindai": [{"s": t.surface, "pos": t.pos1, "goshu": t.goshu} for t in tb],
                    "kind": "split" if sa != sb else "pos",
                }
            )
    return diffs


def tokens_to_json(tokens: list[Token]) -> list[dict]:
    return [asdict(t) for t in tokens]


def save_shard(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
