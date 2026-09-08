# -*- coding: utf-8 -*-
"""批量下载微课视频(mp4, 360p 低清省时省空间)。

用法: python batch_video.py <courses_dir> <output_dir> [清晰度flag,默认href-360p-m3u8]
对每 course json 每个 micro_lesson_video bundle 下载对应清晰度 → <output_dir>/<课时名>.mp4
已存在则跳过（可续跑）。分片逐片缓存(out_dir/.parts/<课时>)，合成后清理。
"""
import json, os, sys, glob, subprocess, shutil, re
import transcript  # 复用 fetch/aes/get_key
import sget


def pick_url(course, flag):
    rel = course.get("relations", {}).get("national_course_resource") or []
    for r in rel:
        if r.get("resource_type_code") != "micro_lesson_video":
            continue
        title = (r.get("global_title") or {}).get("zh-CN", "")
        url = None
        for it in r.get("ti_items") or []:
            if it.get("ti_file_flag") == flag:
                url = it["ti_storages"][0]
                break
        if url:
            yield title, url


def download_video(m3u8_url, mp4_path, parts_dir):
    play = transcript.fetch(m3u8_url).decode()
    base = m3u8_url.rsplit("/", 1)[0] + "/"
    key_url, segs = None, []
    for line in play.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-KEY"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                key_url = m.group(1)
        elif line and not line.startswith("#"):
            segs.append(line)
    os.makedirs(parts_dir, exist_ok=True)
    print(f"  分片 {len(segs)}，下载解密（可续传）…", flush=True)
    key = transcript.get_key(key_url) if key_url else b"\x00" * 16
    for i, s in enumerate(segs):
        part = os.path.join(parts_dir, f"{i:05d}.ts")
        if os.path.exists(part) and os.path.getsize(part) > 1000:
            continue
        raw = transcript._fetch_retry(base + s)
        data = transcript.aes_cbc(raw, key, b"\x00" * 16) if key_url else raw
        with open(part, "wb") as f:
            f.write(data)
        if i % 30 == 0:
            print(f"    {i}/{len(segs)}", flush=True)
    # 合成 mp4（concat demuxer + copy）
    listf = mp4_path + ".list"
    with open(listf, "w") as f:
        for i in range(len(segs)):
            f.write(f"file '{os.path.abspath(os.path.join(parts_dir, f'{i:05d}.ts'))}'\n")
    print("  合成 mp4…", flush=True)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", listf, "-c", "copy", mp4_path], capture_output=True)
    os.remove(listf)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 合成失败: " + r.stderr.decode()[-300:])
    return mp4_path


def main():
    courses_dir, out_dir = sys.argv[1], sys.argv[2]
    flag = sys.argv[3] if len(sys.argv) > 3 else "href-360p-m3u8"
    os.makedirs(out_dir, exist_ok=True)
    jobs = []
    for cf in sorted(glob.glob(os.path.join(courses_dir, "*.json"))):
        course = json.load(open(cf, encoding="utf-8"))
        jobs.extend(pick_url(course, flag))
    print(f"共 {len(jobs)} 个视频（{flag}）")
    done = 0
    for title, url in jobs:
        fname = title.replace("/", "_").replace("（", "(").replace("）", ")").replace(" ", "")
        mp4 = os.path.join(out_dir, fname + ".mp4")
        parts = os.path.join(out_dir, ".parts", fname)
        if os.path.exists(mp4) and os.path.getsize(mp4) > 1e5:
            print("跳过(已存在):", title); done += 1; continue
        print(f"\n>>> {title}  <- {url[:80]}…")
        try:
            download_video(url, mp4, parts)
            shutil.rmtree(parts, ignore_errors=True)
            print(f"  ✓ {mp4}  {os.path.getsize(mp4)/1e6:.0f}MB", flush=True)
            done += 1
        except Exception as e:
            print("  !! 失败:", e)
    print(f"\n完成 {done}/{len(jobs)} -> {out_dir}")


if __name__ == "__main__":
    main()
