# -*- coding: utf-8 -*-
"""docx → 扁平块序列（段落 / 表格），公式与图片就地解析。

这批校本作业的三种公式形态全部处理：
  1. MathType OLE  (w:object + oleObject)  → mtef_pkg 无损转 LaTeX
  2. Word 原生公式 (m:oMath)               → omml.py
  3. Word EQ 域    (eq \\f(a,b))            → omml.eq_to_latex
上下标（w:vertAlign）转 <sub>/<sup>；图片经 w:drawing / w:pict 落盘。

版式表格（单列，仅作分节外框）会被摊平；多列表格作为内容表格保留。
"""
import os, re, sys, zipfile
from lxml import etree

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, '..', '..', '..', 'docx2md', 'vendor'))

from omml import omml_to_latex, eq_to_latex, M as NSM
from latex2html import math_html

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
V = '{urn:schemas-microsoft-com:vml}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
XML = '{http://www.w3.org/XML/1998/namespace}'

MIN_IMG_W = 40          # 窄于此宽度的图视为装饰碎片，丢弃

# 原教辅用 INCLUDEPICTURE 引入的装饰徽章（图片形式的章节小标题）。
# 文件名是中文的即为徽章，是编号的（11-1、11-98）才是真插图。
_BADGE = {'易错辨析', '方法技巧', '特别提醒', '规律总结', '知识链接', '温馨提示',
          '归纳总结', '名师点睛', '素养提升', '拓展延伸'}
_FIGNAME = re.compile(r'^[\d\-—]+$')

# MTEF 个别对象会解错（不是解不出，而是解出看似合理实则错误的公式，最危险）。
# 已核对出的错误逐条纠正，key = (docx 文件名, media 文件名)。
# 按**解码结果**匹配（而不是按文件名）——源文件一改版，wmf 的编号顺序就会变，
# 写死文件名会让修复静默失效、甚至改错对象（11.2 的 C/D 就这么错过一次）。
# key = 错误的解码结果，value = 应该是什么。
MTEF_FIX_BY_TEXT = {
    '$ C-y+1-m=0 $': 'C',      # 原意为字母 C（"图中A、B、C、D四个点"），MTEF v5 解码跑偏
}


def _norm_docname(name):
    """文件名归一化：去扩展名/空格/括号编号。

    源文件常被改名为「11.2导体的电阻(1).docx」，写死全名的话修复会静默失效
    （11.2 的「C-y+1-m=0」就这么复活过一次）。
    """
    n = os.path.splitext(os.path.basename(name or ''))[0]
    n = re.sub(r'[\s　]+', '', n)
    return re.sub(r'\(\d+\)$', '', n)


def _ans_like_html(text):
    """把内嵌文档的纯文本渲染成 HTML（含 $..$ 与裸 LaTeX 的公式）。"""
    try:
        sys.path.insert(0, _HERE)
        from sectionize import _ans_text_html
        return _ans_text_html(text)
    except Exception:
        return _html_esc(text)


def _local(el):
    return etree.QName(el).localname


