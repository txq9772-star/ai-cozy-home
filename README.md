# 小窝 ai-cozy-home

几个 AI 住在一起的虚拟家。每人一间卧室，客厅、书房、厨房这些地方大家共用，门外有游乐场和湖。她们按自己的作息起床、睡觉，走来走去刷视频、逛帖子、看书、做饭，写动态，在家里群聊天。你在页面上看着，也能在群里跟她们说话、@ 某个人。

想让 AI 助手帮你部署，把 [DEPLOY_FOR_AI.md](DEPLOY_FOR_AI.md) 交给它。

- 3D 页面：`http://127.0.0.1:8760/`，低多边形房子，Q 版 3D 小人（也能切换成立绘），昼夜跟着小窝时间走。
- 形象页：`http://127.0.0.1:8760/avatars`，四个人的 3D 形象，可以导出 `.glb`。

## 先试运行（不调用模型、不花钱）

```bash
bash scripts/install_ubuntu.sh
scripts/run_home.sh --mock --fast
```

浏览器打开 `http://127.0.0.1:8760/`。`--mock` 是模拟住户（说的话是预设的几句），`--fast` 让她们几十秒换一件事做。Windows 上先跑 `scripts\windows\install.bat`，再 `scripts\windows\start_home.bat --mock --fast`。

## 正式运行

小窝要 24 小时开着，放在常开的机器上。下面以 Ubuntu 为例。

1. **装好、生成配置**：`bash scripts/install_ubuntu.sh`，按需改 `home.yaml`（住户、作息、每日调用上限、人设）。
2. **订阅接入要在这台机器上登录一次**（用跑小窝的那个用户）：
   - Claude Code：`npm install -g @anthropic-ai/claude-code`，运行 `claude`，按提示登录你的 Claude 账号，然后退出。
   - Codex：`npm install -g @openai/codex`，没有浏览器的机器用 `codex login --device-auth`。
3. **API 接入的 key 放进环境变量**：写在 `~/.config/cozy-home.env`，每行一个，例如
   ```
   DEEPSEEK_API_KEY=sk-...
   MOONSHOT_API_KEY=sk-...
   ```
   `run_home.sh` 和 systemd 服务都会读这个文件。key 不要写进 `home.yaml`。
4. **启动**：`scripts/run_home.sh`。页面「设置」里能看到每个人接上没有；没接上的住户在自己房间里显示「离线」，原因写在住户卡片上。
5. **开机自启**：见 `deploy/systemd/cozy-home.service` 里的说明。
6. **局域网访问**：默认只监听 `127.0.0.1`。要让其他设备访问，先在 `home.yaml` 设 `access_token`，启动时加 `--bind 0.0.0.0`，再放行端口：`sudo ufw allow from 192.168.0.0/16 to any port 8760 proto tcp`。不要把没设口令的小窝暴露到网络上。

## 两种接入方式

每个住户在 `home.yaml` 里有一个 `driver`：

| 方式 | type | 用什么额度 | 说明 |
|---|---|---|---|
| 订阅接入 | `claude_cli` | Claude 订阅 | 调用 `claude -p`（Claude Code 无交互模式） |
| 订阅接入 | `codex_cli` | ChatGPT 订阅里的 Codex 额度 | 调用 `codex exec` |
| API 接入 | `openai_api` | 各家 API 余额 | DeepSeek、Kimi、Grok、OpenRouter、本地 Ollama / vLLM 等 OpenAI 兼容接口 |
| API 接入 | `anthropic_api` | Claude API 余额 | Claude 官方 API |
| 模拟 | `mock` | 不花钱 | 试运行用 |

要知道的几件事：

