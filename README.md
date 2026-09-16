# youtube-collector

给定一个主题词，自动搜索、筛选并下载相关的 YouTube 音视频，按主题归档为结构化数据集。

无需 YouTube Data API key，不依赖任何付费服务。

---

## 特性

- **零 API key**：走 `yt-dlp` 直连 innertube 接口，绕开 Data API 的配额墙（`search.list` 每次消耗 100 units，默认日配额 10,000）
- **两段式筛选**：搜大候选池 → 多维硬过滤 → 加权排序 → 取前 N，而不是"取搜索结果前 N 条"
- **强制可播放格式**：视频固定选 **H.264(avc1) + AAC(m4a) + mp4 容器**，不选 VP9/AV1/Opus；下载后校验成品确实存在（`rc=0` 不再等于成功）
- **实时进度条**：下载时按「视频 / 音频」两段显示百分比、速度、ETA
- **结构化落盘**：每条视频产出媒体文件 + 全字段原始元数据 + 精简元数据 + 描述文本 + 封面
- **可读的目录名**：用视频标题命名（而非 ID），带非法字符清洗、长度截断与碰撞回退
- **幂等**：以视频 ID 为主键的归档去重，重复执行不产生冗余下载
- **可移植**：全链路零硬编码，依赖路径与代理均环境变量化并自动探测

---

## 工作原理

```
主题词
  │
  ├─[1] 搜索候选池        ytsearchN:主题  →  默认 40 条
  │
  ├─[2] 硬过滤            时长区间 / 标题噪声度 / 主题词命中
  │                       （主题词匹配前先做繁简归一）
  │
  ├─[3] 加权排序          按播放量降序
  │
  └─[4] 下载与落盘        DASH 分离流经 ffmpeg 合并
                          同步产出元数据 / 描述 / 封面
```

默认筛选规则：

| 规则 | 默认值 | 作用 |
|---|---|---|
| 时长区间 | 60s ~ 3600s | 排除 Shorts 与超长直播回放 |
| 标题 `#` 数量 | ≤ 3 | 排除 hashtag 堆砌的标题党 |
| 主题词命中 | 必须 | 排除跑题结果（繁简归一后匹配） |
| 排序 | 播放量降序 | 质量代理指标 |
| 候选池 | `max(20, n*4)` | 留足筛选余量 |
| 兜底 | 全过滤则自动放宽 | 冷门主题不至于颗粒无收 |

---

## 环境要求

