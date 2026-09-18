# -*- coding: utf-8 -*-
"""把 retypeset 解析的 sections 渲染成 A4 打印 HTML。

按用户要求：
  - 重排后文字自然流动（自然段 <p>，不保留原 PDF 硬换行）。
  - 教师版：每题后紧跟该题答案/解析；平台无答案处用 SELF_ANSWERS 兜底。
  - 学习任务单等 `h` 段落保留其正文。
"""
import html, re

SCHOOL = "深圳外国语学校博雅高中"
esc = lambda s: html.escape(s or "", quote=False)

# 平台答案缺失时的参考解答兜底（key: (课题名, 题号)）——随用随补
SELF_ANSWERS = {}

# 内容来源开关：平台 PDF 的文字层是硬换行，需要按标点重新拼段（False）；
# docx 来源的每个 <w:p> 本就是完整段落，再拼会粘成一行（True）。
PRESERVE_PARAS = False

# 学习任务单里的问句/填空题下方留一行虚线作答空间（仅 docx 来源启用）
ASK_LINES = False

# 需要留作答行的段落：问句、长填空、短提示语
_Q_END = re.compile(r'[?？]\s*$')
_BLANKS = re.compile(r'_{3,}|＿{3,}|[ 　]{6,}')
_NUM_PROMPT = re.compile(r'^[（(]?\d{1,2}[）).．、]')
# 课堂探究里的「思考1：…」「想一想：…」「做一做」等，同样要留作答空间
_THINK = re.compile(r'^(?:思考|想一想|做一做|试一试|议一议|讨论)\s*\d*\s*[:：]')


def _needs_answer_line(plain):
    t = (plain or '').strip()
    if len(t) < 4:
        return False
    if _Q_END.search(t) or _BLANKS.search(t):
        return True
    if _THINK.match(t):
        return True
    # "1.什么是电流" 这类编号提示语（无句末标点、不长）也是要作答的
    return bool(_NUM_PROMPT.match(t)) and len(t) <= 40 and not t.endswith(('。', '！', '；', ';'))


def _paras_html(item):
    """item 文本项 -> 各自然段 HTML（<p>）。"""
    paras = item.get("paras") or []
    out = []
    for p in paras:
        txt = p.get("html") or esc(p.get("plain", ""))
        out.append(f"<p>{txt}</p>")
    return "".join(out)


_SENT_END = re.compile(r'[。！？!?；;]$')
# 需要断段的新行开头（条目标题 / 新的小问）
_NEW_LINE = re.compile(r'^(【|目标[一二三四五]|问题\d|第[一二三四五六七八九十\d]+[、.]|'
                       r'[（(][一二三四五六七八九十\d]+[)）]|[一二三四五六七八九十\d]+[、.]|'
                       r'想一想|做一做|试一试|①|②|③|④)')
# 选项行：A．/ B．/ A. / A、 开头（独立选项）
_OPT_LINE = re.compile(r'^\s*([A-DＡ-Ｄ])\s*[.、．]')


# 选项标记只认「字母 + . 或 ．」。不能把「、」算进来——题干里
# "图中$ A $、$ B $、C、$ D $四个点" 的顿号会被误当成选项分隔，把题干切碎。
_OPT_MARK_RE = re.compile(r'[A-DＡ-Ｄ]\s*[.．]')


def _strip_tags(h):
    return re.sub(r'<[^>]+>', '', h or '')


def _plain_map(html):
    """去标签后的纯文本 + 「纯文本下标 → html 下标」映射。

    选项定位必须在纯文本上做（公式被包在 <span class="m"> 里，
    字母 A./B. 不在标签外，扫描 html 会漏），但切片必须切 html。
    有了这张映射，两边就能对齐——早先按下标硬切会把 <sub> 拦腰截断。
    """
    plain, pmap, i, n = [], [], 0, len(html)
    while i < n:
        if html[i] == '<':
            j = html.find('>', i)
            if j < 0:
                break
            i = j + 1
            continue
        plain.append(html[i])
        pmap.append(i)
        i += 1
    return ''.join(plain), pmap


_VOID = re.compile(r'<\s*(br|img|hr|meta|link|input)\b', re.I)


