# -*- coding: utf-8 -*-
"""渲染后处理：图片内联为 data URI、注入公式 CSS。

不改 render_ws / build_deck_html 本体，避免影响平台版流水线；
只在这套校本资源的最终 HTML 上做增强。
"""
import base64, os, re

from latex2html import MATH_CSS

# 物理图不会这么窄；这类碎片是 Word 里装饰框被切开的两半
MIN_IMG_W = 40

# 题图尺寸：学生版留白多，图可放大
FIG_CSS = """
.m{white-space:nowrap}
/* 正文内联图与独立图块统一限高，避免大图把段落拦腰截断 */
img{max-height:150px;max-width:96mm;image-rendering:-webkit-optimize-contrast}
.tbl table{border-collapse:collapse;margin:6px 0;font-size:10.5pt;width:100%}
.tbl th,.tbl td{border:1px solid #9bb8a6;padding:3px 8px;text-align:left}
.tbl th{background:#eef6ef;color:#0E4E33;font-weight:700}
/* 答案版：任务参考解析块 */
.ans-block .ans-body{font-family:"Songti SC","Times New Roman",serif;font-size:11pt;
line-height:1.8;color:#12323a}
.ans-block .ans-body .eqline{text-align:center;margin:4px 0}
.ans-block .ans-body i{font-style:italic;font-family:"Times New Roman","STIXGeneral",serif}
.ans-block .ans-body sub,.ans-block .ans-body sup{font-size:.72em;line-height:0}
.ans-block .nonset{color:#a67a00}
.ans-sec{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-weight:800;color:#0E4E33;
font-size:13pt;border-left:5px solid #007020;padding-left:9px;margin:18px 0 8px}
/* 原教辅的图片式小标题（易错辨析/例题…）还原成文字后按小节标题排版 */
.badge{display:inline-block;font-family:"PingFang SC","Microsoft YaHei",sans-serif;
font-weight:800;color:#0E4E33;background:#e9f3ec;border-left:4px solid #007020;
padding:0 10px;margin:4px 2px;border-radius:0 6px 6px 0;font-size:11pt}
"""

_IMG_SRC = re.compile(r'src="media/([^"]+)"')

# 作答区右侧配图：题干在下、作答虚线在左下、图在答题区右侧
SIDE_FIG_CSS = """
/* 题目配图：一律居中排在题干之后 */
.qwrap{display:block}
.qwrap .fig-c{text-align:center;margin:8px 0 10px;break-inside:avoid}
.qwrap .fig-c img{max-height:120px;max-width:88mm}
.qwrap .fig{text-align:center;margin:8px 0 10px;break-inside:avoid}
/* 学习任务/探究里：左作答区 + 右图，同一行并排（不用 float，避免泄漏到下一节） */
.ansfigrow{display:flex;align-items:flex-start;gap:10px}
.ansfigrow .ansspace{flex:1 1 auto;min-width:0}
.ansfigrow .taskfig{flex:0 0 auto}
.taskfig{text-align:center;margin:4px 0 8px}
.taskfig img{max-height:112px;max-width:58mm}
/* 学习任务单的图：排在题干之后、居中 */
.taskfig-c{text-align:center;margin:8px 0 10px;break-inside:avoid}
.taskfig-c img{max-height:120px;max-width:88mm}
"""

_Q_OPEN = re.compile(r'<div class="qwrap">')
# 需要重排配图的区块：学习任务、以及「课堂探究」这类 sec-h
_SEC_OPEN = re.compile(r'<div class="(?:task|sec-h)">')
_LEAD = re.compile(r'^<div class="(?:t-head|sec-t)">.*?</div>', re.S)
_ANSSPACE_OPEN = re.compile(r'<div class="ansspace one">')


def _find_ansspaces(block):
    """返回各作答区的完整片段（按标签配对取，不能用 `.*?</div>`——那会截在半路，
    把配图塞进作答区内部）。"""
    out = []
    for m in _ANSSPACE_OPEN.finditer(block):
        e = _match_close(block, m.start())
        if e > 0:
            out.append(block[m.start():e])
    return out
_FIGDIV = re.compile(r'<div class="fig">.*?</div>', re.S)


def reflow_task_figs(html, media_dir):
    """学习任务 / 课堂探究里的图：抽出来配到右侧栏。

    两条硬约束：
      1. 图必须留在所属区块**内部**——早先没锚点时会 append 到 `</div>` 之后，
         浮动就泄漏到下一节，把后面几段文字都挤成窄条；
      2. 一个区块内所有图都要处理，不能只认第一个（11.4 的课堂探究有 3 张）。
    """
    out, pos = [], 0
    while True:
        m = _SEC_OPEN.search(html, pos)
        if not m:
            out.append(html[pos:])
            break
        end = _match_close(html, m.start())
        if end < 0:
            out.append(html[pos:])
            break
        out.append(html[pos:m.start()])
        out.append(_reflow_section(html[m.start():end]))
        pos = end
    return ''.join(out)


def _reflow_section(block):
    """学习任务 / 课堂探究里的图：**保持原位**，只包一层居中样式。

    源稿里图的位置本来就是对的（题干/文字 → 图 → 图注）。早先"统一移到
    后面第一段"的做法会把它插到图注前、或推到下一段之后（游标卡尺构造图
    被排到「2.各部件的用途」下面就是这么来的）。
    """
    block = re.sub(r'<div class="fig">(.*?)</div>',
                   lambda m: '<div class="taskfig-c">' + m.group(1) + '</div>',
                   block, flags=re.S)
    # 段落内联的图也抽出来居中（图排在行内会挤着文字）
    return re.sub(r'(<img[^>]*>)',
                  lambda m: '<div class="taskfig-c">' + m.group(1) + '</div>', block)


