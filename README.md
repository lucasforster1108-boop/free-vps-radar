# free-vps-radar

> A tiny zero-dependency Python watcher that alerts you on Telegram the moment a free VPS / free-tier offer comes back in stock.

## 一句话介绍

盯住一批「免费 VPS / 免费额度」的页面和接口，只在**从无货变成有货的那一刻**发一条 Telegram 提醒，单文件、纯 Python 标准库、零依赖。

## 为什么做这个

免费的东西补货从来不打招呼：免费机名额、免费额度、限量套餐，往往半夜放出来一批，几分钟就被抢空。靠手刷必错过——要么你刚好不在，要么刷新频率跟不上。把这件事交给一个小脚本 24 小时蹲着，是唯一靠谱的办法。

我之前给几个平台各写了一个一次性的盯守脚本，逻辑都差不多。这次把它们抽象成一个通用工具：目标、判断方式、状态全走配置，换个页面只改 JSON，不用再改代码。

## 功能

- **三种判断方式（mode）**：
  - `keyword_absent`：页面里出现「无货」关键词 = 无货，关键词消失 = 有货
  - `keyword_present`：页面里出现「有货」关键词（如领取按钮文案）= 有货
  - `json_field`：抓 JSON 接口，按点路径读字段，支持 `equals`（相等）和 `>=`（数值大于等于）两种比较
- **只在状态翻转时通知**：无货 → 有货才发提醒；一直有货不重复打扰；抓取失败保留上次状态，不把网络错误当成状态变化
- **首次运行不打扰**：第一次见到某个目标就是有货状态时，默认不发通知（加 `--notify-first` 才发）
- **Telegram 通知**：走环境变量配置；没配环境变量时只在日志里打印提醒，绝不崩溃
- **单个目标出错不影响全局**：每个目标独立 try/except，一个页面挂了其他照常盯
- **零依赖**：Python 3 标准库（urllib / json / argparse），下载下来就能跑

## 快速开始

```bash
cp config.example.json config.json
# 按你要盯的页面改 config.json 里的 url 和关键词
python3 radar.py --config config.json --once          # 只检查一遍
python3 radar.py --config config.json                 # 常驻循环（默认每 300 秒一轮）
python3 radar.py --config config.json --once --dry-run  # 干跑：只打印「会通知什么」，不写状态、不发送
python3 radar.py --test-notify                        # 发一条测试消息，验证 Telegram 通道
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--config` | 配置文件路径（默认 `config.json`） |
| `--state` | 状态文件路径（默认 `state.json`） |
| `--once` | 只检查一遍就退出 |
| `--interval` | 循环模式的轮询间隔秒数（默认 300） |
| `--dry-run` | 只打印会通知的内容，不写状态文件、不发消息 |
| `--notify-first` | 首次运行见到有货也通知 |
| `--test-notify` | 发送一条测试 Telegram 消息后退出 |

## 配置说明

`config.json` 里是一个 `targets` 数组，每个目标包含 `name`、`url`、`mode` 和该 mode 的参数。

**mode 1：`keyword_absent`** —— 页面显示无货文案时无货，文案消失即有货：

```json
{
  "name": "Oracle Cloud 免费套餐",
  "url": "https://www.oracle.com/cloud/free/",
  "mode": "keyword_absent",
  "keyword": "SOLD OUT"
}
```

**mode 2：`keyword_present`** —— 页面出现领取按钮之类的文案才算有货：

```json
{
  "name": "某免费套餐",
  "url": "https://example.com/free-plan",
  "mode": "keyword_present",
  "keyword": "Claim now"
}
```

**mode 3：`json_field`** —— 目标是返回 JSON 的接口时，按点路径读字段比较：

```json
{
  "name": "某平台库存接口",
  "url": "https://example.com/api/stock",
  "mode": "json_field",
  "field": "data.available",
  "op": ">=",
  "expect": 1
}
```

`field` 支持点路径（如 `data.available`、列表下标 `items.0.stock`）；`op` 支持 `equals` 和 `>=`。

## Telegram 通知配置

先在 Telegram 里找 @BotFather 建一个机器人拿到 token，再把机器人拉进一个会话（或给它发一条消息）拿到 chat id，然后：

```bash
export TG_BOT_TOKEN="你的机器人 token"
export TG_CHAT_ID="你的 chat id"
python3 radar.py --test-notify   # 先验证通道
```

没设置这两个环境变量也能跑：提醒只打印在日志里，不发送、也不报错。

## 常驻运行

**cron**（每 10 分钟检查一遍，配合状态文件只在翻转时通知）：

```cron
*/10 * * * * cd /path/to/free-vps-radar && TG_BOT_TOKEN=xxx TG_CHAT_ID=yyy /usr/bin/python3 radar.py --config config.json --once >> radar.log 2>&1
```

**systemd**（循环模式常驻）：

```ini
# /etc/systemd/system/free-vps-radar.service
[Unit]
Description=free-vps-radar
After=network-online.target

[Service]
WorkingDirectory=/path/to/free-vps-radar
Environment=TG_BOT_TOKEN=xxx
Environment=TG_CHAT_ID=yyy
ExecStart=/usr/bin/python3 radar.py --config config.json --interval 300
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now free-vps-radar
```

## 测试

```bash
python3 -m unittest
```

抓取函数在测试里被替换成桩函数，不访问真实网络，覆盖三种 mode 的判断、翻转只通知一次、抓取失败保留状态等场景。

## 和 oracle-snatch 的关系

[oracle-snatch](https://github.com/lucasforster1108-boop/oracle-snatch) 是「抢」：盯到甲骨文放货后自动去开免费 ARM 机器。free-vps-radar 是「盯」：只负责发现补货并通知，不做任何下单/开通动作。两者可以配合：radar 负责第一时间发现，snatch 负责动手；也可以只用 radar，收到提醒后自己去领。

## 免责声明

- `config.example.json` 里的关键词只是示例，各站页面文案随时会改，**用前请打开目标页面核对当前实际文案再填**，填错了会误报或漏报。
- 请遵守目标站点的服务条款；轮询间隔别设太短（建议 ≥ 300 秒），别给人家服务器添堵。
- 本工具只做公开页面的只读检查和通知，不绕过任何登录、验证码或访问控制。