def _stack_at(html, pos):
    """html 中下标 pos 处仍处于打开状态的标签名列表。"""
    st, i, n = [], 0, len(html)
    while i < n and i < pos:
        if html[i] == '<':
            j = html.find('>', i)
            if j < 0:
                break
            tag, i = html[i:j + 1], j + 1
            m = re.match(r'</\s*([a-zA-Z0-9]+)', tag)
            if m:
                nm = m.group(1).lower()
                for k in range(len(st) - 1, -1, -1):
                    if st[k] == nm:
                        del st[k:]
                        break
            elif not tag.endswith('/>') and not _VOID.match(tag):
                nm = re.match(r'<\s*([a-zA-Z0-9]+)', tag)
                if nm:
                    st.append(nm.group(1).lower())
        else:
            i += 1
    return st


def _slice_html(html, a, b):
    """切出 html[a:b]，并把跨越边界的标签补齐（补开/补闭）。

    选项常整段包在一个 <span class="m"> 里，还有 <i> 嵌在标记中间；
    直接按位置切会留下半截标签（渲染成乱码或串到下一个选项）。
    """
    if a >= b:
        return ''
    lo, hi = _stack_at(html, a), _stack_at(html, b)
    return (''.join(f'<{t}>' for t in lo)
            + html[a:b]
            + ''.join(f'</{t}>' for t in reversed(hi)))


_MATH_T = re.compile(r'\$[^$]*\$')


def _opt_marks_in(ptext):
    """在纯文本里找选项标记，返回 [(纯文本下标, 选项字母)]。

    两处排除，否则会误判：
      - 公式里的字母（"得到了图中 $ A $、$ B $、$ C $、$ D $ 四个点"）；
      - 前一个字符是字母数字（"如图A点"）。
    """
    spans = [(m.start(), m.end()) for m in _MATH_T.finditer(ptext)]
    out = []
    for m in _OPT_MARK_RE.finditer(ptext):
        i = m.start()
        if any(a <= i < b for a, b in spans):
            continue
        # 只挡 ASCII 字母数字（"UAB" 里的 A）；Ω、μ 等符号不算
        prev = ptext[i - 1] if i > 0 else ''
        if prev.isascii() and prev.isalnum():
            continue
        out.append((i, m.group(0)[0]))
    return out


def _split_stem_options(items):
    """把题目 items 分成 (题干段序列, 选项列表, 图)。

    全程以 html 为准，plain 由 html 去标签得到——两者长度不一致，
    按下标互相切片必然错位。
    """
    stem = []        # (txt_html, plain)
    opts = []        # {letter, html, plain}
    figs = []
    flow = []        # [('p', html) | ('fig', src)] —— 保持原文段落/图的先后
    cur = stem
    for it in items:
        if "fig" in it:
            figs.append(it["fig"])
            flow.append(('fig', it['fig']))
            continue
        for p in it.get("paras", []):
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = (p.get("plain") or "").strip()
            if not plain:
                continue
            ptext, pmap = _plain_map(txt)
            marks = _opt_marks_in(ptext)
            if marks:
                def cut(a, b):
                    """纯文本区间 [a,b) → 对应的 html 片段（跨边界的标签自动补齐）。

                    a==0 时从 html 最开头切，否则段落开头的题图（<img> 在任何
                    纯文本之前）会被漏掉——11.4 自测第 1、3 题的图就这么丢的。
                    """
                    lo = 0 if a == 0 else (pmap[a] if a < len(pmap) else len(txt))
                    hi = pmap[b] if b < len(pmap) else len(txt)
                    return _slice_html(txt, lo, hi).strip()
                head = cut(0, marks[0][0])
                # 源稿偶有选项漏写字母前缀、且被单列一段（11.4 课后练习第 1 题的
                # 「R₁=5.3×10³Ω」），若它紧跟题干、内容很短且形如公式，按 A 选项收。
                hm = re.match(r'^\s*<p>(.*?)</p>\s*$', head, re.S)
                if hm:
                    ht = re.sub(r'<[^>]+>', '', hm.group(1)).strip()
                    if (marks and marks[0][1] == 'B' and len(ht) <= 30
                            and re.match(r'^[A-Za-z]\s*[_^]?\{?[^=]{0,8}[=＝]', ht)):
                        opts.append({'letter': 'A', 'html': hm.group(1), 'plain': ht})
                        head = '' 
                # 题干与选项之间常单独排一张电路图（如 11.4 自测第 1、3 题）。
                # 早先只把这段当题干文字，图就被静默丢了——必须作为图收下。
                head_figs = re.findall(r'<img[^>]*>', head)
                for hf in head_figs:
                    head = head.replace(hf, '')
                    figs.append(hf)
                head = head.strip()
                if head:
                    if cur is opts:
                        cur = stem          # 选项区里又出现题干文字 → 回到题干
                    stem.append((head, _strip_tags(head).strip()))
                    flow.append(('p', head))
                if not any(k == 'opts' for k, _v in flow):
                    # 选项整体渲染成一块（1/2/4 行），但要留在**它原本的位置**——
                    # 多小问的题里选项常夹在 (4) 和 (5) 之间，
                    # 统一挪到末尾会跑到最后一问后面。
                    flow.append(('opts', None))
                for j, (pos, letter) in enumerate(marks):
                    end = marks[j + 1][0] if j + 1 < len(marks) else len(ptext)
                    seg = cut(pos, end)
                    opts.append({"letter": letter, "html": seg,
                                 "plain": _strip_tags(seg).strip()})
                cur = opts
                continue
            # 无选项标记：题干续行（或图注）
            if cur is opts:
                cur = stem
            stem.append((txt, plain))
            flow.append(('p', txt))
    return stem, opts, figs, flow


