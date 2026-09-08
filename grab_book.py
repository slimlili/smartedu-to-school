# -*- coding: utf-8 -*-
"""抓取 人教版 必修第三册 全部章节（第九~十三 + 课题研究）的
课件 / 教学设计 / 学习任务单 / 课后练习 到本地 out/<章>/<节>/。

数据来源：
  - work/tree.json      教材章节树（章 → 节的顺序与 node_id）
  - work/part_100.json  该册全部 national_lesson 课程清单
  - resources/details/{id}.json  每门课程的资源明细
"""
import json, os, re, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
TOK = json.load(open(os.path.join(HERE, "secret/nd_auth.json"), encoding="utf-8"))
AUTH = 'MAC id="%s",nonce="0",mac="0"' % TOK["access_token"]
HDRS = {"x-nd-auth": AUTH, "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/", "User-Agent": "Mozilla/5.0"}
OUT = os.path.join(HERE, "out")

RES_TYPES = {"coursewares": "课件", "lesson_plandesign": "教学设计",
             "learning_task": "学习任务单", "after_class_exercise": "课后练习"}


def fetch(url, timeout=90, retries=3):
    last = None
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.2 * (a + 1))
    raise last


def fetch_json(url):
    return json.loads(fetch(url, timeout=40).decode("utf-8"))


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:80] or "unnamed"


def pick_file(items):
    def flag(v):
        for it in items:
            if it.get("ti_file_flag") == v:
                return it
        return None

    def first_storage(it):
        for s in it.get("ti_storages") or []:
            if isinstance(s, str) and s.startswith("http"):
                return s
        return None

    it = flag("href") or flag("source") or flag("pdf")
    if it is None:
        for x in items:
            f = x.get("ti_file_flag") or ""
            fmt = x.get("ti_format") or ""
            if fmt in ("folder", "superboard") or str(f).startswith(("thumbnail", "ai_")) or f in ("image", "preview", "remarks", "superboard"):
                continue
            it = x
            break
    if it is None:
        return None, None
    url = first_storage(it)
    if not url:
        return None, None
    fmt = (it.get("ti_format") or "").lower()
    ext = fmt if fmt in ("pdf", "pptx", "docx", "doc", "ppt") else \
        (url.split("?")[0].rsplit(".", 1)[-1] if "." in url.split("?")[0] else "bin")
    return url, ext


def course_endpoint(course_id, rtype):
    if rtype == "national_lesson":
        return f"https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/resources/details/{course_id}.json"
    if rtype == "elite_lesson":
        return f"https://s-file-1.ykt.cbern.com.cn/competitive/elite_lesson/resources/{course_id}.json"
    return None


