# -*- coding: utf-8 -*-
"""扁平块序列 → sections（render_ws / build_deck_html 通用格式）。

section = {'kind': 'h'|'task'|'q'|'ans'|'answer', 'title'|'no', 'items':[...]}
item    = {'paras':[{'html','plain'}]} 或 {'fig': 'media/x.png'}

各文件版式略有差异，用 SPEC 配置驱动，不写死单个文件。
"""
import re

# 大节标题（独立成段；可带 [] 【】 包裹）
H_TITLES = ('学习目标', '课前学习任务', '课上学习任务', '课后练习', '课后作业',
            '课堂探究', '自我测评', '学习目标与任务', '推荐的学习资源',
            '课程基本信息', '课后练习答案')
# 注意：不要把裸「学习任务」放进 H_TITLES —— 会让「【学习任务四】拓展学习…」
# 被截成标题「学习任务」，丢了任务号。任务由 TASK_RE 处理。
# 平台版式表里的样表行，直接丢弃
BOILER_RE = re.compile(r'^(课程基本信息|课题|教科书|书名[:：]|出版社[:：]|出版日期|学生信息|'
                       r'姓名|学校|班级|学号|推荐的学习资源|$)$')
TASK_RE = re.compile(r'^【\s*学习任务[^】]*】|^【\s*目标[^】]*】|^【\s*判断正误\s*】')
Q_NO_RE = re.compile(r'^(\d{1,2})\s*[.．、]\s*(?=\S)')
# 选项行必须以字母+. 开头，且后面不是常见误判
OPT_RE = re.compile(r'^([A-DＡ-Ｄ])\s*[.．、]\s*\S')
# 答案大块内的题号： "答案1AB 2C" / "5答案" / "6. 答案" / "7．答案"
ANS_INLINE_RE = re.compile(r'(\d{1,2})\s*([A-DＡ-Ｄ]{1,4})(?![A-Za-z0-9])')
# 答案块里的逐题标记："2.D" "3. BD" "4. 1.5V"。
# 点号后必须不是数字，否则会把小数（1.5V、2.9×10-3）当题号。
# 全角 ．、 很明确是题号（小数不会用全角点），点号后允许空格；
# 半角 . 后面必须紧跟非数字（"2.D" 是题号，"2.9×10" 是小数）。
# 逐题标记的候选（宽松匹配）：行首/空白后 + 题号 + 点号 + 后面还有内容。
# 半角点号要再过滤（见 _ans_marks）：点号后是数字的其实是小数（4. 1.5V 里的 1.5），
# 只有全角 ．、 才算题号。不能把过滤写进正则——\s* 会回溯，把 "4. " 的空格吐回去。
_ANS_MARK_LOOSE = re.compile(r'(?:^|(?<=[\s　]))(\d{1,2})[.．、](?=\s*\S)')
# 答案行形如 "1．18.4"、"3．10.045　0.320 0"、"7．A　11.28　小于"：
# 题号后紧跟数值/字母答案，而非一段题干文字。
_ANS_LINE = re.compile(r'^\d{1,2}\s*[.．、]\s*'
                       r'(?:[A-D]{1,4}\b|[-−+]?\d+(?:\.\d+)?|[(（]\d{1,2}[)）]'
                       # 答案也可能以公式/符号起头（"1.R_{A}>R_{B}=R_{C}>R_{D}"）
                       r'|\\?[A-Za-z_$]|\$)')
# 答案正文常以「由/因为/根据/解/答」等起头接公式或演算（如 "2.由$ \frac{R_V}{R_x}=…"），
# 这类也属于答案行，不能当题干。
_ANS_PROSE = re.compile(r'^\d{1,2}\s*[.．、]\s*(?:由|因|根据|解|答|故|选|设|当|若|则)')


def _looks_like_answer_line(text):
    """判断是否像「题号 + 答案」的答案行（而非题干）。"""
    t = text.strip()
    return bool(_ANS_LINE.match(t) or _ANS_PROSE.match(t))


_MATH_SPAN = re.compile(r'\$([^$]{1,200})\$')


def _ans_text_html(text):
    """答案串只有 plain（按字符位置切出来的），需自己补 HTML：
    转义后把 $...$ 里的 LaTeX 渲染成公式，避免 `\\frac{...}` 源码漏进成品。"""
    if not text:
        return ''
    try:
        from latex2html import math_html
    except Exception:
        math_html = None
    spans = list(_MATH_SPAN.finditer(text))
    if not spans and math_html and re.search(r'\\[a-zA-Z]{2,}', text):
        # 整串就是裸 LaTeX（无 $ 定界），直接整体渲染
        return math_html(text)
    out, last = [], 0
    for m in spans:
        out.append(_esc(text[last:m.start()]))
        tex = m.group(1)
        out.append(math_html(tex) if math_html else _esc(tex))
        last = m.end()
    out.append(_esc(text[last:]))
    return ''.join(out)