# 选项排布：按长短自动 1 行 / 2 行 / 4 行（仅校本作业启用，见 build.py）
OPTS_LINES = False
# 一行大约能排下的字数（含选项字母），据此决定分几行
_OPT_1LINE_SUM, _OPT_1LINE_MAX = 36, 10
_OPT_2LINE_SUM = 76          # 2 行时每行约 38 字


def _strip_opt_mark(html, letter):
    """去掉选项开头的字母标记（可能被 <i> 包着，如 "<i>A</i>.…"）。"""
    esc = re.escape(letter)
    pat = (r'^\s*(?:<[^>]+>\s*)*' + esc + r'\s*(?:</[^>]+>\s*)*[.、．]?\s*')
    out = re.sub(pat, '', html or '', count=1)
    return out if out.strip() else (html or '')


def _opts_html(opts):
    """选项 HTML。

    旧行为：短的一行铺满(.justified)，否则每项一行(.stacked)。
    新行为(OPTS_LINES)：按长短分 1 / 2 / 4 行，1、2 行时行内等间距、两边对齐。
    """
    items = []
    for o in opts:
        items.append(f'<span class="opt"><span class="ol">{o["letter"]}．</span>'
                     f'<span class="oc">{_strip_opt_mark(o["html"], o["letter"])}</span></span>')
    body = "".join(items)
    if not OPTS_LINES or len(opts) < 2:
        short = opts and max(len(o["plain"]) - 2 for o in opts) <= 16
        cls = "justified" if (short and len(opts) >= 2) else "stacked"
        return f'<div class="opts {cls}">{body}</div>'
    lens = [len(o["plain"]) - 2 for o in opts]
    total, longest = sum(lens), max(lens)
    if longest <= _OPT_1LINE_MAX and total <= _OPT_1LINE_SUM:
        cls = "l1"
    elif total <= _OPT_2LINE_SUM:
        cls = "l2"
    else:
        cls = "l4"
    return f'<div class="opts {cls}">{body}</div>'


