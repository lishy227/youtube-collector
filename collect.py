#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 主题采集器 v2 — 带筛选

流程: 搜大候选池 -> 硬过滤 -> 排序 -> 取前 N -> 下载

用法:
  python collect.py "steam turbine"            # 默认采 10 条
  python collect.py "燃气轮机" -n 3 --audio-only
  python collect.py "topic" -n 5 --sort date --min-views 1000
  python collect.py "topic" -n 5 --no-filter          # 关掉筛选，取搜索前 N

默认筛选规则:
  时长 60s ~ 3600s        (排除 Shorts 和超长直播回放)
  标题 # 标签 <= 3         (排除 hashtag 堆砌的标题党)
  标题须含至少一个主题词    (排除跑题结果)
  按播放量降序取前 N        (质量代理指标)

布局:
  output/<主题slug>/
      _topic.json                # 参数 + 候选池 + 入选/淘汰明细（含淘汰原因）
      <视频标题>/                 # 用标题命名（截断 60 字，碰撞时补 _videoId）
          media.mp4               # 或 media.m4a (--audio-only)
          media.info.json         # yt-dlp 原始元数据
          meta.json               # 精简元数据（含 id，用于回查）
          description.txt         # 内容介绍
          media.jpg               # 封面

设计要点:
  - 终端与浏览器共用同一出口：都走 SOCKS5 127.0.0.1:1234
  - 必须 socks5h（远端解析 DNS）——本机 DNS 被污染，本地解析会拿到假 IP
  - 不要开 TUN/全局模式：系统级代理会把同机上依赖国内 API 的服务一起卷进隧道，
    导致其请求长时间挂起（表现为“卡住”而不是报错）

换机器 / 部署：见同目录 SETUP.md

环境变量:
  YTC_PROXY    代理地址（默认 socks5h://127.0.0.1:1234）
  YTC_FFMPEG   ffmpeg 路径（默认自动探测：PATH → static-ffmpeg → ./bin）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    from zhconv import convert as _zh_convert
    _HAS_ZHCONV = True
except Exception:
    _HAS_ZHCONV = False


def norm(s: str) -> str:
    """繁->简 + 小写，用于关键词匹配（节点在境外，结果常为繁体）"""
    if not s:
        return ""
    if _HAS_ZHCONV:
        s = _zh_convert(s, "zh-cn")
    return s.lower()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"
ARCHIVE_AUDIO = ROOT / "archive_audio.txt"
ARCHIVE_VIDEO = ROOT / "archive_video.txt"

DEFAULT_PROXY = os.environ.get("YTC_PROXY", "socks5h://127.0.0.1:1234")


def resolve_ffmpeg():
    """按优先级找 ffmpeg，返回它所在目录（换机器不用改代码）：
       1) 环境变量 YTC_FFMPEG
       2) 系统 PATH
       3) static-ffmpeg 包（pip install static-ffmpeg）
       4) 项目下 bin/ 目录
    """
    env = os.environ.get("YTC_FFMPEG")
    if env and Path(env).exists():
        return str(Path(env).parent if Path(env).is_file() else Path(env))
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        found = shutil.which("ffmpeg")
        if found:
            return str(Path(found).parent)
    except Exception:
        pass
    local = ROOT / "bin"
    if (local / "ffmpeg.exe").exists() or (local / "ffmpeg").exists():
        return str(local)
    return None


FFMPEG_DIR = resolve_ffmpeg()

META_FIELDS = [
    "id", "title", "uploader", "uploader_id", "channel", "channel_url",
    "duration", "upload_date", "view_count", "like_count", "comment_count",
    "categories", "tags", "webpage_url", "description",
]

ILLEGAL = r'[\\/:*?"<>|\r\n\t]'
SEP = "\t"

RESERVED = ({"CON", "PRN", "AUX", "NUL"}
            | {f"COM{i}" for i in range(1, 10)}
            | {f"LPT{i}" for i in range(1, 10)})


