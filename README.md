# QQ 问答机器人

基于腾讯官方 Python SDK `qq-botpy` 实现的 QQ 问答机器人。第一版使用本地 FAQ 完成用户问答，后续可通过 `AnswerProvider` 接口扩展到 LLM。

## 框架选择

- 已选：`qq-botpy`。腾讯官方 Python SDK，适合快速跑通 QQ 机器人收发消息。
- 备选：FastAPI Webhook。更贴近长期生产部署，但需要公网 HTTPS 回调地址。
- 备选：`qqbot-agent-sdk` 或社区 SDK。适合更底层控制协议细节，第一版暂不采用。

## 安装运行

```bash
pip install -r requirements.txt
copy .env.example .env
python main.py
```

运行前需要在 `.env` 中填入 QQ 开放平台的 `AppID` 和 `AppSecret`。

## FAQ 配置

本地问答配置在 `config/faq.yaml`：

- `question` 用于精确匹配。
- `keywords` 用于关键词匹配。
- `answer` 是回复内容。

## 后续接入 LLM

QQ 消息事件处理层只依赖 `AnswerProvider.answer(user_id, text, context) -> str`。后续接入 LLM 时，新增一个 Provider 实现并在 `main.py` 中替换即可，不需要改事件处理逻辑。

## 测试

```bash
pytest
```
