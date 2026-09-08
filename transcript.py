# -*- coding: utf-8 -*-
"""微课视频 → 上课逐字稿（试点）

流程：
  1) 从课时 course JSON 的 relations 里取某「微课视频」bundle 的 720p m3u8
  2) 下载 + AES 解密 TS 分片（复用智慧平台协议）
  3) ffmpeg 只提音频(16k mono wav)
  4) faster-whisper 语音识别 → .srt(带时间戳) + .txt(纯文本逐字稿)

用法:
  python transcript.py <course_json> <课时关键词,如 第一课时> <输出名>
  例: python transcript.py work/lesson_101.json "第一课时" out_scripts/10.1电势能和电势_第一课时
"""
import base64, hashlib, json, os, re, subprocess, sys, urllib.request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import sget

HDRS = sget.HDRS


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def aes_cbc(data, key, iv):
    c = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
    return c.update(data) + c.finalize()


def aes_ecb(data, key):
    c = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend()).decryptor()
    return c.update(data) + c.finalize()


def get_key(key_url):
    key_id = key_url.rstrip("/").rsplit("/", 1)[-1]
    nonce = json.loads(fetch(key_url + "/signs").decode())["nonce"]
    sign = hashlib.md5((nonce + key_id).encode()).hexdigest()[:16]
    body = json.loads(fetch(f"{key_url}?nonce={nonce}&sign={sign}").decode())
    return aes_ecb(base64.b64decode(body["key"]), sign.encode())[:16]


def pick_video_m3u8(course, period_kw):
    """从 course json 里取匹配课时关键词的微课视频 720p m3u8。返回 (m3u8, 标题)。"""
    rel = (course.get("relations") or {}).get("national_course_resource") or []
    for r in rel:
        if r.get("resource_type_code") != "micro_lesson_video":
            continue
        title = (r.get("global_title") or {}).get("zh-CN", "")
        if period_kw and period_kw not in title:
            continue
        for it in (r.get("ti_items") or []):
            if it.get("ti_file_flag") == "href-720p-m3u8":
                return it["ti_storages"][0], title
            # fallback any m3u8
        for it in (r.get("ti_items") or []):
            if it.get("ti_format") == "m3u8":
                return it["ti_storages"][0], title
    return None, None


def _fetch_retry(url, retries=4, timeout=45):
    import time
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (a + 1))
    raise last


def download_audio(m3u8_url, wav_path, seg_dir=None):
    """下载解密 TS，ffmpeg 提取 16k mono wav。逐分片下载存临时文件，支持重试/续传。"""
    play = fetch(m3u8_url).decode()
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
    if seg_dir is None:
        seg_dir = wav_path + ".parts"
    os.makedirs(seg_dir, exist_ok=True)
    print(f"  分片 {len(segs)} 个（{seg_dir}），逐片下载解密（可续传）…")
    key = get_key(key_url) if key_url else b"\x00" * 16
    ok = 0
    for i, s in enumerate(segs):
        part = os.path.join(seg_dir, f"{i:05d}.ts")
        if os.path.exists(part) and os.path.getsize(part) > 1000:
            ok += 1
            continue
        raw = _fetch_retry(base + s)
        data = aes_cbc(raw, key, b"\x00" * 16) if key_url else raw
        with open(part, "wb") as f:
            f.write(data)
        ok += 1
        if i % 25 == 0:
            print(f"    {i}/{len(segs)}", flush=True)
    # 拼接
    print("  拼接 + 提取音频 wav…")
    listf = wav_path + ".list"
    with open(listf, "w") as f:
        for i in range(len(segs)):
            f.write(f"file '{os.path.abspath(os.path.join(seg_dir, f'{i:05d}.ts'))}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", listf, "-vn", "-ac", "1", "-ar", "16000", wav_path], check=True)
    os.remove(listf)
    return wav_path


def _simplify(text):
    """繁体→简体（识别常输出繁体）。"""
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def recognize(wav_path, out_base, model_size="small", lang="zh"):
    """faster-whisper 识别 → .srt + .txt（简体）。"""
    from faster_whisper import WhisperModel
    print(f"  加载模型 {model_size} (首次会下载)…")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print("  转写中…（按视频时长，可能数分钟）")
    # initial_prompt 引导简体中文，减少繁体倾向
    segments, info = model.transcribe(wav_path, language=lang, vad_filter=True,
                                      beam_size=5,
                                      initial_prompt="以下是简体中文普通话的课堂逐字稿。")
    lines_txt, lines_srt = [], []
    for i, seg in enumerate(segments):
        t = _simplify(seg.text.strip())
        if not t:
            continue
        lines_txt.append(t)
        lines_srt.append(f"{i+1}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{t}\n")
    base_txt = out_base + ".txt"
    with open(base_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_txt) + "\n")
    base_srt = out_base + ".srt"
    with open(base_srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_srt))
    print(f"  完成: {base_txt} / {base_srt}")
    return base_txt, base_srt


def _ts(sec):
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    course_json, period, out_base = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(os.path.dirname(out_base) or ".", exist_ok=True)
    course = json.load(open(course_json, encoding="utf-8"))
    m3u8, title = pick_video_m3u8(course, period)
    if not m3u8:
        print("未找到匹配的微课视频"); sys.exit(1)
    print("视频:", title)
    print("m3u8:", m3u8[:80], "…")
    wav = out_base + ".wav"
    # 清理旧的半成品整段 ts（旧逻辑产物）
    for stale in (wav + ".ts",):
        if os.path.exists(stale):
            os.remove(stale)
    download_audio(m3u8, wav, seg_dir=out_base + ".parts")
    try:
        recognize(wav, out_base)
    finally:
        os.remove(wav)
        import shutil
        shutil.rmtree(out_base + ".parts", ignore_errors=True)


if __name__ == "__main__":
    main()
