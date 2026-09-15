# 部署说明（换机器必读）

> 本文解决一件事：**把整个目录拷到另一台电脑后，怎么让它跑起来。**
> 最关键的是第 3 节——代理/路由配置，也是最容易踩坑的地方。

---

## 0. 什么能拷，什么必须重做

| 内容 | 能否直接拷 | 说明 |
|---|---|---|
| `collect.py` / `collect.bat` / `list.py` / `open-browser.bat` | ✅ | 纯代码，无硬编码路径 |
| `output/`（已采集数据） | ✅ | 目录名是中文标题，目标文件系统需支持 UTF-8 |
| `archive_video.txt` / `archive_audio.txt` | ✅ **建议拷** | 不拷会**重复下载**已有视频 |
| Python 依赖（yt-dlp / zhconv / static-ffmpeg） | ❌ | 新机器重新 `pip install` |
| ffmpeg 二进制 | ❌ | 新机器重新装（或用 `YTC_FFMPEG` 指定） |
| **代理客户端 + 端口** | ❌ | **最容易出问题的地方，见第 3 节** |

---

## 1. 前置条件

- Windows（脚本用了 `collect.bat` / `chcp`；mac/Linux 见第 7 节）
- Python 3.10+，且 `python` 在 PATH 里
- **一个能访问 YouTube 的代理出口**（应用级 SOCKS5 / HTTP，不是系统级 VPN）

---

## 2. 安装依赖

```powershell
cd <项目目录>

# 国内环境 pip 通常也要走代理（端口换成你客户端的 HTTP 代理端口）
$env:HTTPS_PROXY = "http://127.0.0.1:9876"
$env:HTTP_PROXY  = $env:HTTPS_PROXY

python -m pip install -U yt-dlp zhconv static-ffmpeg

# 首次触发 ffmpeg 二进制下载（几十 MB，必须能走通代理）
python -c "import static_ffmpeg, shutil; static_ffmpeg.add_paths(); print(shutil.which('ffmpeg'))"
```

**逐条验证：**

```powershell
python -m yt_dlp --version                                        # 应有版本号
python -c "import zhconv; print(zhconv.convert('熱泵','zh-cn'))"   # 应输出 热泵
python -c "import static_ffmpeg,shutil; static_ffmpeg.add_paths(); print(shutil.which('ffmpeg'))"
```

---

## 3. ⚠️ 代理 / 路由部分（核心，换机器必改）

### 3.1 先搞清楚新机器的代理端口

本项目**默认**假设代理客户端提供 SOCKS5 在 `127.0.0.1:1234`、HTTP 在 `127.0.0.1:9876`。

**换机器 = 换客户端 = 端口大概率不一样。** 先查：

```powershell
netstat -ano | Select-String "LISTENING" | Select-String "127.0.0.1:"
```

找到客户端占用的端口后，**二选一**告诉本项目：

```powershell
# 方式 A：命令行参数
python collect.py "主题" --proxy socks5h://127.0.0.1:<你的端口>

# 方式 B：环境变量（推荐，设一次管一个会话）
$env:YTC_PROXY = "socks5h://127.0.0.1:<你的端口>"
```

### 3.2 三条必须遵守的规则

#### 规则一：必须 `socks5h`，不能 `socks5`

```
socks5  (本地解析 DNS) → 000 失败
socks5h (远端解析 DNS) → 200  0.74s   ✅
```

原因：本机 DNS 被污染时，`socks5` 会**先用污染 DNS 解析出假 IP，再让代理去连那个假 IP**
→ 必然失败。那个 `h` = 把域名原样交给节点，由它解析。

#### 规则二：绝不要开 TUN / 全局 / 系统代理模式

系统级代理会把**同机上所有进程**的流量一起卷进隧道。后果：

- 依赖**国内 API 端点**的服务，请求会**挂住且不报错**（黑洞式丢包，不是连接被拒）→ 表现为"卡死"
- 正确姿势：**保持应用级**，只让采集脚本通过 `--proxy` 显式走代理

**应用级 = 按需、精确；系统级 = 一刀切、透明。** 能不开全局就别开。

如果客户端支持**按进程分流**，把 `python.exe` 排除在加速范围外即可。

#### 规则三：客户端必须处于运行状态

端口是**客户端进程**提供的，客户端一关端口立刻消失：

```
ERROR: [WinError 10061] 由于目标计算机积极拒绝，无法连接。
```

**跑之前先确认端口在听。**

### 3.3 三条命令验证代理（跑采集前必做）

