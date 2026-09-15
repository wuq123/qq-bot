# QQ 问答机器人

基于腾讯官方 Python SDK `qq-botpy` 实现的 QQ 问答机器人。第一版使用本地 FAQ 完成用户问答，后续可通过 `AnswerProvider` 接口扩展到 LLM。

## 框架选择

- 已选：`qq-botpy`。腾讯官方 Python SDK，适合快速跑通 QQ 机器人收发消息。
- 备选：FastAPI Webhook。更贴近长期生产部署，但需要公网 HTTPS 回调地址。
- 备选：`qqbot-agent-sdk` 或社区 SDK。适合更底层控制协议细节，第一版暂不采用。

## 安装运行

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe main.py
```

运行前需要在 `.env` 中填入 QQ 开放平台的 `AppID` 和 `AppSecret`。

已创建 `.venv` 和 `.env` 时，后续直接启动：

```powershell
// 方式一
.\.venv\Scripts\python.exe main.py

// 方式二
.venv\Scripts\activate
python main.py
```

`.env` 配置示例：

```text
QQBOT_APP_ID=你的AppID
QQBOT_APP_SECRET=你的AppSecret
APP_CONFIG_PATH=config/app.yaml
BOT_OWNER_USER_IDS=user_id_1,user_id_2
COC_API_TOKEN=你的部落冲突API Token
DEEPSEEK_API_KEY=你的DeepSeek API Key
ONEBOT_ACCESS_TOKEN=你的OneBot访问Token
```

非敏感运行参数、路径、功能名、LLM 与 OneBot 设置统一保存在 `config/app.yaml`；`.env` 只保存凭据、Token 与所有者 ID。沙箱测试阶段保持 `config/app.yaml` 中 `bot.sandbox: true`，正式环境改为 `false`。

群聊@机器人时需要切换至正式环境

## 帮助菜单

发送：

```text
帮助
```

机器人会返回带 QQ 指令按钮的功能列表。点击“笔记”“部落冲突”“鸣潮”“权限”“FAQ”会自动发送对应帮助命令：

```text
帮助 笔记
帮助 部落冲突
帮助 鸣潮
帮助 权限
帮助 FAQ
```

如果当前 QQ 场景不支持 markdown 或按钮，机器人会降级为纯文本帮助，仍可手动输入上面的命令。

## FAQ 配置

本地问答配置在 `config/faq.yaml`：

- `question` 用于精确匹配。
- `keywords` 用于关键词匹配。
- `answer` 是回复内容。

## 笔记功能

笔记目录由 `config/app.yaml` 的 `paths.note_root` 指定，机器人只会访问该目录下的 Markdown 文件。可识别的 QQ 用户默认是 `user`，可以直接列出和查看笔记；新增、创建、修改和追加共享笔记仅允许“笔记”功能的 `admin` 或全局 `owner`。

新增笔记：

```text
新笔记：Git 这里是笔记内容
新增笔记 标题：Git 内容：这里是笔记内容
```

修改笔记：

```text
改笔记：Git 这里是追加内容
修改笔记 标题：Git 内容：这里是追加内容
```

修改笔记只会把内容追加到已有笔记末尾，不会覆盖原内容。

查询笔记列表：

```text
笔记列表
```

查看笔记内容：

```text
看笔记：Git
查看笔记：Git
```

查看笔记只读取 `paths.note_root` 目录下的 Markdown 文件；内容较长时会截断显示。

## 部落冲突查询

部落冲突玩家查询使用 Clash of Clans 官方 API。需要在开发者后台创建 API Token，并在 `.env` 中配置：

```text
COC_API_TOKEN=你的部落冲突API Token
```

查询玩家：

```text
玩家：#ABC123
查询玩家：#ABC123
查看玩家：#ABC123
部落冲突玩家：#ABC123
```

查询玩家会返回玩家基础信息，并附带英雄、法术、兵种、英雄装备的当前等级和最高等级。

玩家标签可以带 `#`，也可以省略 `#`。如果 API 返回 403，请检查 Token 是否正确，以及当前服务器公网 IP 是否在 Clash of Clans 开发者后台的 Token 白名单中。

官方 API 返回的兵种、英雄、法术、装备名称是英文。机器人会读取 `config/app.yaml` 的 `paths.coc_translations` 指向的本地翻译表，按中国服常用中文名输出；翻译表未覆盖的新单位会保留英文，补充 `config/coc_translations.yaml` 后重启即可生效。

查询建筑剩余时间：

