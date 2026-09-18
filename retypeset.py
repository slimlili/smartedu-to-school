# -*- coding: utf-8 -*-
"""把平台 PDF 解析成结构化内容，供重排成校本 HTML。

设计要点（按用户反馈）：
  - 丢弃原 PDF 版式：识别到题/任务后按自然段重排，文字交给浏览器/CSS 流动换行。
  - 文本以 span 级还原上下标（textflow），同一自然段内行间按需加空格合并。
  - 位图铺白底输出 PNG（避免透明/黑底）。
  - 课后练习答案区按题号拆分，供“教师版逐题紧跟答案”。
"""
import base64, io, re
import fitz
from textflow import spans_to_html

FIG_MIN_W = 40
_CJK = re.compile(r'[一-鿿　-〿＀-￯]')


def _esc(t):
    import html as _h
    return _h.escape(t or "", quote=False)


def _is_header(t):
    return any(k in t for k in ("课程基本信息", "课例编号", "学生信息", "课题",
                                "姓名", "出版社", "书名", "教科书", "学期",
                                "学科", "年级", "出版日期")) or \
           bool(re.match(r'^\d{4}QJ', t)) or \
           (len(t.strip()) <= 4 and t.strip() in ("学", "科", "10", "物理"))


def _render_clip_png(pg, rect, dpi=150, pad=1):
    """把页面上某矩形区域(矢量+位图合成)渲染成 PNG data URI，白底。
    解决：源 PNG 提取常得到“透明底/黑线”的畸形图；直接渲染该区域最保真。"""
    import base64
    r = fitz.Rect(rect)
    # 少量外扩避免裁掉描边
    r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
    pix = pg.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=r, alpha=False)
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()


def fig_png_white(doc, xref, pg=None):
    """返回位图对应页面区域（合成渲染）的 data URI。优先按位图 bbox 渲染。"""
    if pg is None:
        return None
    rects = pg.get_image_rects(xref)
    if not rects:
        return None
    return _render_clip_png(pg, rects[0])


_CJK_CH = re.compile(r'[一-鿿]')
_MATH_ONLY = re.compile(r'^[\w=＋＋\-*/±×÷≤≥<>φθ.()]{1,6}$')


def _is_prose(p):
    """行里含中文 → 视为正文行。"""
    return bool(_CJK_CH.search(p))


def _lines_to_paras(lines):
    """把一文本块的有序行 (html, plain, y0, y1, size) 按垂直间隙聚成自然段。

    处理：丢弃「孤立公式碎片」——纯字母/符号、无中文、且不与任何中文正文行
    在 y 上重叠的漂浮行（多为被拆开的独立公式重复渲染，正文已含同一公式）。
    """
    if not lines:
        return []
    # 正文行（含中文）的 y 区间与最右 x，用于判定孤立碎片 / 右侧公式残留
    prose_bands = [(y0 - 2, y1 + 2) for (h, p, y0, y1, sz, x0, x1) in lines if _is_prose(p)]
    prose_right = max((x1 for (h, p, y0, y1, sz, x0, x1) in lines if _is_prose(p)), default=0)
    keep = []
    for (h, p, y0, y1, sz, x0, x1) in lines:
        if not _is_prose(p):
            frag = p.strip()
            is_math_frag = bool(_MATH_ONLY.match(frag)) or all(ord(c) < 128 for c in frag)
            if is_math_frag and frag:
                # 1) y 与正文重叠 = 行内公式（保留）；2) 完全在正文右侧栏 = 残留公式，丢弃
                overlaps_y = any(lo <= y0 + (y1 - y0) * 0.6 <= hi for (lo, hi) in prose_bands)
                right_of_prose = prose_right > 0 and x0 > prose_right + 1
                if right_of_prose:
                    continue
                if not overlaps_y:
                    continue  # 孤立碎片
        keep.append((h, p, y0, y1, sz, x0, x1))
    lines = [(h, p, y0, y1, sz) for (h, p, y0, y1, sz, _, _) in keep]
    if not lines:
        return []
    paras = []
    cur_plain = []
    cur_html = []
    prev_end = None
    prev_ysize = None
    for (h, p, y0, y1, sz) in lines:
        # 判断是否新段：行距明显大于行高
        if prev_end is not None:
            gap = y0 - prev_end
            lh = (prev_ysize or 10) * 1.35
            if gap > lh:
                paras.append({"plain": "".join(cur_plain), "html": "".join(cur_html)})
                cur_plain, cur_html = [], []
        # 行间连接是否需要空格（仅当上一行尾与下一行首均为 ASCII 字母数字时）
        need_sp = False
        if cur_plain and cur_plain[-1] and p:
            lastc = cur_plain[-1][-1]
            firstc = p[0]
            need_sp = (lastc.isascii() and lastc.isalnum() and
                       firstc.isascii() and firstc.isalnum())
        if need_sp:
            cur_html.append(" ")
            cur_plain.append(" ")
        cur_html.append(h)
        cur_plain.append(p)
        prev_end = y1
        prev_ysize = sz
    if cur_html:
        paras.append({"plain": "".join(cur_plain), "html": "".join(cur_html)})
    return paras