def safe_dir_name(title: str, vid: str, parent: Path, maxlen: int = 60) -> str:
    """视频标题 -> 安全目录名。截断 maxlen 字；碰撞时补 _videoId。"""
    s = re.sub(r"[\x00-\x1f]", "", title or "")
    s = re.sub(ILLEGAL, "_", s)
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    s = s[:maxlen].strip().strip(".")
    if not s or s.upper() in RESERVED:
        return vid
    cand = s
    if (parent / cand).exists():
        want = parent / cand / "meta.json"
        same = False
        if want.exists():
            try:
                same = json.loads(want.read_text(encoding="utf-8")).get("id") == vid
            except Exception:
                same = False
        if not same:
            cand = f"{s}_{vid}"
    return cand


# ---------------- 工具 ----------------

def slugify(name: str) -> str:
    s = re.sub(ILLEGAL, "_", name)
    s = re.sub(r"\s+", "_", s).strip().strip(".")
    return s[:60] or "topic"


def ytdlp(args, timeout=None):
    cmd = [sys.executable, "-m", "yt_dlp", *args]
    # Windows 下 yt-dlp 默认按控制台编码(GBK)写 stdout，中文会报错；
    # 强制它用 UTF-8，与我们的 utf-8 解码对齐。
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env)
    return p.returncode, p.stdout or "", p.stderr or ""


