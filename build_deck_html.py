# -*- coding: utf-8 -*-
"""16:9 翻页 HTML 讲义（单课时，任务单+练习合一，解析点击显示/隐藏）。

slide 类型：
  cover / goals / pretask / task(学习任务N) / exdiv / exq(带解析切换)
"""
import html, re

esc = lambda s: html.escape(s or "", quote=False)

_SENT_END = re.compile(r'[。！？!?；;]$')
_NEW_LINE = re.compile(r'^(【|目标[一二三四五]|问题\d|第[一二三四五六七八九十\d]+[、.]|'
                       r'[（(][一二三四五六七八九十\d]+[)）]|[一二三四五六七八九十\d]+[、.]|'
                       r'想一想|做一做|试一试|①|②|③|④)')


_OPT_LINE_DK = re.compile(r'^\s*([A-DＡ-Ｄ])\s*[.、．]')


def flow(items, is_question=False):
    """items -> (html_blocks, figures)。html 按自然段 <p>，图单独列出。
    is_question=True 时识别 A./B. 选项行，单独成选项块。"""
    if is_question:
        from render_ws import _split_stem_options, _opts_html
        stem, opts, figs, _flow = _split_stem_options(items)
        blocks = []
        sbuf = []
        for (txt, plain) in stem:
            if sbuf and sbuf[-1] and plain:
                lc, fc = (sbuf[-1][-1] if isinstance(sbuf[-1], str) else ""), plain[0]
                if lc.isascii() and lc.isalnum() and fc.isascii() and fc.isalnum():
                    sbuf.append(" ")
            sbuf.append(txt)
        if sbuf:
            blocks.append("".join(sbuf))
        if opts:
            blocks.append(_opts_html(opts))
        return blocks, figs
    html_blocks = []
    figs = []
    buf = []
    buf_plain = []

    def flush():
        if buf:
            html_blocks.append("".join(buf))
            del buf[:]
            del buf_plain[:]

    for it in items:
        if "fig" in it:
            flush()
            figs.append(it["fig"])
            continue
        for p in it.get("paras", []):
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = p.get("plain", "")
            if not plain.strip():
                continue
            if buf_plain:
                prev_last = (buf_plain[-1] or "").strip()[-1:] if (buf_plain[-1] or "").strip() else ""
                if _NEW_LINE.match(plain.strip()) or (_SENT_END.search(prev_last) and plain.strip()[0] not in "，。；、）)"):
                    flush()
            if buf_plain and buf_plain[-1] and plain:
                lc, fc = buf_plain[-1][-1], plain[0]
                if lc.isascii() and lc.isalnum() and fc.isascii() and fc.isalnum():
                    buf.append(" ")
            buf.append(txt)
            buf_plain.append(plain)
    flush()
    return html_blocks, figs


def answer_flow(items):
    """答案 items -> html 字符串（散文合并 + 独立公式分行）。"""
    out = []
    prose = []
    def flush():
        if prose:
            joined = "".join(prose)
            joined = re.sub(r'^\d+\s*[.、．]\s*', "", joined)
            out.append(f"<p>{joined}</p>")
            del prose[:]
    for it in items:
        if "fig" in it:
            flush()
            out.append(f'<div class="afig"><img src="{it["fig"]}"></div>')
            continue
        for p in it.get("paras", []):
            txt = p.get("html") or esc(p.get("plain", ""))
            plain = re.sub(r'<[^>]+>', "", p.get("plain", ""))
            # 公式行
            if re.match(r'^[A-Za-z0-9Wφ𝑈E|]+\s*[=＝]', plain.strip()) and len(plain.strip()) < 90:
                flush()
                eq = re.sub(r'^\d+\s*[.、．]\s*', "", txt)
                out.append(f'<p class="eq">{eq}</p>')
            else:
                prose.append(txt)
    flush()
    return "".join(out)


SCHOOL = "深圳外国语学校博雅高中 · 物理"