def collect_items(doc, pno, y_bot=1e9):
    """该页 y<y_bot 内容项，按 y 排序。

    返回 list of:
      ('t', y0, {'paras':[{plain,html}], 'text':…})   文本块（段落化）
      ('f', y0, datauri, w, h)                         位图
    """
    pg = doc[pno]
    items = []
    dd = pg.get_text("dict")
    for b in dd["blocks"]:
        if b["type"] != 0:
            continue
        lines = []
        for l in b["lines"]:
            spans = sorted(l["spans"], key=lambda s: s["bbox"][0])
            h, p = spans_to_html(spans)
            if p.strip():
                bb = l["bbox"]
                lines.append((h, p, bb[1], bb[3],
                              l["spans"][0]["size"] if l["spans"] else 10,
                              bb[0], bb[2]))
        if not lines:
            continue
        lines.sort(key=lambda x: x[2])
        paras = _lines_to_paras(lines)
        text_all = "\n".join(pa["plain"].strip() for pa in paras if pa["plain"].strip())
        y0 = lines[0][2]
        if text_all.strip():
            items.append(("t", y0, {"paras": paras, "text": text_all}))
    img_rects = []
    for im in pg.get_images(full=True):
        xref = im[0]
        rects = pg.get_image_rects(xref)
        if not rects:
            continue
        r = rects[0]
        if r.width < FIG_MIN_W:
            continue
        du = fig_png_white(doc, xref, pg)
        if du:
            items.append(("f", r.y0, du, r.width, r.height))
            img_rects.append(r)
    # 矢量图（无对应位图的绘制簇）：聚类 drawings 的 bbox
    vec_boxes = []
    for dr in pg.get_drawings():
        r = dr["rect"]
        if r.width < 12 or r.height < 12:
            continue
        # 过滤装饰性横条：很宽很扁（如节标题底纹/分隔线 437x23）不是插图
        if r.width / max(r.height, 1) > 6 and r.height < 45:
            continue
        vec_boxes.append(r)
    # 简单合并重叠/邻近的绘制区
    vec_boxes.sort(key=lambda r: (r.y0, r.x0))
    merged = []
    for r in vec_boxes:
        if not merged or r.y0 > merged[-1].y1 + 6 or r.x0 > merged[-1].x1 + 40 or r.x1 < merged[-1].x0 - 40:
            merged.append(fitz.Rect(r))
        else:
            merged[-1] = merged[-1] | r
    for r in merged:
        # 合并后再滤一次细长条
        if r.width / max(r.height, 1) > 6 and r.height < 60:
            continue
        # 若被已有位图区覆盖则跳过
        if any((r & ir).get_area() > 0.6 * r.get_area() for ir in img_rects):
            continue
        if r.width < 30 or r.height < 20:
            continue
        du = _render_clip_png(pg, r, dpi=150)
        if du:
            items.append(("f", r.y0, du, r.width, r.height))
    items.sort(key=lambda it: (round(it[1]), 0 if it[0] == "t" else 1))
    return items


def _plain(it):
    return it[2]["text"] if it[0] == "t" else ""


def push_item(cur, it):
    if cur is None:
        return
    if it[0] == "t":
        cur["items"].append({"paras": it[2]["paras"]})
    elif it[0] == "f":
        cur["items"].append({"fig": it[2], "w": it[3], "h": it[4]})


# ---------------------------------------------------------------- 学习任务单
def parse_lesson_task(doc):
    sections = []
    cur = None

    def push(kind, title):
        nonlocal cur
        cur = {"kind": kind, "title": title, "items": []}
        sections.append(cur)

    for pno in range(len(doc)):
        for it in collect_items(doc, pno):
            if it[0] != "t":
                push_item(cur, it)
                continue
            t = _plain(it)
            if pno == 0 and _is_header(t):
                continue
            low = t.splitlines()[0].strip()
            m = re.match(r'^(【?\s*(学习任务|课堂任务)\s*[一二三四五六七八九十]】?)', low)
            if m:
                title = m.group(1).strip()
                push("task", title)
                # 标题后的正文（如 "【学习任务五】 根据自己的理解…"）
                rest = low[m.end():].strip() or t[len(low):].strip()
                if rest:
                    push_item(cur, ("t", 0, {"paras": [{"plain": rest, "html": _esc(rest)}],
                                           "text": rest}))
                continue
            if re.match(r'^(课前学习任务|课上学习任务|学习目标|课堂小结|小结|推荐的学习资源|课后思考)', low):
                # 该行可能标题独占一行
                push("h", low)
                rest = t[len(low):].strip()
                if rest:
                    push_item(cur, ("t", 0, {"paras": [{"plain": rest, "html": _esc(rest)}],
                                           "text": rest}))
                continue
            if cur is not None:
                push_item(cur, it)
            else:
                # 首个正式小节出现前的杂项（多为表头残留）丢弃，除非像标题
                push("h", "")
                push_item(cur, it)
    # 清理：去掉标题为空且内容多为表头残留的段
    cleaned = []
    for s in sections:
        if s["kind"] == "h" and not s.get("title"):
            # 丢弃该段（表头残留）——保留带正式标题的 h
            continue
        cleaned.append(s)
    return cleaned