def _flow(items, is_question=False, ask_lines=False, number=False):
    """把某节内 items 重排成 HTML 正文。

    is_question=True：识别题干 + 选项，选项单独成块（不并入题干流），
    并按长短决定每行 1 个或 2 列。
    否则普通段落流动。
    """
    if is_question:
        stem, opts, figs, flow = _split_stem_options(items)
        # 源稿偶有 A 选项漏写字母前缀、独段排在题干与图之间
        # （11.4 课后练习第 1 题的「R₁=5.3×10³Ω」）。它会被当成题干续段，
        # 导致图把它与 B/C/D 隔开。这里把它提出来作为 A 选项。
        if opts and len(stem) > 1:
            last_h, last_p = stem[-1]
            if (len(last_p) <= 30 and not re.search(r'[。？?]\s*$', last_p)
                    and re.match(r'^[A-Za-z]\s*[_^]?\{?[^=＝]{0,8}[=＝]', re.sub(r'<[^>]+>', '', last_h).strip())):
                opts.insert(0, {'letter': 'A', 'html': last_h, 'plain': last_p})
                stem = stem[:-1]
        parts = []
        if PRESERVE_PARAS:
            for (txt, _p) in stem:                 # 段落已完整，逐段输出
                parts.append(f"<p>{txt}</p>")
        else:
            # 题干：合并成流动段落
            sbuf = []
            for (txt, plain) in stem:
                if sbuf and sbuf[-1] and plain:
                    lc, fc = sbuf[-1][-1] if isinstance(sbuf[-1], str) else "", plain[0]
                    if _is_word_boundary(sbuf, plain):
                        sbuf.append(" ")
                sbuf.append(txt)
            if sbuf:
                parts.append(f"<p>{''.join(sbuf)}</p>")
        # 按原文顺序输出「段落 / 图」，图跟它上面的小问走——
        # 一道题有多问时，属于 (2) 的图不能提到整题开头或末尾。
        parts = []
        for kind, val in flow:
            if kind == 'fig':
                parts.append(f'<div class="fig"><img src="{val}"></div>')
            elif kind == 'opts':
                if opts:                     # 选项块就留在原位
                    parts.append(_opts_html(opts))
            else:
                parts.append(f"<p>{val}</p>")
        if opts and not any(k == 'opts' for k, _v in flow):
            parts.append(_opts_html(opts))   # 兜底：flow 里没有占位时仍要输出
        return "".join(parts)
    if PRESERVE_PARAS:
        # 每个 para 独立成段，不做标点驱动的合并
        out = []
        idx = 0
        for it in items:
            if "fig" in it:
                out.append(f'<div class="fig"><img src="{it["fig"]}"></div>')
                continue
            for p in it.get("paras", []):
                plain = (p.get("plain") or "").strip()
                if not plain:
                    continue
                body = p.get("html") or esc(p["plain"])
                idx += 1
                if number:
                    body = f'<span class="subno">{idx}．</span>' + body
                out.append(f'<p>{body}</p>')
                if ask_lines and _needs_answer_line(plain):
                    out.append('<div class="ansspace one"><div class="wline"></div></div>')
        return "".join(out)
    # 普通流动
    out = []
    buf = []
    buf_plain = []
    def flush():
        nonlocal buf, buf_plain
        if buf:
            out.append(f"<p>{''.join(buf)}</p>")
            buf, buf_plain = [], []
    for it in items:
        if "fig" in it:
            flush()
            out.append(f'<div class="fig"><img src="{it["fig"]}"></div>')
            continue
        for p in it.get("paras", []):
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = (p.get("plain") or "").strip()
            if not plain:
                continue
            if buf_plain:
                prev_last = (buf_plain[-1] or "").strip()[-1:] if (buf_plain[-1] or "").strip() else ""
                if _NEW_LINE.match(plain) or (_SENT_END.search(prev_last) and plain[0] not in "，。；、）)"):
                    flush()
            if _is_word_boundary(buf_plain, plain):
                buf.append(" ")
            buf.append(txt)
            buf_plain.append(plain)
    flush()
    return "".join(out)


def _is_word_boundary(buf_plain, plain):
    if buf_plain and buf_plain[-1] and plain:
        lc = buf_plain[-1][-1]
        fc = plain[0]
        return lc.isascii() and lc.isalnum() and fc.isascii() and fc.isalnum()
    return False


def q_key(s):
    """题目在 ans_by_no 里的 key：多题组（11.4 的《一》《二》）时带组号。"""
    g = s.get("qgroup") or 0
    return (s.get("no"), g) if g else s.get("no")


def section_q(s):
    return f'<div class="q"><div class="qn">{s.get("no","")}</div>' \
           f'<div class="qbody">{_flow(s["items"], is_question=True)}</div></div>'


_HAS_BLANK = re.compile(r'[（(]\s*[　\s]*[）)]')
_ALREADY_NO = re.compile(r'^\s*[（(]?\d{1,2}\s*[）).．、]')


def _auto_number(items):
    """多个「带填空括号」的小题且都没编号时，自动补 1．2．3．。

    【判断正误】这类小节常直接罗列若干陈述句，末尾各带一个 (　　)，
    原稿没有序号，学生不好指认，这里自动编号。
    """
    texts = [p["plain"].strip() for it in items if "paras" in it
             for p in it["paras"] if p["plain"].strip()]
    if len(texts) < 2:
        return False
    if not all(_HAS_BLANK.search(t) for t in texts):
        return False
    return not any(_ALREADY_NO.match(t) for t in texts)


def section_task(s):
    num = _auto_number(s["items"])
    return f'<div class="task"><div class="t-head">{esc(s["title"])}</div>' \
           f'{_flow(s["items"], ask_lines=ASK_LINES, number=num)}</div>'


# 需要留作答行的 sec-h 小节（学习目标只列条目，不留白）
_ASK_SECTIONS = ('课前学习任务', '课上学习任务', '课堂探究', '自我测评')