def to_int(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


# ---------------- 搜索 ----------------

def search_candidates(topic: str, pool: int, proxy: str, cookie_args: list) -> list:
    """搜候选池，返回 [{id,duration,view_count,upload_date,title}]"""
    a = [
        "--proxy", proxy, "--no-warnings", "--ignore-config",
        "--flat-playlist",
        "--print", SEP.join(["%(id)s", "%(duration)s", "%(view_count)s",
                             "%(upload_date)s", "%(title)s"]),
        f"ytsearch{pool}:{topic}",
    ] + cookie_args
    rc, out, err = ytdlp(a, timeout=300)
    rows = []
    for line in out.splitlines():
        parts = line.split(SEP, 4)
        if len(parts) < 5 or not parts[0].strip():
            continue
        rows.append({
            "id": parts[0].strip(),
            "duration": to_int(parts[1]),
            "view_count": to_int(parts[2]),
            "upload_date": parts[3].strip() if parts[3].strip() not in ("NA", "") else None,
            "title": parts[4].strip(),
        })
    if not rows and err:
        print("[!] 搜索失败:")
        print(err.strip()[-600:])
    return rows


# ---------------- 筛选 ----------------

def keyword_filter(rows, topic, args):
    """硬过滤，返回 (kept, dropped[带原因])"""
    tokens = [t for t in re.split(r"[\s,，、/|]+", topic) if len(t) >= 2]
    norm_tokens = [norm(t) for t in tokens]
    kept, dropped = [], []
    for r in rows:
        reasons = []
        d = r["duration"]
        if d is None:
            reasons.append("无时长")
        elif d < args.min_duration:
            reasons.append(f"太短({d}s<{args.min_duration})")
        elif d > args.max_duration:
            reasons.append(f"太长({d}s>{args.max_duration})")
        nh = r["title"].count("#")
        if nh > args.max_hashtags:
            reasons.append(f"标签堆砌({nh}个#)")
        if norm_tokens:
            nt = norm(r["title"])
            if not any(t in nt for t in norm_tokens):
                reasons.append("标题不含主题词")
        if (r["view_count"] or 0) < args.min_views:
            reasons.append(f"播放量低({r['view_count']})")
        if reasons:
            r = dict(r, drop_reason=" / ".join(reasons))
            dropped.append(r)
        else:
            kept.append(r)
    return kept, dropped


def sort_pool(kept: list, order: str) -> list:
    if order == "views":
        kept.sort(key=lambda x: (x["view_count"] or 0), reverse=True)
    elif order == "date":
        kept.sort(key=lambda x: (x["upload_date"] or ""), reverse=True)
    # relevance: 保持搜索原序
    return kept


def select(rows, topic, args):
    """返回 (selected, dropped, note)"""
    note = ""
    kept, dropped = keyword_filter(rows, topic, args)

    # 兜底：全被过滤掉 -> 放宽（去掉标签/播放量限制）
    if not kept and rows:
        relax = argparse.Namespace(**vars(args))
        relax.max_hashtags = 999
        relax.min_views = 0
        kept, dropped = keyword_filter(rows, topic, relax)
        if not kept:
            kept = [r for r in rows
                    if args.min_duration <= (r["duration"] or 0) <= args.max_duration] or rows
            dropped = [dict(r, drop_reason="放宽后仍不达标") for r in rows if r not in kept]
        note = "所有候选都被硬条件过滤，已自动放宽（去掉标签/播放量限制）"
        print(f"[!] {note}")

    kept = sort_pool(kept, args.sort)
    selected = kept[:args.num]
    overflow = kept[args.num:]
    for r in overflow:
        dropped.append(dict(r, drop_reason=f"排在 {args.num} 名之外"))
    return selected, dropped, note


def print_report(selected, dropped):
    print(f"\n{'='*74}")
    print(f"筛选结果: 入选 {len(selected)} 条，淘汰 {len(dropped)} 条")
    print(f"{'-'*74}")
    print(f"{'视频ID':<13}{'时长':>6}{'播放':>10}  标题")
    for r in selected:
        d = r["duration"] or 0
        print(f"  ✓ {r['id']:<11}{d//60:>5}:{d%60:02d}{r['view_count'] or 0:>10}  {r['title'][:44]}")
    for r in dropped:
        d = r["duration"] or 0
        print(f"  ✗ {r['id']:<11}{d//60:>5}:{d%60:02d}{r['view_count'] or 0:>10}  {r['title'][:30]}")
        print(f"      └─ {r['drop_reason']}")
    print(f"{'='*74}")


# ---------------- 下载 ----------------

def base_common(proxy):
    a = ["--proxy", proxy, "--no-warnings", "--ignore-config",
         "--socket-timeout", "20", "--retries", "3", "--fragment-retries", "3",
         "--no-playlist"]
    if FFMPEG_DIR:
        a += ["--ffmpeg-location", str(FFMPEG_DIR)]
    return a


MEDIA_EXTS = {".mp4", ".m4a", ".mkv", ".webm", ".mp3", ".opus", ".aac", ".flac"}

# 强制「H.264 视频 + AAC(m4a) 音频 + mp4 容器」，保证 Windows / 常见播放器能直接打开。
# 逐级降级：完全匹配 -> 只要 avc1 -> 渐进式 mp4 -> 任意 mp4 -> 兜底任意流。
FORMAT_VIDEO = (
    "bv*[vcodec^=avc1][acodec=none]+ba[ext=m4a][acodec^=mp4a]"
    "/bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]"
    "/b[ext=mp4][vcodec^=avc1]"
    "/b[ext=mp4]"
    "/bv*+ba/b"
)
FORMAT_AUDIO = "ba[ext=m4a][acodec^=mp4a]/ba[ext=m4a]/ba"


def media_files(dest_dir: Path) -> list:
    """目录里真正的成品媒体（排除 .part 分片与元数据/封面）"""
    out = []
    for f in dest_dir.iterdir():
        if f.is_file() and f.suffix.lower() in MEDIA_EXTS and not f.name.endswith(".part"):
            out.append(f)
    return out


def _cleanup_parts(dest_dir: Path):
    for f in dest_dir.glob("*.part"):
        try:
            f.unlink()
        except Exception:
            pass


PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s")
DEST_RE = re.compile(r"\[download\]\s+Destination:\s*(.+)$")
SPEED_RE = re.compile(r"\bat\s+([\d.]+\s*[KMGTP]?i?B/s)")
ETA_RE = re.compile(r"\bETA\s+([\d:]+)")
PHASE_BY_EXT = {".mp4": "视频", ".m4a": "音频", ".webm": "视频",
                ".mp3": "音频", ".opus": "音频", ".mkv": "视频"}


class ProgressPrinter:
    """把 yt-dlp 的实时输出渲染成单行进度条（\r 覆盖刷新）"""

    def __init__(self, prefix: str = "", width: int = 26):
        self.prefix = prefix
        self.width = width
        self.phase = "下载"
        self.printed = False

    def __call__(self, line: str):
        m = DEST_RE.search(line)
        if m:
            if self.printed:
                sys.stdout.write("\n")
                self.printed = False
            ext = os.path.splitext(m.group(1).strip())[1].lower()
            self.phase = PHASE_BY_EXT.get(ext, "下载")
            return
        m = PROGRESS_RE.search(line)
        if not m:
            return
        pct = float(m.group(1))
        filled = int(self.width * min(pct, 100) / 100)
        bar = "█" * filled + "░" * (self.width - filled)
        sp = SPEED_RE.search(line)
        eta = ETA_RE.search(line)
        tail = ""
        if sp:
            tail += f"  {sp.group(1)}"
        if eta:
            tail += f"  ETA {eta.group(1)}"
        sys.stdout.write(f"\r{self.prefix}{self.phase} [{bar}] {pct:5.1f}%{tail}")
        sys.stdout.flush()
        self.printed = True

    def finish(self):
        if self.printed:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.printed = False


def _run_stream(args, timeout, on_line):
    """流式跑 yt-dlp，逐行回调；带超时杀进程。返回 (rc, 输出行列表)"""
    cmd = [sys.executable, "-m", "yt_dlp", *args]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         env=env, bufsize=1)
    timer = None
    if timeout:
        timer = threading.Timer(timeout, p.kill)
        timer.daemon = True
        timer.start()
    lines = []
    try:
        while True:
            line = p.stdout.readline()
            if not line:
                break
            line = line.rstrip("\r\n")
            lines.append(line)
            on_line(line)
        p.wait()
    finally:
        if timer:
            timer.cancel()
    return p.returncode, lines


