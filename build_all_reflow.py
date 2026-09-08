# -*- coding: utf-8 -*-
"""对某章每课时 学习任务单+课后练习 → 重排 PDF 四件套。

用法: python build_all_reflow.py <章目录名> <输出目录名>
例:   python build_all_reflow.py "第十一章 电路及其应用" reflow_11
产物 <输出目录名>/<课时>/: 学习任务单 学生/教师, 课后练习 学生/教师/答案
"""
import os, re, shutil, sys
import fitz
import render_ws, retypeset

CH_DIR = sys.argv[1] if len(sys.argv) > 1 else "第十章 静电场中的能量"
OUT_REF = sys.argv[2] if len(sys.argv) > 2 else "reflow_10"

OUT_BOOK = "/Users/lishaowei/tools/smartedu-grab/out"
OUT_REF = os.path.join("/Users/lishaowei/tools/smartedu-grab", OUT_REF)
HTML_DIR = "/tmp/ch_html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def html2pdf(html_path, pdf_path):
    import subprocess
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                    f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                    f"file://{html_path}"],
                   capture_output=True)
    return os.path.exists(pdf_path)


def lesson_key(n):
    m = re.match(r"(\d+)\.", n)
    return int(m.group(1)) if m else 99


def build_for_folder(folder, ch_dir):
    base = os.path.basename(folder)
    lesson = base.split(".", 1)[-1]  # "电势能和电势"
    dest = os.path.join(OUT_REF, base)
    os.makedirs(dest, exist_ok=True)
    os.makedirs(HTML_DIR, exist_ok=True)
    made = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".pdf"):
            continue
        kind = None
        for k in ("学习任务单", "课后练习"):
            if k in fn:
                kind = k
                break
        if not kind:
            continue
        src = os.path.join(folder, fn)
        # 课时名（含第X课时）
        period = ""
        m = re.search(r"（([^）]*课时)）", fn)
        period = m.group(1) if m else ""
        full = lesson + (f"（{period}）" if period else "")
        doc = fitz.open(src)
        stem_html = os.path.join(HTML_DIR, f"{full}_{kind}")
        if kind == "学习任务单":
            secs = retypeset.parse_lesson_task(doc)
            title = f"{full} · 学习任务单"
            for mode, suffix in (("student", "_学生"), ("teacher", "_解析")):
                h = render_ws.build_task_sheet(title, secs, mode)
                hp = f"{stem_html}{suffix}.html"
                open(hp, "w", encoding="utf-8").write(h)
                pp = os.path.join(dest, f"{full}_{kind}{suffix}.pdf")
                if html2pdf(hp, pp):
                    made.append(pp)
        else:  # 课后练习
            secs = retypeset.parse_exercise(doc)
            title = f"{full} · 课后练习"
            for mode, suffix in (("student", "_学生"), ("teacher", "_解析"), ("answer", "_答案")):
                h = render_ws.build_page(title, "", secs, mode)
                hp = f"{stem_html}{suffix}.html"
                open(hp, "w", encoding="utf-8").write(h)
                pp = os.path.join(dest, f"{full}_{kind}{suffix}.pdf")
                if html2pdf(hp, pp):
                    made.append(pp)
        doc.close()
    return made


def main():
    if os.path.exists(OUT_REF):
        shutil.rmtree(OUT_REF)
    os.makedirs(OUT_REF, exist_ok=True)
    ch_dir = os.path.join(OUT_BOOK, CH_DIR)
    folders = sorted([os.path.join(ch_dir, n) for n in os.listdir(ch_dir)
                      if os.path.isdir(os.path.join(ch_dir, n))], key=lambda p: lesson_key(os.path.basename(p)))
    total = 0
    for f in folders:
        print("\n== ", os.path.basename(f))
        made = build_for_folder(f, ch_dir)
        for p in made:
            print("   ", os.path.relpath(p, OUT_REF))
        total += len(made)
    print(f"\n共生成 {total} 个 PDF")


if __name__ == "__main__":
    main()