```text
查询建筑剩余时间：#ABC123
查看建筑剩余时间：#ABC123
```

Clash of Clans 官方 API 当前不返回建筑列表、建筑等级或升级结束时间，所以机器人会返回该限制说明，不能给出真实剩余时间。

其他查询：

```text
部落战：#CLAN1
查询部落战：#CLAN1
都城：#CLAN1
查询都城突袭：#CLAN1
战斗日志：#PLAYER1
查询玩家战斗日志：#PLAYER1
联赛历史：#PLAYER1
查询玩家联赛历史：#PLAYER1
```

列表类结果默认只展示最近几条，避免 QQ 单条回复过长。

如果 `查询部落战：#CLAN1` 返回 API 拒绝访问，先确认 `COC_API_TOKEN` 和服务器公网 IP 白名单正确；如果玩家查询、都城突袭等其他接口正常，通常是目标部落在游戏内关闭了公开战争日志，官方 `currentwar` 接口不会返回战争详情。

可识别的 QQ 用户默认可以直接使用部落冲突查询；显式设置为该功能 `guest` 的用户会被拒绝。

## 鸣潮查询

鸣潮功能使用库街区登录态查询玩家数据，并用本地导入的唤取记录做抽卡分析。鸣潮没有类似 Clash of Clans 的公开开发者 API，不能只靠 UID 查询任意玩家完整私有数据。

`config/app.yaml` 配置：

```text
paths:
  wuwa_data_dir: data/wuwa
  wuwa_timeout: 10
```

可识别的 QQ 用户默认可以使用鸣潮登录、绑定、查询、抽卡导入和删除本人绑定；显式设置为该功能 `guest` 的用户会被拒绝。

推荐通过手机号验证码登录。手机号和验证码只能私聊发送：

```text
鸣潮登录：13800138000
鸣潮验证码：123456
```

登录成功后，机器人会读取库街区已绑定的鸣潮角色；只有一个角色或存在默认角色时会自动绑定。如果返回多个角色，根据提示发送：

```text
绑定鸣潮角色：101234567 区服：76402e5b20be2c39f095a152090afddc
```

验证码登录可能使库街区 App 当前登录失效。如果触发人机验证，本次短信不会发送，但登录状态仍会保留 10 分钟。按机器人回复提示，在库街区 App 登录页或 `https://wiki.kurobbs.com/pns/home` 点击右上角头像，使用同一手机号完成人机验证并获取短信，再回到机器人私聊发送 `鸣潮验证码：<验证码>`。无需在库街区页面完成登录。

也可以继续使用手动 Token；Token 同样只能私聊发送：

```text
绑定鸣潮Token：你的库街区token
绑定鸣潮角色：101234567
查看鸣潮绑定
删除鸣潮绑定
```

手机号、验证码不会写入本地文件；待输入验证码的进程内登录状态有效期为 10 分钟。Token 会保存到 `paths.wuwa_data_dir` 指向目录下的用户目录中，不会在普通回复中展示。第一版是本地明文文件，请只部署在可信机器上。

查询玩家数据：

```text
鸣潮面板
鸣潮体力
练度：今汐
鸣潮练度：今汐
```

不带角色名发送 `练度` 或 `鸣潮练度` 会返回当前读取到的角色列表。

查询成功后，面板、体力、角色练度和抽卡分析会返回本地实时生成的 PNG 图片。角色卡片包含角色立绘、属性、武器、声骸和技能，发送成功时仅返回图片，不附带重复文字；群聊与 C2C 图片通过 QQ 富媒体接口以 Base64 上传，不需要单独部署图床。角色卡生成、图片上传或发送失败时会自动回退为文本结果。

抽卡分析：

```text
导入鸣潮抽卡：<游戏内唤取记录URL>
导入鸣潮抽卡JSON：<导出的JSON>
抽卡分析
抽卡分析：角色活动
```

唤取记录 URL 需要用户在游戏内打开抽卡历史后复制，通常有时效限制。机器人只统计本地已导入记录，包括总抽数、五星/四星数量、当前垫数、平均五星抽数、最近五星和卡池统计。

## 身份权限

首次运行前先在 `.env` 中配置机器人所有者：

```text
BOT_OWNER_USER_IDS=user_id_1,user_id_2
```

多个用户 ID 使用英文逗号分隔。机器人从 QQ 消息事件中读取用户 ID/openid；普通 QQ 号通常不是这里要填的值。

启动后控制台应先打印：

```text
bot debug: starting sandbox=true intents=...
bot debug: ready robot=...
```