def download_one(vid, dest_dir, proxy, cookie_args, audio_only, prefix="") -> bool:
    dest_dir.mkdir(parents=True, exist_ok=True)
    a = base_common(proxy) + [
        "--newline",                      # 进度按行输出，便于实时解析
        "--no-overwrites",
        "--download-archive", str(ARCHIVE_AUDIO if audio_only else ARCHIVE_VIDEO),
        "--write-info-json", "--write-description", "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "-o", str(dest_dir / "media.%(ext)s"),
    ] + cookie_args

    if audio_only:
        a += ["-f", FORMAT_AUDIO]
    else:
        a += ["-f", FORMAT_VIDEO,
              "-S", "res:1080,ext:mp4:m4a",
              "--merge-output-format", "mp4"]
    a += ["--extractor-args", "youtube:lang=en"]
    a += [f"https://www.youtube.com/watch?v={vid}"]

    printer = ProgressPrinter(prefix=prefix)
    rc, lines = _run_stream(a, timeout=1800, on_line=printer)
    printer.finish()

    if rc != 0:
        _cleanup_parts(dest_dir)
        print(f"{prefix}[!] {vid} 失败 rc={rc}")
        for ln in lines[-6:]:
            print(prefix + "    " + ln)
        return False

    # rc=0 也不等于真有成品：合并失败只剩分片 / 命中归档被秒跳过
    if not media_files(dest_dir):
        _cleanup_parts(dest_dir)
        print(f"{prefix}[!] {vid} 无产出媒体文件（合并失败，或该视频已在归档中）")
        for ln in lines[-6:]:
            print(prefix + "    " + ln)
        return False
    return True


