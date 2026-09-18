# -*- coding: utf-8 -*-
"""OMML(w:oMath) / Word EQ 域 → LaTeX。

只覆盖这批校本作业实际用到的构造（已普查）：
  m:f 分式 / m:sSub 下标 / m:sSup 上标 / m:sSubSup / m:d 括号 / m:rad 根式
  m:nary 求和 / m:r+m:t 文本(含 m:sty 正体)
EQ 域：eq \\f(a,b) → \\frac{a}{b}
"""
import re

M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

_ESC = {'\\': r'\backslash ', '{': r'\{', '}': r'\}', '$': r'\$',
        '&': r'\&', '#': r'\#', '%': r'\%', '_': r'\_', '^': r'\^', '~': r'\sim '}

# 希腊字母 / 常用符号 → LaTeX 命令
_SYM = {
    'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta', 'Δ': r'\Delta',
    'ε': r'\varepsilon', 'η': r'\eta', 'θ': r'\theta', 'λ': r'\lambda', 'μ': r'\mu',
    'π': r'\pi', 'ρ': r'\rho', 'σ': r'\sigma', 'τ': r'\tau', 'φ': r'\varphi',
    'Φ': r'\Phi', 'ω': r'\omega', 'Ω': r'\Omega', '×': r'\times', '÷': r'\div',
    '±': r'\pm', '≈': r'\approx', '≠': r'\neq', '≤': r'\leq', '≥': r'\geq',
    '→': r'\to', '∞': r'\infty', '∝': r'\propto', '·': r'\cdot', '√': r'\sqrt{}',
}


def _esc(t):
    return ''.join(_SYM.get(c, _ESC.get(c, c)) for c in t)


def _txt(el):
    """取元素下所有 m:t 的文本。"""
    return ''.join(t.text or '' for t in el.iter(M + 't'))


def _sty_of(run):
    """m:r 的字形：返回 'p'(正体) / 'b'(粗) / None(默认斜体)。"""
    pr = run.find(M + 'rPr')
    if pr is None:
        return None
    sty = pr.find(M + 'sty')
    if sty is not None:
        return sty.get(M + 'val')
    if pr.find(M + 'nor') is not None:
        return 'p'
    return None


def _render_run(run):
    t = _txt(run)
    if not t:
        return ''
    sty = _sty_of(run)
    body = _esc(t)
    if sty == 'p':
        return r'\mathrm{%s}' % body
    if sty == 'b':
        return r'\mathbf{%s}' % body
    return body


def _render(el):
    """递归渲染 OMML 片段。"""
    tag = el.tag
    if tag == M + 'r':
        return _render_run(el)
    if tag == M + 'f':                       # 分式
        num, den = el.find(M + 'num'), el.find(M + 'den')
        return r'\frac{%s}{%s}' % (_children(num), _children(den))
    if tag == M + 'sSub':
        e, sub = el.find(M + 'e'), el.find(M + 'sub')
        return '%s_{%s}' % (_children(e), _children(sub))
    if tag == M + 'sSup':
        e, sup = el.find(M + 'e'), el.find(M + 'sup')
        return '%s^{%s}' % (_children(e), _children(sup))
    if tag == M + 'sSubSup':
        e = el.find(M + 'e')
        return '%s_{%s}^{%s}' % (_children(e), _children(el.find(M + 'sub')),
                                 _children(el.find(M + 'sup')))
    if tag == M + 'd':                       # 括号
        e = el.find(M + 'e')
        pr = el.find(M + 'dPr')
        beg, end = '(', ')'
        if pr is not None:
            b, en = pr.find(M + 'begChr'), pr.find(M + 'endChr')
            if b is not None:
                beg = b.get(M + 'val') or ''
            if en is not None:
                end = en.get(M + 'val') or ''
        inner = _children(e)
        # 空括号保留占位（题目里大量 （　　） 填空）
        return r'\left%s %s \right%s' % (beg, inner or r'\ ', end)
    if tag == M + 'rad':
        deg, e = el.find(M + 'deg'), el.find(M + 'e')
        d = _children(deg)
        return (r'\sqrt[%s]{%s}' % (d, _children(e))) if d else (r'\sqrt{%s}' % _children(e))
    if tag == M + 'nary':
        sub, sup, e = el.find(M + 'sub'), el.find(M + 'sup'), el.find(M + 'e')
        pr = el.find(M + 'naryPr')
        op = r'\sum'
        if pr is not None:
            c = pr.find(M + 'chr')
            if c is not None:
                op = {'∑': r'\sum', '∫': r'\int', '∏': r'\prod'}.get(c.get(M + 'val'), r'\sum')
        s = '%s_{%s}^{%s}' % (op, _children(sub), _children(sup))
        return s + _children(e)
    if tag == M + 'func':
        return r'%s\left(%s\right)' % (_children(el.find(M + 'fName')),
                                       _children(el.find(M + 'e')))
    if tag in (M + 'oMath', M + 'oMathPara', M + 'e', M + 'num', M + 'den',
               M + 'sub', M + 'sup', M + 'deg', M + 'fName', M + 'box'):
        return _children(el)
    if tag == M + 'acc':                     # 重音（矢量箭头等）
        e = el.find(M + 'e')
        pr = el.find(M + 'accPr')
        ch = '→'
        if pr is not None:
            c = pr.find(M + 'chr')
            if c is not None:
                ch = c.get(M + 'val') or '→'
        cmd = {'→': r'\vec', '‾': r'\bar', '^': r'\hat', '.': r'\dot'}.get(ch)
        return (r'%s{%s}' % (cmd, _children(e))) if cmd else _children(e)
    if tag == M + 'm':                       # 矩阵：按行 \\ 拼接
        rows = [ _children(r) for r in el.findall(M + 'mr') ]
        return r'\begin{matrix}' + r' \\ '.join(rows) + r'\end{matrix}'
    if tag == M + 'mr':
        return ' & '.join(_children(e) for e in el if e.tag == M + 'e')
    return _children(el)


def _children(el):
    if el is None:
        return ''
    return ''.join(_render(c) for c in el)


def omml_to_latex(el):
    """el: <m:oMath> 或 <m:oMathPara> 元素。"""
    return _children(el).strip()


# ---------------- Word EQ 域 ----------------

_EQ_FN = re.compile(r'\\f\s*\(([^,]*),([^)]*)\)')


def eq_to_latex(instr):
    """Word EQ 域指令 → LaTeX。仅支持实际用到的 \\f(a,b)；其余原样保留文字。"""
    s = instr.strip()
    if not s.lower().startswith('eq'):
        return None
    body = s[2:].strip()
    out = body
    for _ in range(4):                       # 允许嵌套
        new = _EQ_FN.sub(lambda m: r'\frac{%s}{%s}' % (m.group(1).strip(), m.group(2).strip()), out)
        if new == out:
            break
        out = new
    if out == body and '\\' in body:
        return None                          # 不认识的 EQ 指令，交给调用方降级
    return out.replace('\\', '\\') if out else None