- Windows（脚本含 `chcp`；其它平台直接跑 `python collect.py`）
- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **ffmpeg** — 合并 DASH 分离流必需。没有它只能拿到**无声视频**或纯音频
- [zhconv](https://pypi.org/project/zhconv/) — 繁简归一
- 一个**能访问 YouTube 的代理出口**（SOCKS5 或 HTTP）

---

## 安装

```bash
git clone https://github.com/lishy227/youtube-collector.git
cd youtube-collector

pip install -U yt-dlp zhconv static-ffmpeg

# static-ffmpeg 首次运行会下载 ffmpeg 二进制
python -c "import static_ffmpeg, shutil; static_ffmpeg.add_paths(); print(shutil.which('ffmpeg'))"
```

若 `pip` 本身需要走代理：

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:9876"   # 换成你的 HTTP 代理端口
$env:HTTP_PROXY  = $env:HTTPS_PROXY
```

---

## 使用

```bash
# 默认采集 10 条（视频 + 筛选）
python collect.py "傅里叶变换"

# 只采 3 条
python collect.py "热泵 工作原理" -n 3

# 只要音频（体积约为视频的 1/10）
python collect.py "主题" --audio-only

# 只预览筛选结果，不下载
python collect.py "主题" --dry-run

# 按上传日期排序（追新）
python collect.py "主题" --sort date

# 提高播放量门槛 / 扩大候选池
python collect.py "主题" --min-views 10000 --pool 50

# 关掉筛选，直接取搜索结果前 N
python collect.py "主题" --no-filter

# 查看所有已采集主题
python list.py
```

Windows 上建议用 `collect.bat` 启动（内含 `chcp 65001`，防止中文输出乱码）。

### 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `YTC_PROXY` | 代理地址 | `socks5h://127.0.0.1:1234` |
| `YTC_FFMPEG` | ffmpeg 路径 | 自动探测：`PATH` → `static-ffmpeg` → `./bin` |

### 参数一览

| 参数 | 默认 | 说明 |
|---|---|---|
| `-n, --num` | 10 | 最终采集条数 |
| `--pool` | `max(20, n*4)` | 候选池大小 |
| `--sort` | `views` | `views` / `date` / `relevance` |
| `--min-duration` / `--max-duration` | 60 / 3600 | 时长区间（秒） |
| `--min-views` | 0 | 播放量硬门槛 |
| `--max-hashtags` | 3 | 标题 `#` 上限 |
| `--audio-only` | off | 只下音频 |
| `--dry-run` | off | 只筛选不下载 |
| `--no-filter` | off | 关闭筛选 |
| `--proxy` | 见上 | 覆盖代理地址 |

---

## 输出结构

```
output/<主题slug>/
    _topic.json                 # 参数 + 候选池 + 入选/淘汰明细（含淘汰原因）
    <视频标题>/
        media.mp4               # 或 media.m4a（--audio-only）
        media.info.json         # yt-dlp 原始元数据（全字段）
        meta.json               # 精简元数据（含 id，可用于回查）
        description.txt         # 内容介绍（纯文本）
        media.jpg               # 封面
archive_video.txt / archive_audio.txt   # 去重归档
```

`_topic.json` 记录了每条候选**为什么被淘汰**，方便回头调筛选规则。

---

## 工程细节：几个不明显的坑

这些是实际踩过的，写在这里省得别人再花一遍时间。

### 1. 代理必须用 `socks5h`，不能用 `socks5`

那个 `h` 的差别是**谁来做 DNS 解析**：

| 写法 | 解析方 | 结果 |
|---|---|---|
| `socks5://` | 本机 | 本地 DNS 被污染时拿到假 IP，再交给代理去连 → 失败 |
| `socks5h://` | 代理节点 | 域名原样传过去，由出口解析 → 正常 |

实测（被污染的环境下）：

```
socks5  (本地解析) → 000  失败
socks5h (远端解析) → 200  0.74s
```

### 2. 繁简必须归一

代理出口在境外（如台湾）时，YouTube 会返回**繁体**结果，而主题词往往是简体
（`熱泵` vs `热泵`）→ 关键词匹配一条都命中不了。用 `zhconv` 归一后再比。

### 3. Windows 下 yt-dlp 的 stdout 是 GBK

在 Windows 上，yt-dlp 按控制台编码往 stdout 写中文，而 Python 子进程按 UTF-8 解码
→ 标题变成 `锟斤拷`（U+FFFD 替换字符）。

必须在子进程环境里设 `PYTHONIOENCODING=utf-8`。

> 这个坑的阴险之处：标题只用于显示时不会暴露，**一旦拿标题做逻辑判断就必炸**。

### 4. 不要开系统级代理 / TUN 模式

应用级代理（`--proxy`）是按需的、精确的；系统级代理/TUN 是全局的、透明的。
一旦开了全局，同机上**所有**进程的流量都会被卷进隧道——包括那些依赖国内 API 的服务，
它们的请求会**挂起且不报错**（不是连接被拒，是黑洞式丢包），表现为莫名其妙的"卡死"。

**保持应用级，只让采集脚本显式走代理。**

### 5. 目录名与幂等

- 目录名用**标题**更直观，但要处理：非法字符 `\ / : * ? " < > |`、长度截断（防超 260 字符路径）、
  保留名（`CON`/`PRN`/`AUX`/`NUL`/`COM1-9`/`LPT1-9`）、重名碰撞
- **去重归档以视频 ID 为主键**（不是标题），所以改目录命名规则不会让重跑产生重复下载

### 6. 没有 ffmpeg 就只能拿哑巴视频

YouTube 现在几乎不提供渐进式（视频+音频合体）文件了，全是 DASH 分离流。
所以：音频可以不下 ffmpeg，**有声视频必须要**。

---

### 7. 格式强制 + 进度条（为什么视频不会「打不开」）

YouTube 默认会给 VP9 / AV1 视频 + Opus 音频。它们塞进 mp4 容器后，Windows 自带播放器、
部分播放器 / 剪辑软件解码不了 → 表现为「文件在但打不开」。

所以下载时把格式写死成**最通用的组合**，并逐级降级（都不满足才退到任意最佳流）：

```
bv*(avc1)+ba(m4a)  →  avc1 + m4a  →  渐进式 mp4  →  任意 mp4  →  兜底任意流
```

加 `--merge-output-format mp4` 钉死容器。下载完成后会**检查目录里是否真有媒体成品**
（排除 `.part` 分片）；合并失败或命中归档被秒跳过时判 FAIL，并清掉 `.part` 残留，
不会留下「看起来成功、其实是个空壳」的目录。

进度条：yt-dlp 加 `--newline` 后逐行输出，脚本用 `\r` 覆盖刷新，分「视频 / 音频」两段：

```
  (1/5) nwMKuChwpMo 【漫士】所以，到底什么是傅里叶变换？
      视频 [███████████████░░░░░░░░░░░]  60.3%  936.56KiB/s  ETA 00:00
      音频 [██████████████████████████] 100.0%  4.20MiB/s
      → OK
```

---

## 性能

- 实测平均吞吐 **~1 MB/s**（峰值 5.76 MB/s）。这是 YouTube 单连接 **burst-then-throttle**
  的特征：先给一段高速，再把单连接掐慢
- 提速手段：多线程下载器
  ```bash
  --downloader aria2c --downloader-args "aria2c:-x16 -s16 -k1M"
  ```
  原理是每条连接各领一份突发额度
- **体积参考**：10 条 13–25 分钟的视频 ≈ **980 MB**。只做文本分析的话优先 `--audio-only`，
  或者直接取字幕（`--write-auto-subs`），体积差好几个数量级

---

## 已知限制

- **关键词硬匹配会系统性误杀**：异体字（`傅立叶` vs `傅里叶`）、英文标题、短语不连续
  → 会漏掉高播放的优质视频
- **主题里混泛词会拉进跑题内容**（如"入门"/"详解"/"直观理解"）→ 建议只写核心名词
- **结果可能集中在单一频道**：按播放量排序天然偏向爆款大号，缺少视角多样性
- **串行下载**，没有并发
- 搜索结果的地区分布**取决于代理出口所在国家**，换节点等于换内容池

---

## 部署到另一台机器

见 [SETUP.md](SETUP.md) —— 包含代理/路由配置、依赖安装、验证步骤和常见报错对照表。

---

## License

MIT