def write_meta(dest_dir: Path):
    info_path = dest_dir / "media.info.json"
    if not info_path.exists():
        cands = list(dest_dir.glob("*.info.json"))
        if not cands:
            return None
        info_path = cands[0]
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[!] 解析 info.json 失败: {e}")
        return None
    meta = {k: info.get(k) for k in META_FIELDS}
    (dest_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest_dir / "description.txt").write_text(info.get("description") or "", encoding="utf-8")
    return meta


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser(description="YouTube 主题采集器（带筛选）")
    ap.add_argument("topic")
    ap.add_argument("-n", "--num", type=int, default=10, help="最终采集条数（默认 10）")
    ap.add_argument("--pool", type=int, default=0, help="候选池大小（默认 max(20, n*4)）")
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--proxy", default=DEFAULT_PROXY)
    ap.add_argument("--cookies-from", default=None)
    ap.add_argument("--sort", choices=["views", "date", "relevance"], default="views",
                    help="排序方式（默认 views）")
    ap.add_argument("--min-duration", type=int, default=60)
    ap.add_argument("--max-duration", type=int, default=3600)
    ap.add_argument("--min-views", type=int, default=0)
    ap.add_argument("--max-hashtags", type=int, default=3)
    ap.add_argument("--no-filter", action="store_true", help="关掉筛选，直接取搜索前 N")
    ap.add_argument("--dry-run", action="store_true", help="只预览筛选结果，不下载")
    args = ap.parse_args()

    if args.no_filter:
        args.min_duration, args.max_duration = 0, 10**9
        args.max_hashtags, args.min_views = 10**9, 0

    pool = args.pool or max(20, args.num * 4)
    cookie_args = ["--cookies-from-browser", args.cookies_from] if args.cookies_from else []

    slug = slugify(args.topic)
    topic_dir = OUT_DIR / slug
    topic_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== 主题: {args.topic}")
    print(f"=== 目录: {topic_dir}")
    print(f"=== 代理: {args.proxy}")
    if FFMPEG_DIR:
        print(f"=== ffmpeg: {FFMPEG_DIR}")
    elif not args.audio_only:
        print("=== [!] 未找到 ffmpeg：只能拿哑巴视频。装法见 SETUP.md")
        print("        （或先用 --audio-only 绕过）")

    print(f"\n[1/4] 搜索候选池 ({pool} 条)...")
    rows = search_candidates(args.topic, pool, args.proxy, cookie_args)
    print(f"      拿到 {len(rows)} 条候选")

    print("\n[2/4] 筛选...")
    selected, dropped, note = select(rows, args.topic, args)
    print_report(selected, dropped)

    if not selected:
        print("[x] 没有可用候选，退出。")
        return

    if args.dry_run:
        print("\n[dry-run] 不下载，退出。")
        return

    print(f"\n[3/4] 下载 {len(selected)} 条...")
    ok, failed, results = 0, [], []
    for i, r in enumerate(selected, 1):
        print(f"  ({i}/{len(selected)}) {r['id']} {r['title'][:40]}")
        d = topic_dir / safe_dir_name(r["title"], r["id"], topic_dir)
        if download_one(r["id"], d, args.proxy, cookie_args, args.audio_only,
                        prefix="      "):
            meta = write_meta(d)
            ok += 1
            results.append({
                "id": r["id"],
                "title": (meta or {}).get("title") or r["title"],
                "uploader": (meta or {}).get("uploader"),
                "views": (meta or {}).get("view_count"),
                "likes": (meta or {}).get("like_count"),
                "duration": (meta or {}).get("duration"),
                "pool_rank_views": r["view_count"],
            })
            print("      → OK")
        else:
            failed.append(r["id"])
            print("      → FAIL")

    print("\n[4/4] 写任务清单...")
    manifest = {
        "topic": args.topic, "slug": slug,
        "query": f"ytsearch{pool}:{args.topic}",
        "proxy": args.proxy, "audio_only": args.audio_only,
        "cookies_from": args.cookies_from,
        "filter": {
            "min_duration": args.min_duration, "max_duration": args.max_duration,
            "min_views": args.min_views, "max_hashtags": args.max_hashtags,
            "sort": args.sort, "pool": pool, "note": note,
        },
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "candidates": len(rows),
        "selected": len(selected),
        "succeeded": ok,
        "videos": results,
        "dropped": [{"id": d["id"], "title": d["title"],
                     "views": d["view_count"], "duration": d["duration"],
                     "reason": d["drop_reason"]} for d in dropped],
        "failed": failed,
    }
    (topic_dir / "_topic.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成: 候选 {len(rows)} -> 入选 {len(selected)} -> 成功 {ok}；失败 {len(failed)}")
    if failed:
        print(f"失败清单: {failed}")


if __name__ == "__main__":
    main()
