#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看已采集的主题清单（正确按 UTF-8 读取，避开 PowerShell 的 GBK 误读）"""
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent / "output"


def size_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1024 / 1024


def main():
    if not ROOT.exists():
        print("还没有任何采集结果。")
        return
    topics = sorted([d for d in ROOT.iterdir() if d.is_dir()])
    if not topics:
        print("output/ 下还没有主题目录。")
        return

    for t in topics:
        print(f"\n{'='*78}")
        print(f"主题目录: {t.name}    (共 {size_mb(t):.2f} MB)")
        man = t / "_topic.json"
        if man.exists():
            m = json.loads(man.read_text(encoding="utf-8"))
            flt = m.get("filter") or {}
            print(f"搜索词  : {m.get('query')}")
            print(f"采集时间: {m.get('collected_at')}    排序={flt.get('sort')}    时长 {flt.get('min_duration')}~{flt.get('max_duration')}s")
            print(f"筛选    : 候选 {m.get('candidates')} -> 入选 {m.get('selected')} -> 成功 {m.get('succeeded')}")
        print(f"{'-'*78}")
        print(f"{'视频ID':<13}{'时长':>6}{'播放':>10}{'赞':>8}  博主 / 标题")
        for d in sorted([x for x in t.iterdir() if x.is_dir()]):
            mp = d / "meta.json"
            if not mp.exists():
                print(f"{d.name[:20]:<13}{'(无 meta.json)':>20}")
                continue
            mm = json.loads(mp.read_text(encoding="utf-8"))
            dur = mm.get("duration") or 0
            dur_s = f"{dur//60}:{dur%60:02d}"
            vc = mm.get("view_count")
            lc = mm.get("like_count")
            vid = mm.get("id") or d.name
            title = (mm.get("title") or d.name)[:46]
            up = (mm.get("uploader") or "")[:18]
            print(f"{vid:<13}{dur_s:>6}{str(vc):>10}{str(lc):>8}  {up} / {title}")


if __name__ == "__main__":
    main()