# ---------------------------------------------------------------- 课后练习
def find_answer_start(doc):
    pat_h = re.compile(r'^\s*(【?\s*(参考答案|答案|解析|课后练习解析和答案)\s*】?\s*[:：]?)')
    for pno in range(len(doc)):
        for it in collect_items(doc, pno):
            if it[0] != "t":
                continue
            t = _plain(it)
            low = t.splitlines()[0].strip()
            if pat_h.match(low) or re.match(r'^\d+\s*[.、．]\s*答案', low):
                return pno, it[1]
    return None


def parse_exercise(doc):
    start = find_answer_start(doc)
    ans_pno = start[0] if start else None
    ans_y = start[1] if start else None
    sections = []
    cur = None
    in_ans = False

    def push(kind, **kw):
        nonlocal cur
        cur = {"kind": kind, "items": [], **kw}
        sections.append(cur)

    for pno in range(len(doc)):
        for it in collect_items(doc, pno, 1e9):
            # 越过答案起始线 → 进入答案区（该页在此线之上是题尾/图，之下是答案）
            if ans_pno is not None and (pno > ans_pno or (pno == ans_pno and it[1] >= ans_y)):
                if not in_ans:
                    push("answer", title="参考答案")
                    in_ans = True
                if it[0] == "t":
                    low = _plain(it).splitlines()[0].strip()
                    ma = re.match(r'^(\d+)\s*[.、．]\s*(答案|解析)[:：]?', low)
                    if ma:
                        push("ans", no=int(ma.group(1)), tag=ma.group(2))
                        rest = _plain(it)[ma.end():].strip()
                        if rest:
                            cur["items"].append({"paras": [{"plain": rest, "html": _esc(rest)}],
                                                "text": rest})
                        continue
                push_item(cur, it)
                continue
            # 题目/正文区
            if it[0] != "t":
                push_item(cur, it)
                continue
            t = _plain(it)
            if pno == 0 and _is_header(t):
                continue
            low = t.splitlines()[0].strip()
            mq = re.match(r'^(\d+)\s*[.、．]\s*', low)
            if mq:
                push("q", no=int(mq.group(1)))
                rest = re.sub(r'^(\d+\s*[.、．]\s*)', "", t, count=1)
                cur["items"].append({"paras": [{"plain": rest, "html": _esc(rest)}],
                                     "text": rest})
                continue
            if cur is not None:
                push_item(cur, it)
            else:
                push("pre", title="")
                push_item(cur, it)
    return sections


def split_answer_by_no(sections):
    """把 sections 里 kind in (ans,answer) 按各自题号组织成 {题号: [items]}。

    - 'ans' 小节已带 no（N.答案/N.解析），直接把该小节 items 归到该题；
    - 对无独立小节的 'answer' 大块，尝试按行首数字再切。
    """
    ans = {}
    pending = []          # answer 大块里先于首个数字的内容
    cur_no = None
    for s in sections:
        if s["kind"] == "ans":
            no = s.get("no")
            if no is not None:
                # 多题组（同一讲里两套 1~N 题）→ 用 (题号, 组号) 作 key，避免跨组错配
                g = s.get("qgroup") or 0
                ans.setdefault((no, g) if g else no, []).extend(s["items"])
            continue
        if s["kind"] != "answer":
            continue
        # 统一的参考答案大块：按行首数字切
        for it in s["items"]:
            if "paras" in it:
                txt = "\n".join(p["plain"] for p in it["paras"])
                low = txt.splitlines()[0] if txt.splitlines() else ""
                m = re.match(r'^(\d+)\s*[.、．]', low)
                if m:
                    cur_no = int(m.group(1))
                    it2 = dict(it)
                    it2["paras"] = [dict(p) for p in it["paras"]]
                    ans.setdefault(cur_no, []).append(it2)
                else:
                    if cur_no is not None:
                        ans.setdefault(cur_no, []).append(it)
                    else:
                        pending.append(it)
            elif "fig" in it:
                if cur_no is not None:
                    ans.setdefault(cur_no, []).append(it)
                else:
                    pending.append(it)
    if pending and ans:
        ans[list(ans.keys())[0]] = pending + ans.get(list(ans.keys())[0], [])
    return ans
