# -*- coding: utf-8 -*-
"""为单个课时生成 16:9 翻页 HTML 讲义。用法: python deck_one.py <课时目录> <输出html>"""
import os, re, sys
import fitz
import retypeset
from build_deck_html import build_slides, assemble


def build_one(folder, out_html, task_file=None, ex_file=None):
    files = sorted(os.listdir(folder))
    task_pdf = task_file or next((f for f in files if f.endswith(".pdf") and "学习任务单" in f), None)
    ex_pdf = ex_file or next((f for f in files if f.endswith(".pdf") and "课后练习" in f), None)
    if not task_pdf and not ex_pdf:
        return None
    lesson_dir = os.path.basename(folder)
    lesson = lesson_dir.split(".", 1)[-1]
    # 课题 + 课时
    period = ""
    m = re.search(r"（([^）]*课时)）", (task_pdf or ex_pdf) or "")
    period = m.group(1) if m else ""
    lesson_title = lesson
    label = lesson if not period else f"{lesson}（{period}）"
    task_sections = []
    ex_questions = []
    if task_pdf:
        doc = fitz.open(os.path.join(folder, task_pdf))
        task_sections = retypeset.parse_lesson_task(doc)
        doc.close()
    if ex_pdf:
        doc = fitz.open(os.path.join(folder, ex_pdf))
        ex_secs = retypeset.parse_exercise(doc)
        ans = retypeset.split_answer_by_no(ex_secs)
        for s in ex_secs:
            if s["kind"] == "q":
                qtitle = ""
                ex_questions.append({"no": s.get("no"), "q_section": s,
                                     "ans_items": ans.get(s.get("no")),
                                     "qtitle": qtitle})
        doc.close()
    slides = build_slides(task_sections, ex_questions, lesson_title, label)
    html = assemble(label, "\n".join(slides))
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return out_html


if __name__ == "__main__":
    folder = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/deck.html"
    r = build_one(folder, out)
    print("written", r, "| slides:", 0 if not r else r)