```powershell
# 1) 端口在听吗
netstat -ano | Select-String "127.0.0.1:1234"

# 2) 能出海吗（200 = 通）
curl.exe -s -o NUL -w "%{http_code} %{time_total}s`n" --max-time 15 -x socks5h://127.0.0.1:1234 https://www.youtube.com/

# 3) 出口在哪（应该是境外国家 + hosting=true）
curl.exe -s --max-time 12 -x socks5h://127.0.0.1:1234 "http://ip-api.com/json/?fields=query,country,as,hosting,proxy"
```

第 3 条的意义：确认你**确实通过节点出去了**，而不是走了本地直连（直连必然超时）。

---

## 4. ffmpeg 路径

代码**自动探测**，优先级：

1. 环境变量 `YTC_FFMPEG`
2. 系统 `PATH`
3. `static-ffmpeg` 包（pip 装的）
4. 项目下的 `bin/` 目录

没找到时：
- 音频模式（`--audio-only`）**不受影响**，照常能跑
- 视频模式会提示警告，且只能拿到**无声视频**

指定自定义路径：

```powershell
$env:YTC_FFMPEG = "D:\tools\ffmpeg.exe"      # 或它所在目录
```

---

## 5. 环境变量一览

| 变量 | 作用 | 默认 |
|---|---|---|
| `YTC_PROXY` | 代理地址 | `socks5h://127.0.0.1:1234` |
| `YTC_FFMPEG` | ffmpeg 路径 | 自动探测 |
| `HTTPS_PROXY` / `HTTP_PROXY` | 只在 `pip install` 时需要 | — |

---

## 6. 部署完成验证（三步）

```powershell
cd <项目目录>

python collect.py "test topic" -n 1 --dry-run      # ① 搜索 + 筛选（不下载）
python collect.py "test topic" -n 1 --audio-only   # ② 真下一条（小，几 MB）
python list.py                                      # ③ 能看到清单
```

**三步都通 = 部署完成。** 之后再跑视频模式。

---

## 7. 跨平台 / 其它差异

| 项 | 说明 |
|---|---|
| **非 Windows** | `collect.bat` 不可用，直接 `python collect.py ...`；控制台编码问题不存在 |
| **Windows 用户名不同** | 无影响（路径自动探测，代码无硬编码用户目录） |
| **Python 版本不同** | 无影响，但 ffmpeg 需在新 Python 环境里重装一次 |
| **路径过深** | 视频标题会拼进路径，可能触发 Windows 260 字符限制 → 项目别放太深，或调小代码里的 `maxlen`（默认 60） |
| **文件名非法字符** | 代码已统一替换 `\ / : * ? " < > \|`，跨文件系统保守可用 |

---

## 8. 常见报错对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `WinError 10061 目标计算机积极拒绝` | 代理客户端没开 / 端口不对 | 开客户端，按 3.1 查端口 |
| `000` + 超时 | 用了 `socks5` 而非 `socks5h`（DNS 污染） | 加 `h` |
| `000` + 超时（端口正常） | 节点不可用 | 客户端里换节点 |
| 中文输出乱码 | 没用 `collect.bat` 启动 | 用 bat（内含 `chcp 65001`） |
| 标题显示 `锟斤拷` | yt-dlp stdout 编码错配 | 代码已修（子进程设 `PYTHONIOENCODING=utf-8`）；别改回去 |
| `Requested format is not available` | 该视频没有所请求格式 | 降分辨率：`-S res:720` |
| `Could not copy Chrome cookie database` | 浏览器正在运行，锁住了 Cookies 库 | 关掉浏览器；要保登录态需走 CDP 导出 cookie |
| 视频下下来没声音 | 没装 ffmpeg | 装 ffmpeg，或用 `--audio-only` |
| 采到不相关的内容 | 主题里混了泛词（"入门"/"详解"/"直观理解"） | **主题只写核心名词** |

---

## 9. 已知限制

1. **关键词硬匹配会误杀**：异体字（`傅立叶` vs `傅里叶`）、英文标题、短语不连续 → 会漏掉高播放优质视频
2. **结果可能集中于单一频道**：按播放量排序天然偏心爆款大号，缺视角多样性
3. **串行下载偏慢**：实测平均 ~1 MB/s（YouTube 单连接限速）。可加 `aria2c` 提速：
   ```
   --downloader aria2c --downloader-args "aria2c:-x16 -s16 -k1M"
   ```
4. **体积大**：10 条视频实测约 980 MB。只要内容的话优先 `--audio-only`
5. **搜索地区随节点走**：换节点 = 换内容池