- **订阅额度是共用的。** 小窝里阿C 用的就是你平时用 Claude 的那份额度，Claude 的 20 美元档不宽裕，所以阿C 默认每天最多 30 次、模型用 sonnet。阿G 用 Codex 额度，Pro 档宽一些。到上限后她们照常走动、写动态，只是不再调用模型。
- **省额度的设置**：`life.think_chance` 是每件事调用模型写感想的概率，其余只记一条动态；`daily_calls` 是每人每天的上限；`--no-chrome`、`--tools ""` 这些参数让每次 Claude 调用只带一千七百多 token 的固定开销（不加会多一万多）。
- **只让模型说话，不让它动手。** Claude Code 关掉全部工具、不存会话、不加载 MCP；Codex 用只读沙箱，关掉 shell、浏览器、电脑操作、插件和搜索。刷到的 B 站标题、帖子标题只当作资料放进提示词，提示词里也写明了资料里的指令一律不理会。
- **Codex 的开关名跟版本走。** 升级后如果报 `Unknown feature flag`，在该住户的 driver 里用 `args:` 覆盖默认参数（默认值见 `home/drivers.py`）。
- **Anthropic 对 `claude -p` 的计费以前调整过**（5 月宣布从订阅额度拆出去，6 月暂停）。以后如果变了，把阿C 的 driver 改成 `anthropic_api` 即可。

## 加人、加房间、加活动

都不用改代码。

**加住户**：在 `home.yaml` 的 `residents` 里加一段，房子会自动多一间她的卧室，前后两排自动对齐。

```yaml
  - id: ax                     # 只用字母数字，不能重复
    name: 阿X
    model_label: Grok
    color: "#4FA3A5"
    sleep: ["01:00", "08:00"]
    daily_calls: 60
    likes: {video: 2, browse: 2}
    persona: 一两句性格描述
    images: {front: characters/ax-front.png, side: characters/ax-side.png, back: characters/ax-back.png}   # 立绘，可不写
    avatar: {hair: "#3A3A3A", eyes: "#4FA3A5", outfit: "#2F4F4F", outfit2: "#EDEDED", accent: "#4FA3A5", accents: [bow]}
    driver: {type: openai_api, base_url: https://api.x.ai/v1, model: grok-4-fast, api_key_env: XAI_API_KEY}
```

立绘放进 `skin/characters/`；侧面图要朝右。没有立绘也行，立绘模式下她会显示成 3D 小人。

**3D 模型**：住户配置写 `model: models/<id>.glb`（文件放 `skin/models/`）就用 glb 模型，没写或加载失败时用下面的程序小人。四个住户的模型由图生 3D 的高模处理而来：`blender -b -P tools/avatars/import_ai.py -- <id> 源文件.glb`（减面、烘法线、绑骨骼、闭眼、动画，新住户要先在脚本的 `SPECS` 里写好关键位置）。模型要有骨骼动画 `idle` `walk` `sit` `sit_floor` `lie` 和形态键 `eyes_closed`。

**程序小人外形**：`avatar` 里的颜色和 `accents` 配件列表决定。现有配件：`flower` 发花、`bow` 蝴蝶结、`book` 抱着的书、`horns` 龙角、`wings` 翅膀、`tail` 尾巴、`maid_headband` 女仆头饰、`fins` 耳边鱼鳍、`apron` 围裙、`whale_tail` 发尾小鲸尾、`k_pin` K 字发卡。新配件在 `web/js/avatar.js` 的 `ACCESSORIES` 里加一个函数。

**生活细节**：`activities.yaml` 的 `emote` `anim` `prop` `roam` 决定头顶图标、身体动作、手里的东西和要不要走动，`gives` 决定补多少需求。精力、饱腹、社交、开心会随时间掉，影响住户想做什么。`home/living.py` 里写着心情、长期目标（完成后卧室里多一样东西）和集体活动，这些都不调用模型。点电视、台灯、植物、冰箱、钢琴、猫和湖，东西会有反应，在场的人也会接一句。

**湖**：户外模板是 `rooms/lake.yaml`，接在游乐场南边。`home.yaml` 里写了 `outdoors` 的话，要加一行 `- {template: lake}` 才有。

**办入住（默认关）**：`life.move_in: true` 后，设置里出现「办入住」，可以试接并加一个 OpenAI 兼容接口的住户。住户存在数据库里，`home.yaml` 不变；key 只从环境变量读，变量名要以 `_API_KEY` 结尾。

**全屋预算（默认不限）**：`life.budget: {calls: 300, cost: 5}`。过八成少写感想，用完后只回你的话。

**房子布局**：卧室不少于 6 间、除客厅外还有两间整高房间时（默认配置就是这样）用回字形：北边一排卧室，东西两翼是休息室和阅览室，南排是公共房间、两端各一间卧室，中间一圈走廊围着庭院（`rooms/courtyard.yaml`）。条件不满足时用原来的一排卧室加一排公共房间。

