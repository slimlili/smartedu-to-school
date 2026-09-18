# -*- coding: utf-8 -*-
"""LaTeX（来自 MathType OLE / OMML / EQ 域）→ 纯 HTML。

刻意不用 MathJax/KaTeX：本校流水线的打印件与投屏 HTML 全部离线自包含，
且 Chrome headless 打印不嵌 webfont（会乱码）。分数用 CSS 叠式，其余用
<sub>/<sup>/<i>，零外部依赖，打印与投屏表现一致。
"""
import re

# LaTeX 命令 → unicode / HTML
_CMD = {
    r'\times': '×', r'\div': '÷', r'\pm': '±', r'\mp': '∓',
    r'\approx': '≈', r'\neq': '≠', r'\leq': '≤', r'\geq': '≥',
    r'\to': '→', r'\rightarrow': '→', r'\leftarrow': '←', r'\infty': '∞',
    r'\propto': '∝', r'\cdot': '·', r'\ldots': '…', r'\cdots': '…',
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\Delta': 'Δ', r'\varepsilon': 'ε', r'\epsilon': 'ε', r'\eta': 'η',
    r'\theta': 'θ', r'\lambda': 'λ', r'\mu': 'μ', r'\pi': 'π',
    r'\rho': 'ρ', r'\sigma': 'σ', r'\tau': 'τ', r'\varphi': 'φ',
    r'\phi': 'φ', r'\Phi': 'Φ', r'\omega': 'ω', r'\Omega': 'Ω',
    r'\sum': '∑', r'\int': '∫', r'\prod': '∏', r'\surd': '√',
    r'\angle': '∠', r'\perp': '⊥', r'\parallel': '∥', r'\circ': '°',
    r'\degree': '°', r'\quad': ' ', r'\qquad': '  ', r'\,': ' ', r'\;': ' ',
    r'\!': '', r'\ ': ' ', r'\{': '{', r'\}': '}', r'\%': '%',
    r'\&': '&', r'\#': '#', r'\_': '_', r'\$': '$',
    r'\backslash': '\\', r'\sim': '~',
}
# 需要包 <i> 的（\mathrm 内的除外）
_VAR = re.compile(r'(?<![\\A-Za-z])([A-Za-z])(?![A-Za-z])')


def _brace(s, i):
    """s[i]=='{' → 返回 (内容, 右括号后位置)。"""
    d, j = 1, i + 1
    while j < len(s) and d:
        if s[j] == '{':
            d += 1
        elif s[j] == '}':
            d -= 1
        j += 1
    return s[i + 1:j - 1], j


def _atom(s, i):
    """取一个参数：{...} 或单字符。返回 (内容, 新位置)。"""
    while i < len(s) and s[i] == ' ':
        i += 1
    if i < len(s) and s[i] == '{':
        return _brace(s, i)
    return (s[i] if i < len(s) else ''), i + 1


# MathType(MTEF) 吐出的老式 LaTeX 需要清洗：$ 定界符、\rm/\bf/\it 等旧字体命令、
# 花括号内多余空格（如 "$ 4{ \rm{ m } }{ \rm{ m } } ^ { 2 }  $" → "4mm²"）。
_OLD_FONT = {r'\rm': r'\mathrm', r'\bf': r'\mathbf', r'\mit': '', r'\mbf': r'\mathbf',
             r'\msf': '', r'\mtt': r'\mathtt', r'\it': '', r'\cal': '', r'\sl': ''}