def build_slides(task_sections, ex_questions, lesson_title, period_label, book=None,
                 task_key=None):
    """组装幻灯片 HTML。ex_questions: list of {no, q_section, ans_items_or_None}"""
    slides = []
    # 封面
    slides.append(f"""<section class="slide cover">
      <div class="cv-school">{SCHOOL}</div>
      <div class="cv-book">{esc(book or "必修第三册 · 第十章 静电场中的能量")}</div>
      <div class="cv-title">{esc(lesson_title)}</div>
      <div class="cv-sub">{esc(period_label)}</div>
      <div class="cv-hint">→ 方向键/空格翻页 · 讲解要点点击展开</div>
    </section>""")

    def text_slide(kind, head, items, crumb=""):
        blocks, figs = flow(items)
        body = ""
        for blk in blocks:
            body += f"<p>{blk}</p>"
        for f in figs:
            body += f'<div class="fig"><img src="{f}"></div>'
        cls = {"goals": "goalcard", "pretask": "goalcard"}.get(kind, "plaincard")
        slides.append(f"""<section class="slide"><div class="s-head"><span class="crumb">{crumb or head}</span><span class="s-title">{head}</span></div><div class="s-body {cls}">{body}</div></section>""")

    # 学习目标
    for s in task_sections:
        if s["kind"] == "h" and s.get("title", "").strip() == "学习目标":
            text_slide("goals", "学习目标", s["items"], "本课目标")
    # 课前任务
    for s in task_sections:
        if s["kind"] == "h" and "课前" in (s.get("title", "") or ""):
            text_slide("pretask", s["title"].strip(), s["items"], "课前任务")
    # 课上学习任务
    for s in task_sections:
        if s["kind"] == "task":
            title = s["title"]
            blocks, figs = flow(s["items"])
            body = ""
            for blk in blocks:
                body += f"<p>{blk}</p>"
            for f in figs:
                body += f'<div class="fig"><img src="{f}"></div>'
            # 任务解析（可展开）
            ans_html = ""
            try:
                from task_answers import pick_task_answer
                task_body = " ".join(p.get("plain", "")
                                     for it in s["items"] for p in it.get("paras", []))
                raw = pick_task_answer(task_key or period_label or lesson_title, title, task_body)
                if raw:
                    if "<" in raw:
                        ans_html = raw
                    else:
                        ans_html = esc(raw).replace("\n", "<br>")
            except Exception:
                pass
            toggle = ""
            if ans_html:
                toggle = ('<button class="toggle" type="button">💡 显示解析</button>'
                          + '<div class="ansbox">' + ans_html + '</div>')
            crumb = title.strip("【】")
            slides.append(f"""<section class="slide"><div class="s-head"><span class="crumb">{esc(crumb)}</span><span class="s-title">{esc(title)}</span></div>
          <div class="s-body">{body}{toggle}</div></section>""")
        elif s["kind"] == "h" and "课上" in (s.get("title", "") or ""):
            pass  # 只作分隔
    # 课后练习 分隔 + 每题
    slides.append("""<section class="slide divider"><div class="dv">课后练习</div><div class="dv2">点击题目下方按钮查看解析</div></section>""")
    for q in ex_questions:
        s = q["q_section"]
        blocks, figs = flow(s["items"], is_question=True)
        body = ""
        for blk in blocks:
            body += f"<p>{blk}</p>"
        for f in figs:
            body += f'<div class="fig"><img src="{f}"></div>'
        ans_html = ""
        if q["ans_items"] is not None:
            ans_html = answer_flow(q["ans_items"])
        elif q.get("note"):
            ans_html = f'<p class="nonset">{esc(q["note"])}</p>'
        if ans_html:
            ans_div = ('<button class="toggle" type="button">💡 显示解析</button>'
                       + '<div class="ansbox">' + ans_html + '</div>')
        else:
            ans_div = ""
        slides.append(f"""<section class="slide"><div class="s-head"><span class="crumb">课后练习 {q.get("qno", q["no"])}</span><span class="s-title">{q.get('qtitle','')}</span></div>
      <div class="s-body">{body}{ans_div}</div></section>""")
    return slides