def _pair_figs_with_answers(block):
    """图配到作答区右侧；多出的图放到区块标题之后（仍在区块内）。"""
    pending = []
    block = re.sub(r'<img[^>]*>', lambda m: (pending.append(m.group(0)), '')[1], block)
    for f in _FIGDIV.findall(block):
        im = re.search(r'<img[^>]*>', f)
        if im:
            pending.append(im.group(0))
        block = block.replace(f, '')
    block = re.sub(r'<p>\s*</p>', '', block)
    if not pending:
        return block
    used, extra = set(), []
    for im in pending:
        target = next((a for a in _find_ansspaces(block) if a not in used), None)
        if target:
            used.add(target)
            block = block.replace(
                target,
                '<div class="ansfigrow">' + target
                + '<div class="taskfig">' + im + '</div></div>', 1)
        else:
            extra.append(im)
    if extra:
        m = re.search(r'(</div>)', block)          # 区块标题 div 的收尾
        pos = m.end() if m else len(block)
        block = (block[:pos]
                 + '<div class="taskfig">' + ''.join(extra) + '</div>'
                 + block[pos:])
    return block


def _match_close(html, start):
    """返回 html 中 start 处 <div> 所对应的 </div> 之后的位置。"""
    depth, i, n = 0, start, len(html)
    while i < n:
        if html.startswith('<div', i):
            depth += 1
            i = html.find('>', i)
            if i < 0:
                return -1
            i += 1
            continue
        if html.startswith('</div>', i):
            depth -= 1
            i += len('</div>')
            if depth == 0:
                return i
            continue
        i += 1
    return -1


def move_figs_beside_answer(html):
    """把题图挪到作答区右侧（左作答、右图）。

    只处理学生版的 <div class="qwrap">…</div> 结构。定位收尾必须按标签配对，
    早先用 html.find('</div></div>') 找会被嵌套的 <div class="qbody"> 提前截断。
    """
    out, pos = [], 0
    while True:
        m = _Q_OPEN.search(html, pos)
        if not m:
            out.append(html[pos:])
            break
        end = _match_close(html, m.start())
        if end < 0:
            out.append(html[pos:])
            break
        out.append(html[pos:m.start()])
        out.append(_reflow_block(html[m.start():end]))
        pos = end
    return ''.join(out)


_LEAD_IMG = re.compile(r'^(<img[^>]*>)')


def _reflow_block(block):
    """课后练习的配图：一律**居中**排在题干之后。

    图在源稿里多排在题干之后、选项之前；render 层已按「题干→图→选项」
    输出。这里只把图包成居中块，不再做「左作答区 + 右图」的左右分栏
    （用户要求一律居中）。
    """
    out = re.sub(r'<div class="fig">(.*?)</div>',
                 lambda m: '<div class="fig-c">' + m.group(1) + '</div>',
                 block, flags=re.S)
    # 题干里内联的图也抽出来居中（原稿常把图放在题号之前）
    def _pull(m):
        return '<div class="fig-c"><img src="' + m.group(1) + '"></div>'
    out = re.sub(r'<p>(\s*<img[^>]*src="([^"]+)"[^>]*>)', _pull, out)
    return out


def _data_uri(path):
    ext = os.path.splitext(path)[1].lower().lstrip('.')
    mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'gif': 'image/gif', 'emf': 'image/emf', 'wmf': 'image/wmf',
            'svg': 'image/svg+xml', 'bmp': 'image/bmp'}.get(ext, 'image/png')
    with open(path, 'rb') as f:
        return f'data:{mime};base64,' + base64.b64encode(f.read()).decode('ascii')


def inline_images(html, media_dir):
    """把 src="media/x.png" 换成内联 data URI（自包含，无路径依赖）。"""
    miss = []

    def rep(m):
        p = os.path.join(media_dir, m.group(1))
        if not os.path.exists(p):
            miss.append(m.group(1))
            return 'src=""'
        return 'src="' + _data_uri(p) + '"'

    out = _IMG_SRC.sub(rep, html)
    if miss:
        print('   [warn] 缺图:', ', '.join(sorted(set(miss))))
    return out


def inject_css(html, extra=None):
    """把公式/题图 CSS 追加到最后一个 </style> 之前。"""
    block = MATH_CSS + FIG_CSS + (extra or '')
    i = html.rfind('</style>')
    if i < 0:
        return html
    return html[:i] + block + html[i:]


_CAPTION_P = re.compile(r'<p>\s*图\s*\d+\s*</p>')


def drop_captions(html):
    """删掉源稿自带的图注段（"图2"、"图 3"）。

    原稿在每张图下面写了图号，但本套资源的题干里已经用「如图2所示」
    引用了它们，再印一行「图2」是冗余，用户要求去掉。
    """
    return _CAPTION_P.sub('', html)


def finalize(html, media_dir, extra_css=None, side_figs=False):
    html = inline_images(html, media_dir)
    if side_figs:
        html = move_figs_beside_answer(html)
        extra_css = (extra_css or '') + SIDE_FIG_CSS
    return inject_css(html, extra_css)