收到消息时，控制台会打印：

```text
bot debug: event_type=c2c_message user_id=xxx
```

也可以给机器人发送：

```text
查看我的ID
```

把这里的 `xxx` 填入 `BOT_OWNER_USER_IDS` 作为初始所有者。如果私发消息没有任何打印，请确认 QQ 开放平台已开启 C2C/私信消息事件权限，并在修改代码后重启 `main.py`。

群聊 @ 机器人没有回应时，先确认已经打印 `ready`，再看控制台是否打印：

```text
bot debug: event_type=group_at_message user_id=xxx
```

如果没有打印 `ready`，说明程序没有建立有效 WebSocket 连接，先检查 AppID/AppSecret、网络和沙箱配置。如果已打印 `ready` 但没有 `group_at_message`，说明群聊 @ 事件没有下发到程序，重点检查 QQ 开放平台是否开启群/C2C 公域消息事件、机器人是否已加入当前群、当前机器人使用范围是否允许该群、沙箱环境是否包含当前群成员。部分 QQ 客户端还需要群主在群机器人设置中允许机器人接收群消息；如果打印了 `group_msg_reject`，说明群聊拒绝机器人主动消息，需要在 QQ 侧重新允许接收机器人消息。

所有者可以在 QQ 会话中设置任意功能权限：

```text
设置权限 用户：user_openid 功能：笔记 身份：user
设置权限 用户：user_openid 功能：笔记 身份：guest
设置权限 用户：user_openid 功能：笔记 身份：admin
设置权限 用户：user_openid 功能：部落冲突 身份：user
设置权限 用户：user_openid 功能：鸣潮 身份：user
```

所有可识别的 QQ 用户在没有显式权限记录时默认为各功能的 `user`，该默认值不会写入 `auth.yaml`。显式设置为 `guest` 会禁用对应功能，无法识别的用户也会被拒绝。管理员只能在自己拥有 `admin` 身份的功能内，把其他用户设置为 `user` 或 `guest`；只有“笔记”功能的 `admin` 和全局 `owner` 可以修改共享笔记。

群聊内可以通过 @ 提升别人对应功能的权限，每次只提升一层，最高只能提升到发起人下一层级的身份。默认用户当前为 `user`，因此 owner 首次提升会直接设为 `admin`；功能 admin 只能把显式 `guest` 恢复为 `user`：

```text
@机器人 提升笔记权限 @某某
@机器人 提升部落冲突权限 @某某
@机器人 提升鸣潮权限 @某某
```

功能中文名由 `config/app.yaml` 的 `features` 分区维护：

```yaml
features:
  notes: 笔记
  clash: 部落冲突
  wuwa: 鸣潮
```

查看权限：

```text
查看权限
查看权限 用户：user_openid
```

用户没有显式权限记录时，“查看权限”会显示“默认 user”。

权限会持久化到 `config/app.yaml` 的 `paths.auth` 指向的 YAML 文件，默认是 `config/auth.yaml`：

```yaml
owners:
  - owner_openid
features:
  notes:
    user_openid: user
  clash:
    user_openid: user
```

## OpenAI 兼容 LLM

普通消息会先匹配业务命令和本地 FAQ，只有 FAQ 未命中时才调用 LLM。默认配置使用 DeepSeek 的 `deepseek-flash`；在 DeepSeek 平台创建 API Key 后写入 `.env`：

```text
DEEPSEEK_API_KEY=你的DeepSeek API Key
```

模型配置位于 `config/app.yaml` 的 `llm` 分区：

```yaml
llm:
  enabled: true
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  model: deepseek-flash
  context_rounds: 5
  timeout: 30
  max_tokens: 1024
  temperature: 1.0
  tool_call_mode: json
  max_tool_iterations: 3
  confirmation_ttl_seconds: 120
```

- `enabled` 控制是否启用 LLM。关闭时继续使用 FAQ 的原兜底回答。
- `api_key_env` 是保存 API Key 的环境变量名，密钥本身不要写入 YAML。
- `context_rounds` 是每位用户在当前进程内保留的对话轮数；设为 `0` 表示单轮问答，重启机器人后历史会清空。
- `base_url` 和 `model` 可替换为其他支持 OpenAI Chat Completions 的服务配置，无需修改代码。
- `tool_call_mode` 可设为 `json` 或 `native`。默认的 DeepSeek 模型支持工具调用；如需使用原生 Function Call，可改为 `native`。
- `max_tool_iterations` 限制每次问答最多调用多少个工具，`confirmation_ttl_seconds` 控制待确认操作的有效时间。