def section_h(s):
    # 课前任务、课堂探究里的思考题等都要留作答空间
    ask = ASK_LINES and any(k in (s.get("title") or '') for k in _ASK_SECTIONS)
    return f'<div class="sec-h"><div class="sec-t">{esc(s["title"])}</div>' \
           f'{_flow(s["items"], ask_lines=ask)}</div>'


_EQUATIONISH = re.compile(r'^[A-Za-z0-9E=𝑊φU|]+\s*[=＝]|^[A-Za-z]{1,3}\d?\s*[=＝]|^W\d*\s*=')

def _is_eq_line(t):
    """判断一行是否像独立公式行（以变量=开头等）。"""
    s = t.strip()
    if not s:
        return False
    # 去除开头的题号
    s = re.sub(r'^\d+\s*[.、．]\s*', "", s)
    # 去 html 标签后判断
    s2 = re.sub(r'<[^>]+>', "", s)
    return bool(_EQUATIONISH.match(s2)) and len(s2) < 80


def answer_items_html(items):
    """答案内容：
      - 纯文字(散文行)合并成连续段落；
      - 独立公式行(变量=…)保留断行成独立 <p>，避免公式粘连；
      - 去掉行首残留题号。
    """
    if PRESERVE_PARAS:
        out = []
        for it in items:
            if "fig" in it:
                out.append(f'<div class="fig"><img src="{it["fig"]}"></div>')
                continue
            for p in it["paras"]:
                if (p.get("plain") or "").strip():
                    out.append(f'<p>{p.get("html") or esc(p["plain"])}</p>')
        return "".join(out)
    out = []
    prose = []
    def flush_prose():
        nonlocal prose
        if prose:
            joined = "".join(t for t in prose)
            joined = re.sub(r'^\d+\s*[.、．]\s*', "", joined)
            out.append(f"<p>{joined}</p>")
            prose = []
    for it in items:
        if "fig" in it:
            flush_prose()
            out.append(f'<div class="fig"><img src="{it["fig"]}"></div>')
            continue
        for p in it["paras"]:
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = re.sub(r'<[^>]+>', "", txt)
            if _is_eq_line(plain):
                flush_prose()
                eq = re.sub(r'^\d+\s*[.、．]\s*', "", txt)
                out.append(f"<p class='eq'>{eq}</p>")
            else:
                prose.append(txt)
    flush_prose()
    return "".join(out)


def section_ans(s):
    tag = "参考答案" if s["kind"] == "answer" else ("解析" if s.get("tag") == "解析" else "答案")
    return (f'<div class="ans-block"><div class="ans-tag">{esc(s.get("title") or tag)}</div>'
            f'{answer_items_html(s["items"])}</div>')


def _question_has_options(s):
    """判断题目是否带 A./B./C./D. 选项（选项须作为独立条目出现，排除"A 点"等几何点）。"""
    for it in s["items"]:
        if "paras" in it:
            for p in it["paras"]:
                t = re.sub(r"<[^>]+>", "", p.get("html", "") or p.get("plain", ""))
                # 独立成行的 A.内容（选项通常独占一行/一段）
                if re.match(r'^\s*[A-DＡ-Ｄ]\s*[.、．]', t.strip()):
                    return True
                # 或文本内出现连续选项段 "A．… B．…"
                if re.search(r'[A-DＡ-Ｄ]\s*[.、．][^。]{4,40}?[A-DＡ-Ｄ]\s*[.、．]', t):
                    return True
    return False


