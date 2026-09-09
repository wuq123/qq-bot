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
NOTE_ALLOWED_USER_IDS=user_id_1,user_id_2
```

沙箱测试阶段保持 `QQBOT_SANDBOX=true`，正式环境改为 `false`。

## FAQ 配置

本地问答配置在 `config/faq.yaml`：

- `question` 用于精确匹配。
- `keywords` 用于关键词匹配。
- `answer` 是回复内容。

## 笔记功能

笔记目录由 `.env` 中的 `NOTE_ROOT` 指定，机器人只会访问该目录下的 Markdown 文件。笔记列表、查看、新增、修改都需要用户 ID 在 `NOTE_ALLOWED_USER_IDS` 白名单中。

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

身份校验：

```text
NOTE_ALLOWED_USER_IDS=user_id_1,user_id_2
```

多个用户 ID 使用英文逗号分隔。机器人从 QQ 消息事件中读取用户 ID/openid，只有白名单内用户可以操作笔记；FAQ 问答不受限制。

启动后收到消息时，控制台会打印：

```text
bot debug: event_type=c2c_message user_id=xxx
```

把这里的 `xxx` 填入 `NOTE_ALLOWED_USER_IDS`。如果私发消息没有任何打印，请确认 QQ 开放平台已开启 C2C/私信消息事件权限，并在修改代码后重启 `main.py`。

## 后续接入 LLM

QQ 消息事件处理层只依赖 `AnswerProvider.answer(user_id, text, context) -> str`。后续接入 LLM 时，新增一个 Provider 实现并在 `main.py` 中替换即可，不需要改事件处理逻辑。

## 测试

```bash
pytest
```
