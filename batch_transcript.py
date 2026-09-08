# -*- coding: utf-8 -*-
"""批量微课视频 → 逐字稿。按章归档到资源包目录。

用法: python batch_transcript.py <courses_dir> <output_root> <章名>
例:   python batch_transcript.py work/courses10 ~/Downloads/必修三校本资源/逐字稿 第十章

对 courses_dir 里每个 course json 的每个 micro_lesson_video bundle：
  产出 <output_root>/<章名>/<课时名>.txt 与 .srt（已存在则跳过=可续跑）
依赖 transcript 的下载/识别逻辑（视频分片可续传）。
"""
import json, os, sys, glob
import transcript
import sget


def video_bundles(course):
    out = []
    rel = course.get("relations", {}).get("national_course_resource") or []
    for r in rel:
        if r.get("resource_type_code") != "micro_lesson_video":
            continue
        title = (r.get("global_title") or {}).get("zh-CN", "")
        url = None
        for it in r.get("ti_items") or []:
            if it.get("ti_file_flag") == "href-720p-m3u8":
                url = it["ti_storages"][0]
                break
        if url:
            out.append((title, url))
    return out


def main():
    courses_dir, out_root, ch_name = sys.argv[1], sys.argv[2], sys.argv[3]
    out_dir = os.path.join(out_root, ch_name)
    os.makedirs(out_dir, exist_ok=True)
    jobs = []
    for cf in sorted(glob.glob(os.path.join(courses_dir, "*.json"))):
        course = json.load(open(cf, encoding="utf-8"))
        jobs.extend(video_bundles(course))
    print(f"共 {len(jobs)} 个微课视频")
    for title, url in jobs:
        # 课时名做文件名
        fname = title.replace("/", "_").replace("（", "(").replace("）", ")").replace(" ", "")
        base = os.path.join(out_dir, fname)
        if os.path.exists(base + ".txt") and os.path.getsize(base + ".txt") > 200:
            print("跳过(已存在):", title)
            continue
        print(f"\n>>> {title}")
        print("  m3u8:", url[:90], "…")
        wav = base + ".wav"
        try:
            transcript.download_audio(url, wav, seg_dir=base + ".parts")
            try:
                transcript.recognize(wav, base)
            finally:
                for p in (wav, base + ".parts"):
                    import shutil
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    elif os.path.exists(p):
                        os.remove(p)
        except Exception as e:
            print("  !! 失败:", e)
            # 保留 parts 便于续传；wav 清理
            if os.path.exists(wav):
                os.remove(wav)
            continue
    print("\n全部完成")


if __name__ == "__main__":
    main()
