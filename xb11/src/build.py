# -*- coding: utf-8 -*-
"""校本作业 docx → 结构化 JSON → 学生版/教师版/答案版 PDF + 16:9 讲解 HTML。

用法:
    python3 build.py                 # 构建全部讲次
    python3 build.py 11.1            # 只构建匹配的讲次
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 输出根目录：默认本目录；换章时用 CHAPTER_ROOT 指向新目录（media/json/out 各自独立），
# 代码仍共用这一份——不要为换章复制整个目录（会漂移）。
ROOT = os.environ.get('CHAPTER_ROOT') or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'smartedu-grab'))

import docxparse, sectionize, postprocess                       # noqa: E402
from latex2html import MATH_CSS                                 # noqa: E402
import render_ws                                                # noqa: E402
import build_deck_html as deck                                  # noqa: E402

render_ws.PRESERVE_PARAS = True      # docx 来源：段落已是完整段落
render_ws.ASK_LINES = True           # 任务单问句下留一行作答虚线
render_ws.OPTS_LINES = True          # 选项按长短排 1/2/4 行

# 讲义的正文区可滚动：展开解析后内容会超过一屏 16:9
DECK_EXTRA_CSS = """
.ansbox .m .frac{vertical-align:-.42em}
.s-body{overflow-y:auto;max-height:calc(720px - 150px);padding-right:6px}
.s-body::-webkit-scrollbar{width:8px}
.s-body::-webkit-scrollbar-thumb{background:#bcd6c6;border-radius:4px}
"""

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MEDIA = os.path.join(ROOT, 'media')
JSOND = os.path.join(ROOT, 'json')
PDFD = os.path.join(ROOT, 'pdf')
HTMLD = os.path.join(ROOT, 'html')
OUTD = os.path.join(ROOT, 'out')
# 章配置：换一章只改这一份 JSON，代码不动（避免多份拷贝各自漂移）
# 章配置：默认取**本目录**的 chapter.json（不是 ROOT——换章后 ROOT 指向新目录，
# 配置仍应放在代码旁边，或用 CHAPTER_JSON 显式指定）
CFG = json.load(open(os.environ.get('CHAPTER_JSON')
                     or os.path.join(HERE, 'chapter.json'), encoding='utf-8'))
BOOK = CFG['book']

# 源目录：校对版 docx（WPS 云盘「2025级校本作业」同步下来的）
SRCD = os.path.join(ROOT, 'src', CFG.get('srcd', 'src_new'))

# 讲次表： (id, 显示名, 来源文件)  —— 每讲可由多个源文件组成，按顺序拼接
LESSONS = [(l['id'], l['title'], l['sources']) for l in CFG['lessons']]


# ---------------------------------------------------------------- 解析
REPORTS = []          # [(课程 id, 源文件名, 公式清单, 修正项)]


def parse_docx(path, media_sub):
    md = os.path.join(MEDIA, media_sub)
    # 先清空该讲的 media 目录：源文件里同名图片的内容可能已经变了
    # （image3.png 从碎片图换成正常图），旧文件残留会让新图被误判、
    # 或沿用旧内容导致图片错位/丢失。
    import shutil
    if os.path.isdir(md):
        shutil.rmtree(md)
    blocks, rep = docxparse.parse_with_report(path, md)
    REPORTS.append((media_sub, os.path.basename(path), rep))
    return sectionize.sectionize(blocks)


def write_formula_report(path):
    """输出全部公式的 LaTeX 清单，便于逐条人工校对（MTEF 解错是静默的）。"""
    lines = ['# 公式解码清单（供人工校对）', '',
             'MTEF MathType 公式解码后如下。个别对象会解出"看似合理但错误"的公式，',
             '请对照原 docx 逐条核对；确认有误的写进 `src/docxparse.py` 的 `MTEF_FIXES`。', '']
    n = 0
    for lid, src, rep in REPORTS:
        if not rep['formulas'] and not rep['fixed'] and not rep['dropped']:
            continue
        lines.append(f'## {lid} — {src}')
        fixes = {m: f for m, _o, f in rep['fixed']}
        for media, app, tex in rep['formulas']:
            mark = '  ← 已人工修正' if media in fixes else ''
            lines.append(f'- `{media}` ({app}) → `{tex}`{mark}')
            n += 1
        for media, orig, fix in rep['fixed']:
            lines.append(f'  - 修正：`{media}` 原解码 `{orig}` → `{fix}`')
        for media, size in rep['dropped']:
            lines.append(f'  - 已丢弃装饰图：`{media}` {size}')
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return n


# 原稿未附答案的讲次 → 我方补写的参考解答（构建时注入，标题标「参考解答」）。
# key: (题号, 题组号)，题组号对应 sectionize 的 qgroup（无分组时为 0/省略）。
# 原稿未附答案的讲次 → 我方补写的参考解答（配置在 chapter.json 的 self_answers）
LESSON_SELF_ANSWERS = {
    k: {tuple(int(x) for x in kk.split(',')): vv for kk, vv in v.items()}
    for k, v in CFG.get('self_answers', {}).items()
}


# 源文件答案标号有误时的人工纠正：{课时: {(错标题号, 组): 实际题号}}
# 11.2 原稿把「(1)肥胖的人…脂肪不容易导电」标成第 7 题，但第 7 题是长方体样品，
# 该答案实际属于第 8 题（人体脂肪测量仪）。
ANSWER_REMAP = {
    k: {tuple(int(x) for x in kk.split(',')): vv for kk, vv in v.items()}
    for k, v in CFG.get('answer_remap', {}).items()
}


def remap_answers(data, key):
    """按 ANSWER_REMAP 调整答案归属（同时改 ans 小节与 answers 字典）。"""
    remap = ANSWER_REMAP.get(key)
    if not remap:
        return data
    fixes = []
    for s in data['sections']:
        if s.get('kind') == 'ans':
            k = (s.get('no'), s.get('qgroup') or 0)
            if k in remap:
                new = remap[k]
                fixes.append((s['no'], new))
                s['no'] = new
                s['title'] = f'{new}．' + ('解析' if s.get('tag') == '解析' else '答案')
    for old, new in fixes:
        for k in list(data['answers']):
            if k == str(old) or (k.startswith('(%d,' % old)):
                data['answers'][str(new)] = data['answers'].pop(k)
    return data


def inject_self_answers(data, key):
    """把补写的参考解答作为 ans 小节注入（标题标「参考解答」）。"""
    sa = LESSON_SELF_ANSWERS.get(key)
    if not sa:
        return data
    for (no, grp), body in sa.items():
        item = _paras_html(body)
        data['sections'].append({
            'kind': 'ans', 'no': no, 'qgroup': grp, 'tag': '参考',
            'title': f'{no}．参考解答', 'items': [item]})
        # 讲评 HTML 与答案版读的是 answers 字典，必须同步登记
        key_ = str((no, grp)) if grp else str(no)
        data.setdefault('answers', {})[key_] = [item]
    return data


def _paras_html(body):
    return {'paras': [{'html': body, 'plain': re.sub(r'<[^>]+>', '', body)}]}


def merge_sections(datas):
    """把一讲的多个源文件（任务单 + 课后练习）合成一个 sections 序列。"""
    if len(datas) == 1:
        return datas[0]
    base = datas[0]
    for d in datas[1:]:
        base['sections'].extend(d['sections'])
        for k, v in d.get('answers', {}).items():
            base.setdefault('answers', {})[k] = v
    return base


def lesson_json(lesson_id, docx_names, key):
    if docx_names is None:
        # 源是 PDF（无结构可依），JSON 由专用脚本预先生成，这里直接读
        dst = os.path.join(JSOND, f'{lesson_id}.json')
        with open(dst, encoding='utf-8') as f:
            return json.load(f), dst
    if isinstance(docx_names, str):
        docx_names = [docx_names]
    datas = []
    for i, name in enumerate(docx_names):
        src = os.path.join(SRCD, name)
        datas.append(parse_docx(src, f'{lesson_id}_{i}' if i else lesson_id))
    data = merge_sections(datas)
    data = remap_answers(data, key)            # 源文件答案标号错误的人工纠正
    data = inject_self_answers(data, key)      # 原稿缺答案的讲次补参考解答
    data['meta'] = {'id': lesson_id, 'book': BOOK}
    os.makedirs(JSOND, exist_ok=True)
    dst = os.path.join(JSOND, f'{lesson_id}.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data, dst


# ---------------------------------------------------------------- 渲染
def lesson_key(title):
    """显示名「11.1　电源与电流」→ 解析库 key「11.1 电源与电流」（全角空格归一）。"""
    return re.sub(r'\s+', ' ', (title or '').replace('　', ' ')).strip()


def build_pdfs(lesson_id, title, data):
    """单讲 PDF —— 用户只要整章总册，此处默认不产出（见 build.py 末尾说明）。

    保留函数以便需要时单独出某讲：把 main() 里的 build_pdfs 调用取消注释即可。
    """
    secs = data['sections']
    os.makedirs(PDFD, exist_ok=True)
    md = os.path.join(MEDIA, lesson_id)
    key = lesson_key(title)          # 三个版本共用同一 key，否则解析库里查不到
    outs = []
    for mode, suffix in (('student', '学生版'), ('teacher', '教师版'), ('answer', '答案版')):
        html = render_ws.build_page(f'{title}（{suffix}）', '', secs, mode, lesson_key=key)
        html = postprocess.finalize(html, md, side_figs=(mode == 'student'))
        if mode == 'student':
            # 学习任务里的图也要挪到小问右侧
            html = postprocess.reflow_task_figs(html, md)
        hp = os.path.join(PDFD, f'{lesson_id}_{suffix}.html')
        with open(hp, 'w', encoding='utf-8') as f:
            f.write(html)
        pp = os.path.join(PDFD, f'{lesson_id}_{suffix}.pdf')
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                        f"--print-to-pdf={pp}", "--no-pdf-header-footer",
                        f"file://{hp}"], capture_output=True)
        outs.append(pp if os.path.exists(pp) else None)
    return outs


def build_deck(lesson_id, title, data):
    """唯一的 HTML 产物：内容同教师版（题目+解析），供上课讲评。

    16:9 翻页，题目下方的「💡显示解析」点击展开/隐藏。
    """
    secs = data['sections']
    ex = [s for s in secs if s['kind'] == 'q']
    ans = data['answers']
    ex_q = []
    for s in ex:
        key = (s['no'], s['qgroup']) if s.get('qgroup') else s['no']
        # answers 字典的键：多题组是 "(题号, 组号)"，单题组是 "题号"
        a = ans.get(str(key)) or ans.get(str(s['no']))
        ex_q.append({'no': key, 'qno': s['no'], 'q_section': s,
                     'qtitle': '', 'ans_items': a})
    slides = deck.build_slides(secs, ex_q, title, '', book=BOOK,
                               task_key=lesson_key(title))
    html = deck.assemble(title, ''.join(slides))
    html = postprocess.finalize(html, os.path.join(MEDIA, lesson_id),
                                extra_css=DECK_EXTRA_CSS)
    os.makedirs(HTMLD, exist_ok=True)
    hp = os.path.join(HTMLD, f'{lesson_id}_课堂讲评.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    return hp


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for lid, title, docx_names in LESSONS:
        if want and want not in lid:
            continue
        print(f'== {lid} {title}')
        data, jp = lesson_json(lid, docx_names, lesson_key(title))
        print(f'   JSON: {jp}  sections={len(data["sections"])}')
        # 只产出 JSON；整章总册由 merge.py 生成（单讲 PDF/讲义不再需要）
        if '--per-lesson' in sys.argv:
            pdfs = build_pdfs(lid, title, data)
            for p in pdfs:
                print('   PDF:', os.path.basename(p) if p else 'FAILED')
            hp = build_deck(lid, title, data)
            print('   DECK:', os.path.basename(hp))
    n = write_formula_report(os.path.join(ROOT, '公式校对清单.md'))
    print(f'\n公式校对清单：{n} 条 → {os.path.join(ROOT, "公式校对清单.md")}')


if __name__ == '__main__':
    main()