def main():
    tree = json.load(open(os.path.join(HERE, "work/tree.json"), encoding="utf-8"))
    parts = json.load(open(os.path.join(HERE, "work/part_100.json"), encoding="utf-8"))

    # ---- 章节结构：章(id,标题, 节列表[(序号,节名,nodeid)]) ----
    chapters = []
    node_to_chap = {}     # nodeid -> (章序号idx, 节序号, 节名)
    for ci, ch in enumerate(tree):
        title = (ch.get("title") or "").strip()
        if not title:
            continue
        kids = []
        for j, kid in enumerate((ch.get("child_nodes") or [])):
            kt = (kid.get("title") or "").strip()
            kid_id = kid.get("id")
            if not kt or not kid_id:
                continue
            kids.append((j + 1, kt, kid_id))
            node_to_chap[kid_id] = (ci, j + 1, kt)
        chapters.append({"id": ch.get("id"), "title": title, "lessons": kids})

    chap_by_id = {c["id"]: c for c in chapters}

    # ---- 归集要下载的课程 ----
    jobs = []  # (course_id, rtype, chapter_idx, lesson_order, lesson_name, raw_title)
    seen = set()
    for it in parts:
        rtype = it.get("resource_type_code")
        if rtype not in ("national_lesson", "elite_lesson"):
            continue
        raw = it.get("title") or (it.get("global_title") or {}).get("zh-CN") or ""
        cid = it.get("id")
        if not cid or cid in seen:
            continue
        paths = it.get("chapter_paths") or []
        # 找第一条 章/节 层级路径（首段是已知章）
        chosen = None
        for p in paths:
            seg = p.split("/")
            if len(seg) >= 1 and seg[0] in chap_by_id:
                chosen = (chap_by_id[seg[0]], seg[1] if len(seg) > 1 else None)
                break
        if not chosen:
            continue
        chapter, nodeid = chosen
        seen.add(cid)
        if nodeid and nodeid in node_to_chap:
            ci, order, lname = node_to_chap[nodeid]
            jobs.append({"cid": cid, "rtype": rtype, "chapter": chapter,
                         "ci": ci, "order": order, "lname": lname, "raw": raw})
        else:
            # 复习/其他挂在章节点直接下
            jobs.append({"cid": cid, "rtype": rtype, "chapter": chapter,
                         "ci": None, "order": None, "lname": None, "raw": raw})

    print(f"整册待下载课程: {len(jobs)}")
    for j in sorted(jobs, key=lambda x: (x["ci"] or 99, x["order"] or 99)):
        print("  ", j["chapter"]["title"], "/", j["lname"] or j["raw"], "/", j["raw"])

    # 章目录索引（在章内找到某节该放哪）
    os.makedirs(OUT, exist_ok=True)

    # 预计算每门课的存放目录
    def folder_for(j):
        chapter = j["chapter"]
        chdir = sanitize(chapter["title"])
        if j["rtype"] == "elite_lesson":
            return os.path.join(OUT, chdir, "课题研究"), chapter["title"], "课题研究"
        raw = j["raw"]
        if "必修第三册" in raw and "复习" in raw:
            return os.path.join(OUT, "0.必修第三册复习"), "整册", "复习"
        if "复习" in raw:
            n = len(j["chapter"]["lessons"]) + 1
            return os.path.join(OUT, chdir, f"{n}.{sanitize(raw)}"), chapter["title"], raw
        # 普通节
        return (os.path.join(OUT, chdir, f"{j['order']}.{sanitize(j['lname'])}"),
                chapter["title"], j["lname"])

    dl = []  # (folder, res, url, ext)
    for j in jobs:
        folder, ch_title, lesson_name = folder_for(j)
        try:
            course = fetch_json(course_endpoint(j["cid"], j["rtype"]))
        except Exception as e:
            print("  !! course meta fail", j["cid"], e)
            continue
        rel = (course.get("relations") or {}).get("national_course_resource") or []
        bundles = []
        for r in rel:
            rt = r.get("resource_type_code")
            if rt not in RES_TYPES:
                continue
            period = (r.get("global_title") or {}).get("zh-CN") or lesson_name
            url, ext = pick_file(r.get("ti_items") or [])
            if url:
                bundles.append((rt, period, url, ext))
        periods = {b[1] for b in bundles}
        multi = len(periods) > 1
        for rt, period, url, ext in bundles:
            if multi and period not in (lesson_name, j["raw"]):
                fname = f"{sanitize(period)}-{RES_TYPES[rt]}.{ext}"
            else:
                fname = f"{RES_TYPES[rt]}.{ext}"
            dl.append({"folder": folder, "ch": ch_title, "lesson": lesson_name,
                       "course_id": j["cid"], "type": rt, "type_name": RES_TYPES[rt],
                       "period": period, "url": url, "ext": ext, "file": fname})

    # ---- 去重并下载 ----
    seen_f = set()
    uniq = []
    for d in dl:
        key = (d["folder"], d["file"])
        if key in seen_f:
            continue
        seen_f.add(key)
        uniq.append(d)
    print(f"\n待下载文件: {len(uniq)}")

    results = {}
    def work(d):
        os.makedirs(d["folder"], exist_ok=True)
        fpath = os.path.join(d["folder"], d["file"])
        if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            return d, "exists"
        try:
            data = fetch(d["url"])
            if len(data) < 2000:
                return d, "small:" + str(len(data))
            open(fpath, "wb").write(data)
            return d, "ok"
        except Exception as e:
            return d, "err:" + str(e)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(work, d): d for d in uniq}
        for f in as_completed(futs):
            d, st = f.result()
            results[(d["folder"], d["file"])] = st
            print(f"  [{st}] {os.path.relpath(os.path.join(d['folder'], d['file']), OUT)}")

    # ---- 写 catalog.json ----
    cat_chapters = []
    for ci, ch in enumerate(chapters):
        entries = []
        # 各节资源
        for order, lname, nodeid in ch["lessons"]:
            folder = os.path.join(OUT, sanitize(ch["title"]), f"{order}.{sanitize(lname)}")
            ress = [d for d in uniq if d["folder"] == folder]
            if ress:
                entries.append({"order": order, "name": lname,
                                "resources": [{k: d[k] for k in ("type_name", "file", "period", "url")}
                                              for d in ress]})
        # 复习/课题等
        for d in uniq:
            if d["ch"] == ch["title"] and not any(e["name"] == d["lesson"] for e in entries):
                if d["lesson"] not in [e["name"] for e in entries]:
                    entries.append({"order": 99, "name": d["lesson"],
                                    "resources": [{k: d[k] for k in ("type_name", "file", "period", "url")} for d in [d]]})
        cat_chapters.append({"title": ch["title"], "lessons": entries})

    # 整册复习单独列出
    whole_rev = [d for d in uniq if os.path.dirname(d["folder"]) == OUT]
    catalog = {"book": "高中物理人教版必修第三册", "chapters": cat_chapters,
               "whole_book_review": [
                   {"name": os.path.basename(os.path.dirname(d["folder"])),
                    "resources": [{k: d[k] for k in ("type_name", "file", "period", "url")} for d in whole_rev]}]
               if whole_rev else []}
    with open(os.path.join(OUT, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print("\nSaved out/catalog.json")
    # 统计
    ok = sum(1 for v in results.values() if v == "ok")
    print(f"ok={ok}  exists={sum(1 for v in results.values() if v=='exists')}  fail={sum(1 for v in results.values() if v!='ok' and v!='exists')}")


if __name__ == "__main__":
    main()
