# -*- coding: utf-8 -*-
"""整章总册：把各讲渲染进同一个 HTML，一次打印成 PDF。

早先是把各讲的 PDF 逐页搬进总册再贴标题条——那样每讲必定另起一页，
页面底部常剩半页空白，而且节标题条只能靠版面坐标硬塞。
改成整章一个 HTML，内容自然流动：节标题就是一段加粗大字，
Chrome 自己分页；标题放不下时会连同后文一起挪到下一页。
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 输出根目录：默认本目录；换章时用 CHAPTER_ROOT 指向新目录（media/json/out 各自独立），
# 代码仍共用这一份——不要为换章复制整个目录（会漂移）。
ROOT = os.environ.get('CHAPTER_ROOT') or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'smartedu-grab'))

import render_ws, postprocess                                    # noqa: E402

render_ws.PRESERVE_PARAS = True
render_ws.OPTS_LINES = True

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
JSOND = os.path.join(ROOT, 'json')
OUTD = os.path.join(ROOT, 'out')
MEDIA = os.path.join(ROOT, 'media')

# 与 build.py 共用同一份章配置
# 章配置：默认取**本目录**的 chapter.json（不是 ROOT——换章后 ROOT 指向新目录，
# 配置仍应放在代码旁边，或用 CHAPTER_JSON 显式指定）
CFG = json.load(open(os.environ.get('CHAPTER_JSON')
                     or os.path.join(HERE, 'chapter.json'), encoding='utf-8'))
CHAPTER = CFG['chapter']

# (节序, 节名, 课时, 讲次 id, 解析库 key)；节序为空表示不编节的补充内容
LESSONS = [(l['sec'], l['name'], l['period'], l['id'], l['key'])
           for l in CFG['lessons']]

MODES = [
    ("学生用作业本", "student", "仅题目与作答区，无答案"),
    ("教师用批改本", "teacher", "题目后紧跟答案与解析"),
    ("答案速查本", "answer", "纯答案，无题干"),
]

HEAD_CSS = """
/* 章标题 */
.chapter-head{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:30pt;font-weight:900;color:#0E4E33;text-align:center;
 letter-spacing:4px;margin:10px 0 18px;padding-bottom:12px;
 border-bottom:3.5px solid #007020}
/* 节标题：章 / 节 / 课时 各占一行，居中；整块不跨页 */
.sec-head{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 text-align:center;margin:26px 0 12px;padding:10px 0;
 border-top:1.5px solid #b0d0c0;border-bottom:1.5px solid #b0d0c0;
 background:#f2f8f3;break-inside:avoid;break-after:avoid}
/* 层级：章(30pt) > 节(19pt) > 课时(14pt) > 正文(11.5pt) */
.sec-head .sh-ch{display:block;font-size:13pt;font-weight:700;
 color:#4a705b;letter-spacing:2px;line-height:1.5}
.sec-head .sh-ti{display:block;font-size:19pt;font-weight:900;
 color:#0E4E33;letter-spacing:2px;line-height:1.4}
.sec-head .sh-per{display:block;font-size:14pt;font-weight:700;
 color:#007020;letter-spacing:2px;line-height:1.5}
.section-body{margin-top:2px}
"""


def sec_parts(num, name, period):
    """节标题：章名 / 第N节 节名 / 课时。

    num 为空表示不编节的独立小节（如章末复习卷）。
    """
    return CHAPTER, (f"第{num}节　{name}" if num else name), period


def lesson_html(parts, lid, mode, key):
    ch, ti, per = parts
    path = os.path.join(JSOND, f'{lid}.json')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    # 学生版：任务单的问题留作答空白（选择题由 render_ws 自动排除）
    render_ws.ASK_LINES = (mode == 'student')
    body = render_ws.render_mode(data['sections'], mode, ti, lesson_key=key)
    # 各讲的图在自己的 media 目录，按讲内联成 data URI
    body = postprocess.inline_images(body, os.path.join(MEDIA, lid))
    # 配图统一处理：任务单与课后练习的图都居中排在题干之后
    body = postprocess.reflow_task_figs(body, os.path.join(MEDIA, lid))
    body = postprocess.move_figs_beside_answer(body)
    body = postprocess.drop_captions(body)      # 去掉冗余的「图2/图3」图注
    # 不再单独印一行章名——首页已有 30pt 的章标题，节标题里再印一遍
    # 会紧挨在下面，看着像"节比章大"。节标题直接写「第N节 节名」（+课时）。
    head = (f'<div class="sec-head">'
            f'<span class="sh-ti">{ti}</span>'
            + (f'<span class="sh-per">{per}</span>' if per else '') + '</div>')
    return head + f'<div class="section-body">{body}</div>'


def cover_html(subtitle, logo_uri):
    """极简封面：浅色底、校徽、章名、副标题。"""
    return f"""<section class="cover">
  <img class="cv-logo" src="{logo_uri}" alt="校徽">
  <div class="cv-school">深圳外国语学校博雅高中</div>
  <div class="cv-dept">高二年级物理组</div>
  <div class="cv-rule"></div>
  <h1 class="cv-title">{CHAPTER}</h1>
  <div class="cv-sub">{subtitle}</div>
</section>"""


COVER_CSS = """
.cover{height:247mm;display:flex;flex-direction:column;
 align-items:center;justify-content:center;text-align:center;
 break-after:page;background:#f7faf8}
.cv-logo{width:104px;height:104px;object-fit:contain;margin-bottom:26px}
.cv-school{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:17pt;font-weight:700;color:#0E4E33;letter-spacing:5px}
.cv-dept{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:11pt;color:#5c7a68;letter-spacing:4px;margin-top:8px}
.cv-rule{width:64px;height:2px;background:#9dc4ae;margin:30px 0 34px}
.cv-title{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:34pt;font-weight:900;color:#0E4E33;letter-spacing:6px;margin:0}
.cv-sub{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:12.5pt;color:#4a705b;letter-spacing:3px;margin-top:22px}
"""


PAGE_CSS = """
/* 节另起一页（由第二遍排版按剩余空间决定，见 build()） */
.sec-head.newpage{break-before:page}
"""


def _with_page_breaks(html, titles):
    """给指定的节标题加 break-before:page。

    titles 里同一节名可能出现多次（第三节有第一/第二课时）。因此按
    **出现顺序**逐次往后找，不能每次都从头 find——否则第二次仍命中
    第一个同名标题，后面的课时永远分不了页。
    """
    open_tag = '<div class="sec-head">'
    # titles 里元素是 (节名, 第几次出现)；按位置从后往前插入，
    # 这样前面的插入不会让后面的下标失效。
    targets = []
    for t, k in titles:
        needle = f'<span class="sh-ti">{t}</span>'
        pos, seen = -1, -1
        while True:
            pos = html.find(needle, pos + 1)
            if pos < 0:
                break
            seen += 1
            if seen == k:
                j = html.rfind(open_tag, 0, pos)
                if j >= 0:
                    targets.append(j)
                break
    out = html
    for j in sorted(set(targets), reverse=True):
        out = out[:j] + '<div class="sec-head newpage">' + out[j + len(open_tag):]
    return out


def _logo_uri():
    """校徽 → data URI（自包含，避免打印时路径依赖）。"""
    import base64
    p = os.path.expanduser('~/Downloads/06_图片素材/校徽.png')
    if not os.path.exists(p):
        return ''
    with open(p, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')


def paginate_sections(pdf):
    """按剩余空间决定节是否另起一页。

    规则（用户要求）：上一节结束后，
      - 当前页剩余 **≥ 半页** → 下一节在本页继续；
      - 剩余 **< 半页** → 下一节另起一页。

    实现思路：Chrome 先把整章按自然流动排好版；此处找出每个节标题，
    若它出现在页面的**下半部分**（说明上一节已占掉半页以上、剩下的
    空间不足以舒服地开始新一节），就把该节标题连同其后内容整体
    挪到下一页——PDF 层做不到"整体挪"，因此改为在标题前插一个
    空白页并把标题以下的整块内容搬过去，代价高且易错。

    更稳的做法是把判断前置到 HTML：见 `probe_sections()`。
    这里仅作为兜底，返回需要分页的节标题位置供调用方参考。
    """
    import fitz
    doc = fitz.open(pdf)
    half = doc[0].rect.height / 2
    out = []
    for i in range(doc.page_count):
        for blk in doc[i].get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = line.get("spans") or []
                if not spans:
                    continue
                sz = max(sp["size"] for sp in spans)
                txt = "".join(sp["text"] for sp in spans).strip()
                if sz > 17 and re.match(r'^第[一二三四五六七八九十]+节', txt):
                    out.append((i, round(line["bbox"][1], 1),
                                "下半页" if line["bbox"][1] > half else "上半页", txt[:22]))
    doc.close()
    return out


def stamp_headers(pdf, skip_first=True):
    """逐页盖页眉：深圳外国语学校博雅高中　高二年级物理组　校本作业。

    Chrome 的 @page 边距框支持不稳，改为打印后用 PyMuPDF 画，
    与封面同一套做法，位置和字号都可控。
    """
    import fitz
    doc = fitz.open(pdf)
    start = 1 if skip_first else 0
    for i in range(start, doc.page_count):
        p = doc[i]
        r = p.rect
        y = 32
        p.insert_textbox(fitz.Rect(45, y - 12, r.width - 45, y + 6),
                         "深圳外国语学校博雅高中　高二年级物理组　校本作业",
                         fontsize=8.5, color=(0.29, 0.44, 0.36),
                         align=0, fontname="china-s")
        p.draw_line(fitz.Point(45, y + 9), fitz.Point(r.width - 45, y + 9),
                    color=(0.69, 0.82, 0.75), width=0.7)
    doc.saveIncr()
    doc.close()


def build(mode, out_name, subtitle):
    """两遍打印：先排版测量各节落点，再按「剩余过半则续排」决定分页。"""
    secs = []
    for num, name, period, lid, key in LESSONS:
        try:
            secs.append(lesson_html(sec_parts(num, name, period), lid, mode, key))
        except Exception as e:
            import traceback
            print(f'   [warn] {lid} 渲染失败: {e}')
            traceback.print_exc()
    parts = [cover_html(subtitle, _logo_uri())] + secs
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<style>{render_ws.CSS}{HEAD_CSS}{COVER_CSS}{PAGE_CSS}</style></head><body>'
            + ''.join(parts) + '</body></html>')
    html = postprocess.inject_css(html, postprocess.SIDE_FIG_CSS if mode == 'student' else None)
    os.makedirs(OUTD, exist_ok=True)
    hp = os.path.join(OUTD, f'{out_name}.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    pdf = os.path.join(OUTD, f'{out_name}.pdf')
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                    f"--print-to-pdf={pdf}", "--no-pdf-header-footer",
                    f"file://{hp}"], capture_output=True)
    # 迭代排版：每轮量出落在下半页的节标题，给它们加分页；直到不再变化。
    # 一轮不够——给 A 节加分页后，后面的节会往前挪，可能又落到下半页。
    if os.path.exists(pdf):
        added, cur_html = set(), html
        for rnd in range(1, 6):
            marks = paginate_sections(pdf)
            # 用 (节名, 第几次出现) 作键——同名节（第三节两个课时）要去重且保序
            occ = {}
            need = []
            for _p, _y, pos, t in marks:
                k = occ.get(t, 0)
                occ[t] = k + 1
                if pos == '下半页' and (t, k) not in added:
                    need.append((t, k))
            if not need:
                break
            added |= set(need)
            cur_html = _with_page_breaks(html, sorted(added))
            with open(hp, 'w', encoding='utf-8') as f:
                f.write(cur_html)
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                            f"--print-to-pdf={pdf}", "--no-pdf-header-footer",
                            f"file://{hp}"], capture_output=True)
            print(f'   第 {rnd} 轮分页: {len(need)} 节 → {sorted(need)}')
        stamp_headers(pdf)          # 逐页页眉（封面除外）
    size = os.path.getsize(pdf) / 1e6 if os.path.exists(pdf) else 0
    print(f'   {out_name}.pdf  {size:.1f} MB')


if __name__ == '__main__':
    for label, mode, note in MODES:
        print(f'== {label}')
        build(mode, f'{CFG.get("file_prefix", CHAPTER.split()[0])}_{label}', note)
