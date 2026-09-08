# -*- coding: utf-8 -*-
"""合并第十章课时产物为 学生总册 / 教师总册 两个 PDF（含封面+课时分隔页）。"""
import os
import fitz

REF = os.environ.get("MB_REF", "/Users/lishaowei/tools/smartedu-grab/out_reflow")
OUT = os.environ.get("MB_OUT", "/Users/lishaowei/tools/smartedu-grab/out_merged")
GREEN_DARK = (0.055, 0.306, 0.2)
GREEN = (0.0, 0.44, 0.125)
W, H = 595.3, 841.9


def make_cover(doc, title, subtitle):
    p = doc.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(0, 0, W, H), color=None, fill=(0.95, 0.97, 0.95))
    p.draw_rect(fitz.Rect(0, 0, W, 8), color=None, fill=GREEN)
    p.insert_textbox(fitz.Rect(50, 250, W - 50, 360), "深圳外国语学校博雅高中",
                     fontsize=20, color=GREEN_DARK, align=1, fontname="china-s")
    p.insert_textbox(fitz.Rect(50, 330, W - 50, 430), "物理 · 必修第三册",
                     fontsize=14, color=(0.3, 0.44, 0.36), align=1, fontname="china-s")
    p.insert_textbox(fitz.Rect(50, 420, W - 50, 520), title,
                     fontsize=28, color=GREEN_DARK, align=1, fontname="china-s")
    p.insert_textbox(fitz.Rect(50, 520, W - 50, 600), subtitle,
                     fontsize=14, color=(0.4, 0.5, 0.44), align=1, fontname="china-s")


def make_section(doc, num, name, parts):
    p = doc.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(0, 0, W, H), color=None, fill=(0.93, 0.965, 0.94))
    p.draw_rect(fitz.Rect(0, H - 8, W, H), color=None, fill=GREEN)
    p.insert_textbox(fitz.Rect(50, 300, W - 50, 400),
                     f"第十章 · 第 {num} 讲", fontsize=16, color=(0.3, 0.5, 0.4),
                     align=1, fontname="china-s")
    p.insert_textbox(fitz.Rect(50, 350, W - 50, 500), name,
                     fontsize=24, color=GREEN_DARK, align=1, fontname="china-s")
    p.insert_textbox(fitz.Rect(50, 470, W - 50, 540),
                     " · ".join(parts), fontsize=14, color=(0.4, 0.5, 0.44),
                     align=1, fontname="china-s")


# (章节顺序, 课时标签, 目录名, [文件名通配前缀])
LESSONS = [
    ("一", "1. 电路中的能量转化", "1.电路中的能量转化", "电路中的能量转化"),
    ("二", "2. 闭合电路的欧姆定律（第一课时）", "2.闭合电路的欧姆定律", "闭合电路的欧姆定律（第一课时）"),
    ("三", "3. 闭合电路的欧姆定律（第二课时）", "2.闭合电路的欧姆定律", "闭合电路的欧姆定律（第二课时）"),
    ("四", "4. 实验：电池电动势和内阻的测量（第一课时）", "3.实验：电池电动势和内阻的测量", "实验：电池电动势和内阻的测量（第一课时）"),
    ("五", "5. 实验：电池电动势和内阻的测量（第二课时）", "3.实验：电池电动势和内阻的测量", "实验：电池电动势和内阻的测量（第二课时）"),
    ("六", "6. 能源与可持续发展", "4.能源与可持续发展", "能源与可持续发展"),
    ("七", "7. 电能 能量守恒定律复习", "5.电能 能量守恒定律复习", "电能 能量守恒定律复习"),
]


def find(folder, prefix, kind):
    folder = os.path.join(REF, folder)
    for fn in os.listdir(folder):
        if fn.startswith(prefix) and fn.endswith(".pdf") and kind in fn:
            return os.path.join(folder, fn)
    return None


def stamp_title(page, text):
    """在页首覆盖一条绿色色条 + 节标题（不新增页）。用白色文字覆盖原页眉。"""
    r = page.rect
    page.draw_rect(fitz.Rect(0, 6, r.width, 40), color=None, fill=GREEN)
    page.insert_textbox(fitz.Rect(14, 10, r.width - 14, 36), text,
                        fontsize=15, color=(1, 1, 1), align=0, fontname="china-s")


def build(out_path, cover_title, cover_sub, use_teacher_ex):
    doc = fitz.open()
    make_cover(doc, cover_title, cover_sub)
    for num, label, folder, prefix in LESSONS:
        if use_teacher_ex:
            task = find(folder, prefix, "_学习任务单_解析") or find(folder, prefix, "_学习任务单_学生")
            ex = find(folder, prefix, "_课后练习_解析")
        else:
            task = find(folder, prefix, "_学习任务单_学生")
            ex = find(folder, prefix, "_课后练习_学生")
        files = []
        if task:
            files.append((task, f"第 {num} 讲　{label}　·　学习任务单"))
        if ex:
            files.append((ex, f"第 {num} 讲　{label}　·　课后练习" + ("（含解析）" if use_teacher_ex else "")))
        for f, band in files:
            sub = fitz.open(f)
            # 在该 PDF 首页叠色条标题（不新增页）
            stamp_title(sub[0], band)
            doc.insert_pdf(sub)
            sub.close()
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    print("saved:", out_path, "%.1f MB" % (os.path.getsize(out_path) / 1e6))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    build(os.path.join(OUT, "第十二章_学生用作业本.pdf"),
          "第十二章 电能 能量守恒定律 · 作业本",
          "学生用 · 学习任务单 + 课后练习（含作答区，无答案）",
          use_teacher_ex=False)
    build(os.path.join(OUT, "第十二章_解析版.pdf"),
          "第十二章 电能 能量守恒定律 · 解析版",
          "学习任务单 + 课后练习（含逐题解析与学习任务解析）",
          use_teacher_ex=True)
