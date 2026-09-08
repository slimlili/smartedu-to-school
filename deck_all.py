# -*- coding: utf-8 -*-
"""批量生成第十章每课时 16:9 翻页 HTML 讲义。

配对逻辑：一个课时 = 同名 学习任务单+课后练习（可能带 第一课时/第二课时 后缀）。
输出到 out_deck/<课时>.html
"""
import os, re, shutil
from deck_one import build_one

import sys
OUT_BOOK = "/Users/lishaowei/tools/smartedu-grab/out"
CH_DIR = sys.argv[1] if len(sys.argv)>1 else "第十章 静电场中的能量"
OUT_DECK = sys.argv[2] if len(sys.argv)>2 else "/Users/lishaowei/tools/smartedu-grab/out_deck"


def period_of(fn):
    m = re.search(r"（([^）]*课时)）", fn)
    return m.group(1) if m else ""


def main():
    if os.path.exists(OUT_DECK):
        shutil.rmtree(OUT_DECK)
    os.makedirs(OUT_DECK)
    ch10 = os.path.join(OUT_BOOK, CH_DIR)
    n = 0
    for d in sorted(os.listdir(ch10)):
        folder = os.path.join(ch10, d)
        if not os.path.isdir(folder):
            continue
        lesson = d.split(".", 1)[-1]
        # 找出该目录所有 学习任务单/课后练习，按课时后缀分组
        groups = {}
        for fn in os.listdir(folder):
            if not fn.endswith(".pdf"):
                continue
            if "学习任务单" not in fn and "课后练习" not in fn:
                continue
            per = period_of(fn)
            g = groups.setdefault(per, {"dir": folder, "task": None, "ex": None})
            if "学习任务单" in fn:
                g["task"] = fn
            if "课后练习" in fn:
                g["ex"] = fn
        for per, g in sorted(groups.items(), key=lambda kv: "0" if not kv[0] else kv[0]):
            if not (g["task"] or g["ex"]):
                continue
            suffix = f"（{per}）" if per else ""
            label = f"{lesson}{suffix}"
            out = os.path.join(OUT_DECK, f"{label}.html")
            try:
                build_one(g["dir"], out, task_file=g["task"], ex_file=g["ex"])
                print("  ✓", label)
                n += 1
            except Exception as e:
                print("  ✗", label, "->", e)
    print(f"\n共生成 {n} 个 HTML 讲义 -> {OUT_DECK}")


if __name__ == "__main__":
    main()