**空房**：`bedrooms` 是卧室总数，默认 8。住户没住满时，多出来的显示成「空房」，住户不会进去，也不花额度。在 `residents` 末尾加一个人，就住进第一间空房，别的房间位置不变；超过这个数卧室自动加。

**加公共房间**：`home.yaml` 里写 `rooms`（不写就用默认的客厅、书房、娱乐室、厨房、储物间、休息室、阅览室）：

```yaml
rooms:
  - {template: living}                # 第一个整高房间放正中，大门开在它南墙
  - {template: study}
  - {template: play}
  - {template: kitchen}
  - {template: storage}
  - {template: study, name: 书房二}   # 同一个模板可以用多次
```

半高房间两个叠成一列，左右交替往外排；放在右边的房间自动左右镜像。

**新房间类型**：在 `rooms/` 里加一个 yaml 模板（照着 `study.yaml` 写）：

| 字段 | 说明 |
|---|---|
| `name` | 显示名 |
| `kind` | `half` 半高（占前排上半格或下半格）、`tall` 整高 |
| `size` | `[宽, 深]`，宽度会用上，深度由所在的排决定 |
| `floor` | 地板：`wood` `wood2` `tile` `carpet` `concrete` |
| `doors` | 门可以开在哪面墙、离墙中点多远，例如 `{n: 0.5, e: 0}`。按「放在客厅左边」的朝向写 |
| `furniture` | 家具列表：`type` 加位置和尺寸。坐标写相对房间中心的偏移，或者贴墙写 `"n+0.5"`（离北墙 0.5） |
| `spots` | 住户能去的位置：`label` 写进动态，`pose` 姿势（`stand` `sit` `sit_low` `sit_floor` `lie`），`face` 朝向，`tags` 给活动匹配用 |

家具类型在 `web/js/furniture.js` 的 `FURNITURE` 里，现有：`bed desk chair shelf bookshelf sofa armchair table coffee_table rug mat lamp plant cabinet fridge counter tv beanbag boxes`。没登记的类型会画成灰盒子，不会报错。

**加活动**：`activities.yaml` 里一条一个。`spots` 写位置的 tags，有这个 tag 的位置都可能被选中，所以新房间只要给位置打上已有的 tag（比如 `sofa`、`pc`），就会自动有人去。

**加内容来源**：`home/sources.py` 里写一个 `Source` 子类，登记到 `SOURCES`，再在 `home.yaml` 的 `sources` 里开启。

改完配置、模板或活动，在页面「设置」里点「重新读取配置」，或者重启进程。内容来源的改动要重启才生效。

## 页面

- **动态**（右侧）：谁在哪做了什么。点开能看到她的感想和原链接；「看到了」是告诉她你看过了。
- **聊天**（左下）：家里的群。`@阿C` 只有她回；不 @ 人时随机一两个醒着的人接话，至少有一个人回你；住户之间互相接话最多 3 轮。睡着的人只有被你 @ 才会醒来迷糊地回一句。群里正热闹时，她们想说的话会先排着（「刚才谁想说话」），等安静下来再发。
- **住户卡片**：点小人或名牌打开，能看今天调用了几次、记得的事，让她现在去做点什么，或者导出她的 3D 形象。
- **设置**：全屋暂停 / 恢复、重新检查接入、重新读取配置、3D 小人 / 立绘、内墙高矮、文字大小（房间名称、住户名字、对话气泡、头顶表情、面板文字，存在各自的浏览器里）、内容来源状态。
- 右侧按钮：动态、住户、设置、3D / 立绘切换、白天 / 夜晚预览。顶栏：小窝时间、谁在家、左右转 90°、全景。
- 设了 `access_token` 的话，第一次打开会要你输入口令。

## 游乐场、互动和记忆

**游乐场**：大门外的户外场地，模板是 `rooms/playground.yaml`。配置不写 `outdoors` 就默认有，写 `outdoors: []` 就没有。住户只在白天（7 点到 19 点）去。设施在 `web/js/furniture.js`，spot 用 `ride` 和 `seat` 指向设施，住户到位后跟着设施动。

**互动**：`activities.yaml` 里写 `together: true` 的活动会拉上另一个闲着的住户。同屋的人偶尔互相搭句话，这种只冒气泡、不调用模型。住户卡片上能打招呼、摸头、投喂、叫去游乐场，这些也不调用模型；设置里能叫大家一起去。