def _esc(t):
    return (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _ans_marks(text, strict=True):
    """返回答案串里各题号标记的 (起点, 题号)。

    strict=True 时把「半角点号后跟数字」的当作小数跳过（4. 1.5V 的 1.5），
    但它仍是一个分段边界——否则 4.、5. 两题的答案会被并进上一题。
    """
    out = []
    for m in _ANS_MARK_LOOSE.finditer(text):
        dot = text[m.end() - 1]
        nxt = text[m.end()] if m.end() < len(text) else ''
        # 半角点号「紧跟」数字才是小数（1.5、10.045）；隔了空格就是题号（"4. 1.5V"）
        if dot == '.' and nxt.isdigit():
            continue
        out.append((m.start(), int(m.group(1))))
    return out
ANS_HEAD_RE = re.compile(r'^(?:【[^】]*答案[^】]*】|参考答案|答案)\s*[:：]?')
ANS_NO_RE = re.compile(r'^(\d{1,2})\s*[.．、]?\s*(?:【[^】]*答案[^】]*】|答案|参考答案)\s*[:：]?\s*')
JX_RE = re.compile(r'^(?:【[^】]*解析[^】]*】|解析|详解|点拨)\s*[:：]?\s*')


def _fig_name(item):
    """取图项的 media 文件名；非图项返回 None。"""
    f = item.get('fig') if isinstance(item, dict) else None
    return f.split('/')[-1] if f else None


def _dedup_figs(items):
    """同一题的图去重。

    源稿常把图**同时**内联在题干段落里（html 中的 <img>）和作为独立
    图块排在题干之后，两处都收就会重复出现（11.5 第 6 题、11.3b 任务五）。
    以题干里已内联的图为准，其余按文件名去重。
    """
    inline = set()
    for it in items:
        for p in it.get('paras', []):
            for m in re.finditer(r'src="media/([^"]+)"', p.get('html') or ''):
                inline.add(m.group(1).split('/')[-1])
    seen, out = set(), []
    for it in items:
        nm = _fig_name(it)
        if nm is None:
            out.append(it)
            continue
        if nm in inline or nm in seen:
            continue
        seen.add(nm)
        out.append(it)
    return out


def _paras(html, plain):
    """构造段落。总闸：调用方若把 plain 直接当 html 传（html == plain），
    而这段文字里含 LaTeX，就自动转义并渲染公式——否则源码会漏进成品。"""
    if html == plain and plain and ('\\' in plain or '$' in plain):
        html = _ans_text_html(plain)
    return {'paras': [{'html': html, 'plain': plain}]}


# 题号标记之前可能挂着的题图与空标签——找标记时要跳过，但内容要保留。
# 不能笼统跳过 <[^>]+> 再把结果丢掉，那会把题图整个吃掉（11.2 第 1、3 题丢过图）。
_LEAD_KEEP = re.compile(
    r'^(?:\s|<img[^>]*>|<(?:sub|sup|i|b|em|strong|span)[^>]*>\s*</(?:sub|sup|i|b|em|strong|span)>)*')


def _cut_marker(html, plain, m, rex):
    """按 plain 上的标记 m 切 html。

    两者结构未必对齐：html 可能以 <img> 等标签开头（题图在题号之前），
    或标记内部含公式。对不上时整段保留原 html——绝不能拿 plain 当 html，
    否则 LaTeX 源码会漏到成品里。
    """
    body_p = plain[m.end():]
    # 前导的题图（<img>）与空标签要保留，只在它们之后找题号标记
    lead = _LEAD_KEEP.match(html)
    head, rest = html[:lead.end()], html[lead.end():]
    mh = rex.match(rest)
    if mh:
        return (head + rest[mh.end():]).strip().lstrip('　 '), body_p
    if rex.match(html):
        return html[m.end():].strip(), body_p
    # html 与 plain 对不上：整段保留，避免把 LaTeX 源码当正文漏出去
    return html.strip(), plain


def _table_html(rows):
    out = ['<div class="tbl"><table>']
    for ri, row in enumerate(rows):
        tag = 'th' if ri == 0 else 'td'
        out.append('<tr>' + ''.join(
            f'<{tag}>{"" .join(p["html"] for p in cell)}</{tag}>' for cell in row) + '</tr>')
    out.append('</table></div>')
    return ''.join(out)


def _table_plain(rows):
    return ' '.join(' '.join(p['plain'] for p in cell) for row in rows for cell in row)


# 文档头（校名/册次/姓名栏）——跳过，页眉由渲染层统一盖
HEADER_RE = re.compile(r'^(深圳外国语学校博雅高中|必修三|必修第三册|深外博雅|姓名[:：]|班级[:：]|'
                       r'第[一二三四五六七八九十]+章|学习目标与任务$)')
LESSON_RE = re.compile(r'^(\d{1,2}\.\d{1,2})\s*(.+)$')

# 上下文：决定 "N．…" 是题目还是编号条目
CTX_OF_TITLE = {
    '学习目标': 'list', '课前学习任务': 'list', '课上学习任务': 'task',
    '课后练习': 'exercise', '课后作业': 'exercise', '自我测评': 'exercise',
    '课堂探究': 'task',
    '推荐的学习资源': 'list', '课程基本信息': 'list', '学习目标与任务': 'list',
    '课后练习答案': 'answer',
}


class Sectionizer:
    def __init__(self, meta=None, default_ctx='list'):
        self.sections = []
        self.answers = {}      # {题号: [items]}
        self.cur_q = None
        self.cur_ans_no = None
        self.meta = meta or {}
        self.ctx = default_ctx
        self.ans_mode = False   # 处于答案区，未标记的行续到当前题
        self.started = False   # 是否已越过文档头
        self.lesson_title = ''
        # 一讲里可能有多个大题组（如 11.4 的《一》《二》各自 1~6 题），
        # 题号会重复。内部用 qgroup 把 no 变唯一以匹配答案，显示仍用原题号。
        self.qgroup = 0
        self._pending_figs = []   # 题干之前的图，等题干到了再挂上去
        self._blocks = []         # 当前正在处理的块序列（供向后看一个块）
        self._bi = 0
        self._force_next_no = None   # 下一道题强制使用的题号（源稿漏编号时）
        self._q_last_bi = None       # 最近一道题最后收录的块下标
        self.force_exercise_at = None  # 到达该块时把 ctx 切到 exercise

    # ---- 文档头 ----
    def _skip_header(self, html, plain):
        if self.started:
            return False
        m = LESSON_RE.match(plain)
        if m and len(plain) < 30:
            self.lesson_title = plain
        if HEADER_RE.match(plain) or m:
            return True
        self.started = True
        return False

    # ---- 工具 ----
    def _add(self, sec):
        self.sections.append(sec)
        return sec

    def _last(self, kind=None):
        for s in reversed(self.sections):
            if kind is None or s['kind'] == kind:
                return s
        return None

    def _push_item(self, item, target=None):
        """把 item 放到 target 节（默认当前节）的 items 末尾。"""
        tgt = target or self._last()
        if tgt is None:
            tgt = self._add({'kind': 'h', 'title': '正文', 'items': []})
        tgt['items'].append(item)

    # ---- 答案处理 ----
    def _akey(self, no):
        """答案 key = 题号 + 所在大题组。单一题组时退化为纯题号。"""
        return (no, self.qgroup) if self.qgroup else no

    def _ans(self, no, item, tag='答案'):
        k = self._akey(no)
        self.answers.setdefault(k, {'tag': tag, 'no': no, 'qgroup': self.qgroup,
                                    'items': []})['items'].append(item)
        if tag == '解析':
            self.answers[k]['tag'] = '解析'

    def _ans_continuation(self, html, plain):
        """答案区里不带标记的后续行（如解析的 (2)(3) 小问）→ 归到当前题。"""
        if not self.ans_mode or self.cur_ans_no is None:
            return False
        self._ans(self.cur_ans_no, _paras(html, plain), tag='解析')
        return True

    def _split_answers(self, text, head_no=None):
        """把 "2.D  3. BD  4. 1.5V" 这样的答案串按题号切开。

        首个题号标记通常在行首；但源稿也常**省略第 1 题的题号**
        （11.5：`AD   2．B  3．AB …`），此时把标记前的内容归给第 1 题。
        head_no 给定时才允许这种省略，避免把普通段落误当答案串。
        """
        marks = _ans_marks(text)
        if not marks:
            return False
        if marks[0][0] != 0:
            if head_no is None:
                return False
            head = text[:marks[0][0]].strip()
            if head:
                self._ans(head_no, _paras(head, head))
            # 注意：不要丢掉 marks[0]——它就是第 2 题的标记，
            # 早先 marks=marks[1:] 把首题标记连同答案一起扔了。
            pos = [m[0] for m in marks] + [len(text)]
            for i in range(len(pos) - 1):
                seg = text[pos[i]:pos[i + 1]].strip()
                mo = re.match(r'(\d{1,2})\s*[.．、]\s*(.*)$', seg, re.S)
                if mo:
                    self._ans(int(mo.group(1)), _paras(_ans_text_html(mo.group(2)),
                                                       mo.group(2).strip()))
            self.cur_ans_no = marks[0][1]
            self.ans_mode = True
            return True
        pos = [m[0] for m in marks] + [len(text)]
        for i in range(len(pos) - 1):
            seg = text[pos[i]:pos[i + 1]].strip()
            mo = re.match(r'(\d{1,2})\s*[.．、]\s*(.*)$', seg, re.S)
            if mo:
                self._ans(int(marks[i][1]), _paras(_ans_text_html(mo.group(2)),
                                                   mo.group(2).strip()))
        self.cur_ans_no = marks[0][1]
        self.ans_mode = True
        return True

    def _handle_answer_line(self, html, plain):
        """返回 True 表示本行已作为答案消费。"""
        # 1) 显式答案标题：「答案」「参考答案：」「【课后练习答案】」…
        m = ANS_HEAD_RE.match(plain)
        if m:
            self.ans_mode = True
            self.cur_ans_no = None
            # 「【课后练习答案】」这类标题必须先于小标题分支被消费，
            # 因此这里要一并把上下文切到 answer——否则紧随其后的
            # "1．18.4  2．0.900" 会被题号规则抓成题目，学生版就把答案印出来了。
            self.ctx = 'answer'
            rest_p = plain[m.end():].strip()
            if not rest_p:
                return True                 # 答案在后续行，本行只是标题
            if self._split_answers(rest_p):
                return True
            pairs = ANS_INLINE_RE.findall(rest_p)
            if len(pairs) >= 2:             # "答案1AB 2C 3A 4D"
                pos = [mm.start() for mm in ANS_INLINE_RE.finditer(rest_p)]
                pos.append(len(rest_p))
                for i in range(len(pos) - 1):
                    seg = rest_p[pos[i]:pos[i + 1]].strip()
                    mo = ANS_INLINE_RE.match(seg)
                    no = mo.group(1)
                    # 只留选项本身，题号由答案标题承担（"1AB" → "AB"）
                    self._ans(int(no), _paras(seg[mo.start(2):].strip(),
                                              seg[mo.start(2):].strip()))
                self.cur_ans_no = None
                return True
            no = self.cur_q
            if no is not None:
                self._ans(no, _paras(rest_p, rest_p))
                self.cur_ans_no = no
                return True
            return False
        # 2) 「5答案 …」「6. 答案 …」——题号在答案标记之前
        m2 = ANS_NO_RE.match(plain)
        if m2:
            no = int(m2.group(1))
            m3 = ANS_NO_RE.match(html)
            body_p = plain[m2.end():].strip()
            body_h = html[m3.end():].strip() if m3 else _ans_text_html(body_p)
            self._ans(no, _paras(body_h, body_p))
            self.cur_ans_no = no
            self.ans_mode = True
            return True
        # 3) 答案区内的续行
        if not self.ans_mode:
            return False
        if self._split_answers(plain):
            return True
        m4 = JX_RE.match(plain)
        if m4 and self.cur_ans_no is not None:
            body_p = plain[m4.end():].strip()
            mm = JX_RE.match(html)
            body_h = html[mm.end():].strip() if mm else body_p
            self._ans(self.cur_ans_no, _paras(body_h, body_p), tag='解析')
            return True
        if self.cur_ans_no is not None:     # 无标记的解析续行
            self._ans(self.cur_ans_no, _paras(html, plain), tag='解析')
            return True
        return False

    def _next_is_question(self, idx=None):
        """idx 之后的第一个非空块是否是题干。

        三种形式都算：
          - 直接以题号开头（"1．如图所示…"）；
          - 小节标题与题干同段（"【自我测评】1．…"）——11.4 的自我测评第 1 题
            就因此把它前面的电路图错挂到了上一节；
          - 漏了题号但后面紧跟选项行（11.4 第二个自我测评的第 1 题）。
        """
        i = self._bi if idx is None else idx
        for b in self._blocks[i + 1:]:
            if b['type'] != 'p':
                return False
            t = b['plain'].strip()
            if not t:
                continue
            if Q_NO_RE.match(t):
                return True
            # 剥掉「【小节】」前缀后是题号开头也算
            if re.match(r'^[\[【][^】]{1,12}[\]】]\s*\d{1,2}\s*[.．、]', t):
                return True
            if self.ctx == 'exercise' and not OPT_RE.match(t):
                return self._block_after_is_option(self._blocks.index(b))
            return False
        return False

    def _last_is_question_body(self):
        """上一块是否属于当前题（题干或选项）——用来判断紧随其后的图归属。

        直接看**块编号**：每道题建好时记下它的最后一块下标（`self._q_last_bi`），
        图块紧跟在那个下标之后就归它。比按文本形态猜可靠得多——源稿里
        题干可能没有题号（11.2 课后练习第 1 题），形态判据认不出来。
        """
        for b in reversed(self._blocks[:self._bi]):
            if b['type'] != 'p':
                return False
            if not b['plain'].strip():
                continue                      # 空段跳过，继续往前找
            return self._q_last_bi is not None and self._bi == self._q_last_bi + 1
        return False

    def _next_block(self):
        """紧跟当前块之后的第一个非空段落块。"""
        for b in self._blocks[self._bi + 1:]:
            if b['type'] == 'p' and b['plain'].strip():
                return b
        return None

    def _block_after_is_option(self, idx):
        """跳过空段，判断 idx 之后的第一个非空块是否是选项行。"""
        for b in self._blocks[idx + 1:]:
            if b['type'] != 'p':
                return False
            t = b['plain'].strip()
            if not t:
                continue
            return bool(OPT_RE.match(t))
        return False

    def cur_max_no(self):
        """当前题组里**最近出现**的题号。

        漏编号的题干按「上一题的题号 + 1」补号——源稿里漏号多是遗漏而非
        重排（11.2 新版把第 1、3 题的题号删掉了）。不能用全局最大号：
        那样补出的号会跟后面的题撞车、或在末尾冒出一个 Q1。
        """
        for sec in reversed(self.sections):
            if sec['kind'] == 'q' and (sec.get('qgroup') or 0) == self.qgroup:
                return sec.get('no') or 0
        return 0

    def _next_is_subq(self, window=2):
        """往后若干块内是否出现「(1)」「（1）」小问标记。"""
        seen = 0
        for b in self._blocks[self._bi + 1:]:
            if b['type'] != 'p':
                return False
            t = b['plain'].strip()
            if not t:
                continue
            if re.match(r'^[（(]\s*1\s*[）)]', t):
                return True
            seen += 1
            if seen >= window:
                return False
        return False

    def _next_option_letter(self, window=4):
        """往后若干块内第一个选项行的字母；没有则 None。"""
        seen = 0
        for b in self._blocks[self._bi + 1:]:
            if b['type'] != 'p':
                return None
            t = b['plain'].strip()
            if not t:
                continue
            m = OPT_RE.match(t)
            if m:
                return m.group(1)
            seen += 1
            if seen >= window:
                return None
        return None

    def _next_is_option(self, window=4):
        """往后若干块内是否出现选项行。

        不能只看紧邻一块：选项 A 常与题干同段，紧接着的
        "I1∶I2∶I3=5∶3∶2" 是 A 的续行，真正的 "B．…" 在再下一块。
        """
        seen = 0
        for b in self._blocks[self._bi + 1:]:
            if b['type'] != 'p':
                return False
            t = b['plain'].strip()
            if not t:
                continue
            if OPT_RE.match(t):
                return True
            seen += 1
            if seen >= window:
                return False
        return False

    # ---- 主流程 ----
    def feed(self, blocks):
        self._blocks = blocks
        for _i, b in enumerate(blocks):
            self._bi = _i
            if self.force_exercise_at is not None and _i == self.force_exercise_at:
                self.ctx = 'exercise'
                self.qgroup += 1
            if b['type'] == 'table':
                item = _paras(_table_html(b['rows']), _table_plain(b['rows']))
                self._push_item(item)
                continue
            html, plain = b['html'], b['plain'].strip()
            if not plain:
                # 纯图段：图常排在题干「之前」，若下一段是以题号开头的题干，
                # 该图属于下一题而不是上一题（否则会错挂到上一题末尾）。
                # 注意 b['imgs'] 是列表——一段里可能并排多张图，只取 [0] 会丢图。
                if b['imgs']:
                    items = [{'fig': 'media/' + f} for f in b['imgs']]
                    # 规则（用户明确）：Word 稿里的图片一律排在题干**下方**，
                    # 因此图永远归「它上面最近的那道题」。任务单里没有"题"，
                    # 就放到当前小节末尾（同样在题干/文字下方）。
                    tgt = self._last('q')
                    if tgt is not None and self.ctx == 'exercise':
                        tgt['items'].extend(items)
                    else:
                        for it in items:
                            self._push_item(it)
                continue
            # 图已内联在本段 html 里（docxparse 就地输出 <img>），不再另立图块，
            # 否则同一张图会在题干和正文里各出现一次。
            extra_figs = []

            # --- 文档头 / 平台样表 ---
            if self._skip_header(html, plain):
                continue
            if BOILER_RE.match(plain):
                continue
            # 出现新题号说明上一题的解析结束了，必须先退出答案模式。
            # 这一步要放在下面 `if self.ctx == 'answer'` 之前——那段会把
            # ans_mode 强设回 True，抢在前面的话退出逻辑永远到不了，
            # 后续题干全被当答案吞掉（解析版复习卷曾因此只剩 1 道题）。
            # 但答案区里 "1．18.4  2．0.900" 这种**答案行**同样是「题号+点号」，
            # 不能当作题干，否则学生版会把答案印出来。
            # 答案区内遇到 "N." 时要不要退出？两种情形表面相同、实质不同：
            #   - 复习卷：N.题干 后面跟 A./B./C./D. 选项 → 是新题，必须退出；
            #   - 11.3b：N.答案 后面跟的是解析文字 → 仍是答案，不能退出。
            # 因此以「后面是否紧跟选项行」为准。
            # 判据：后面紧跟「A．选项」或「(1) 小问」的，是新题干；
            # 后面接解析文字的，是上一题答案的续行（11.3b 第 2~4 题）。
            # 判据（按可靠性排序）：
            #   1) 该题号的答案已经收过 → 这是第二个同名题，必是新题干
            #      （复习卷源稿把第 15 题误标成 5．，与真第 5 题重号）；
            #   2) 后面紧跟 A．选项 或 (1) 小问 → 新题干；
            #   3) 否则视为上一题答案的续行（11.3b 第 2~4 题）。
            _mq = Q_NO_RE.match(plain)
            _dup = bool(_mq and self._akey(int(_mq.group(1))) in self.answers)
            _is_new_q = bool(_mq and (_dup or self._next_option_letter() == 'A'
                                      or self._next_is_subq()))
            _next_ans = bool(_mq and not _is_new_q)
            if (self.ans_mode and _mq
                    and not _next_ans
                    and not _looks_like_answer_line(plain)):
                self.ans_mode = False
                self.cur_ans_no = None
                if self.ctx == 'answer':
                    self.ctx = 'exercise'

            # 「课后练习答案」区：此后内容全部是答案（如 1．18.4 2．0.900）
            if self.ctx == 'answer':
                self.ans_mode = True
                # 切分交给 _split_answers —— 它已能处理各种间距
                # （"2.D   3. BD"、"1．18.4"、"3.（1）ACDFH"），
                # 以及源稿省略第 1 题题号的情形（head_no=1）。
                if self._split_answers(plain, head_no=1):
                    continue

            # --- 答案区 ---
            if self._handle_answer_line(html, plain):
                continue
            if self._ans_continuation(html, plain):
                continue

            # --- 大节标题（可带 []/【】 包裹，后面可紧跟正文） ---
            plain_bare = plain.strip()
            # 长标题优先（"课后练习答案" 需先于 "课后练习" 匹配）
            _H_ALT = '|'.join(sorted(H_TITLES, key=len, reverse=True))
            m_h = re.match(r'^[\[【]?\s*(' + _H_ALT + r')\s*[\]】]?\s*(.*)$', plain_bare)
            if m_h:
                name, rest = m_h.group(1), m_h.group(2).strip()
                # "1.知道电阻的定义式…" 这类正文不应被当成节标题
                if not re.match(r'^\d', name):
                    self.cur_q = None
                    self.ans_mode = False
                    if name == '课后练习答案':
                        self.ctx = 'answer'
                        self.ans_mode = True
                        self._add({'kind': 'h', 'title': name, 'items': []})
                        continue
                    # 进入新的大题组（自我测评/课后练习）时，题号重新计数
                    if CTX_OF_TITLE.get(name) == 'exercise':
                        self.qgroup += 1
                    self.ctx = CTX_OF_TITLE.get(name, self.ctx)
                    sec = self._add({'kind': 'h', 'title': name, 'items': []})
                    # 标题段自带的图（如「【自我测评】」与第 1 题的电路图同段）
                    # 归给紧随其后的那道题，否则图会挂到标题上、题也丢了图。
                    if self.ctx == 'exercise' and b['imgs'] and self._next_is_question():
                        self._pending_figs.extend(
                            {'fig': 'media/' + f} for f in b['imgs'])
                        # 紧随其后的题干若漏了编号，按本组序号补一个
                        nxt = self._next_block()
                        if nxt is not None and not Q_NO_RE.match(nxt['plain'].strip()):
                            self._force_next_no = self.cur_max_no() + 1
                    if rest:
                        # 标题行内还带了内容（如 "[学习目标]　1.掌握…"）
                        mm = re.search(r'[\]】]', html)
                        rest_h = html[mm.end():].strip() if mm else rest
                        sec['items'].append(_paras(rest_h, rest))
                        if self.ctx == 'exercise':
                            mq = Q_NO_RE.match(rest)
                            if mq:
                                sec['items'] = []
                                qs = self._add({'kind': 'q', 'no': int(mq.group(1)),
                                                'qgroup': self.qgroup,
                                                'title': '', 'items': []})
                                # 标题与题干同段（"【自我测评】1．如图所示…"）时，
                                # 排在标题之前的图属于这一题——不消费就会被丢掉
                                # （11.4 自我测评第 1 题的 R₁/R₂ 电路图）。
                                if self._pending_figs:
                                    qs['items'].extend(self._pending_figs)
                                    self._pending_figs = []
                                bh, bp = _cut_marker(rest_h, rest, mq, Q_NO_RE)
                                qs['items'].append(_paras(bh, bp))
                                self._q_last_bi = self._bi
                                self.cur_q = int(mq.group(1))
                            elif self._next_is_option() or (
                                    self._pending_figs and OPT_RE.match(rest)):
                                # 源稿漏了题号，但其后紧跟选项行 → 当作一道题并补号。
                                # （11.4 第二个「自我测评」的第 1 题就是这种）
                                sec['items'] = []
                                # 源稿漏编号 → 按本组内"该题干之前已建的题数 + 1"补
                                self.qno_seq = self.cur_max_no() + 1
                                qs = self._add({'kind': 'q', 'no': self.qno_seq,
                                                'qgroup': self.qgroup,
                                                'title': '', 'items': []})
                                if self._pending_figs:
                                    qs['items'].extend(self._pending_figs)
                                    self._pending_figs = []
                                _m0 = Q_NO_RE.match(rest)
                                if _m0:
                                    body_h, body_p = _cut_marker(rest_h, rest, _m0, Q_NO_RE)
                                else:
                                    body_h, body_p = rest_h, rest
                                qs['items'].append(_paras(body_h, body_p))
                                self.cur_q = self.qno_seq
                    continue

            # --- 学习任务 / 小标题 ---
            m = TASK_RE.match(plain_bare)
            if m:
                self.cur_q = None
                self.ans_mode = False
                title = m.group(0).strip()
                self.ctx = 'exercise' if '自我测评' in title else 'task'
                rest = plain_bare[m.end():].strip()
                sec = self._add({'kind': 'task', 'title': title, 'items': []})
                if rest:
                    rest_h = html[html.find('】') + 1:] if '】' in html else rest
                    sec['items'].append(_paras(rest_h.strip(), rest))
                continue
            # 形如 "《二电表的改装与读数》【学习目标】" 的小节标题（学案分篇）
            m_sec = re.match(r'^(《[^》]{1,20}》\s*【[^】]{2,8}】)\s*(.*)$', plain_bare)
            if m_sec:
                self.cur_q = None
                self.ans_mode = False
                sec = self._add({'kind': 'task', 'title': m_sec.group(1), 'items': []})
                if m_sec.group(2):
                    mm2 = re.search(r'】', html)
                    sec['items'].append(_paras(html[mm2.end():].strip() if mm2
                                               else m_sec.group(2), m_sec.group(2)))
                continue
            # 形如 "【课堂探究】第一部分 串、并联电路中的电流" 的分隔标题
            m_div = re.match(r'^(【[^】]{2,10}】)\s*(.{0,40})$', plain_bare)
            if m_div and not re.match(r'^【[^】]*答案|^【[^】]*解析', plain_bare):
                self.cur_q = None
                if '自我测评' in plain_bare:
                    self.ctx = 'exercise'
                self._add({'kind': 'task', 'title': plain_bare, 'items': []})
                continue

            # --- 题干： "N．…"（仅在练习/测评上下文） ---
            m = Q_NO_RE.match(plain_bare) if self.ctx == 'exercise' else None
            force = self.ctx == 'exercise' and not m and self._force_next_no is not None
            if m or force:
                no = (self._force_next_no if force else int(m.group(1)))
                self._force_next_no = None
                if force:
                    m = re.match(r'\s*', plain_bare)     # 无标记可切
                body_h, body_p = _cut_marker(html, plain_bare, m, Q_NO_RE)
                sec = self._add({'kind': 'q', 'no': no, 'qgroup': self.qgroup,
                                 'title': '', 'items': []})
                if self._pending_figs:            # 题干之前排的图，归本题
                    sec['items'].extend(self._pending_figs)
                    self._pending_figs = []
                sec['items'].append(_paras(body_h, body_p))
                self._q_last_bi = self._bi
                self.cur_q = no
                self._q_last_bi = self._bi
                self.ans_mode = False
                for f in extra_figs:
                    sec['items'].append({'fig': 'media/' + f})
                continue

            # --- 选项行 ---
            if OPT_RE.match(plain_bare) and self.cur_q is not None:
                q = None
                for s in reversed(self.sections):
                    if s['kind'] == 'q' and s.get('no') == self.cur_q:
                        q = s
                        break
                if q is not None:
                    # 一段可能含多个选项，交给 render 层再拆；这里整段作为一个 para
                    q['items'].append(_paras(html, plain_bare))
                    self._q_last_bi = self._bi
                    continue

            # --- 漏编号的题干：练习区内、后面紧跟选项行 ---
            # 源稿偶有题目忘写题号（11.4 课后练习第 2 题），
            # 不补号就会被并进上一题、整题消失。
            # 排除 "(1)…(2)…" 这类小问——它们是上一题的一部分，不是新题
            # 允许「紧跟在练习标题之后」的无号题干——源稿常把第 1 题的
            # 题号连同标题一起删掉（11.2 新版：课后练习下直接是题干）。
            _after_head = bool(self.sections and self.sections[-1]['kind'] == 'h'
                               and CTX_OF_TITLE.get(self.sections[-1].get('title')) == 'exercise')
            # 仅当后面跟的选项是「A．」时才认定是新题——若当前题已有选项，
            # 而本段后面跟的是 B./C./D.，那本段其实是上一个选项的续行
            # （题干与 A 同段时很常见），不能新建题。
            _starts_new_opts = self._next_option_letter() == 'A'
            if (self.ctx == 'exercise' and (self._last_is_question_body() or _after_head)
                    and not OPT_RE.match(plain_bare)
                    and not re.match(r'^[（(]\s*\d{1,2}\s*[）)]', plain_bare)
                    and self._next_is_option() and _starts_new_opts):
                self.qno_seq = self.cur_max_no() + 1
                sec = self._add({'kind': 'q', 'no': self.qno_seq, 'qgroup': self.qgroup,
                                 'title': '', 'items': []})
                if self._pending_figs:
                    sec['items'].extend(self._pending_figs)
                    self._pending_figs = []
                sec['items'].append(_paras(html, plain_bare))
                self._q_last_bi = self._bi
                self.cur_q = self.qno_seq
                continue

            # --- 普通段落：并入当前节 ---
            self._push_item(_paras(html, plain_bare))
            for f in extra_figs:
                self._push_item({'fig': 'media/' + f})
        return self

    def result(self):
        # 题目内的图去重（源稿常同时内联在题干里、又作独立图块排一遍）
        for sec in self.sections:
            if sec['kind'] in ('q', 'task'):
                sec['items'] = _dedup_figs(sec['items'])
        # 答案作为 ans 节插到末尾，供 render_ws.split_answer_by_no 直接消费
        for k in sorted(self.answers, key=lambda x: (x[1], x[0]) if isinstance(x, tuple) else (0, x)):
            a = self.answers[k]
            no = a['no']
            # 标题带题号（用原始题号，不带分组），便于逐题速查
            self.sections.append({'kind': 'ans', 'no': no, 'qgroup': a.get('qgroup', 0),
                                  'tag': a['tag'],
                                  'title': f'{no}．' + ('解析' if a['tag'] == '解析' else '答案'),
                                  'items': a['items']})
        return {'meta': self.meta, 'sections': self.sections,
                'answers': {str(k): v['items'] for k, v in self.answers.items()}}


# 复习卷/解析版这类文档没有「课后练习」小标题，题目直接编号排列，
# 靠块内容判定：出现多处【答案】【解析】【详解】即视为练习文档。
_ANS_MARK = re.compile(r'^【\s*(答案|解析|详解|解答|点拨)\s*】')


_ANY_H_TITLE = re.compile(r'^[\[【]?\s*(?:' + '|'.join(H_TITLES) + r')\s*[\]】]?\s*$')


def _looks_like_exercise(blocks):
    """文档是否含成组的练习（需要默认 exercise 上下文才认得出题目）。

    三种情形：
      1. 整篇直接编号排题、没有大节标题（复习卷/解析版）；
      2. 有「课后练习」这类小节标题 —— 由标题自己设上下文，无需默认值；
      3. **有「答案：」小节但上文没有「课后练习」标题**（如 11.3 第二课时，
         题目直接接在课上任务之后）。这种必须整体按 exercise 处理，
         否则答案行挂不到题目上。
    """
    has_h = any(b['type'] == 'p' and _ANY_H_TITLE.match(b['plain'].strip())
                for b in blocks)
    n = sum(1 for b in blocks
            if b['type'] == 'p' and _ANS_MARK.match(b['plain'].strip()))
    if has_h:
        return False
    if n >= 3:
        return True
    hits = 0
    for i, b in enumerate(blocks):
        if b['type'] != 'p' or not Q_NO_RE.match(b['plain'].strip()):
            continue
        for nb in blocks[i + 1:i + 3]:
            if nb['type'] == 'p' and OPT_RE.match(nb['plain'].strip()):
                hits += 1
                break
    return hits >= 3


def _answer_exercise_from(blocks):
    """返回「答案：」之前那道题的块下标；没有则 None。

    11.3 第二课时把课后练习直接接在课上任务之后，没有「课后练习」标题，
    题目因此落在 list 上下文里、认不出来，答案也就挂不上去。
    这里定位答案小节前最后一道题，从那里起强制切到 exercise。
    """
    ans_i = None
    for i, b in enumerate(blocks):
        if b['type'] == 'p' and _ANS_MARK.match(b['plain'].strip()):
            ans_i = i
            break
    if ans_i is None:
        return None
    if any(b['type'] == 'p' and b['plain'].strip().startswith('课后练习')
           for b in blocks[:ans_i]):
        return None                      # 有课后练习标题，交给标题处理
    for i in range(ans_i - 1, -1, -1):
        b = blocks[i]
        if b['type'] == 'p' and Q_NO_RE.match(b['plain'].strip()):
            return i
    return None


def sectionize(blocks, meta=None, default_ctx=None):
    if default_ctx is None:
        default_ctx = 'exercise' if _looks_like_exercise(blocks) else 'list'
    sz = Sectionizer(meta, default_ctx=default_ctx)
    t = _answer_exercise_from(blocks)
    if t is not None:
        sz.force_exercise_at = t
    return sz.feed(blocks).result()