CSS = """
:root{--green:#007020;--green-dark:#0E4E33;--green-deep:#00501f;--green-light:#E9F3EC;--line:#B0D0C0;--gold:#C9A227}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#26302b;font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif}
#stage{position:fixed;left:50%;top:50%;width:1280px;height:720px;transform:translate(-50%,-50%) scale(var(--s,1));transform-origin:center;background:#fff;border-radius:10px;box-shadow:0 14px 60px rgba(0,0,0,.5);overflow:hidden}
.slide{position:absolute;inset:0;padding:34px 56px;display:none;flex-direction:column}
.slide.on{display:flex}
.s-head{display:flex;align-items:baseline;gap:14px;border-bottom:3px solid var(--green);padding-bottom:8px;margin-bottom:12px;flex:0 0 auto}
.crumb{background:var(--green);color:#fff;font-weight:700;font-size:18px;padding:2px 14px;border-radius:12px;white-space:nowrap}
.s-title{font-size:34px;font-weight:800;color:var(--green-dark)}
.s-body{flex:1 1 auto;font-size:28px;line-height:1.65;overflow-y:auto;min-height:0}
.s-body p{margin:.28em 0}
.fig{text-align:center;margin:10px 0}
.fig img{max-height:300px;max-width:80%;background:#fff}
.goalcard p,.plaincard p{font-size:28px}
.goalcard{background:linear-gradient(180deg,#f7fbf7,#eef6ef);border:1px solid var(--line);border-radius:14px;padding:18px 24px}
/* 选择题选项 */
.opts{margin:6px 0;display:flex;align-items:baseline}
.opts .opt{display:inline-flex;align-items:baseline;line-height:1.6;font-size:26px;margin:2px 0}
.opts .ol{font-weight:700;color:var(--green);margin-right:4px;flex:0 0 auto}
.opts .oc{flex:0 1 auto}
.opts.justified{justify-content:space-between;flex-wrap:nowrap}
.opts.justified .opt{flex:1 1 0}
.opts.stacked{flex-direction:column;align-items:stretch}
.opts.stacked .opt{width:100%}

/* cover —— 浅色底 */
.slide.cover{background:linear-gradient(145deg,#F4FBF6 0%,#E6F3EA 55%,#D7ECDE 100%);color:var(--green-dark);justify-content:center;align-items:center;text-align:center}
.cv-school{font-size:22px;letter-spacing:3px;color:var(--green-dark);font-weight:700}
.cv-book{font-size:16px;color:#4a705b;margin:6px 0 20px;letter-spacing:2px}
.cv-title{font-size:58px;font-weight:900;letter-spacing:2px;color:var(--green-deep);margin:6px 0;text-shadow:0 1px 0 #fff}
.cv-sub{font-size:25px;color:var(--green-dark);background:rgba(255,255,255,.8);border:1px solid var(--line);border-radius:999px;padding:4px 24px;margin-top:8px}
.cv-hint{position:absolute;bottom:22px;font-size:14px;color:#55705f;opacity:.75}
/* divider */
.slide.divider{justify-content:center;align-items:center;text-align:center;background:linear-gradient(180deg,#fff,#eef6ef)}
.slide.divider .dv{font-size:60px;font-weight:900;color:var(--green-dark)}
.slide.divider .dv2{font-size:18px;color:#55705f;margin-top:6px}
/* toggle answer */
.toggle{margin-top:16px;border:2px solid var(--green);background:#fff;color:var(--green-dark);font-weight:700;border-radius:999px;padding:8px 26px;cursor:pointer;font-size:22px;font-family:inherit}
.s-body.open .toggle{background:var(--green);color:#fff}
.ansbox{display:none;margin-top:12px;background:#f2f8f3;border:1px solid var(--line);border-left:5px solid var(--green);border-radius:10px;padding:12px 22px;font-size:24px;line-height:1.6}
.s-body.open .ansbox{display:block}
.ansbox p{margin:.18em 0}.ansbox p.eq{font-family:"Times New Roman",serif}
.ansbox .afig{text-align:center}.ansbox .afig img{max-height:180px}
.nonset{color:#a67a00}
/* nav */
#prev,#next{position:fixed;top:50%;transform:translateY(-50%);z-index:30;background:rgba(10,20,14,.72);color:#fff;border:0;width:54px;height:54px;border-radius:50%;font-size:26px;cursor:pointer;font-family:inherit}
#prev{left:calc(50% - min(50vw,50vh*1.7778)/2 - 76px)}
#next{right:calc(50% - min(50vw,50vh*1.7778)/2 - 76px)}
#prev:disabled,#next:disabled{opacity:.25}
#pager{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);color:#d8e2db;background:rgba(0,0,0,.45);padding:4px 18px;border-radius:999px;font-size:14px}
kbd{border:1px solid rgba(255,255,255,.4);border-radius:4px;padding:0 6px;font-family:inherit}
"""

JS = r"""
function fit(){var s=Math.min(innerWidth/1280,innerHeight/720);document.getElementById('stage').style.setProperty('--s',(s*.98).toFixed(4));}
addEventListener('resize',fit);
var S=[].slice.call(document.querySelectorAll('.slide')),i=0;
function go(n){i=Math.max(0,Math.min(S.length-1,n));S.forEach(function(s,k){s.classList.toggle('on',k===i)});
document.getElementById('prev').disabled=i===0;document.getElementById('next').disabled=i===S.length-1;
document.getElementById('pg').textContent=(i+1)+' / '+S.length;
document.getElementById('stage').scrollTop=0;}
document.getElementById('prev').onclick=function(){go(i-1)};
document.getElementById('next').onclick=function(){go(i+1)};
addEventListener('keydown',function(e){
 if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();go(i+1);}
 else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();go(i-1);}
 else if(e.key==='Home')go(0); else if(e.key==='End')go(S.length-1);});
document.addEventListener('click',function(e){
  var t=e.target.closest('.toggle'); if(!t)return;
  var body=t.parentNode; var open=body.classList.toggle('open');
  t.textContent = open ? '🙈 隐藏解析' : '💡 显示解析';
});
fit();go(0);
"""


def assemble(lesson_title, slides_html):
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(lesson_title)} · 课堂讲义</title>
<style>{CSS}</style></head><body>
<div id="stage">{slides_html}</div>
<button id="prev" disabled>‹</button><button id="next">›</button>
<div id="pager"><span id="pg"></span></div>
<script>{JS}</script></body></html>"""