def normalize(tex):
    """把 MTEF/OMML 产出的脏 LaTeX 归一成 to_html 能吃的形式。"""
    if not tex:
        return ''
    t = tex.replace('$', '')
    t = re.sub(r'\\(rm|bf|mit|mbf|msf|mtt|it|cal|sl)\b',
               lambda m: _OLD_FONT.get('\\' + m.group(1), ''), t)
    t = re.sub(r'[ \t\u00a0]{2,}', ' ', t)
    t = re.sub(r'\s*\}\s*\}', '}}', t)
    # \mathrm{ m } \u2192 \mathrm{m}\uff1b"m m" \u2192 "mm"\uff08\u5355\u4f4d\u8fde\u5199\uff09\uff1b"^ { 2 }" \u2192 "^{2}"
    t = re.sub(r'\\mathrm\{\s*([^}]*?)\s*\}', lambda m: r'\mathrm{%s}' % m.group(1).replace(' ', ''), t)
    t = re.sub(r'(?<=[A-Za-z])\s+(?=[A-Za-z](?![A-Za-z]))', '', t)
    t = re.sub(r'([_^])\s*\{\s*', r'\1{', t)
    # 去掉所有与花括号相邻的空白（\{ m \} → \{m\}），避免渲染出多余空格
    t = re.sub(r'\{\s+', '{', t)
    t = re.sub(r'\s+\}', '}', t)
    return t.strip()


def to_html(tex, italic=True):
    """把 LaTeX 片段转成 HTML（不含外层 $）。"""
    if not tex:
        return ''
    out, i, n = [], 0, len(tex)
    while i < n:
        c = tex[i]
        if c == '\\':
            m = re.match(r'\\([A-Za-z]+|.)', tex[i:])
            if not m:
                i += 1
                continue
            cmd = '\\' + m.group(1)
            i += len(m.group(0))
            if cmd == r'\frac':
                a, i = _atom(tex, i)
                b, i = _atom(tex, i)
                out.append(f'<span class="frac"><span class="fn">{to_html(a, italic)}</span>'
                           f'<span class="fd">{to_html(b, italic)}</span></span>')
            elif cmd in (r'\sqrt',):
                a, i = _atom(tex, i)
                out.append('√<span class="rad">' + to_html(a, italic) + '</span>')
            elif cmd in (r'\mathrm', r'\text', r'\mathbf', r'\mathtt'):
                a, i = _atom(tex, i)
                body = to_html(a.strip(), italic=False).strip()
                out.append(f'<b>{body}</b>' if cmd == r'\mathbf' else body)
            elif cmd in (r'\vec', r'\bar', r'\hat', r'\dot'):
                a, i = _atom(tex, i)
                mk = {r'\vec': '→', r'\bar': '‾', r'\hat': '^', r'\dot': '·'}[cmd]
                out.append(to_html(a, italic) + f'<span class="acc">{mk}</span>')
            elif cmd in (r'\left', r'\right'):
                continue
            elif cmd in _CMD:
                out.append(_CMD[cmd])
            else:
                out.append(cmd.lstrip('\\'))
            continue
        if c == '{':
            body, i = _brace(tex, i)
            out.append(to_html(body, italic))
            continue
        if c == '}':
            i += 1
            continue
        if c == '_' or c == '^':
            a, i = _atom(tex, i + 1)          # 跳过 _ / ^ 本身
            tag = 'sub' if c == '_' else 'sup'
            out.append(f'<{tag}>{to_html(a, italic)}</{tag}>')
            continue
        if c == ' ':
            out.append(' ')
            i += 1
            continue
        if italic and c.isalpha() and c.isascii():
            j = i
            while j < n and tex[j].isalpha() and tex[j].isascii():
                j += 1
            out.append('<i>' + tex[i:j] + '</i>')
            i = j
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def math_html(tex):
    """内联公式 → HTML 片段（先清洗脏 LaTeX，再转 HTML）。"""
    h = to_html(normalize(tex))
    return f'<span class="m">{h}</span>' if h else ''


MATH_CSS = """
.m{white-space:nowrap;font-family:"Times New Roman","Songti SC",serif}
.m i{font-style:italic;font-family:"Times New Roman","STIXGeneral",serif}
.m .frac{display:inline-block;vertical-align:-.42em;text-align:center;margin:0 .12em}
.m .frac .fn{display:block;padding:0 .18em;border-bottom:1.1px solid currentColor;line-height:1.15}
.m .frac .fd{display:block;padding:0 .18em;line-height:1.15}
.m .rad{border-top:1.1px solid currentColor;padding:0 .1em}
.m .acc{font-size:.8em;vertical-align:.45em;margin-left:-.12em}
"""
