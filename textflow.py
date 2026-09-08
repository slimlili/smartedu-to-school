# -*- coding: utf-8 -*-
"""PDF 文本 span → 干净 HTML 文本（还原上下标、斜体）。

几何判定（Word 行内公式）：
  - 主字号为行主体；小字号(ratio<0.82)是上下标。
  - 下标：小字底边(y1) ≈ 主体基线(y1主)，靠下（如 W_AB 的 AB）
  - 上标：小字底边(y1) 明显高于主体基线（如 10^-9 的 -9）
  斜体（字体名含 Italic，多为 TimesNewRomanPS-Italic）包 <i>。
"""
import html, re, unicodedata
from collections import Counter


def esc(t):
    return html.escape(t or "", quote=False)


_STD_GREEK = {"ALPHA":"Α","BETA":"Β","GAMMA":"Γ","DELTA":"Δ","EPSILON":"Ε","ZETA":"Ζ",
              "ETA":"Η","THETA":"Θ","IOTA":"Ι","KAPPA":"Κ","LAMDA":"Λ","LAMBDA":"Λ",
              "MU":"Μ","NU":"Ν","XI":"Ξ","OMICRON":"Ο","PI":"Π","RHO":"Ρ","SIGMA":"Σ",
              "TAU":"Τ","UPSILON":"Υ","PHI":"Φ","CHI":"Χ","PSI":"Ψ","OMEGA":"Ω",
              "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","zeta":"ζ",
              "eta":"η","theta":"θ","iota":"ι","kappa":"κ","lamda":"λ","lambda":"λ",
              "mu":"μ","nu":"ν","xi":"ξ","omicron":"ο","pi":"π","rho":"ρ",
              "sigma":"σ","varsigma":"ς","tau":"τ","upsilon":"υ","phi":"φ","chi":"χ",
              "psi":"ψ","omega":"ω","theta symbol":"ϑ","phi symbol":"ϕ",
              "epsilon symbol":"ϵ","kappa symbol":"ϰ","rho symbol":"ϱ",
              "pi symbol":"ϖ","digamma":"ϝ"}


def norm_math_alnum(text):
    """把 Unicode 数学字母数字符(U+1D400+)还原成普通字母/希腊字母。

    这些字形在常见中文字体(宋体/黑体)中常缺 → 打印显示成 ??。逐一按官方 Unicode
    名称映射回普通字符。
    """
    out = []
    for c in text:
        o = ord(c)
        if not (0x1D400 <= o <= 0x1D7FF):
            out.append(c)
            continue
        try:
            name = unicodedata.name(c)  # e.g. "MATHEMATICAL ITALIC CAPITAL PHI"
        except ValueError:
            out.append(c)
            continue
        parts = name.split()
        # 形如 MATHEMATICAL ... CAPITAL/SMALL <LETTER> 或 DIGIT
        letter = None
        cap = None
        for p in parts:
            if p in ("CAPITAL", "SMALL", "DIGIT"):
                cap = p
            elif p in _STD_GREEK and letter is None:
                letter = p
        if letter is not None and letter in _STD_GREEK:
            g = _STD_GREEK[letter]
            out.append(g)
        elif cap == "DIGIT":
            out.append(parts[-1])
        else:
            # 拉丁字母：CAPITAL/SMALL A..Z
            for p in parts:
                if len(p) == 1 and p.isalpha():
                    out.append(p)
                    break
            else:
                out.append(c)
    return "".join(out)


# Windows Symbol 字体 PUA → Unicode 数学符号/希腊字母。
# 实测本文档用到：U+F03D = '='，U+F06A = 'φ'(电势 phi)。
SYMBOL_MAP = {
    "": "=",    # =
    "": "φ",    # φ  (实测 电势 phi)
    "": "θ",    # θ
    "": "φ",    # φ
    "": "α",    # α
    "": "β",    # β
    "": "γ",    # γ
    "": "ε",    # ε
    "": "λ",    # λ
    "": "π",    # π
    "": "×",    # ×
    "": "÷",    # ÷
    "": "≤",    # ≤
    "": "≥",    # ≥
    "": "←",    # ←
    "": "→",    # →
    "": "±",    # ±
    "": "+",    # +
    "": "<",    # <
    "": "Δ",    # Δ
}


def map_symbol_font(text, font):
    """若字体为 Symbol 且字符在 PUA 区，按映射替换为 Unicode。"""
    if "symbol" not in font.lower():
        return text
    return "".join(SYMBOL_MAP.get(c, c) for c in text)


def spans_to_html(spans):
    if not spans:
        return "", ""
    sizes = [round(s["size"], 1) for s in spans]
    main_sz = Counter(sizes).most_common(1)[0][0]
    main_y1 = max(s["bbox"][3] for s in spans)          # 行主体基线（底边最大值）
    out = []
    plain = []
    prev = None
    for s in spans:
        t = map_symbol_font(s["text"], s["font"])
        t = norm_math_alnum(t)
        if not t:
            continue
        sz = s["size"]
        ratio = sz / main_sz if main_sz else 1
        tag_open = ""
        tag_close = ""
        is_italic = "italic" in s["font"].lower()
        e = esc(t)
        if ratio < 0.82:
            sp_y1 = s["bbox"][3]
            # 与主体基线比较
            if abs(sp_y1 - main_y1) <= 1.6:
                # 底边贴基线 → 下标
                e = f"<sub>{e}</sub>"
            else:
                e = f"<sup>{e}</sup>"
        # 斜体包 <i>（Times italic 变量）
        if is_italic and e:
            e = f"<i>{e}</i>"
        out.append(e)
        plain.append(t)
    return "".join(out), "".join(plain)
