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
QQBOT_SANDBOX=true
QQBOT_FAQ_PATH=config/faq.yaml
NOTE_ROOT=C:\Users\test\Desktop\study\study
AUTH_CONFIG_PATH=config/auth.yaml
BOT_OWNER_USER_IDS=user_id_1,user_id_2
FEATURE_NAMES_PATH=config/features.yaml
COC_API_TOKEN=你的部落冲突API Token
COC_TRANSLATIONS_PATH=config/coc_translations.yaml
```

沙箱测试阶段保持 `QQBOT_SANDBOX=true`，正式环境改为 `false`。

## FAQ 配置

本地问答配置在 `config/faq.yaml`：

- `question` 用于精确匹配。
- `keywords` 用于关键词匹配。
- `answer` 是回复内容。

## 笔记功能

笔记目录由 `.env` 中的 `NOTE_ROOT` 指定，机器人只会访问该目录下的 Markdown 文件。笔记列表、查看、新增、修改都需要“笔记”功能的 `owner`、`admin` 或 `user` 身份。

新增笔记：

```text
新增笔记 标题：Git 内容：这里是笔记内容
```

修改笔记：

```text
修改笔记 标题：Git 内容：这里是追加内容
```

修改笔记只会把内容追加到已有笔记末尾，不会覆盖原内容。

查询笔记列表：

```text
笔记列表
```

查看笔记内容：

```text
查看笔记：Git
```

查看笔记只读取 `NOTE_ROOT` 目录下的 Markdown 文件；内容较长时会截断显示。

## 部落冲突查询

部落冲突玩家查询使用 Clash of Clans 官方 API。需要在开发者后台创建 API Token，并在 `.env` 中配置：

```text
COC_API_TOKEN=你的部落冲突API Token
```

查询玩家：

```text
查询玩家：#ABC123
查看玩家：#ABC123
部落冲突玩家：#ABC123
```

查询玩家会返回玩家基础信息，并附带英雄、法术、兵种、英雄装备的当前等级和最高等级。

玩家标签可以带 `#`，也可以省略 `#`。如果 API 返回 403，请检查 Token 是否正确，以及当前服务器公网 IP 是否在 Clash of Clans 开发者后台的 Token 白名单中。

官方 API 返回的兵种、英雄、法术、装备名称是英文。机器人会读取 `COC_TRANSLATIONS_PATH` 指向的本地翻译表，按中国服常用中文名输出；翻译表未覆盖的新单位会保留英文，补充 `config/coc_translations.yaml` 后重启即可生效。

查询建筑剩余时间：

```text
查询建筑剩余时间：#ABC123
查看建筑剩余时间：#ABC123
```

Clash of Clans 官方 API 当前不返回建筑列表、建筑等级或升级结束时间，所以机器人会返回该限制说明，不能给出真实剩余时间。

其他查询：

```text
查询部落战：#CLAN1
查询都城突袭：#CLAN1
查询玩家战斗日志：#PLAYER1
查询玩家联赛历史：#PLAYER1
```

列表类结果默认只展示最近几条，避免 QQ 单条回复过长。

部落冲突查询需要“部落冲突”功能权限：

```text
设置权限 用户：user_openid 功能：部落冲突 身份：user
```

## 身份权限

首次运行前先在 `.env` 中配置机器人所有者：

```text
AUTH_CONFIG_PATH=config/auth.yaml
BOT_OWNER_USER_IDS=user_id_1,user_id_2
FEATURE_NAMES_PATH=config/features.yaml
```

多个用户 ID 使用英文逗号分隔。机器人从 QQ 消息事件中读取用户 ID/openid；普通 QQ 号通常不是这里要填的值。

启动后收到消息时，控制台会打印：

```text
bot debug: event_type=c2c_message user_id=xxx
```

也可以给机器人发送：

```text
查看我的ID
```

把这里的 `xxx` 填入 `BOT_OWNER_USER_IDS` 作为初始所有者。如果私发消息没有任何打印，请确认 QQ 开放平台已开启 C2C/私信消息事件权限，并在修改代码后重启 `main.py`。

所有者可以在 QQ 会话中设置任意功能权限：

```text
设置权限 用户：user_openid 功能：笔记 身份：user
设置权限 用户：user_openid 功能：笔记 身份：guest
设置权限 用户：user_openid 功能：笔记 身份：admin
设置权限 用户：user_openid 功能：部落冲突 身份：user
```

管理员只能在自己拥有 `admin` 身份的功能内，把其他用户设置为 `user` 或 `guest`。用户可以使用对应功能；游客不能使用对应功能。

群聊内可以通过 @ 提升别人对应功能的权限，每次只提升一层，最高只能提升到发起人身份的下一层：

```text
@机器人 提升笔记权限 @某某
@机器人 提升部落冲突权限 @某某
```

功能中文名由 `FEATURE_NAMES_PATH` 指向的 YAML 文件维护，默认是 `config/features.yaml`：

```yaml
features:
  notes: 笔记
  clash: 部落冲突
```

查看权限：

```text
查看权限
查看权限 用户：user_openid
```

权限会持久化到 `AUTH_CONFIG_PATH` 指向的 YAML 文件，默认是 `config/auth.yaml`：

```yaml
owners:
  - owner_openid
features:
  notes:
    user_openid: user
  clash:
    user_openid: user
```

## 后续接入 LLM

QQ 消息事件处理层只依赖 `AnswerProvider.answer(user_id, text, context) -> str`。后续接入 LLM 时，新增一个 Provider 实现并在 `main.py` 中替换即可，不需要改事件处理逻辑。

## 测试

```bash
pytest
```