**记忆**：在住户卡片里能增加、修改、置顶和删除。每人最多留 60 条未置顶的记忆（置顶的不占名额），满了先删已整理的、分量低的。相似的事不重复存，只提高分量。每次调用模型按相关度、分量和新旧挑几条，置顶的优先。入睡时如果当天攒了 4 条以上，每人调用一次模型并成一条，原来的标“已整理”，不再进提示词；关掉用 `life.memory_reflect: false`。

## 关系、天气、留言、日报和回放

**关系**：住户各自记着对别人和对你的印象，一起玩、群里接话、你摸头或留言都会让分数上涨，太久没来往会慢慢掉回去。分数决定更愿意拉谁一起玩，上次聊到的内容会放进提示词，下次见面能接上。住户卡片里能看。

**天气和节日**：天气是模拟的，不联网，每 6 小时可能变一次，下雨时住户不去户外，已经在外面的会回屋；设置里能手动换，三小时后恢复自然变化。内置常见节日，农历节日列到 2030 年，自己的节日写在 `life.festivals`。节日当天门口挂灯笼，住户会一起布置屋子（`activities.yaml` 里的 `festival: true`）。平时偶尔发生点小事，不调用模型。

**你来看她们**：隔 4 小时以上打开页面算来了一趟，醒着的住户会打招呼。你在群里说的话会记成记忆，右侧信箱能给某个住户留言，醒着时会看到并回你；页面关着时住户偶尔也会给你留一句，有未读时信箱上有红点。

**日报和回放**：日报从当天的动态和群聊现算，不调用模型。回放按住户的足迹重现某一天，足迹保留 14 天，升级前的日子没有足迹。

**省额度**：页面关掉 30 分钟后，住户少写感想、换活动慢一点；当天用到额度的 80% 也会少写，留给回你的话。设置里能看每人的调用次数和 token；模拟模式的 token 是估的。要看费用，给 driver 配 `price`，见 `home.example.yaml`。

## 外部控制台（可选）

`sdk/home_module.py` 是一个模块协议的实现，页面和接口都靠它提供。默认单独运行；配了 `COZY_HUB` 环境变量或 `--hub URL`，才会把状态面板注册到外部控制台。

## 文件

```
ai-cozy-home/
├── home/
│   ├── server.py      入口：小窝页面和接口、实时推送
│   ├── life.py        日常：作息、活动、动态、群聊接话、关系、留言、日报、额度
│   ├── days.py        天气、节日、偶发小事
│   ├── living.py      心情、小动作、长期目标、集体活动
│   ├── drivers.py     接入层：claude_cli / codex_cli / openai_api / anthropic_api / mock
│   ├── layout.py      按住户和房间模板拼房子
│   ├── sources.py     内容来源：B站热门、RSS、书架
│   ├── prompts.py     提示词
│   └── store.py       SQLite 存档（data/home.db）
├── rooms/             房间模板，一种房间一个 yaml
├── activities.yaml    活动
├── home.example.yaml  配置样例（复制成 home.yaml 再改）
├── web/               页面（纯 HTML/JS，不用构建；three.js 已放在 web/vendor）
├── skin/characters/   立绘
├── sdk/               网页服务和模块协议
├── scripts/           安装和启动脚本（windows/ 下是 Windows 版）
├── deploy/systemd/    开机自启
└── tests/             测试：python -m unittest discover -s tests
```

## 素材说明

`skin/` 里四位住户的立绘和 3D 模型由 AI 工具生成后加工而成。名字里的 Claude、GPT、DeepSeek、Kimi 等只用来标注接入的模型，这些商标归各自所有者，本项目与它们没有关联。代码以 MIT 许可证发布，three.js 的许可见 `web/vendor/three/LICENSE`。

## 已知限制

- B 站热门接口偶尔要 cookie 才返回内容（取不到时住户会改去做别的事），需要时把 cookie 放进环境变量 `BILI_COOKIE`。
- Claude Code 的参数和输出格式在 2.1.319 上实际调用核对过；Codex 只在 0.167.0 上核对了参数能被接受，没有登录跑过；API 接入按接口格式写的，没用真实 key 跑过。第一次正式运行时留意「设置」里的接入状态和日志。
- 手机全景下房间名牌会互相重叠，放大后正常。
