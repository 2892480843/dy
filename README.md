# 抖音旅行规划 Agent

一个从抖音视频链接生成旅行方案的 MVP。前端使用 Next.js、Tailwind 和 ShadUI 风格组件，后端使用 FastAPI 和 DeepAgents。

## 目录

- `web/`：移动端优先的网页控制台
- `api/`：抖音解析、旅行工具、DeepAgents 规划接口

## 本地运行

后端：

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd web
npm install
cp .env.example .env.local
npm run dev
```

打开 http://localhost:3000 体验。

## 环境变量

后端没有 `OPENAI_API_KEY` 时会自动使用本地兜底规划，保证流程可跑通。接入模型后，DeepAgents 会负责调用旅行工具并生成更细的方案。

大模型配置写在 `api/.env`：

```env
OPENAI_API_KEY=你的真实 API key
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
QWEN_ASR_API_KEY=你的百炼/DashScope API key
QWEN_ASR_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_ASR_MODEL=qwen3-asr-flash
QWEN_ASR_STREAM=true
```

如果使用 OpenAI 官方接口，`OPENAI_BASE_URL` 留空即可。如果使用 DeepSeek、通义千问等 OpenAI-compatible 接口，把对应 base url 填到 `OPENAI_BASE_URL`。填完后重启后端，并访问 `http://localhost:8000/api/llm/status` 检查 `enabled` 是否为 `true`。

抖音复刻流程会调用 `https://api.bugpk.com/api/douyin?url=...` 解析视频，并把 `data.music.url` 的音频保存到 `api/data/audio/`。音频保存后优先用本地文件的 Base64 Data URL 调用 Qwen3-ASR；音频过大时会退回使用解析到的公网音频 URL。后端会等待 Qwen3-ASR 完成后再调用大模型总结，并按 `data.video_id` 把语音转写和结构化分析缓存到 `api/data/cache/douyin/`。

真实数据源配置：

- 地图/天气：在 `api/.env` 配置 `AMAP_API_KEY` 后，会调用高德 POI、地理编码和天气接口。
- 12306 MCP：ModelScope 服务页为 https://modelscope.cn/mcp/servers/bwxnwnx/12306 。复制托管 MCP 地址到 `MCP_12306_URL`，或复制本地启动命令到 `MCP_12306_COMMAND` / `MCP_12306_ARGS`。
- 酒店 MCP：ModelScope 服务页为 https://modelscope.cn/mcp/servers/liu860502/Hotel_MCP 。复制托管 MCP 地址到 `MCP_HOTEL_URL`，或复制本地启动命令到 `MCP_HOTEL_COMMAND` / `MCP_HOTEL_ARGS`。

如果 MCP 需要鉴权，可以设置 `MCP_12306_BEARER_TOKEN`、`MCP_HOTEL_BEARER_TOKEN`，或用共享的 `MODELSCOPE_SDK_TOKEN`。
