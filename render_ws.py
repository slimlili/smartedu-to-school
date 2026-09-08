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


def _split_stem_options(items):
    """把题目 items 分成 (题干段序列, 选项列表, 图)。选项按行识别。"""
    stem = []        # (txt_html, plain)
    opts = []        # {letter, html, plain}
    figs = []
    cur = stem
    for it in items:
        if "fig" in it:
            figs.append(it["fig"])
            continue
        for p in it.get("paras", []):
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = (p.get("plain") or "").strip()
            if not plain:
                continue
            m = _OPT_LINE.match(plain)
            if m:
                cur = opts
                # 一个 para 可能含多个选项（如 "A．a B．b C．c D．d"），拆开
                parts = re.split(r'(?=[A-DＡ-Ｄ]\s*[.、．])', plain)
                html_parts = re.split(r'(?=[A-DＡ-Ｄ]\s*[.、．])', txt)
                for pp, hh in zip(parts, html_parts):
                    pm = _OPT_LINE.match(pp.strip())
                    if pm and pm.group(1):
                        opts.append({"letter": pm.group(1), "html": hh, "plain": pp.strip()})
                # 若拆分失败（无字母匹配）则整段当作一个选项
                if not any(o.get("letter") == m.group(1) for o in opts[-8:]):
                    opts.append({"letter": m.group(1), "html": txt, "plain": plain})
            else:
                # 题干行内可能内嵌选项：如 "麦克斯韦电磁场理论告诉我们( ) A．… B．…"
                # 找到第一个选项标记的位置切开：前段=题干，后段拆成选项
                idxs = [mm.start() for mm in re.finditer(r'[A-DＡ-Ｄ]\s*[.、．]', plain)]
                if idxs:
                    first = idxs[0]
                    head_plain = plain[:first].strip()
                    head_txt = txt[:first].strip()
                    rest_plain = plain[first:]
                    rest_txt = txt[first:]
                    if head_plain:
                        stem.append((head_txt, head_plain))
                    # 拆 rest 成选项
                    parts = re.split(r'(?=[A-DＡ-Ｄ]\s*[.、．])', rest_plain)
                    hparts = re.split(r'(?=[A-DＡ-Ｄ]\s*[.、．])', rest_txt)
                    for pp, hh in zip(parts, hparts):
                        pm = _OPT_LINE.match(pp.strip())
                        if pm and pm.group(1):
                            opts.append({"letter": pm.group(1), "html": hh, "plain": pp.strip()})
                    continue
                # 若已进入选项区却出现非选项文本，多半是题干续行/图注 → 仍并入题干
                if cur is opts and not _OPT_LINE.match(plain):
                    cur = stem
                stem.append((txt, plain))
    return stem, opts, figs


def _opts_html(opts):
    """选项 HTML。
    - 四项都较短 → 一行内等间距铺满(.justified, space-between)
    - 否则 → 每项占一行(自动按内容换行)"""
    items = []
    for o in opts:
        t = re.sub(r'^[A-DＡ-Ｄ]\s*[.、．]\s*', "", o["html"])
        items.append(f'<span class="opt"><span class="ol">{o["letter"]}．</span><span class="oc">{t}</span></span>')
    short = opts and max(len(o["plain"]) - 2 for o in opts) <= 16
    cls = "justified" if (short and len(opts) >= 2) else "stacked"
    return f'<div class="opts {cls}">{"".join(items)}</div>'


def _flow(items, is_question=False):
    """把某节内 items 重排成 HTML 正文。

    is_question=True：识别题干 + 选项，选项单独成块（不并入题干流），
    并按长短决定每行 1 个或 2 列。
    否则普通段落流动。
    """
    if is_question:
        stem, opts, figs = _split_stem_options(items)
        parts = []
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
        for f in figs:
            parts.append(f'<div class="fig"><img src="{f}"></div>')
        if opts:
            parts.append(_opts_html(opts))
        return "".join(parts)
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


def section_q(s):
    return f'<div class="q"><div class="qn">{s.get("no","")}</div>' \
           f'<div class="qbody">{_flow(s["items"], is_question=True)}</div></div>'


def section_task(s):
    return f'<div class="task"><div class="t-head">{esc(s["title"])}</div>' \
           f'{_flow(s["items"])}</div>'


def section_h(s):
    # 学习目标/课前任务等：标题 + 正文
    return f'<div class="sec-h"><div class="sec-t">{esc(s["title"])}</div>{_flow(s["items"])}</div>'


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
        parts = []
        for s in sections:
            if s["kind"] in ("ans", "answer"):
                parts.append(section_ans(s))
        return "".join(parts)
    # student / teacher
    parts = []
    for s in sections:
        if s["kind"] == "q":
            has_opts = _question_has_options(s)
            qh = section_q(s)
            if mode == "student" and not has_opts:
                parts.append(f'<div class="qwrap">{qh}{_answer_space_html(s)}</div>')
            else:
                parts.append(qh)
            if mode == "teacher":
                no = s.get("no")
                aitems = ans_by_no.get(no)
                if aitems:
                    parts.append(f'<div class="ans-inline"><div class="ans-tag">【答案】</div>'
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
                try:
                    from task_answers import pick_task_answer
                    task_body = " ".join(p.get("plain", "")
                                         for it in s["items"] for p in it.get("paras", []))
                    raw = pick_task_answer(lesson_key, s.get("title", ""), task_body)
                    if raw:
                        if "<" in raw:
                            body = raw  # 已是 HTML（含 sub/sup）
                        else:
                            body = esc(raw).replace("\n", "<br>")  # 纯文本 → 转义 + 换行
                        parts.append(f'<div class="ans-inline self taskans"><div class="ans-tag">【参考解析】</div>'
                                     f'<div class="ans-body">{body}</div></div>')
                except Exception:
                    pass
        elif s["kind"] == "h":
            parts.append(section_h(s))
    return "".join(parts)


def build_page(title, subtitle, sections, mode):
    body = render_mode(sections, mode, title)
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