def _answer_space_html(s, q_body_len=None):
    """为学生版计算/解答题生成作答横线留白（虚线）。

    行数按题干长短决定但整体偏少，避免作答区过高而把整题挤到下一页：
      - 简短题(≤120字): 4 行
      - 中等(≤220字): 5 行
      - 较长: 6~8 行
    """
    chars = sum(len(re.sub(r"<[^>]+>", "", p.get("html", "") or p.get("plain", "")))
                for it in s["items"] for p in it.get("paras", []))
    if chars <= 130:
        lines = 3
    elif chars <= 230:
        lines = 4
    else:
        lines = min(5 + chars // 100, 6)
    return f'<div class="ansspace">' + "".join('<div class="wline"></div>' for _ in range(lines)) + '</div>'


def _lesson_tag_from_title(title):
    """从标题 "电势能和电势（第一课时）· 学习任务单" 提取课时前缀。"""
    t = (title or "").split("·")[0].strip()
    return t


def _task_answer_html(s, lesson_key, self_answers=None):
    """取某学习任务的参考解析（HTML 片段），无则返回 None。

    查找顺序：本节自带的 ans 小节 → task_answers 解析库 → SELF_ANSWERS 兜底。
    """
    sa = self_answers if self_answers is not None else SELF_ANSWERS
    title = s.get("title", "")
    no = s.get("no")
    # 1) 本节自带的答案小节（docx 直接写在学习任务里的情形）
    if no is not None and no in sa:
        return answer_items_html(sa[no]) if isinstance(sa[no], list) else str(sa[no])
    try:
        from task_answers import pick_task_answer
    except Exception:
        return None
    task_body = " ".join(p.get("plain", "")
                         for it in s.get("items", []) for p in it.get("paras", []))
    try:
        raw = pick_task_answer(lesson_key, title, task_body)
    except Exception:
        return None
    if not raw:
        return None
    return raw if "<" in raw else esc(raw).replace("\n", "<br>")


def _maybe_task_answer(parts, s, lesson_key, self_answers=None, tag="【参考解析】"):
    body = _task_answer_html(s, lesson_key, self_answers)
    if body:
        parts.append(f'<div class="ans-inline self taskans"><div class="ans-tag">{tag}</div>'
                     f'<div class="ans-body">{body}</div></div>')


def render_mode(sections, mode, title, self_answers=None, lesson_key=None):
    """按 mode 输出正文 HTML。mode: student/teacher/answer"""
    self_answers = self_answers or SELF_ANSWERS
    if lesson_key is None:
        lesson_key = _lesson_tag_from_title(title)
    try:
        from retypeset import split_answer_by_no
        ans_by_no = split_answer_by_no(sections)
    except Exception:
        ans_by_no = {}
    if mode == "answer":
        # 答案版 = 纯答案：不印题干、不印任务单内容、不插图。
        # 学习任务只留「任务名 + 参考解析」，课后练习只留「题号 + 答案」。
        parts = []
        ex_head_done = False
        for s in sections:
            if s["kind"] == "task":
                head = esc(s.get("title", ""))
                body = _task_answer_html(s, lesson_key, self_answers)
                if not body:
                    body = '<p class="nonset">（开放性任务，无统一答案）</p>'
                parts.append(f'<div class="ans-block"><div class="ans-tag">{head}　参考答案</div>'
                             f'<div class="ans-body">{body}</div></div>')
            elif s["kind"] in ("ans", "answer"):
                if not ex_head_done:
                    parts.append('<div class="ans-sec">课后练习</div>')
                    ex_head_done = True
                parts.append(section_ans(s))
        return "".join(parts)
    # student / teacher
    parts = []
    for s in sections:
        if s["kind"] == "q":
            has_opts = _question_has_options(s)
            qh = section_q(s)
            # 学生版：只要该题需要作答区（选择、填空、解答）都包 qwrap，
            # 这样带图的题才能排成「题干 / 左作答区 + 右配图」。
            # 纯选择且完全不需要留白的题不包，保持紧凑。
            if mode == "student":
                # 选择题不需要留作答虚线（答案就写在选项上）。
                # 但仍要包 qwrap——带图的选择题靠它排成「题干 + 左区/右图」。
                space = "" if has_opts else _answer_space_html(s)
                parts.append(f'<div class="qwrap">{qh}{space}</div>')
            else:
                parts.append(qh)
            if mode == "teacher":
                no = s.get("no")
                aitems = ans_by_no.get(q_key(s)) or ans_by_no.get(no)
                if aitems:
                    # 分清两件事：答案本身是否来自原稿、解析是否我方补写。
                    # 有的讲原稿只给答案不给解析（如 11.5 多用电表），
                    # 那时答案照常标【答案】，只有解析标【参考解析】。
                    has_ref_only = all(
                        any(p.get('plain', '').strip() for p in it.get('paras', []))
                        for it in aitems) and any('参考' in (x.get('title') or '')
                                                  for x in sections
                                                  if x.get('kind') == 'ans'
                                                  and x.get('no') == no
                                                  and (x.get('qgroup') or 0) == (s.get('qgroup') or 0))
                    cls = 'ans-inline self' if has_ref_only else 'ans-inline'
                    lab = '【答案与参考解析】' if has_ref_only else '【答案】'
                    parts.append(f'<div class="{cls}"><div class="ans-tag">{lab}</div>'
                                 f'{answer_items_html(aitems)}</div>')
                else:
                    # 去空白后匹配（标题可能含不同空格）
                    def _norm(s_):
                        return re.sub(r"\s+", "", s_ or "")
                    key = (title, no)
                    found = None
                    if key in self_answers:
                        found = self_answers[key]
                    else:
                        for (kt, kn), v in self_answers.items():
                            if kn == no and _norm(kt) == _norm(title):
                                found = v
                                break
                    if found is not None:
                        if "<" in found:
                            fb = found
                        else:
                            fb = esc(found).replace("\n", "<br>")
                        parts.append(f'<div class="ans-inline self"><div class="ans-tag">【参考解答】</div>'
                                     f'<p>{fb}</p></div>')
        elif s["kind"] == "task":
            parts.append(section_task(s))
            # 教师版：任务后跟人工解析（HTML 已含上下标/斜体排版）
            if mode == "teacher":
                _maybe_task_answer(parts, s, lesson_key, self_answers)
        elif s["kind"] == "h":
            parts.append(section_h(s))
    return "".join(parts)


def build_page(title, subtitle, sections, mode, lesson_key=None):
    body = render_mode(sections, mode, title, lesson_key=lesson_key)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>
<div class="hd"><span class="sch">{SCHOOL} · 物理校本作业</span><span class="ttl">{esc(title)}</span></div>
{body}
</body></html>"""


CSS = """
@page{size:A4;margin:17mm 16mm 16mm 16mm}
*{box-sizing:border-box}
body{font-family:"Songti SC","STSong","SimSun","Noto Serif CJK SC",serif;font-size:11.5pt;line-height:1.85;color:#111;margin:0}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2.2px solid #007020;padding-bottom:3px;margin-bottom:12px;font-family:"PingFang SC","Microsoft YaHei",sans-serif}
.hd .sch{font-weight:800;color:#0E4E33;font-size:10pt}
.hd .ttl{color:#0E4E33;font-size:10.5pt;font-weight:700}
p{margin:0 0 .35em;text-align:justify}
/* 含行内公式的段落不要两端对齐：公式是 nowrap 的原子块，
   浏览器为了撑满行宽会把两侧汉字拉成"散字"（判断正误第 3 条就出现过）。 */
p:has(.m){text-align:left}
/* 段落（学习目标/课前任务） */
.sec-h{margin:14px 0 4px}
.sec-h .sec-t,.task .t-head{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-weight:800;color:#007020;font-size:13pt;border-left:5px solid #007020;padding-left:9px;margin:2px 0 6px}
.sec-h .sec-t{color:#0E4E33}
.sec-h p{margin:.15em 0}
.sec-h ol,.sec-h ul{margin:.2em 0 .4em;padding-left:1.6em}
/* 任务 */
.task{margin:12px 0 6px}
.task .t-head{font-size:12pt;color:#0E4E33;border-left:4px solid #0E4E33}
/* 题目 */
.q .qn{font-weight:800;color:#007020;flex:0 0 auto;font-family:"PingFang SC",sans-serif}
.q .qbody{flex:1;min-width:0}
.q .qbody p{margin:0 0 .3em}
/* 图 */
.fig{text-align:center;margin:6px 0}
.fig img{max-height:108px;max-width:80mm;background:#fff}
/* 答案（教师版逐题/答案整段） */
.ans-inline,.ans-block{font-family:"PingFang SC","Microsoft YaHei",sans-serif}
.ans-inline{margin:2px 0 16px 34px;padding:7px 12px;background:#f1f7f2;border-left:3px solid #007020;border-radius:0 8px 8px 0}
.ans-inline.self{background:#fff7e6;border-left-color:#c9a227}
.ans-inline.taskans .ans-body{font-family:"Songti SC","Times New Roman",serif;font-size:11pt;line-height:1.8;color:#3a2c05}
.ans-inline.taskans .ans-body i{font-style:italic;font-family:"Times New Roman","STIXGeneral",serif}
.ans-inline.taskans .ans-body sub,.ans-inline.taskans .ans-body sup{font-size:.72em;line-height:0}
.ans-inline.taskans .ans-body .eqline{text-align:center;margin:4px 0;font-size:11.5pt}
.ans-tag{font-weight:800;color:#0E4E33;font-size:10.5pt;margin-bottom:2px}
.ans-block{margin:16px 0;break-inside:avoid}
.ans-block .ans-tag{font-size:12pt}
.ans-inline p,.ans-block p{margin:.15em 0;color:#123;font-family:"Songti SC",serif;text-align:left;overflow-wrap:break-word;word-break:break-word}
.ans-inline sup,.ans-inline sub,.ans-block sup,.ans-block sub,.qbody sup,.qbody sub{line-height:0}
.ans-inline i,.ans-block i,.qbody i,.pbody i{font-style:italic}
p{overflow-wrap:break-word;word-break:break-word}
/* 学生版作答留白：虚线（可随页续排以填满空间；单条虚线不截断） */
.ansspace{margin:2px 0 10px 0;padding-left:2px}
.ansspace .wline{height:1.45em;border-bottom:1px dashed #b9c4bb;margin:0 6px 0 0;break-inside:avoid}
.ansspace .wline:last-child{margin-bottom:2px}
/* 任务单作答行：仅一条虚线，紧贴问题下方 */
.ansspace.one{margin:1px 0 9px;padding-left:1.6em}
.ansspace.one .wline{height:1.5em;margin-bottom:0}
/* 允许自然跨页以填满空间；虚线区整块不拆 */
.qwrap{break-inside:auto}
.q{display:flex;gap:8px;margin:12px 0 3px;break-inside:auto}
.q .qn{font-weight:800;color:#007020;flex:0 0 auto;font-family:"PingFang SC",sans-serif}
.q .qbody{flex:1;min-width:0}
.q .qbody p{margin:0 0 .3em;break-inside:avoid}
.q .qbody .fig{break-inside:avoid}
/* 选择题选项 */
.opts{margin:4px 0 6px;display:flex;align-items:baseline}
.opts .opt{display:inline-flex;align-items:baseline;margin:2px 0}
.opts .ol{font-weight:700;color:#007020;flex:0 0 auto;margin-right:3px}
.opts .oc{flex:0 1 auto}
.q .qbody .opts .opt{break-inside:avoid}
/* 短选项：一行内等间距铺满 */
.opts.justified{justify-content:space-between;flex-wrap:nowrap}
.opts.justified .opt{flex:1 1 0;justify-content:flex-start}
/* 长选项：每项占整行（内容超长时内部自然折行） */
.opts.stacked{flex-direction:column;align-items:stretch}
.opts.stacked .opt{width:100%}
/* 自动补的小题号（判断正误等） */
.subno{font-weight:700;color:#007020;margin-right:2px}
/* 1 行：各项等分，铺满整行、两边对齐 */
.opts.l1{flex-wrap:nowrap;justify-content:space-between}
.opts.l1 .opt{flex:1 1 0;min-width:0;justify-content:flex-start}
/* 2 行：每行 2 项，行内等间距、两边对齐 */
.opts.l2{flex-wrap:wrap;justify-content:space-between;row-gap:2px}
.opts.l2 .opt{flex:0 0 48%;max-width:48%}
/* 4 行：每项独占一行 */
.opts.l4{flex-direction:column;align-items:stretch}
.opts.l4 .opt{width:100%}
"""


def build_task_sheet(title, sections, mode):
    return build_page(title, "", sections, mode)


# 平台未提供答案的课后练习题目 → 人工参考解答
# key: (题面标题, 题号)；标题形如 "电源和电流（第二课时）· 课后练习"
SELF_ANSWERS_EXTRA = {
    ("电源和电流（第二课时）· 课后练习", 1):
        "I = n e S v。推导：Δt 内通过横截面的自由电子数 N=n·(S·vΔt)，"
        "电量 Q=Ne=n e S v Δt，I=Q/Δt=n e S v。",
    ("电源和电流（第二课时）· 课后练习", 2):
        "个数 N=n·S·v·Δt（即 n S v Δt 个）。"
        "也可由 I=nqSv 得 nSv=I/q，故 N=nSvΔt=IΔt/q。",
    ("电源和电流（第二课时）· 课后练习", 3):
        "电子绕核运动一周时间 T=2πR/v，而库仑力提供向心力 ke²/R²=mv²/R ⇒ v=√(ke²/(mR))。"
        "等效环形电流 I=e/T=e/(2πR/v)=ev/(2πR)= (e/2πR)·√(ke²/(mR))。",
    ("电源和电流（第二课时）· 课后练习", 4):
        "串联电流相等：I1=I2，即 n1 e S v1 = n2 e S v2（S 相同）⇒ v1/v2 = n2/n1。"
        "设第二条导线单位体积电子数为 n，第一条为 2n，则 v1/v2 = n/(2n)=1/2。",
    ("电源和电流（第二课时）· 课后练习", 5):
        "单位长度银的质量 m=ρS·1；对应摩尔数 ρS/M；银原子数（自由电子数）"
        "N=ρS·NA/M。故单位长度自由电子数 nL = ρ S NA / M。",
}

SELF_ANSWERS.update(SELF_ANSWERS_EXTRA)