def _html_esc(t):
    return (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


class Docx:
    def __init__(self, path, media_dir):
        self.path = path
        self.media_dir = media_dir
        self.z = zipfile.ZipFile(path)
        self.doc = etree.fromstring(self.z.read('word/document.xml'))
        self.rid = {}
        try:
            rels = etree.fromstring(self.z.read('word/_rels/document.xml.rels'))
        except KeyError:
            rels = None
        if rels is not None:
            for rel in rels:
                self.rid[rel.get('Id')] = rel.get('Target')
        self.basename = os.path.basename(path)
        self.formulas = []      # [(media, MTEF版本, LaTeX)] —— 供构建时人工校对
        self.fixed = []         # [(media, 原解码, 修正值)]
        self._embed_cache = {}  # 内嵌 Word 文档对象正文缓存
        self._mtef = self._load_mtef()
        self.dropped = []
        os.makedirs(media_dir, exist_ok=True)

    # ---------- MathType ----------
    def _load_mtef(self):
        """{预览图 media 名: LaTeX}，同时记录本文档引用了哪些预览图。"""
        fmap, self.object_media = {}, set()
        try:
            from mtef_pkg import MTEF
        except Exception:
            return fmap
        # vendor 库内含 (DEBUG) 打印，会淹没构建日志；仅在本模块调用期间屏蔽
        import contextlib, io
        for om in re.finditer(rb'<w:object[^>]*>.*?</w:object>',
                              self.z.read('word/document.xml'), re.S):
            blk = om.group(0).decode('utf-8', 'replace')
            img = re.search(r'<v:imagedata[^>]*r:id="([^"]+)"', blk)
            ole = re.search(r'<o:OLEObject[^>]*r:id="([^"]+)"', blk)
            if not (img and ole):
                continue
            iname = self.rid.get(img.group(1), '').split('/')[-1]
            oname = self.rid.get(ole.group(1), '').split('/')[-1]
            self.object_media.add(iname)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    mtef, err = MTEF.OpenBytes(self.z.read('word/embeddings/' + oname))
                    tex = (mtef.Translate() or '').strip() if mtef is not None else ''
                    app = (mtef.mApplication.decode(errors='replace') if mtef is not None else '?')
                fix = MTEF_FIX_BY_TEXT.get(tex)
                if fix is not None:
                    self.fixed.append((iname, tex, fix))
                    tex = fix
                if tex:
                    fmap.setdefault(iname, tex)
                    self.formulas.append((iname, app, tex))
            except Exception:
                pass
        return fmap

    # ---------- 内嵌 Word 文档对象 ----------
    def _embed_doc_text(self, ole_name):
        """OLEObject(ProgID=Word.Document) → 内嵌文档正文的 HTML 片段。

        原教辅把整段内容（如某题的选项）做成嵌套 Word 文档，其预览图是 EMF，
        浏览器渲染不了（显示为破图），内容也全丢。这里把内嵌包解出来读正文。
        """
        key = 'word/embeddings/' + ole_name
        if key in self._embed_cache:
            return self._embed_cache[key]
        out = None
        try:
            import io as _io
            import olefile
            ole = olefile.OleFileIO(_io.BytesIO(self.z.read(key)))
            if ole.exists('package'):
                inner = zipfile.ZipFile(_io.BytesIO(ole.openstream('package').read()))
                xml = inner.read('word/document.xml')      # 保留 bytes：带编码声明
                sub = Docx.__new__(Docx)          # 复用段落解析
                sub.z = inner
                sub.rid = {}
                try:
                    rels = etree.fromstring(inner.read('word/_rels/document.xml.rels'))
                    for rel in rels:
                        sub.rid[rel.get('Id')] = rel.get('Target')
                except Exception:
                    pass
                sub._mtef = {}
                sub.basename = self.basename
                sub.dropped, sub.formulas, sub.fixed = [], [], []
                sub.media_dir = self.media_dir
                root = etree.fromstring(xml)
                buf = []
                for p in root.iter(W + 'p'):
                    r = sub.para(p)
                    if not r['plain'].strip():
                        continue
                    # 必须用 html：里面已带 <sub>/<sup> 上下标（I₁、10⁻³）
                    # 与 MathType 分数。早先只取 plain，角标全丢了。
                    row = r['html'].strip()
                    row = re.sub(r'\\f\(([^,]*),([^)]*)\)',
                                 lambda m: r'\frac{%s}{%s}' % (m.group(1).strip(),
                                                               m.group(2).strip()), row)
                    buf.append(row)
                if buf:
                    out = ' '.join(buf)
        except Exception:
            out = None
        self._embed_cache[key] = out
        return out

    # ---------- 图片 ----------
    def _save_media(self, target):
        """target 形如 media/image1.png → 落盘并返回文件名；过窄碎片返回 None。"""
        name = target.split('/')[-1]
        src = 'word/' + target if not target.startswith('word/') else target
        dst = os.path.join(self.media_dir, name)
        if not os.path.exists(dst):
            try:
                with open(dst, 'wb') as f:
                    f.write(self.z.read(src))
            except KeyError:
                return None
        # 丢弃装饰框被切开的细条（如「例题」徽章的左右两半）
        try:
            from PIL import Image
            with Image.open(dst) as im:
                if im.width < MIN_IMG_W:
                    self.dropped.append((name, im.size))
                    return None
        except Exception:
            pass
        return name

    def _img_from(self, el):
        """从 w:drawing / w:pict 里取 r:embed / r:id → 落盘路径。"""
        for blip in el.iter(A + 'blip'):
            rid = blip.get(R + 'embed') or blip.get(R + 'link')
            if rid and rid in self.rid:
                return self._save_media(self.rid[rid])
        for im in el.iter(V + 'imagedata'):
            rid = im.get(R + 'id')
            if rid and rid in self.rid:
                return self._save_media(self.rid[rid])
        return None

    # ---------- 段落 ----------
    def para(self, p):
        """→ {'html':…, 'plain':…, 'imgs':[…]}; html 为行内 HTML。"""
        out, plain, imgs = [], [], []
        # EQ 域占位：begin 时压栈，instrText 累积，end/separate 时定性
        fields = []
        inc = {'name': None}      # 当前 INCLUDEPICTURE 域的目标名
        buf = []                  # 文字 run 缓冲（公式/图/徽章前先冲刷）

        def _set_inc(instr):
            """记录 INCLUDEPICTURE 域的目标名（供 _img_ok 判定图 / 徽章）。"""
            # 路径形如 ...\\第十一章　电路及其应用\\易错辨析.TIF" \* MERGEFORMAT
            hits = re.findall(r'([^\\/"]+?)\.(?:tif|png|jpe?g|emf|wmf)', instr, re.I)
            inc['name'] = hits[-1].strip() if hits else None

        def _img_ok(el):
            """真插图 → (True, None)；文字徽章 → (False, 徽章文字)；纯装饰 → (False, None)。

            原教辅的章节小标题是用 INCLUDEPICTURE 引入的图片，文件名即其文字
            （如「易错辨析」「例题」）；真插图文件名是编号（11-1、11-98）。
            """
            nm = inc['name']
            if nm is None:
                return True, None
            base = nm.split('\\')[-1].split('/')[-1]
            base = re.sub(r'\.(tif|png|jpg|jpeg|emf|wmf)$', '', base, flags=re.I)
            if _FIGNAME.match(base):
                return True, None
            if '左括' in base or '右括' in base:
                return False, None                    # 括号装饰
            return False, base                        # 一律还原成文字

        def emit_run(run):
            # 上下标
            va = None
            rpr = run.find(W + 'rPr')
            if rpr is not None:
                v = rpr.find(W + 'vertAlign')
                if v is not None:
                    va = v.get(W + 'val')
            for ch in run:
                t = _local(ch)
                if t == 't':
                    buf.append(ch.text or '')
                elif t in ('drawing', 'pict', 'object'):
                    if t == 'object':
                        # 内嵌 Word 文档对象（选项被包在里面，预览图是渲染不了的 EMF）
                        emb = None
                        for o in ch.iter('{urn:schemas-microsoft-com:office:office}OLEObject'):
                            if 'Word.Document' in (o.get('ProgID') or ''):
                                rid = o.get(R + 'id')
                                if rid and rid in self.rid:
                                    emb = self.rid[rid].split('/')[-1]
                        if emb:
                            html_ = self._embed_doc_text(emb)
                            if html_:
                                if buf:
                                    _emit_text(''.join(buf), va)
                                    buf.clear()
                                out.append(html_)
                                plain.append(re.sub(r'<[^>]+>', '', html_))
                                continue
                        # MathType：预览图名 → LaTeX
                        name = None
                        for im in ch.iter(V + 'imagedata'):
                            rid = im.get(R + 'id')
                            if rid and rid in self.rid:
                                name = self.rid[rid].split('/')[-1]
                        if name and name in self._mtef:
                            if buf:
                                _emit_text(''.join(buf), va)
                                buf.clear()
                            tex = self._mtef[name]
                            out.append(math_html(tex))
                            plain.append(tex)
                        elif name and name.lower().endswith(('.emf', '.wmf')):
                            pass          # 渲染不了的矢量预览图，直接丢弃
                        else:
                            _emit_img(ch)
                    else:
                        _emit_img(ch)
                elif t in ('oMath', 'oMathPara'):
                    if buf:
                        _emit_text(''.join(buf), va)
                        buf.clear()
                    tex = omml_to_latex(ch)
                    out.append(math_html(tex))
                    plain.append(tex)
                elif t in ('tab',):
                    buf.append('\t')
                elif t in ('br', 'cr'):
                    buf.append(' ')
            if buf:
                _emit_text(''.join(buf), va)
                buf.clear()

        def _emit_img(el):
            """插图 / 徽章统一出口：徽章还原成文字，插图落盘内联。"""
            keep, badge = _img_ok(el)
            if not keep:
                if buf:
                    _emit_text(''.join(buf), None)
                    buf.clear()
                if badge:
                    out.append(f'<span class="badge">{_html_esc(badge)}</span>')
                    plain.append(badge)
                return
            fp = self._img_from(el)
            if fp:
                if buf:
                    _emit_text(''.join(buf), None)
                    buf.clear()
                out.append(f'<img src="media/{fp}">')
                imgs.append(fp)

        def _emit_text(txt, va):
            if not txt:
                return
            esc = _html_esc(txt)
            if va in ('superscript', 'subscript'):
                tag = 'sup' if va == 'superscript' else 'sub'
                # 相邻同类型上下标合并（10^-19 常被拆成两个 run）
                if out and out[-1].startswith(f'<{tag}>') and out[-1].endswith(f'</{tag}>'):
                    out[-1] = f'<{tag}>{out[-1][len(tag)+2:-len(tag)-3]}{esc}</{tag}>'
                else:
                    out.append(f'<{tag}>{esc}</{tag}>')
            else:
                out.append(esc)
            plain.append(txt)

        def walk(el):
            for ch in el:
                t = _local(ch)
                if t == 'r':
                    # EQ 域：先看是否在域指令区
                    fc = ch.find(W + 'fldChar')
                    it = ch.find(W + 'instrText')
                    if fc is not None:
                        typ = fc.get(W + 'fldCharType')
                        if typ == 'begin':
                            mark = len(out)
                            out.append('')
                            fields.append({'mark': mark, 'instr': '', 'phase': 'instr',
                                           'start': len(plain)})
                        elif typ == 'separate' and fields:
                            fields[-1]['phase'] = 'result'
                            _set_inc(fields[-1]['instr'])
                        elif typ == 'end' and fields:
                            f = fields.pop()
                            instr = f['instr']
                            tex = eq_to_latex(instr)
                            if tex:
                                out[f['mark']] = math_html(tex)
                                plain.insert(f['start'], tex)
                            else:
                                out[f['mark']] = ''
                        continue
                    if it is not None and fields and fields[-1]['phase'] == 'instr':
                        # 域指令里的上下标（eq \f(q,t₁) 的 1）用 LaTeX 记法保留
                        t_ = it.text or ''
                        rpr_ = ch.find(W + 'rPr')
                        va_ = None
                        if rpr_ is not None:
                            v_ = rpr_.find(W + 'vertAlign')
                            if v_ is not None:
                                va_ = v_.get(W + 'val')
                        if va_ == 'subscript':
                            t_ = '_{%s}' % t_
                        elif va_ == 'superscript':
                            t_ = '^{%s}' % t_
                        fields[-1]['instr'] += t_
                        continue
                    if fields and fields[-1]['phase'] == 'instr':
                        continue          # 域指令区里的其它 run：丢弃
                    emit_run(ch)
                elif t in ('hyperlink', 'smartTag', 'sdt', 'sdtContent', 'ins', 'del'):
                    walk(ch)
                elif t in ('oMath', 'oMathPara'):
                    tex = omml_to_latex(ch)
                    out.append(math_html(tex))
                    plain.append(tex)
                elif t == 'fldSimple':
                    instr = ch.get(W + 'instr') or ''
                    tex = eq_to_latex(instr)
                    if tex:
                        out.append(math_html(tex))
                        plain.append(tex)
                    else:
                        walk(ch)
                elif t == 'bookmarkStart' or t == 'bookmarkEnd' or t == 'proofErr':
                    continue
        walk(p)
        return {'html': ''.join(out), 'plain': ''.join(plain), 'imgs': imgs}

    # ---------- 表格 ----------
    def table(self, tbl):
        rows = []
        for tr in tbl.findall(W + 'tr'):
            cells = []
            for tc in tr.findall(W + 'tc'):
                cells.append(self.blocks(tc))
            rows.append(cells)
        return rows

    # ---------- 块序列 ----------
    def blocks(self, container):
        res = []
        for ch in container:
            t = _local(ch)
            if t == 'p':
                pr = self.para(ch)
                if pr['plain'].strip() or pr['imgs']:
                    res.append({'type': 'p', **pr})
            elif t == 'tbl':
                grid = ch.find(W + 'tblGrid')
                ncol = len(grid.findall(W + 'gridCol')) if grid is not None else 1
                head = ''.join(x.text or '' for x in ch.iter(W + 't'))[:60]
                # 版式表格（单列外框、或平台的「课程基本信息」表）摊平成块序列；
                # 只有真正的多列内容表（如手机说明书）才保留成表格。
                if ncol <= 1 or '课程基本信息' in head:
                    res.extend(self.blocks(ch))
                else:
                    res.append({'type': 'table', 'rows': self.table(ch)})
            elif t in ('sdt', 'sdtContent', 'tr', 'tc', 'body'):
                res.extend(self.blocks(ch))
        return res


def parse(path, media_dir):
    d = Docx(path, media_dir)
    body = d.doc.find(W + 'body')
    blocks = d.blocks(body)
    return blocks


def parse_with_report(path, media_dir):
    """除块序列外，回传公式清单（供构建时人工校对 MTEF 解码是否正确）。"""
    d = Docx(path, media_dir)
    body = d.doc.find(W + 'body')
    return d.blocks(body), {'formulas': d.formulas, 'fixed': d.fixed,
                            'dropped': d.dropped}