FAQ 未命中后，LangChain Agent 会判断是直接回答，还是调用笔记、部落冲突、鸣潮、权限或帮助工具。查询结果为文本时会交给模型整理；图片和按钮等富消息会直接回复。

由模型识别出的笔记写入、权限修改、鸣潮绑定、抽卡导入和删除操作不会立即执行。机器人会返回操作摘要，需要在当前会话中发送：

```text
确认执行
取消执行
```

手机号、验证码和 Token 不会交给模型识别，仍需在私聊使用原有固定命令。启用 LLM 但对应密钥环境变量为空时，机器人会继续使用 FAQ 兜底，同时记录配置提示。

## OneBot 群聊随机回复

QQ 官方群消息事件只包含 @ 机器人的消息。如需从未 @ 的普通群聊中随机回复，需要单独部署兼容 OneBot 11 的网关，并开启正向 WebSocket 服务。本项目不会安装或管理 OneBot 网关。

在 `.env` 配置：

```text
ONEBOT_ACCESS_TOKEN=你的OneBot访问Token
```

默认 `config/app.yaml` 的 `onebot` 分区：

```yaml
onebot:
  enabled: true
  ws_url: ws://127.0.0.1:3001
  access_token_env: ONEBOT_ACCESS_TOKEN
  reply_probability: 0.02
  context_messages: 5
  max_message_chars: 500
  reconnect_delay: 5
  startup_timeout_seconds: 10
  failover_after_failures: 3
  reply_cooldown_seconds: 30
  max_reply_chars: 200
```

配置好网关地址和 Token 后，将 `enabled` 改为 `true`。NapCat 是主消息入口：私聊和 @NapCat 的群消息会执行全部业务命令、帮助、FAQ 和 LLM；@其他账号的群消息会忽略，避免与官方机器人重复回复。未 @ 的普通群文本独立以 2% 概率调用 LLM；这是长期平均每五十条回复一次，并不保证任意连续五十条恰好回复一次。

抽中时会把该群最近 `context_messages` 条未 @ 文本发送给已配置的外部 LLM，群之间隔离，重启后清空。消息不会携带 QQ 用户 ID 或昵称，单条会按 `max_message_chars` 截断；手机号、验证码和鸣潮 Token 等敏感消息不会进入上下文。随机群聊回复只生成普通文本，不调用 Agent 工具。同一群生成回复时不会重复调用，发送成功后会等待 `reply_cooldown_seconds` 秒；回复超过 `max_reply_chars`、或复述上下文时会被丢弃。

官方 botpy 机器人会继续运行：用户 @官方机器人账号时仍可获得原有 Markdown 按钮帮助。NapCat 与官方机器人是两个 QQ 身份；NapCat 连续 `failover_after_failures` 次重连失败后，会记录切换到 botpy 备用状态。官方 botpy 无法接收未 @ 的普通群消息，因此故障期间随机群聊回复会暂停，改为 @官方机器人使用功能。

NapCat 安装在项目上层目录 `F:\agent\NapCatQQ`。不要直接双击窗口后关闭，使用 [start-napcat.cmd](F:/agent/NapCatQQ/start-napcat.cmd) 启动；失败日志会保留在 `F:\agent\NapCatQQ\logs\startup.log`。

## 21 点文字游戏

21 点仅通过 OneBot 11 / NapCat 提供，不接入官方 `qq-botpy`。私聊发送 `21点` 或 `21点 下注：10` 开始一局；群聊需 @NapCat 后发送该命令，牌局开始后发送操作命令无需再 @。下注仅用于本局虚拟盈亏展示，不保存余额或涉及真实货币。

初始两张牌中 A 与任意 10 点牌构成 Blackjack，赔付为 3:2。庄家发一张明牌与一张暗牌：明牌为 10 点时会立即检查 Blackjack；明牌为 A 时可发送 `买保险` 或 `不买保险`。保险金额为初始下注的一半，庄家拥有 Blackjack 时净赔付为保险下注的两倍。

正常回合可发送 `要牌`、`停牌`、`加倍`、`分牌`、`投降` 或 `结束21点`。加倍会使本手下注翻倍、仅再发一张牌并自动停牌；两张相同牌可分成两手；首手未要牌时可以投降并损失一半下注。A 自动按不爆牌时的最大点数计算，庄家点数低于 17 时必须要牌、软 17 停牌。同一群或私聊会话仅保留一局，群聊中只有开局玩家可以操作。

## 测试

```bash
pytest
```
