from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import ipaddress
import inspect
import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Literal
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

API_DIR = Path(__file__).resolve().parents[1]
load_dotenv(API_DIR / ".env")

try:
    from deepagents import create_deep_agent
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - dependency can be intentionally absent in mock mode
    create_deep_agent = None
    ChatOpenAI = None

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except Exception:  # pragma: no cover - MCP is optional until configured
    ClientSession = None
    StdioServerParameters = None
    sse_client = None
    stdio_client = None
    streamablehttp_client = None


POPULAR_DESTINATIONS = [
    "北京",
    "上海",
    "广州",
    "深圳",
    "成都",
    "重庆",
    "长沙",
    "武汉",
    "西安",
    "南京",
    "杭州",
    "苏州",
    "厦门",
    "泉州",
    "福州",
    "青岛",
    "大连",
    "哈尔滨",
    "沈阳",
    "天津",
    "郑州",
    "洛阳",
    "开封",
    "济南",
    "烟台",
    "昆明",
    "大理",
    "丽江",
    "香格里拉",
    "西双版纳",
    "桂林",
    "阳朔",
    "北海",
    "三亚",
    "海口",
    "贵阳",
    "遵义",
    "黄山",
    "婺源",
    "景德镇",
    "南昌",
    "张家界",
    "凤凰古城",
    "稻城亚丁",
    "九寨沟",
    "阿坝",
    "甘孜",
    "拉萨",
    "林芝",
    "敦煌",
    "兰州",
    "西宁",
    "青海湖",
    "乌鲁木齐",
    "喀什",
    "伊犁",
    "呼伦贝尔",
    "阿尔山",
    "香港",
    "澳门",
    "台北",
]

SPOT_HINT_WORDS = (
    "山",
    "湖",
    "海",
    "岛",
    "寺",
    "庙",
    "城",
    "镇",
    "村",
    "街",
    "巷",
    "湾",
    "馆",
    "园",
    "谷",
    "桥",
    "瀑布",
    "草原",
    "古城",
    "夜市",
)

POPULAR_SPOTS = [
    "橘子洲",
    "岳麓山",
    "太平老街",
    "五一广场",
    "解放碑",
    "洪崖洞",
    "磁器口",
    "宽窄巷子",
    "锦里",
    "武侯祠",
    "西湖",
    "灵隐寺",
    "雷峰塔",
    "鼓浪屿",
    "曾厝垵",
    "中山路",
    "兵马俑",
    "大唐不夜城",
    "钟楼",
    "故宫",
    "天坛",
    "颐和园",
    "外滩",
    "武康路",
    "迪士尼",
    "拙政园",
    "平江路",
    "栈桥",
    "八大关",
    "洱海",
    "大理古城",
    "玉龙雪山",
    "丽江古城",
    "张家界国家森林公园",
    "天门山",
    "凤凰古城",
    "九寨沟",
    "稻城亚丁",
    "莫高窟",
    "鸣沙山",
    "青海湖",
    "茶卡盐湖",
]

BudgetStyle = Literal["budget", "comfort", "luxury"]
TransportMode = Literal["train", "any", "car", "flight"]

MCP_12306_SOURCE_URL = "https://modelscope.cn/mcp/servers/bwxnwnx/12306"
MCP_HOTEL_SOURCE_URL = "https://modelscope.cn/mcp/servers/liu860502/Hotel_MCP"
DOUYIN_AUDIO_DIR = API_DIR / "data" / "audio"
DOUYIN_ANALYSIS_CACHE_DIR = API_DIR / "data" / "cache" / "douyin"
MAX_ASR_LOCAL_AUDIO_BYTES = 9 * 1024 * 1024


class DouyinParseRequest(BaseModel):
    url: str = Field(..., min_length=5)


class DouyinParseResponse(BaseModel):
    status: Literal["success", "needs_manual_input"]
    title: str
    destination: str
    spots: list[str]
    needsManualInput: bool
    message: str | None = None


class ReplicatePlaceOption(BaseModel):
    id: str
    name: str
    type: Literal["spot", "food", "hotel", "shopping", "area", "other"] = "spot"
    reason: str = ""
    source: Literal["blogger", "nearby"] = "blogger"
    selected: bool = False


class DouyinAnalyzeResponse(BaseModel):
    videoId: str = ""
    cacheHit: bool = False
    status: Literal["success", "partial", "needs_manual_input"]
    title: str = ""
    destination: str = ""
    summary: str = ""
    transcript: str = ""
    audioSaved: bool = False
    audioLocalPath: str = ""
    audioUrl: str = ""
    spots: list[str] = Field(default_factory=list)
    foods: list[str] = Field(default_factory=list)
    budgetText: str = ""
    budgetAmount: int | None = None
    bloggerPlaces: list[ReplicatePlaceOption] = Field(default_factory=list)
    nearbyPlaces: list[ReplicatePlaceOption] = Field(default_factory=list)
    needsManualInput: bool = False
    message: str = ""


class ReverseGeoResponse(BaseModel):
    status: Literal["success", "needs_manual_input"]
    city: str
    message: str = ""


class PlacePhotoResponse(BaseModel):
    status: Literal["success", "not_found", "needs_config"]
    imageUrl: str = ""
    title: str = ""
    message: str = ""


class ImageSearchResponse(BaseModel):
    status: Literal["success", "not_found", "needs_config"]
    imageUrl: str = ""
    title: str = ""
    sourceUrl: str = ""
    message: str = ""


class TripPreferences(BaseModel):
    link: str = ""
    videoId: str = ""
    videoTitle: str = ""
    videoSummary: str = ""
    videoTranscript: str = ""
    videoBudgetText: str = ""
    videoBudgetAmount: int | None = Field(default=None, ge=0, le=10000000)
    videoFoods: list[str] = Field(default_factory=list)
    routeReferencePlaces: list[str] = Field(default_factory=list)
    origin: str = ""
    destination: str = ""
    spots: list[str] = Field(default_factory=list)
    departureDate: str = ""
    returnDate: str = ""
    startDateRange: str = ""
    days: int = Field(default=3, ge=1, le=14)
    travelers: int = Field(default=1, ge=1, le=20)
    budgetStyle: BudgetStyle = "comfort"
    transportMode: TransportMode = "train"
    trainSeatPreference: str = "不限"
    hotelPreference: str = "交通方便"
    hotelBudgetPerNight: int | None = Field(default=None, ge=0, le=100000)
    travelInterests: list[str] = Field(default_factory=list)
    spotTypes: list[str] = Field(default_factory=list)
    notes: str = ""


class PlanRequest(BaseModel):
    preferences: TripPreferences


class RefineRequest(BaseModel):
    preferences: TripPreferences
    currentPlan: str
    feedback: str


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)
    style: str = "用清晰、温和、像旅行向导一样的语气朗读，语速适中，重点信息稍作停顿。"
    voice: str = ""


class TransportSummaryRequest(BaseModel):
    origin: str = ""
    destination: str = ""
    firstSpot: str = ""
    departureDate: str = ""
    transportMode: TransportMode = "train"
    seatPreference: str = "不限"


class TransportSummaryItem(BaseModel):
    label: str
    value: str
    detail: str = ""


class TransportSummaryResponse(BaseModel):
    status: Literal["success", "partial", "needs_manual_input"]
    origin: str = ""
    destination: str = ""
    mode: TransportMode = "train"
    items: list[TransportSummaryItem] = Field(default_factory=list)
    message: str = ""


def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [item.strip() for item in raw.split(",") if item.strip()]


app = FastAPI(title="Douyin Trip Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def llm_config_status() -> dict[str, Any]:
    api_key = _env("OPENAI_API_KEY")
    return {
        "enabled": bool(api_key),
        "hasApiKey": bool(api_key),
        "model": _env("OPENAI_MODEL", "gpt-4o-mini"),
        "baseUrl": _env("OPENAI_BASE_URL") or "OpenAI default",
        "deepAgentsInstalled": create_deep_agent is not None,
        "langchainOpenAIInstalled": ChatOpenAI is not None,
        "planningMode": "direct_llm_with_tool_context",
    }


@app.get("/api/llm/status")
async def llm_status() -> dict[str, Any]:
    return llm_config_status()


def tts_config_status() -> dict[str, Any]:
    api_key = _env("MIMO_TTS_API_KEY") or _env("OPENAI_API_KEY")
    return {
        "enabled": bool(api_key),
        "hasApiKey": bool(api_key),
        "model": _env("MIMO_TTS_MODEL", "mimo-v2.5-tts"),
        "baseUrl": _env("MIMO_TTS_BASE_URL") or _env("OPENAI_BASE_URL") or "https://api.xiaomimimo.com/v1",
        "voice": _env("MIMO_TTS_VOICE", "mimo_default"),
    }


@app.get("/api/tts/status")
async def tts_status() -> dict[str, Any]:
    return tts_config_status()


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    title = re.sub(r"[-_ ]*抖音.*$", "", title, flags=re.IGNORECASE).strip()
    return title[:160]


def extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        return text.strip()
    return match.group(0).rstrip("，。；;)")


async def fetch_title_from_url(raw_url: str) -> str:
    url = extract_first_url(raw_url)
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=8, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for selector in [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            'meta[name="description"]',
        ]:
            tag = soup.select_one(selector)
            content = tag.get("content") if tag else None
            if content:
                return clean_title(content)
        if soup.title and soup.title.text:
            return clean_title(soup.title.text)
    return ""


def _slug(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^\w\u4e00-\u9fa5-]+", "-", value.strip(), flags=re.UNICODE).strip("-")
    return text[:48] or fallback


def _stable_option_id(prefix: str, name: str) -> str:
    digest = hashlib.sha1(f"{prefix}:{name}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _clean_name(value: str, limit: int = 24) -> str:
    name = re.sub(r"\s+", "", str(value or ""))
    name = name.strip("，。；;、|｜#[]【】()（）《》「」“”\"'")
    name = re.sub(r"(附近|周边|一带|区域|可以|推荐|安排|打卡|游玩|吃)$", "", name)
    if not name or len(name) < 2:
        return ""
    return name[:limit]


def _unique_names(values: list[str], limit: int = 12) -> list[str]:
    names: list[str] = []
    for value in values:
        name = _clean_name(value)
        if not name:
            continue
        if any(item == name or item in name or name in item for item in names):
            continue
        names.append(name)
        if len(names) >= limit:
            break
    return names


def _json_from_text(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _find_first_url_field(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("url", "play_url", "audio", "music_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in data.values():
            found = _find_first_url_field(value)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_first_url_field(item)
            if found:
                return found
    return ""


def _extract_douyin_title(data: dict[str, Any]) -> str:
    candidates = [
        data.get("title"),
        data.get("desc"),
        data.get("text"),
        data.get("data", {}).get("title") if isinstance(data.get("data"), dict) else "",
        data.get("data", {}).get("desc") if isinstance(data.get("data"), dict) else "",
    ]
    for candidate in candidates:
        if candidate:
            return clean_title(str(candidate))
    return ""


def _extract_douyin_audio_url(data: dict[str, Any]) -> str:
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    music = nested.get("music") if isinstance(nested.get("music"), dict) else {}
    url = music.get("url")
    if isinstance(url, list):
        url = url[0] if url else ""
    if isinstance(url, str) and url.startswith("http"):
        return url
    return _find_first_url_field(music) or _find_first_url_field(nested)


def _extract_douyin_video_id(data: dict[str, Any]) -> str:
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates = [
        nested.get("video_id"),
        nested.get("aweme_id"),
        nested.get("id"),
        nested.get("item_id"),
        data.get("video_id"),
        data.get("aweme_id"),
        data.get("id"),
    ]
    for candidate in candidates:
        if candidate not in ("", None, []):
            return str(candidate).strip()
    return ""


def _video_cache_key(video_id: str, raw_url: str) -> str:
    if video_id:
        return _slug(video_id, "video")
    digest = hashlib.sha1(raw_url.strip().encode("utf-8")).hexdigest()[:20]
    return f"url-{digest}"


def _video_cache_path(video_id: str, raw_url: str) -> Path:
    return DOUYIN_ANALYSIS_CACHE_DIR / f"{_video_cache_key(video_id, raw_url)}.json"


def _load_video_analysis_cache(video_id: str, raw_url: str) -> DouyinAnalyzeResponse | None:
    path = _video_cache_path(video_id, raw_url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        response_data = data.get("response") if isinstance(data, dict) else data
        if not isinstance(response_data, dict):
            return None
        response_data["cacheHit"] = True
        if video_id and not response_data.get("videoId"):
            response_data["videoId"] = video_id
        return DouyinAnalyzeResponse.model_validate(response_data)
    except Exception:
        return None


def _save_video_analysis_cache(video_id: str, raw_url: str, response: DouyinAnalyzeResponse) -> None:
    DOUYIN_ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_response = response.model_dump()
    cache_response["cacheHit"] = False
    payload = {
        "video_id": video_id,
        "cache_key": _video_cache_key(video_id, raw_url),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "transcript": response.transcript,
        "llm_analysis": {
            "summary": response.summary,
            "destination": response.destination,
            "spots": response.spots,
            "foods": response.foods,
            "budgetText": response.budgetText,
            "budgetAmount": response.budgetAmount,
            "bloggerPlaces": [place.model_dump() for place in response.bloggerPlaces],
        },
        "response": cache_response,
    }
    _video_cache_path(video_id, raw_url).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")


async def fetch_douyin_payload(raw_url: str) -> dict[str, Any]:
    url = extract_first_url(raw_url)
    parsed = urlparse(url)
    if not url or not parsed.scheme or not parsed.netloc:
        raise RuntimeError("未找到抖音视频链接")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get("https://api.bugpk.com/api/douyin", params={"url": url})
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("抖音解析接口返回格式异常")
    return data


def _extension_from_audio_response(audio_url: str, content_type: str) -> str:
    content_type = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(content_type) if content_type else ""
    if guessed:
        return ".mp3" if guessed == ".mpga" else guessed
    path = urlparse(audio_url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".mp4"}:
        return suffix
    return ".mp3"


async def download_audio_to_local(audio_url: str, seed: str) -> tuple[Path, str]:
    if not audio_url:
        raise RuntimeError("未找到视频音频地址")
    DOUYIN_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }
    async with httpx.AsyncClient(timeout=60, headers=headers, follow_redirects=True) as client:
        response = await client.get(audio_url)
        response.raise_for_status()
    suffix = _extension_from_audio_response(audio_url, response.headers.get("content-type", ""))
    digest = hashlib.sha1(f"{seed}:{audio_url}".encode("utf-8")).hexdigest()[:16]
    path = DOUYIN_AUDIO_DIR / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{digest}{suffix}"
    path.write_bytes(response.content)
    return path, response.headers.get("content-type", "").split(";")[0].strip()


def _audio_data_uri(path: Path, content_type: str = "") -> str:
    mime_type = content_type or mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_stream_delta_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


async def async_transcribe_audio_qwen(
    audio_path: Path,
    audio_url: str,
    content_type: str = "",
    progress: Callable[[str, str, int], Awaitable[None]] | None = None,
) -> str:
    api_key = _env("QWEN_ASR_API_KEY") or _env("DASHSCOPE_API_KEY") or _env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("QWEN_ASR_API_KEY 或 DASHSCOPE_API_KEY 未配置")
    if not audio_path.exists():
        raise RuntimeError("本地音频文件不存在")

    if audio_path.stat().st_size <= MAX_ASR_LOCAL_AUDIO_BYTES:
        audio_data = _audio_data_uri(audio_path, content_type)
    elif audio_url:
        audio_data = audio_url
    else:
        raise RuntimeError("音频超过 10MB，且没有可供模型访问的公网音频 URL")

    base_url = (_env("QWEN_ASR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/")
    payload = {
        "model": _env("QWEN_ASR_MODEL", "qwen3-asr-flash"),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_data,
                        },
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": {
            "language": "zh",
            "enable_itn": True,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if _env("QWEN_ASR_STREAM", "true").lower() not in {"0", "false", "no"}:
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        transcript = ""
        last_reported = 0
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=stream_payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = _extract_stream_delta_text(chunk)
                        if not delta:
                            continue
                        transcript += delta
                        if progress and len(transcript) - last_reported >= 20:
                            last_reported = len(transcript)
                            await progress("asr", f"Qwen3-ASR 正在转写：已识别 {len(transcript)} 字。", 58)
            if transcript.strip():
                return transcript.strip()
        except Exception as exc:
            if progress:
                await progress("asr", f"Qwen3-ASR 流式转写未返回完整文本，改用一次性等待：{exc}", 56)

    async with httpx.AsyncClient(timeout=180) as client:
        if progress:
            await progress("asr", "正在等待 Qwen3-ASR 返回完整转写文本。", 58)
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
    return _extract_chat_text(response.json())


def _fallback_video_analysis(title: str, transcript: str, raw_text: str = "") -> dict[str, Any]:
    source = "\n".join(item for item in [title, transcript, raw_text] if item)
    destination = infer_destination(source)
    spots = infer_spots(source, destination)
    foods = _unique_names(
        re.findall(r"([\u4e00-\u9fa5]{2,14}(?:粉|面|鱼|肉|虾|鸡|鸭|糕|饼|汤|粥|饭|茶|火锅|烧烤|小吃|臭豆腐|糖油粑粑|米粉|咖啡))", source),
        limit=8,
    )
    budget_match = re.search(r"(?:花了|花费|预算|人均|一共|总共)[^\d]{0,8}(\d{2,6})(?:\s*元|块|rmb|RMB)?", source, flags=re.I)
    budget_text = budget_match.group(0) if budget_match else ""
    budget_amount = int(budget_match.group(1)) if budget_match else None
    return {
        "destination": destination,
        "summary": clean_title(title or transcript[:120]),
        "spots": spots,
        "foods": foods,
        "budgetText": budget_text,
        "budgetAmount": budget_amount,
        "bloggerPlaces": [{"name": item, "type": "spot", "reason": "视频中出现的路线点"} for item in spots],
    }


async def extract_video_analysis_json(title: str, transcript: str, raw_payload: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_video_analysis(title, transcript, _summarize_payload(raw_payload, 1200))
    if not (_env("OPENAI_API_KEY")):
        return fallback
    prompt = f"""
你要从抖音旅行视频信息中提取“复刻路线”所需数据，只返回 JSON，不要 Markdown。

视频标题：
{title or "无"}

Qwen3-ASR 转写文本：
{transcript or "无"}

解析接口原始摘要：
{_summarize_payload(raw_payload, 1600)}

JSON schema：
{{
  "destination": "城市或目的地，尽量具体",
  "summary": "80字以内总结视频路线和玩法",
  "spots": ["博主去过的景点/街区/商圈，按视频顺序"],
  "foods": ["视频提到的具体食物或店铺"],
  "budgetText": "如果提到花费/人均/预算，保留原文短句，否则空字符串",
  "budgetAmount": 1234,
  "bloggerPlaces": [
    {{"name": "地点名", "type": "spot|food|hotel|shopping|area|other", "reason": "为什么它是复刻点"}}
  ]
}}

要求：
- 不确定就留空数组或空字符串，不要编造。
- budgetAmount 只填整数人民币；没有明确金额填 null。
- bloggerPlaces 必须来自标题、转写或解析摘要，不要加入网上推荐。
"""
    try:
        text = await run_llm_text(prompt, system_prompt="你是旅行视频结构化信息抽取器。只输出可解析 JSON。")
        extracted = _json_from_text(text or "")
    except Exception:
        extracted = {}
    if not extracted:
        return fallback

    merged = {**fallback, **{key: value for key, value in extracted.items() if value not in ("", None, [])}}
    if extracted.get("budgetAmount") is None:
        merged["budgetAmount"] = fallback.get("budgetAmount")
    return merged


async def async_recommend_nearby_places(destination: str, anchors: list[str], limit: int = 8) -> list[ReplicatePlaceOption]:
    if not destination:
        return []
    recommendations: list[ReplicatePlaceOption] = []

    async def append_pois(params: dict[str, Any], reason_prefix: str) -> None:
        nonlocal recommendations
        data = await amap_get("/v3/place/text", params)
        if data.get("status") != "1":
            return
        for poi in data.get("pois") or []:
            name = _clean_name(str(poi.get("name") or ""))
            if not name:
                continue
            if any(place.name == name for place in recommendations):
                continue
            address = str(poi.get("address") or poi.get("adname") or "")
            reason = f"{reason_prefix}{'，' + address if address else ''}"
            recommendations.append(
                ReplicatePlaceOption(
                    id=_stable_option_id("nearby", name),
                    name=name,
                    type="spot",
                    reason=reason[:80],
                    source="nearby",
                    selected=False,
                )
            )
            if len(recommendations) >= limit:
                return

    try:
        for anchor in anchors[:4]:
            if len(recommendations) >= limit:
                break
            await append_pois(
                {
                    "city": destination,
                    "citylimit": "true",
                    "keywords": f"{anchor} 周边 景点",
                    "offset": 5,
                    "page": 1,
                    "extensions": "base",
                },
                f"{anchor}周边可顺路安排",
            )

        if len(recommendations) < limit:
            await append_pois(
                {
                    "city": destination,
                    "citylimit": "true",
                    "keywords": "景点 公园 博物馆 老街 夜市",
                    "offset": limit,
                    "page": 1,
                    "extensions": "base",
                },
                f"{destination}常见攻略推荐",
            )
    except Exception:
        return recommendations
    return recommendations[:limit]


def infer_destination(text: str) -> str:
    compact = text.replace(" ", "")
    for destination in sorted(POPULAR_DESTINATIONS, key=len, reverse=True):
        if destination in compact:
            return destination

    patterns = [
        r"(?:去|在|到|玩转|打卡|旅行|旅游|攻略|周末去)([\u4e00-\u9fa5]{2,8})",
        r"([\u4e00-\u9fa5]{2,8})(?:旅游|旅行|攻略|景点|打卡|避坑)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            candidate = match.group(1)
            candidate = re.sub(r"(一定|必须|不要|值得|适合|最全|小众|宝藏)$", "", candidate)
            if 2 <= len(candidate) <= 8:
                return candidate
    return ""


def infer_spots(text: str, destination: str) -> list[str]:
    compact = text.replace(" ", "")
    spots: list[str] = []
    for spot in sorted(POPULAR_SPOTS, key=len, reverse=True):
        if spot in compact and spot != destination and spot not in spots:
            spots.append(spot)
        if len(spots) >= 6:
            return spots

    chunks = re.split(r"[，,。.!！?？、|｜/#\s]+", text)
    for chunk in chunks:
        chunk = chunk.strip("《》「」“”\"'()（）[]【】")
        chunk = chunk.replace(destination, "")
        chunk = re.sub(r"(攻略|旅游|旅行|打卡|三天两晚|两天一夜|一日游|自由行)$", "", chunk)
        if not chunk or chunk == destination:
            continue
        if any(word in chunk for word in SPOT_HINT_WORDS) and 2 <= len(chunk) <= 12:
            if chunk not in spots:
                spots.append(chunk)
        if len(spots) >= 6:
            break
    return spots


def _place_options_from_analysis(data: dict[str, Any], spots: list[str], foods: list[str]) -> list[ReplicatePlaceOption]:
    places: list[ReplicatePlaceOption] = []
    raw_places = data.get("bloggerPlaces")
    if isinstance(raw_places, list):
        for item in raw_places:
            if isinstance(item, str):
                name = _clean_name(item)
                place_type = "spot"
                reason = "视频中出现的复刻点"
            elif isinstance(item, dict):
                name = _clean_name(str(item.get("name") or ""))
                place_type = str(item.get("type") or "spot")
                if place_type not in {"spot", "food", "hotel", "shopping", "area", "other"}:
                    place_type = "spot"
                reason = str(item.get("reason") or "视频中出现的复刻点")
            else:
                continue
            if not name or any(place.name == name for place in places):
                continue
            places.append(
                ReplicatePlaceOption(
                    id=_stable_option_id("blogger", name),
                    name=name,
                    type=place_type,  # type: ignore[arg-type]
                    reason=reason[:90],
                    source="blogger",
                    selected=True,
                )
            )

    for name in spots:
        clean = _clean_name(name)
        if clean and not any(place.name == clean for place in places):
            places.append(
                ReplicatePlaceOption(
                    id=_stable_option_id("blogger", clean),
                    name=clean,
                    type="spot",
                    reason="视频中出现的景点或街区",
                    source="blogger",
                    selected=True,
                )
            )
    for name in foods:
        clean = _clean_name(name)
        if clean and not any(place.name == clean for place in places):
            places.append(
                ReplicatePlaceOption(
                    id=_stable_option_id("blogger", clean),
                    name=clean,
                    type="food",
                    reason="视频中提到的食物或餐饮点",
                    source="blogger",
                    selected=True,
                )
            )
    return places[:14]


def _status_from_analysis(destination: str, transcript: str, message: str) -> Literal["success", "partial", "needs_manual_input"]:
    if destination and transcript:
        return "success"
    if destination:
        return "partial"
    if message:
        return "partial"
    return "needs_manual_input"


ProgressCallback = Callable[[str, str, int], Awaitable[None]]


async def _noop_progress(stage: str, message: str, progress: int) -> None:
    return None


async def analyze_douyin_core(request: DouyinParseRequest, progress: ProgressCallback = _noop_progress) -> DouyinAnalyzeResponse:
    raw_url = request.url.strip()
    raw_payload: dict[str, Any] = {}
    title = ""
    video_id = ""
    audio_url = ""
    audio_path: Path | None = None
    audio_content_type = ""
    transcript = ""
    messages: list[str] = []

    await progress("fetch", "正在读取视频链接并解析视频信息。", 5)
    try:
        raw_payload = await fetch_douyin_payload(raw_url)
        video_id = _extract_douyin_video_id(raw_payload)
        cached = _load_video_analysis_cache(video_id, raw_url)
        if cached:
            await progress("cache", "命中视频缓存，直接使用上次的语音转写和路线分析。", 100)
            return cached
        title = _extract_douyin_title(raw_payload)
        audio_url = _extract_douyin_audio_url(raw_payload)
    except Exception as exc:
        messages.append(f"视频解析接口暂时不可用，已改用链接标题做兜底：{exc}")
        cached = _load_video_analysis_cache("", raw_url)
        if cached:
            await progress("cache", "命中链接缓存，直接使用上次的分析结果。", 100)
            return cached

    if not title:
        try:
            title = await fetch_title_from_url(raw_url)
        except Exception:
            title = ""
    if not title:
        title = clean_title(re.sub(r"https?://[^\s]+", "", raw_url).strip())

    await progress("download", "正在下载视频音频到本地。", 24)
    if audio_url:
        try:
            audio_path, audio_content_type = await download_audio_to_local(audio_url, raw_url)
            await progress("download", "音频已保存，准备提交 Qwen3 语音转文本。", 38)
        except Exception as exc:
            messages.append(f"音频下载失败，已跳过音频转写：{exc}")
    else:
        messages.append("没有识别到视频音频地址，已使用标题和链接信息分析。")

    if audio_path:
        try:
            await progress("asr", "Qwen3-ASR 正在转换语音，请等待模型返回完整文本。", 52)
            transcript = await async_transcribe_audio_qwen(audio_path, audio_url, audio_content_type, progress)
            await progress("asr", "语音转文本完成，开始交给大模型总结路线。", 70)
        except Exception as exc:
            messages.append(f"Qwen3 语音转文本暂时失败，已使用标题和接口信息分析：{exc}")
            await progress("asr", "语音转文本未完成，使用标题和接口信息继续兜底分析。", 70)
    else:
        await progress("asr", "没有可转写音频，使用标题和接口信息继续分析。", 70)

    await progress("llm", "正在让大模型总结目的地、路线、美食和预算。", 78)
    analysis = await extract_video_analysis_json(title, transcript, raw_payload)
    await progress("llm", "大模型总结完成，正在整理可选择的复刻路线。", 88)

    destination = str(analysis.get("destination") or infer_destination(f"{title}\n{transcript}") or "")
    spots = _unique_names([str(item) for item in analysis.get("spots") or []] + infer_spots(f"{title}\n{transcript}", destination), limit=12)
    foods = _unique_names([str(item) for item in analysis.get("foods") or []], limit=10)
    summary = str(analysis.get("summary") or title or "已完成视频路线分析。")[:160]
    budget_text = str(analysis.get("budgetText") or "")
    budget_amount_raw = analysis.get("budgetAmount")
    budget_amount: int | None = None
    if isinstance(budget_amount_raw, (int, float)) and budget_amount_raw > 0:
        budget_amount = int(budget_amount_raw)
    elif isinstance(budget_amount_raw, str) and budget_amount_raw.isdigit():
        budget_amount = int(budget_amount_raw)

    blogger_places = _place_options_from_analysis(analysis, spots, foods)
    anchor_names = [place.name for place in blogger_places if place.type in {"spot", "area", "shopping"}] or spots
    await progress("nearby", "正在补充博主路线周边可顺路游玩的地点。", 92)
    nearby_places = await async_recommend_nearby_places(destination, anchor_names)

    message = "；".join(messages)
    status = _status_from_analysis(destination, transcript, message)
    response = DouyinAnalyzeResponse(
        videoId=video_id,
        cacheHit=False,
        status=status,
        title=title,
        destination=destination,
        summary=summary,
        transcript=transcript,
        audioSaved=audio_path is not None,
        audioLocalPath=str(audio_path) if audio_path else "",
        audioUrl=audio_url,
        spots=spots,
        foods=foods,
        budgetText=budget_text,
        budgetAmount=budget_amount,
        bloggerPlaces=blogger_places,
        nearbyPlaces=nearby_places,
        needsManualInput=not bool(destination),
        message=message or ("视频音频已转写并整理为可复刻路线。" if transcript else "已完成可用信息整理。"),
    )
    _save_video_analysis_cache(video_id, raw_url, response)
    await progress("done", "视频路线分析完成。", 100)
    return response


@app.post("/api/douyin/analyze", response_model=DouyinAnalyzeResponse)
async def analyze_douyin(request: DouyinParseRequest) -> DouyinAnalyzeResponse:
    return await analyze_douyin_core(request)


@app.post("/api/douyin/analyze/stream")
async def analyze_douyin_stream(request: DouyinParseRequest) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        yield_queue: list[str] = []

        async def emit_progress(stage: str, message: str, progress_value: int) -> None:
            yield_queue.append(event("status", message, {"stage": stage, "progress": progress_value}))

        try:
            task = asyncio.create_task(analyze_douyin_core(request, emit_progress))
            while not task.done():
                while yield_queue:
                    yield yield_queue.pop(0)
                await asyncio.sleep(0.1)
            while yield_queue:
                yield yield_queue.pop(0)
            result = await task
            yield event("done", "视频路线分析完成。", result.model_dump())
        except Exception as exc:
            yield event("error", str(exc) or exc.__class__.__name__)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/douyin/parse", response_model=DouyinParseResponse)
async def parse_douyin(request: DouyinParseRequest) -> DouyinParseResponse:
    text = request.url.strip()
    title = ""
    try:
        title = await fetch_title_from_url(text)
    except Exception:
        title = ""

    if not title:
        title = clean_title(re.sub(r"https?://[^\s]+", "", text).strip())

    destination = infer_destination(title or text)
    spots = infer_spots(title or text, destination)
    success = bool(destination)

    return DouyinParseResponse(
        status="success" if success else "needs_manual_input",
        title=title,
        destination=destination,
        spots=spots,
        needsManualInput=not success,
        message=None if success else "未能稳定识别目的地，请手动补充视频标题或目的地。",
    )


def event(event_type: str, message: str = "", payload: Any | None = None) -> str:
    data = {"type": event_type, "message": message, "payload": payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def budget_label(style: BudgetStyle) -> str:
    return {
        "budget": "穷游优先",
        "comfort": "舒适均衡",
        "luxury": "富游体验",
    }[style]


def transport_label(mode: TransportMode | str) -> str:
    return {
        "train": "优先火车/高铁",
        "any": "交通方式不限",
        "car": "自驾/包车",
        "flight": "可接受飞机",
    }.get(str(mode), str(mode) or "未指定")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _summarize_payload(data: Any, limit: int = 1600) -> str:
    text = _json(data) if not isinstance(data, str) else data
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _parse_json_env(name: str) -> dict[str, Any]:
    raw = _env(name)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _mcp_headers(prefix: str) -> dict[str, str]:
    headers = {str(key): str(value) for key, value in _parse_json_env(f"{prefix}_HEADERS").items()}
    token = _env(f"{prefix}_BEARER_TOKEN") or _env("MODELSCOPE_SDK_TOKEN")
    if token and "authorization" not in {key.lower() for key in headers}:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mcp_args(prefix: str) -> list[str]:
    raw_json = _env(f"{prefix}_ARGS_JSON")
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                return [str(item) for item in data]
        except json.JSONDecodeError:
            pass
    return shlex.split(_env(f"{prefix}_ARGS"))


def _default_mcp_stdio(prefix: str) -> tuple[str, list[str]]:
    if prefix == "MCP_12306":
        return "npx", ["-y", "12306-mcp"]
    return "", []


def _extract_text_content(result: Any) -> str:
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text") or item.get("data")
            if text is not None:
                parts.append(str(text))
        return "\n".join(parts)
    if content is not None:
        return str(content)
    return _summarize_payload(result)


def _extract_tools(result: Any) -> list[Any]:
    tools = getattr(result, "tools", None)
    if tools is None and isinstance(result, dict):
        tools = result.get("tools")
    return list(tools or [])


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or "")
    return str(getattr(tool, "name", ""))


def _tool_description(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("description") or "")
    return str(getattr(tool, "description", ""))


def _tool_schema(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    else:
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return schema if isinstance(schema, dict) else {}


def _candidate_tool_names(tools: list[Any], keywords: list[str]) -> list[str]:
    scored: list[tuple[int, str]] = []
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        name_lower = name.lower()
        description_lower = _tool_description(tool).lower()
        best_score = 0
        for index, keyword in enumerate(lowered_keywords):
            if not keyword:
                continue
            weight = max(1, len(lowered_keywords) - index)
            if name_lower == keyword:
                best_score = max(best_score, 10000 + weight)
            elif keyword in name_lower:
                best_score = max(best_score, 5000 + weight)
            elif keyword in description_lower:
                best_score = max(best_score, 100 + weight)
        if best_score:
            scored.append((best_score, name))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in scored]


def _arguments_for_schema(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if not isinstance(properties, dict):
        return {key: value for key, value in values.items() if value not in ("", None, [])}

    aliases = {
        "origin": ["origin", "from", "from_station", "fromStation", "departure", "departure_city", "start", "start_city", "出发地", "出发城市"],
        "destination": ["destination", "to", "to_station", "toStation", "arrival", "arrival_city", "end", "end_city", "city", "target", "目的地", "到达地", "到达城市"],
        "date": ["date", "travel_date", "departure_date", "departureDate", "train_date", "day", "出发日期", "入住日期"],
        "checkin": ["checkin", "check_in", "checkIn", "arrival_date", "start_date", "入住日期"],
        "checkout": ["checkout", "check_out", "checkOut", "departure_date", "end_date", "离店日期"],
        "keyword": ["keyword", "query", "q", "name", "hotel", "hotel_name", "景点", "关键词"],
        "adults": ["adults", "adult", "travelers", "passengers", "people", "人数"],
        "budget": ["budget", "price", "max_price", "price_max", "hotelBudgetPerNight", "预算"],
        "train_filter": ["trainFilterFlags", "train_filter_flags", "trainFilter", "train_type", "trainType", "车次筛选"],
        "earliest_start_time": ["earliestStartTime", "earliest_start_time", "start_time_from"],
        "latest_start_time": ["latestStartTime", "latest_start_time", "start_time_to"],
        "sort_flag": ["sortFlag", "sort_flag", "sort"],
        "sort_reverse": ["sortReverse", "sort_reverse"],
        "limited_num": ["limitedNum", "limited_num", "limit"],
        "format": ["format", "return_format"],
    }

    args: dict[str, Any] = {}
    for field in properties:
        field_lower = str(field).lower()
        selected_key = None
        for value_key, names in aliases.items():
            if field in names or field_lower in [name.lower() for name in names]:
                selected_key = value_key
                break
        if selected_key is None:
            for value_key in values:
                if value_key.lower() in field_lower or field_lower in value_key.lower():
                    selected_key = value_key
                    break
        if selected_key and values.get(selected_key) not in ("", None, []):
            args[field] = values[selected_key]

    for field in required:
        if field in args:
            continue
        field_lower = str(field).lower()
        if "date" in field_lower and values.get("date"):
            args[field] = values["date"]
        elif ("city" in field_lower or "dest" in field_lower or "to" == field_lower) and values.get("destination"):
            args[field] = values["destination"]
        elif ("from" in field_lower or "origin" in field_lower or "start" in field_lower) and values.get("origin"):
            args[field] = values["origin"]
        elif values.get("keyword"):
            args[field] = values["keyword"]
    return args


async def _call_mcp(prefix: str, preferred_keywords: list[str], values: dict[str, Any]) -> str:
    if ClientSession is None:
        return f"{prefix} MCP 依赖未安装，无法调用。"

    url = _env(f"{prefix}_URL")
    command = _env(f"{prefix}_COMMAND")
    default_command, default_args = _default_mcp_stdio(prefix)
    if not url and not command and default_command:
        command = default_command
    headers = _mcp_headers(prefix)
    transport = _env(f"{prefix}_TRANSPORT", "auto").lower()
    errors: list[str] = []

    if url and streamablehttp_client is not None and (transport in {"auto", "http", "streamable_http"}):
        try:
            async with streamablehttp_client(url, headers=headers or None, timeout=20, sse_read_timeout=60) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = _extract_tools(await session.list_tools())
                    return await _call_matching_mcp_tool(session, tools, preferred_keywords, values)
        except Exception as exc:
            errors.append(f"streamable_http: {exc}")

    if url and sse_client is not None and transport in {"auto", "sse"}:
        try:
            async with sse_client(url, headers=headers or None, timeout=20, sse_read_timeout=60) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = _extract_tools(await session.list_tools())
                    return await _call_matching_mcp_tool(session, tools, preferred_keywords, values)
        except Exception as exc:
            errors.append(f"sse: {exc}")

    if command and stdio_client is not None and StdioServerParameters is not None:
        try:
            args = _mcp_args(prefix) or default_args
            async with stdio_client(
                StdioServerParameters(command=command, args=args, env=_parse_json_env(f"{prefix}_ENV") or None)
            ) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = _extract_tools(await session.list_tools())
                    return await _call_matching_mcp_tool(session, tools, preferred_keywords, values)
        except Exception as exc:
            errors.append(f"stdio: {exc}")

    if errors:
        return f"{prefix} MCP 调用失败：" + "；".join(errors[:3])
    return f"{prefix} MCP 未配置。请在 api/.env 设置 {prefix}_URL 或 {prefix}_COMMAND。"


async def _call_matching_mcp_tool(
    session: Any,
    tools: list[Any],
    preferred_keywords: list[str],
    values: dict[str, Any],
) -> str:
    candidate_names = _candidate_tool_names(tools, preferred_keywords)
    if not candidate_names and tools:
        candidate_names = [_tool_name(tools[0])]

    tool_by_name = {_tool_name(tool): tool for tool in tools}
    errors: list[str] = []
    for name in candidate_names:
        if not name:
            continue
        args = _arguments_for_schema(_tool_schema(tool_by_name.get(name, {})), values)
        try:
            result = await session.call_tool(name, arguments=args or values)
            return _extract_text_content(result)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        return "MCP 工具匹配失败：" + "；".join(errors[:3])
    return "MCP 服务未返回可调用工具。"


def run_async_blocking(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - defensive bridge
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


async def amap_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    key = _env("AMAP_API_KEY")
    if not key:
        return {"status": "not_configured", "message": "AMAP_API_KEY 未配置"}
    query = {key_: value for key_, value in params.items() if value not in ("", None, [])}
    query["key"] = key
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(f"https://restapi.amap.com{path}", params=query)
        response.raise_for_status()
        return response.json()


async def async_reverse_geocode_city(latitude: float, longitude: float) -> str:
    data = await amap_get(
        "/v3/geocode/regeo",
        {
            "location": f"{longitude},{latitude}",
            "extensions": "base",
            "radius": 1000,
        },
    )
    if data.get("status") == "not_configured":
        raise RuntimeError(data.get("message") or "AMAP_API_KEY 未配置")
    if data.get("status") != "1":
        raise RuntimeError(data.get("info") or "逆地理编码失败")
    address = data.get("regeocode", {}).get("addressComponent", {})
    city = address.get("city") or address.get("province") or ""
    if isinstance(city, list):
        city = city[0] if city else ""
    city = str(city).replace("市", "").strip()
    if not city:
        raise RuntimeError("未识别到城市")
    return city


def normalize_amap_city(value: Any) -> str:
    city = value
    if isinstance(city, list):
        city = city[0] if city else ""
    return str(city).replace("市", "").strip()


def public_client_ip_from_request(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    candidates = [item.strip() for item in forwarded_for.split(",") if item.strip()]
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        candidates.append(real_ip)
    if request.client and request.client.host:
        candidates.append(request.client.host)

    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
            return candidate
    return ""


async def async_ip_geocode_city(ip: str = "") -> str:
    attempts = 3 if not ip else 1
    for _ in range(attempts):
        data = await amap_get("/v3/ip", {"ip": ip})
        if data.get("status") == "not_configured":
            raise RuntimeError(data.get("message") or "AMAP_API_KEY 未配置")
        if data.get("status") != "1":
            raise RuntimeError(data.get("info") or "IP 定位失败")

        city = normalize_amap_city(data.get("city"))
        if not city:
            city = normalize_amap_city(data.get("province"))
        if city:
            return city
    raise RuntimeError("未识别到城市")


@app.get("/api/geo/reverse", response_model=ReverseGeoResponse)
async def reverse_geo(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
) -> ReverseGeoResponse:
    try:
        city = await async_reverse_geocode_city(latitude, longitude)
        return ReverseGeoResponse(status="success", city=city, message="已通过当前位置识别出发城市。")
    except Exception as exc:
        return ReverseGeoResponse(status="needs_manual_input", city="", message=str(exc))


@app.get("/api/geo/ip", response_model=ReverseGeoResponse)
async def ip_geo(request: Request) -> ReverseGeoResponse:
    try:
        city = await async_ip_geocode_city(public_client_ip_from_request(request))
        return ReverseGeoResponse(status="success", city=city, message="已通过网络位置识别出发城市。")
    except Exception as exc:
        return ReverseGeoResponse(status="needs_manual_input", city="", message=str(exc))


@app.get("/api/places/photo", response_model=PlacePhotoResponse)
async def place_photo(
    destination: str = Query("", max_length=40),
    keyword: str = Query(..., min_length=1, max_length=80),
) -> PlacePhotoResponse:
    keywords = [item.strip() for item in re.split(r"[|,，、\n]+", keyword) if item.strip()]
    if not keywords:
        keywords = [keyword]
    last_title = keyword
    last_message = ""
    try:
        for item in keywords[:6]:
            data = await amap_get(
                "/v3/place/text",
                {
                    "city": destination,
                    "citylimit": "true",
                    "keywords": item,
                    "offset": 3,
                    "page": 1,
                    "extensions": "all",
                },
            )
            if data.get("status") == "not_configured":
                return PlacePhotoResponse(status="needs_config", message=data.get("message", "AMAP_API_KEY 未配置"))
            if data.get("status") != "1":
                last_message = data.get("info") or "未找到图片"
                continue
            pois = data.get("pois") or []
            if not pois:
                last_message = f"未找到相关地点：{item}"
                continue
            for poi in pois[:3]:
                last_title = str(poi.get("name") or item)
                photos = poi.get("photos") or []
                if isinstance(photos, list):
                    for photo in photos:
                        if isinstance(photo, dict) and photo.get("url"):
                            image_url = str(photo["url"]).replace("http://", "https://", 1)
                            return PlacePhotoResponse(status="success", imageUrl=image_url, title=last_title)
                last_message = f"{last_title} 存在但无照片"
        return PlacePhotoResponse(status="not_found", title=last_title, message=last_message or "未找到可用地点照片")
    except Exception as exc:
        return PlacePhotoResponse(status="not_found", message=str(exc) or exc.__class__.__name__)


def _decode_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return url


async def async_search_web_results(query: str, limit: int = 5) -> list[dict[str, str]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(timeout=18, headers=headers, follow_redirects=True) as client:
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, str]] = []
    for item in soup.select(".result"):
        title_node = item.select_one(".result__a")
        snippet_node = item.select_one(".result__snippet")
        if not title_node:
            continue
        title = title_node.get_text(" ", strip=True)
        href = _decode_duckduckgo_url(str(title_node.get("href") or ""))
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        if not title:
            continue
        results.append({
            "title": title,
            "url": href,
            "snippet": snippet,
        })
        if len(results) >= limit:
            break
    return results


async def async_search_web_images(query: str, limit: int = 6) -> list[dict[str, str]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        landing = await client.get("https://duckduckgo.com/", params={"q": query, "iax": "images", "ia": "images"})
        landing.raise_for_status()
        match = re.search(r"vqd=([\d-]+)&", landing.text) or re.search(r'"vqd":"([^"]+)"', landing.text) or re.search(r"vqd='([^']+)'", landing.text)
        if not match:
            return []
        vqd = match.group(1)
        response = await client.get(
            "https://duckduckgo.com/i.js",
            params={"l": "cn-zh", "o": "json", "q": query, "vqd": vqd, "f": ",,,", "p": "1"},
        )
        response.raise_for_status()
        data = response.json()
    results = data.get("results") or []
    images: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or query)
        image = str(item.get("image") or "")
        thumbnail = str(item.get("thumbnail") or "")
        source_url = str(item.get("url") or item.get("source") or "")
        chosen = ""
        for candidate in (thumbnail, image):
            if candidate.startswith("https://"):
                chosen = candidate
                break
        if not chosen:
            chosen = thumbnail or image
        if not chosen:
            continue
        images.append({"title": title, "imageUrl": chosen, "sourceUrl": source_url})
        if len(images) >= limit:
            break
    return images


@app.get("/api/images/search", response_model=ImageSearchResponse)
async def search_image(
    destination: str = Query("", max_length=40),
    keyword: str = Query(..., min_length=1, max_length=80),
) -> ImageSearchResponse:
    query = f"{destination} {keyword}".strip()
    try:
        images = await async_search_web_images(query, limit=6)
        if not images:
            return ImageSearchResponse(status="not_found", title=keyword, message="未找到图片")
        image = images[0]
        return ImageSearchResponse(
            status="success",
            imageUrl=image.get("imageUrl", ""),
            title=image.get("title", keyword),
            sourceUrl=image.get("sourceUrl", ""),
            message="已从互联网搜索到图片。",
        )
    except Exception as exc:
        return ImageSearchResponse(status="not_found", title=keyword, message=str(exc) or exc.__class__.__name__)


def _sync(coro: Any) -> Any:
    return run_async_blocking(coro)


def _today_plus(days: int) -> str:
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def normalized_departure_date(preferences: TripPreferences) -> str:
    return preferences.departureDate or _today_plus(1)


def normalized_return_date(preferences: TripPreferences) -> str:
    if preferences.returnDate:
        return preferences.returnDate
    try:
        departure = dt.date.fromisoformat(normalized_departure_date(preferences))
        return (departure + dt.timedelta(days=max(preferences.days - 1, 0))).isoformat()
    except ValueError:
        return _today_plus(1 + max(preferences.days - 1, 0))


def search_destination_info(destination: str, interests: str = "") -> str:
    """Search practical travel information for a destination."""
    return (
        f"{destination}适合按区域聚合游玩，优先减少跨城折返。"
        f"当前兴趣关键词：{interests or '未指定'}。"
        "建议把高热度景点安排在早晨或傍晚，把室内项目作为天气兜底。"
    )


def get_weather_hint(destination: str, start_date_range: str = "") -> str:
    """Get weather planning hints for a destination and approximate travel time."""
    when = start_date_range or "未指定时间"
    return (
        f"{destination}在{when}出行前需要提前 3-5 天复查天气。"
        "方案应准备雨天室内替代路线，并避免把全天户外项目排得过满。"
    )


def estimate_budget(destination: str, days: int, budget_style: str) -> str:
    """Estimate rough travel budget by destination, days, and budget style."""
    base = {"budget": 320, "comfort": 680, "luxury": 1380}.get(budget_style, 680)
    total_low = base * days
    total_high = int(base * days * 1.35)
    return (
        f"{destination}{days}天{budget_label(budget_style)}预算建议："
        f"不含大交通约 {total_low}-{total_high} 元/人。"
    )


def estimate_total_trip_cost(preferences: TripPreferences) -> str:
    days = max(preferences.days, 1)
    travelers = max(preferences.travelers, 1)
    daily_base = {"budget": 240, "comfort": 520, "luxury": 980}.get(preferences.budgetStyle, 520)
    default_hotel = {"budget": 220, "comfort": 520, "luxury": 1200}.get(preferences.budgetStyle, 520)
    hotel_per_night = preferences.hotelBudgetPerNight or default_hotel
    nights = max(days - 1, 0)
    local_low = daily_base * days
    local_high = int(local_low * 1.35)
    hotel_low = hotel_per_night * nights
    hotel_high = int(hotel_low * 1.25)
    per_person_low = local_low + hotel_low
    per_person_high = local_high + hotel_high
    group_low = per_person_low * travelers
    group_high = per_person_high * travelers
    return (
        f"约 {per_person_low:,}-{per_person_high:,} 元/人，"
        f"全团约 {group_low:,}-{group_high:,} 元；按 {days} 天 {nights} 晚估算，"
        "不含实时大交通票价。"
    )


def optimize_daily_route(destination: str, days: int, spot_types: str = "") -> str:
    """Optimize a daily route skeleton for the destination."""
    return (
        f"{destination}{days}天路线应按“抵达适应-核心景点-小众体验-返程缓冲”组织。"
        f"偏好景点类型：{spot_types or '未指定'}。每天控制 2-4 个主要停靠点。"
    )


def _clean_user_facing_tool_text(text: str) -> str:
    cleaned = re.sub(
        r"^(地图 POI|地图景点|地图美食|地图路线|地图坐标|天气预报|天气信息|火车票|酒店|预算估算|路线优化|目的地信息|工具数据分析)[：:]\s*",
        "",
        str(text).strip(),
    )
    cleaned = cleaned.replace("工具返回了", "").replace("工具返回", "").replace("已调用工具数据", "参考信息")
    cleaned = cleaned.replace("地图 POI：", "").replace("地图 POI", "地点")
    cleaned = cleaned.replace("Hotel MCP", "住宿信息").replace("MCP", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def async_query_map_pois(destination: str, keywords: str = "") -> str:
    keywords = keywords or "景点"
    data = await amap_get(
        "/v3/place/text",
        {"city": destination, "citylimit": "true", "keywords": keywords, "offset": 8, "page": 1, "extensions": "base"},
    )
    if data.get("status") == "not_configured":
        return f"{data['message']}，暂按{destination}和已识别地点做路线聚合。"
    if data.get("status") != "1":
        return f"{destination}{keywords}查询失败：{data.get('info') or _summarize_payload(data, 300)}"
    pois = data.get("pois") or []
    if not pois:
        return f"未查到 {destination} {keywords} 的结果。"
    lines = []
    for poi in pois[:6]:
        name = poi.get("name", "")
        district = poi.get("adname") or poi.get("district") or ""
        address = poi.get("address") or ""
        rating = poi.get("biz_ext", {}).get("rating") if isinstance(poi.get("biz_ext"), dict) else ""
        lines.append(f"{name}（{district}{'，评分 ' + rating if rating else ''}{'，' + address if address else ''}）")
    return "；".join(lines)


def query_map_pois(destination: str, keywords: str = "") -> str:
    """Query real map POIs with AMAP when AMAP_API_KEY is configured."""
    return _sync(async_query_map_pois(destination, keywords))


async def async_query_route_distance(origin: str, destination: str) -> str:
    if not origin or not destination:
        return "地图距离：缺少出发地或目的地，无法查询跨城距离。"
    geo_origin = await amap_get("/v3/geocode/geo", {"address": origin})
    geo_dest = await amap_get("/v3/geocode/geo", {"address": destination})
    if geo_origin.get("status") == "not_configured" or geo_dest.get("status") == "not_configured":
        return "地图距离：AMAP_API_KEY 未配置，无法查询真实坐标距离。"
    if geo_origin.get("status") != "1" or geo_dest.get("status") != "1":
        return f"地图距离：地理编码失败，{_summarize_payload({'origin': geo_origin, 'destination': geo_dest}, 360)}"
    origin_geos = geo_origin.get("geocodes") or []
    dest_geos = geo_dest.get("geocodes") or []
    if not origin_geos or not dest_geos:
        return "地图距离：未找到出发地或目的地坐标。"
    return (
        "地图坐标："
        f"{origin} {origin_geos[0].get('location')}；"
        f"{destination} {dest_geos[0].get('location')}。"
        "跨城出行需结合 12306/航班工具确认耗时。"
    )


def query_route_distance(origin: str, destination: str) -> str:
    """Query geocoding hints for route planning with AMAP when configured."""
    return _sync(async_query_route_distance(origin, destination))


async def async_geocode_location(address: str, city: str = "") -> tuple[str, str]:
    data = await amap_get("/v3/geocode/geo", {"address": address, "city": city})
    if data.get("status") == "not_configured":
        raise RuntimeError(data.get("message") or "AMAP_API_KEY 未配置")
    if data.get("status") != "1":
        raise RuntimeError(data.get("info") or "地理编码失败")
    geocodes = data.get("geocodes") or []
    if not geocodes:
        raise RuntimeError(f"未找到坐标：{address}")
    location = str(geocodes[0].get("location") or "")
    formatted = str(geocodes[0].get("formatted_address") or address)
    if not location:
        raise RuntimeError(f"未找到坐标：{address}")
    return location, formatted


def _format_duration(seconds: Any) -> str:
    try:
        total_minutes = max(1, round(int(float(seconds)) / 60))
    except Exception:
        return ""
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def _format_distance(meters: Any) -> str:
    try:
        distance_km = float(meters) / 1000
    except Exception:
        return ""
    if distance_km >= 100:
        return f"{distance_km:.0f}公里"
    return f"{distance_km:.1f}公里"


def _parse_first_train_ticket(text: str, preferred_seat: str = "不限") -> tuple[str, str, str]:
    train = re.search(r"\b([GDCZTK]\d+)\b", text)
    duration = re.search(r"历时[:：]\s*(\d{2}:\d{2})", text)
    seat_order = [preferred_seat] if preferred_seat and preferred_seat != "不限" else ["二等座"]
    seat_order.extend(["二等座", "一等座", "商务座", "硬卧", "软卧", "无座"])
    seen_seats: list[str] = []
    price_text = ""
    for seat in seat_order:
        if not seat or seat in seen_seats:
            continue
        seen_seats.append(seat)
        escaped = re.escape(seat)
        price = re.search(rf"{escaped}[:：][^-\n；;]*?(\d{{2,5}})元", text)
        if price:
            price_text = f"约 {price.group(1)} 元起"
            break
    train_text = train.group(1) if train else ""
    duration_text = ""
    if duration:
        hours, minutes = duration.group(1).split(":")
        duration_text = f"{int(hours)}小时{int(minutes)}分钟"
    return train_text, duration_text, price_text


async def async_transport_summary(request: TransportSummaryRequest) -> TransportSummaryResponse:
    origin = request.origin.strip()
    destination = request.destination.strip()
    first_spot = request.firstSpot.strip()
    mode = request.transportMode
    if not origin or not destination:
        return TransportSummaryResponse(
            status="needs_manual_input",
            origin=origin,
            destination=destination,
            mode=mode,
            message="请先确认出发城市和目的地。",
        )

    items: list[TransportSummaryItem] = []
    target_address = f"{destination}{first_spot}" if first_spot and destination not in first_spot else first_spot or destination
    messages: list[str] = []

    try:
        origin_location, origin_name = await async_geocode_location(origin)
        target_location, target_name = await async_geocode_location(target_address, destination)
        driving = await amap_get(
            "/v3/direction/driving",
            {
                "origin": origin_location,
                "destination": target_location,
                "extensions": "base",
                "strategy": 10,
            },
        )
        if driving.get("status") == "1":
            paths = driving.get("route", {}).get("paths") or []
            if paths:
                path = paths[0]
                distance = _format_distance(path.get("distance"))
                duration = _format_duration(path.get("duration"))
                tolls_raw = path.get("tolls")
                try:
                    tolls = float(tolls_raw or 0)
                except Exception:
                    tolls = 0
                try:
                    km = float(path.get("distance") or 0) / 1000
                except Exception:
                    km = 0
                fuel = round(km * 0.65)
                driving_cost = fuel + round(tolls)
                items.append(TransportSummaryItem(label="路程距离", value=distance or "已获取", detail=f"{origin_name} 到 {target_name}"))
                items.append(TransportSummaryItem(label="驾车耗时", value=duration or "需复核", detail="实际会受拥堵、限行和停车影响"))
                items.append(
                    TransportSummaryItem(
                        label="驾车花费",
                        value=f"约 {driving_cost} 元" if driving_cost else "需复核",
                        detail=f"按油费约 {fuel} 元、过路费约 {round(tolls)} 元估算",
                    )
                )
        else:
            messages.append(driving.get("info") or "驾车路线暂未返回")
    except Exception as exc:
        messages.append(f"地图路线暂未返回：{exc}")

    if mode in {"train", "any"}:
        try:
            train_text = await asyncio.wait_for(
                async_query_train_tickets(origin, destination, request.departureDate or _today_plus(1), request.seatPreference),
                timeout=25,
            )
            train_no, train_duration, train_price = _parse_first_train_ticket(train_text, request.seatPreference)
            if train_no or train_duration or train_price:
                items.append(
                    TransportSummaryItem(
                        label="火车参考",
                        value=" · ".join(item for item in [train_no, train_duration, train_price] if item),
                        detail="以 12306 临近出发余票和票价为准",
                    )
                )
            elif train_text:
                items.append(TransportSummaryItem(label="火车参考", value="已查询", detail=_clean_user_facing_tool_text(train_text)[:120]))
        except Exception as exc:
            messages.append(f"火车票暂未返回：{exc}")

    if not items:
        items.append(TransportSummaryItem(label="交通信息", value="待复核", detail="地图或票务暂未返回，后续规划会继续跳过失败项。"))
    return TransportSummaryResponse(
        status="success" if not messages else "partial",
        origin=origin,
        destination=destination,
        mode=mode,
        items=items[:5],
        message="；".join(messages) or "已整理到达目的地的交通参考。",
    )


@app.post("/api/trips/transport/summary", response_model=TransportSummaryResponse)
async def transport_summary(request: TransportSummaryRequest) -> TransportSummaryResponse:
    return await async_transport_summary(request)


async def async_query_weather(destination: str, date_range: str = "") -> str:
    data = await amap_get("/v3/weather/weatherInfo", {"city": destination, "extensions": "all"})
    if data.get("status") == "not_configured":
        return get_weather_hint(destination, date_range)
    if data.get("status") != "1":
        return f"天气查询失败：{data.get('info') or _summarize_payload(data, 300)}"
    forecasts = data.get("forecasts") or []
    casts = forecasts[0].get("casts", []) if forecasts else []
    if not casts:
        return get_weather_hint(destination, date_range)
    lines = []
    for cast in casts[:4]:
        lines.append(
            f"{cast.get('date')} {cast.get('dayweather')}/{cast.get('nightweather')} "
            f"{cast.get('nighttemp')}-{cast.get('daytemp')}℃ {cast.get('daywind')}风"
        )
    return "天气预报：" + "；".join(lines)


def query_weather(destination: str, date_range: str = "") -> str:
    """Query real weather with AMAP weather API when AMAP_API_KEY is configured."""
    return _sync(async_query_weather(destination, date_range))


async def async_query_train_tickets(
    origin: str,
    destination: str,
    departure_date: str,
    seat_preference: str = "不限",
) -> str:
    if not origin or not destination:
        return "火车票：缺少出发城市或目的地，无法查询。"
    values = {
        "origin": origin,
        "destination": destination,
        "date": departure_date or _today_plus(14),
        "seat": seat_preference,
        "keyword": f"{origin}到{destination}火车票",
        "train_filter": "G" if "高铁" in seat_preference or seat_preference in {"不限", "二等座", "一等座", "商务座"} else "",
        "earliest_start_time": 0,
        "latest_start_time": 24,
        "sort_flag": "duration",
        "sort_reverse": False,
        "limited_num": 6,
        "format": "text",
    }
    result = await _call_mcp(
        "MCP_12306",
        ["get-tickets", "余票", "车票", "ticket", "train"],
        values,
    )
    if "未配置" in result:
        return (
            f"12306 暂未返回实时余票。"
            f"查询条件：{origin} -> {destination}，{values['date']}，席别 {seat_preference}；"
            "出发前需要复核余票和票价。"
        )
    return "火车票：" + _summarize_payload(result)


def query_train_tickets(origin: str, destination: str, departure_date: str, seat_preference: str = "不限") -> str:
    """Query train tickets through the configured ModelScope 12306 MCP server."""
    return _sync(async_query_train_tickets(origin, destination, departure_date, seat_preference))


async def async_query_hotels(
    destination: str,
    checkin: str,
    checkout: str,
    preference: str = "交通方便",
    budget_per_night: int | None = None,
    travelers: int = 1,
) -> str:
    if not destination:
        return "酒店：缺少目的地，无法查询。"
    values = {
        "destination": destination,
        "city": destination,
        "checkin": checkin or _today_plus(14),
        "checkout": checkout or _today_plus(16),
        "keyword": preference or "酒店",
        "budget": budget_per_night,
        "adults": travelers,
    }
    result = await _call_mcp(
        "MCP_HOTEL",
        ["hotel", "酒店", "住宿", "search", "query", "room"],
        values,
    )
    if any(marker in result for marker in ["未配置", "调用失败", "工具匹配失败", "未返回可调用工具"]):
        fallback_query = f"{destination} {preference} 酒店 {budget_per_night or ''}元"
        web_hotels = await async_search_web_results(fallback_query, limit=4)
        if web_hotels:
            lines = []
            for index, hotel in enumerate(web_hotels, start=1):
                title = hotel.get("title", "")
                snippet = hotel.get("snippet", "")
                url = hotel.get("url", "")
                parts = [f"{index}. {title}"]
                if snippet:
                    parts.append(snippet)
                if url:
                    parts.append(url)
                lines.append(" - ".join(parts))
            return (
                f"住宿实时房态暂未返回，已用互联网搜索做兜底推荐。"
                f"查询条件：{destination}，{values['checkin']} 至 {values['checkout']}，"
                f"{preference}，预算 {budget_per_night or '未限定'} 元/晚。\n"
                + "\n".join(lines)
            )
        return (
            f"住宿实时房态暂未返回，互联网搜索也未找到稳定推荐。"
            f"查询条件：{destination}，{values['checkin']} 至 {values['checkout']}，"
            f"{preference}，预算 {budget_per_night or '未限定'} 元/晚。"
        )
    return "酒店：" + _summarize_payload(result)


def query_hotels(
    destination: str,
    checkin: str,
    checkout: str,
    preference: str = "交通方便",
    budget_per_night: int | None = None,
    travelers: int = 1,
) -> str:
    """Query hotels through the configured ModelScope Hotel MCP server."""
    return _sync(async_query_hotels(destination, checkin, checkout, preference, budget_per_night, travelers))


SYSTEM_PROMPT = """
你是一个中文旅行规划 Deep Agent，目标是把抖音视频灵感转换为可执行行程。
你必须先理解用户的出发地、目的地、日期、天数、人数、预算风格、交通/住宿偏好、兴趣和景点类型偏好。
规划时优先使用真实地点、天气、12306 火车票、酒店信息；如果信息源明确未配置或失败，必须说明具体项目需要出发前复核，不要伪造实时票价、余票、酒店房态。
输出必须务实、可执行、可调整，避免空泛营销文案。若信息不完整，基于现有信息给出可行默认值并说明。
每天必须使用三级标题，格式严格为“### Day 1｜主题”“### Day 2｜主题”，方便前端按天拆成 tab。
每天都要有时间线，明确“几点到几点做什么、预计游玩多久、移动多久”；到 12:00 和 18:00 左右必须安排午餐/晚餐或说明为什么跳过。
餐饮必须结合真实美食地点、用户兴趣和当天所在区域；没有真实店铺数据时，只能写区域、菜品方向和“需出发前复核”，不能编造店名。
每天必须把备选内容放在“#### 备选方案”小节里，正文不要展开多个备选。
严禁在给用户的方案中出现“工具返回”“工具调用”“已调用工具数据”“地图 POI”“MCP”等技术表述；直接写地点名、天气、酒店建议和复核提醒。
"""

SUBAGENTS = [
    {
        "name": "destination_researcher",
        "description": "整理目的地、景点、区域分布和路线亮点。",
        "system_prompt": "你专注目的地研究，输出紧凑、准确、偏实用的信息。",
    },
    {
        "name": "budget_planner",
        "description": "按穷游、舒适、富游估算预算和消费取舍。",
        "system_prompt": "你专注旅行预算，按住宿、交通、餐饮、门票拆分建议。",
    },
    {
        "name": "itinerary_optimizer",
        "description": "按天数、偏好、体力和路线顺序优化每日行程。",
        "system_prompt": "你专注路线优化，减少折返，控制每天停靠点数量。",
    },
]


def build_prompt(
    preferences: TripPreferences,
    current_plan: str = "",
    feedback: str = "",
    travel_data: list[dict[str, str]] | None = None,
) -> str:
    departure_date = normalized_departure_date(preferences)
    return_date = normalized_return_date(preferences)
    return f"""
请根据以下信息生成或调整旅行计划。

抖音链接：{preferences.link or "未提供"}
视频标题：{preferences.videoTitle or "未提供"}
视频路线总结：{preferences.videoSummary or "未提供"}
视频预算线索：{preferences.videoBudgetText or (str(preferences.videoBudgetAmount) + " 元" if preferences.videoBudgetAmount else "未提及")}
视频提到的食物：{", ".join(preferences.videoFoods) or "未识别"}
用户选择复刻/增加的地点：{", ".join(preferences.routeReferencePlaces or preferences.spots) or "未选择"}
出发城市：{preferences.origin or "未提供"}
目的地：{preferences.destination}
识别景点：{", ".join(preferences.spots) or "未识别"}
出发日期：{departure_date}
返回/离店日期：{return_date}
天数：{preferences.days}
人数：{preferences.travelers}
预算风格：{budget_label(preferences.budgetStyle)}
交通方式偏好：{preferences.transportMode}
火车席别偏好：{preferences.trainSeatPreference}
酒店偏好：{preferences.hotelPreference}
酒店预算：{preferences.hotelBudgetPerNight or "未限定"} 元/晚
出行爱好：{", ".join(preferences.travelInterests) or "未指定"}
景点类型偏好：{", ".join(preferences.spotTypes) or "未指定"}
补充要求：{preferences.notes or "无"}

参考信息：
{_format_reference_info(travel_data)}

数据使用规则：
- 你必须先分析“参考信息”，再生成攻略。
- 参考信息里有真实地点、天气、火车票、酒店结果时，必须把这些结果落实到每日路线、住宿区域、交通建议和风险提醒中。
- 如果某项工具显示“未配置”“调用失败”“需复核”，不能编造具体票价、余票、酒店名或营业时间，只能给出查询条件和出发前复核动作。
- 识别景点来自抖音视频时，必须优先解释这些点为什么值得玩、适合放在哪一天、和哪些吃饭/住宿区域搭配。
- 如果视频预算线索里有明确花费，预算估算和住宿/餐饮档位要参考它；不确定时写明是视频口径而非实时价格。
- 对用户输出时不要说“工具返回/工具显示/已调用工具数据/地图 POI/MCP”，直接写地点名、日期、天气、车次/酒店建议或“需复核”。

当前方案：
{current_plan or "无"}

用户调整要求：
{feedback or "无"}

输出要求：
1. 开头只保留“关键摘要”，用 5-8 条 bullet 覆盖数据来源、交通、住宿区域、总预算、风险提醒。
2. 每天必须用“### Day N｜主题”作为标题，N 从 1 到 {preferences.days}。
3. 每天只写关键攻略：路线、好玩点、好吃推荐、交通/预约、备选调整。
4. 好玩和好吃要具体，不要写“当地特色美食”这种空话；如果工具没有给出真实结果，就写“推荐到核心商圈/夜市复核高分店”。
5. 不要输出大段泛泛介绍，不要输出表格。
"""


def _tool_content(travel_data: list[dict[str, str]] | None, source: str) -> str:
    if not travel_data:
        return ""
    for item in travel_data:
        if item.get("source") == source:
            return item.get("content", "")
    return ""


def _format_reference_info(travel_data: list[dict[str, str]] | None) -> str:
    if not travel_data:
        return "无"
    labels = {
        "destination": "目的地",
        "map_route": "路线",
        "map_poi": "景点",
        "map_food": "美食",
        "weather": "天气",
        "train_12306": "车票",
        "hotel_mcp": "住宿",
        "budget": "预算",
        "route": "行程节奏",
    }
    lines: list[str] = []
    for item in travel_data:
        source = item.get("source", "")
        if source == "tool_analysis":
            continue
        content = _clean_user_facing_tool_text(item.get("content", ""))
        if not content:
            continue
        label = labels.get(source, "参考")
        lines.append(f"- {label}：{content}")
    return "\n".join(lines) or "无"


def _data_is_real(content: str) -> bool:
    lowered = content.lower()
    return bool(content) and not any(
        marker in lowered
        for marker in [
            "未配置",
            "调用失败",
            "查询失败",
            "未查到",
            "无法获取",
            "无法查询",
            "not_configured",
            "需复核",
        ]
    )


def _extract_poi_names(content: str, limit: int = 5) -> list[str]:
    if not _data_is_real(content):
        return []
    text = _clean_user_facing_tool_text(content)
    names: list[str] = []
    for raw in re.split(r"[；;\n]+", text):
        name = raw.strip()
        if not name:
            continue
        name = re.split(r"[（(，,]", name, maxsplit=1)[0].strip()
        if 1 < len(name) <= 32 and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _title_from_day(text: str, day_index: int) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    title = re.sub(r"^###\s*", "", first).strip()
    return title or f"Day {day_index}"


def _extract_day_block(text: str, day_index: int, preferences: TripPreferences) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return fallback_day_plan(preferences, day_index)

    headings = list(re.finditer(r"^###\s*(?:Day\s*(\d+)|D(\d+)|第\s*(\d+)\s*天)[^\n]*", cleaned, flags=re.I | re.M))
    if headings:
        wanted = None
        for index, match in enumerate(headings):
            number = next((group for group in match.groups() if group), "")
            if number and int(number) == day_index:
                next_start = headings[index + 1].start() if index + 1 < len(headings) else len(cleaned)
                wanted = cleaned[match.start():next_start].strip()
                break
        if wanted:
            return wanted
        first_next = headings[1].start() if len(headings) > 1 else len(cleaned)
        return cleaned[headings[0].start():first_next].strip()

    title = f"Day {day_index}｜{preferences.destination or '目的地'}当日路线"
    return f"### {title}\n{cleaned}"


def _target_date_for_day(preferences: TripPreferences, day_index: int) -> str:
    try:
        departure = dt.date.fromisoformat(normalized_departure_date(preferences))
        return (departure + dt.timedelta(days=day_index - 1)).isoformat()
    except ValueError:
        return f"第 {day_index} 天"


def build_key_summary(preferences: TripPreferences, travel_data: list[dict[str, str]]) -> str:
    destination = preferences.destination or "目的地"
    departure_date = normalized_departure_date(preferences)
    return_date = normalized_return_date(preferences)
    map_status = "已参考真实地点信息" if _data_is_real(_tool_content(travel_data, "map_poi")) else "景点开放和位置需出发前复核"
    food_status = "已参考真实美食地点" if _data_is_real(_tool_content(travel_data, "map_food")) else "餐厅店名不强行编造，按区域复核高分店"
    train_status = "已尝试查询 12306" if _tool_content(travel_data, "train_12306") else "未查询大交通"
    hotel_content = _tool_content(travel_data, "hotel_mcp")
    if "互联网搜索" in hotel_content:
        hotel_status = "住宿实时房态暂未返回，已补充联网推荐"
    elif _data_is_real(hotel_content):
        hotel_status = "已参考住宿信息"
    elif hotel_content:
        hotel_status = "酒店查询已完成，结果需复核"
    else:
        hotel_status = "未查询酒店"
    hotel_budget = f"{preferences.hotelBudgetPerNight} 元/晚" if preferences.hotelBudgetPerNight else "未限定"
    cost = estimate_total_trip_cost(preferences)
    video_budget = ""
    if preferences.videoBudgetText:
        video_budget = f"；视频里提到的花费线索：{preferences.videoBudgetText}"
    elif preferences.videoBudgetAmount:
        video_budget = f"；视频里提到的花费线索：约 {preferences.videoBudgetAmount} 元"
    selected_places = preferences.routeReferencePlaces or preferences.spots

    return f"""## 关键摘要
- 路线：{preferences.origin or "出发地待定"} → {destination}，{preferences.days} 天 {preferences.travelers} 人，{departure_date} 至 {return_date}。
- 预算：{budget_label(preferences.budgetStyle)}，住宿偏好 {preferences.hotelPreference}，酒店预算 {hotel_budget}。
- 总花费：{cost}{video_budget}
- 交通：{transport_label(preferences.transportMode)}，火车席别 {preferences.trainSeatPreference}；{train_status}，余票/票价以临近出发查询为准。
- 住宿：{hotel_status}，建议住在交通方便且靠近主线景点或核心商圈的区域。
- 复刻点：{", ".join(selected_places[:8]) or "用户未选择具体点位"}。
- 地点：{map_status}；{food_status}。
- 节奏：每天控制 2-4 个主要停靠点，时间线包含游玩时长、移动时长和饭点安排。
- 风险：天气、开放时间、预约规则、酒店房态和餐厅排队情况都需要出发前复核。"""


def build_day_prompt(
    preferences: TripPreferences,
    day_index: int,
    travel_data: list[dict[str, str]],
    previous_days: list[str],
    current_plan: str = "",
    feedback: str = "",
) -> str:
    destination = preferences.destination or "目的地"
    date_label = _target_date_for_day(preferences, day_index)
    previous_text = "\n\n".join(previous_days[-2:]) or "无"
    return f"""
请只生成第 {day_index} 天的中文旅行攻略，不要输出其他天，不要输出总摘要。

基础信息：
- 出发城市：{preferences.origin or "未提供"}
- 目的地：{destination}
- 日期：{date_label}
- 总天数：{preferences.days}
- 人数：{preferences.travelers}
- 预算风格：{budget_label(preferences.budgetStyle)}
- 交通偏好：{preferences.transportMode}，火车席别 {preferences.trainSeatPreference}
- 住宿偏好：{preferences.hotelPreference}，预算 {preferences.hotelBudgetPerNight or "未限定"} 元/晚
- 抖音识别景点：{", ".join(preferences.spots) or "未识别"}
- 视频路线总结：{preferences.videoSummary or "未提供"}
- 视频预算线索：{preferences.videoBudgetText or (str(preferences.videoBudgetAmount) + " 元" if preferences.videoBudgetAmount else "未提及")}
- 视频提到的食物：{", ".join(preferences.videoFoods) or "未识别"}
- 用户选择复刻/增加的地点：{", ".join(preferences.routeReferencePlaces or preferences.spots) or "未选择"}
- 出行爱好：{", ".join(preferences.travelInterests) or "未指定"}
- 景点类型偏好：{", ".join(preferences.spotTypes) or "未指定"}
- 补充要求：{preferences.notes or "无"}

参考信息，必须作为事实依据：
{_format_reference_info(travel_data)}

前面已规划的天数，避免重复和折返：
{previous_text}

当前方案：
{current_plan or "无"}

用户调整要求：
{feedback or "无"}

严格输出格式：
### Day {day_index}｜一句话主题
- **时间线**
  - 09:00-10:30：点位/交通，说明游玩约多久或移动约多久
  - 12:00-13:10：午餐，说明当时所在区域、推荐吃什么；有真实美食 POI 才能写具体店名，否则写“到某区域复核高分店”
  - 18:00-19:20：晚餐，规则同上
- **好玩重点**：2-4 条，解释为什么值得去、适合拍照/人文/亲子/轻徒步等哪类偏好
- **好吃安排**：午餐和晚餐分别写，不要空泛
- **交通/预约**：写清跨区移动、排队、预约、天气或营业时间复核
#### 备选方案
- 只给 1 个备选：适用于下雨、体力不足或热门点排队过长时怎么替换。

要求：
- 必须有具体时间段和预计停留/移动时长。
- 如果参考信息明确未配置或失败，不得编造实时票价、余票、酒店房态、营业时间、餐厅评分。
- 不要在输出中写“工具返回”“工具调用”“已调用工具数据”“地图 POI”“MCP”，直接写地点和建议。
- 内容要像真实自由行攻略，保留关键信息，不要写营销口号。
"""


def fallback_day_plan(
    preferences: TripPreferences,
    day_index: int,
    travel_data: list[dict[str, str]] | None = None,
    feedback: str = "",
) -> str:
    destination = preferences.destination or "目的地"
    map_spots = _extract_poi_names(_tool_content(travel_data, "map_poi"), limit=6)
    food_pois = _extract_poi_names(_tool_content(travel_data, "map_food"), limit=4)
    candidates = preferences.spots[:6] or map_spots or [
        f"{destination}核心景区",
        f"{destination}城市漫步街区",
        f"{destination}本地生活商圈",
    ]
    focus = candidates[(day_index - 1) % len(candidates)]
    second = candidates[day_index % len(candidates)] if len(candidates) > 1 else f"{destination}同区域点位"
    third = candidates[(day_index + 1) % len(candidates)] if len(candidates) > 2 else f"{destination}夜游区域"
    lunch = food_pois[(day_index - 1) % len(food_pois)] if food_pois else f"{focus}附近商圈复核高分本地菜/小吃店"
    dinner = food_pois[day_index % len(food_pois)] if len(food_pois) > 1 else f"{third}附近夜市或老街复核高分店"
    interests = "、".join(preferences.travelInterests) or "轻松体验"
    date_label = _target_date_for_day(preferences, day_index)

    if day_index == 1:
        theme = "抵达适应和核心区域初体验"
        timeline = [
            f"09:30-10:20：抵达{destination}后前往酒店寄存行李，移动和整理约50分钟；具体时间按车次/航班微调。",
            f"10:30-12:00：游玩{focus}，停留约90分钟，先完成视频里最想复刻的主点位。",
            f"12:00-13:10：午餐：{lunch}，优先选排队可控、离下午路线近的店。",
            f"13:30-15:30：前往{second}，游玩约2小时，把拍照和人文点集中完成。",
            f"15:30-16:00：同区域移动/咖啡休息约30分钟，避免下午过度赶路。",
            f"16:00-17:30：补充{destination}城市漫步或室内点位，停留约90分钟。",
            f"18:00-19:20：晚餐：{dinner}，以当地菜、小吃或夜市为主。",
            f"19:30-21:00：夜游{third}或核心商圈，停留约90分钟后回酒店。",
        ]
    elif day_index == preferences.days:
        theme = "补漏、伴手礼和返程缓冲"
        timeline = [
            "09:00-09:40：退房并寄存行李，预留约40分钟。",
            f"09:50-11:40：补玩{focus}，停留约110分钟，优先选择离酒店/车站不远的点。",
            f"12:00-13:10：午餐：{lunch}，选择不绕路、出餐稳定的店。",
            f"13:20-15:00：逛{destination}伴手礼或本地生活街区，停留约100分钟。",
            "15:00-16:00：返回酒店取行李并前往车站/机场，移动约60分钟；按实际票务提前调整。",
            "18:00 左右：若返程较晚，在车站/商圈附近安排简餐，不再跨区。",
        ]
    else:
        theme = "核心景点串联和兴趣体验"
        timeline = [
            f"08:50-10:50：游玩{focus}，停留约2小时，热门点尽量早到。",
            f"10:50-11:30：前往{second}，同城移动约40分钟。",
            f"11:30-12:20：游玩{second}前半段，先完成必看点。",
            f"12:20-13:30：午餐：{lunch}，选择当前区域，不为吃饭额外跨区。",
            f"13:40-15:40：继续{second}或相邻点位，停留约2小时。",
            f"15:40-16:20：休息/转场约40分钟。",
            f"16:20-17:50：安排{preferences.spotTypes[0] if preferences.spotTypes else '城市漫步'}体验，停留约90分钟。",
            f"18:10-19:30：晚餐：{dinner}，结合{interests}选择本地菜、小吃或夜市。",
            f"19:40-21:00：夜游{third}或回酒店附近轻松活动。",
        ]

    timeline_md = "\n".join(f"  - {item}" for item in timeline)
    return f"""### Day {day_index}｜{theme}
- **时间线**
{timeline_md}
- **好玩重点**
  - {focus}：作为当天主线点位，建议把拍照、打卡或视频复刻玩法放在这里完成。
  - {second}：和主线区域搭配，减少跨区折返，适合{interests}。
  - {third}：更适合傍晚或夜间补充，节奏比白天轻。
- **好吃安排**
  - 午餐：{lunch}，控制在 70 分钟左右，避免影响下午路线。
  - 晚餐：{dinner}，如果没有实时营业数据，出发前复核营业时间、排队和评分。
- **交通/预约**
  - 当天控制 2-3 次主要移动；热门景点预约、开放时间和天气需出发前复核。
  - {date_label} 的大交通、酒店房态和餐厅排队情况以当天查询为准。
#### 备选方案
- 如果下雨、体力不足或热门点排队超过 45 分钟，删掉最远的点位，改成酒店/商圈附近的室内展馆、老街咖啡或本地市集。"""


def build_agent() -> Any | None:
    if not _env("OPENAI_API_KEY") or create_deep_agent is None or ChatOpenAI is None:
        return None

    model = ChatOpenAI(
        model=_env("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=_env("OPENAI_API_KEY"),
        base_url=_env("OPENAI_BASE_URL") or None,
        temperature=0.4,
    )
    tools = [
        search_destination_info,
        query_map_pois,
        query_route_distance,
        query_weather,
        query_train_tickets,
        query_hotels,
        estimate_budget,
        optimize_daily_route,
    ]

    # DeepAgents changed constructor naming across early releases. Try newest first,
    # then fall back to legacy spellings so local installs remain usable.
    try:
        return create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            subagents=SUBAGENTS,
        )
    except TypeError:
        legacy_subagents = [
            {
                "name": item["name"],
                "description": item["description"],
                "prompt": item["system_prompt"],
            }
            for item in SUBAGENTS
        ]
        try:
            return create_deep_agent(
                tools=tools,
                instructions=SYSTEM_PROMPT,
                model=model,
                subagents=legacy_subagents,
            )
        except TypeError:
            return create_deep_agent(tools, SYSTEM_PROMPT)


def extract_agent_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content:
                return str(content)
            if isinstance(last, dict) and last.get("content"):
                return str(last["content"])
        for key in ("output", "final", "content"):
            if result.get(key):
                return str(result[key])
    return str(result)


async def run_deep_agent(prompt: str) -> str | None:
    agent = build_agent()
    if agent is None:
        return None

    payload = {"messages": [{"role": "user", "content": prompt}]}
    if hasattr(agent, "ainvoke"):
        result = await agent.ainvoke(payload)
    else:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: agent.invoke(payload))
    return extract_agent_text(result)


def _extract_chat_text(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return ""


async def run_llm_text(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str | None:
    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = (_env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": _env("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
    text = _extract_chat_text(response.json())
    return text or None


async def synthesize_tts(request: TtsRequest) -> bytes:
    config = tts_config_status()
    api_key = _env("MIMO_TTS_API_KEY") or _env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("MIMO_TTS_API_KEY 或 OPENAI_API_KEY 未配置")

    base_url = str(config["baseUrl"]).rstrip("/")
    voice = request.voice.strip() or str(config["voice"])
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "user", "content": request.style},
            {"role": "assistant", "content": request.text[:6000]},
        ],
        "audio": {
            "format": "wav",
            "voice": voice,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "audio" in content_type or response.content[:4] == b"RIFF":
        return response.content

    data = response.json()
    audio_data = _find_audio_payload(data)
    if not audio_data:
        raise RuntimeError(f"TTS 响应中未找到音频数据：{_summarize_payload(data, 500)}")
    return audio_data


def _find_audio_payload(data: Any) -> bytes | None:
    import base64

    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception:
            return None
    if isinstance(data, list):
        for item in data:
            found = _find_audio_payload(item)
            if found:
                return found
    if isinstance(data, dict):
        for key in ("message", "audio", "data", "content", "b64_json"):
            value = data.get(key)
            if isinstance(value, str):
                found = _find_audio_payload(value)
                if found:
                    return found
            if isinstance(value, (dict, list)):
                found = _find_audio_payload(value)
                if found:
                    return found
        choices = data.get("choices")
        if choices:
            found = _find_audio_payload(choices)
            if found:
                return found
    return None


def fallback_plan(
    preferences: TripPreferences,
    current_plan: str = "",
    feedback: str = "",
    travel_data: list[dict[str, str]] | None = None,
) -> str:
    destination = preferences.destination or "目的地"
    departure_date = normalized_departure_date(preferences)
    return_date = normalized_return_date(preferences)
    budget = estimate_budget(destination, preferences.days, preferences.budgetStyle)
    weather = get_weather_hint(destination, normalized_departure_date(preferences))
    hotel_budget = f"{preferences.hotelBudgetPerNight} 元/晚" if preferences.hotelBudgetPerNight else "未限定"
    interests = "、".join(preferences.travelInterests) or "轻松体验"
    spot_types = "、".join(preferences.spotTypes) or "经典景点"
    daily_sections = [fallback_day_plan(preferences, day, travel_data=travel_data, feedback=feedback) for day in range(1, preferences.days + 1)]

    adjustment = ""
    if feedback:
        adjustment = f"\n\n## 本次调整\n已按“{feedback}”重新压缩节奏、预算或兴趣权重；如与原方案冲突，优先满足本次反馈。"
    elif current_plan:
        adjustment = "\n\n## 本次调整\n保留原方案的目的地和天数，重新整理为更清晰的执行版。"

    cost = estimate_total_trip_cost(preferences)

    return f"""# {destination}{preferences.days}天旅行方案

## 关键摘要
- 玩法重点：围绕{interests}和{spot_types}，每天 2-4 个主要停靠点。
- 数据来源：实时地图、火车票或酒店工具未返回完整可用数据时，本方案按本地规则降级生成。
- 复核事项：余票、房态、开放时间和天气需出发前再次确认。
- 出发城市：{preferences.origin or "未提供"}
- 日期：{departure_date} 至 {return_date}
- 人数：{preferences.travelers} 人
- 交通：{transport_label(preferences.transportMode)}，火车席别 {preferences.trainSeatPreference}。
- 住宿：偏好 {preferences.hotelPreference}，预算 {hotel_budget}。
- 天气：{weather}
- 总花费：{cost}

{chr(10).join(daily_sections)}

## 预算
{budget}{adjustment}
"""


async def plan_events(preferences: TripPreferences, current_plan: str = "", feedback: str = "") -> AsyncIterator[str]:
    yield event("status", "正在理解视频标题和旅行偏好。")
    llm_status_data = llm_config_status()
    day_llm_timeout = _env_float("PLAN_DAY_LLM_TIMEOUT_SECONDS", 15)
    if llm_status_data["enabled"]:
        yield event("status", f"大模型已启用：{llm_status_data['model']}。")
    else:
        reason = "OPENAI_API_KEY 未配置"
        yield event("status", f"大模型未启用，稍后使用本地兜底方案：{reason}。")
    travel_data: list[dict[str, str]] = []

    async def collect(label: str, message: str, value: str) -> AsyncIterator[str]:
        cleaned = _clean_user_facing_tool_text(value)
        travel_data.append({"source": label, "content": cleaned})
        yield event("tool", cleaned or message)
        await asyncio.sleep(0.05)

    async def collect_call(label: str, message: str, call: Any, timeout: float = 18) -> AsyncIterator[str]:
        try:
            value = await asyncio.wait_for(call, timeout=timeout)
        except Exception as exc:
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                exc_text = f"超过 {timeout:.0f}s 未返回"
            else:
                exc_text = str(exc) or exc.__class__.__name__
            value = f"{message}查询失败，已跳过并继续后续内容：{exc_text}"
        async for item in collect(label, message, str(value)):
            yield item

    destination = preferences.destination
    departure_date = normalized_departure_date(preferences)
    return_date = normalized_return_date(preferences)
    interest_text = "、".join(preferences.travelInterests)
    spot_text = "、".join(preferences.spotTypes)
    route_reference_places = preferences.routeReferencePlaces or preferences.spots
    poi_keywords = " ".join(route_reference_places[:3]) or (spot_text or "景点")
    food_keywords = " ".join(preferences.videoFoods[:4]) or "美食 小吃 夜市 当地菜"

    basic_info = search_destination_info(destination, interest_text)
    async for item in collect("destination", "目的地信息", basic_info):
        yield item

    async for item in collect_call(
        "map_route",
        "地图路线",
        async_query_route_distance(preferences.origin, destination),
    ):
        yield item

    async for item in collect_call(
        "map_poi",
        "地图景点",
        async_query_map_pois(destination, poi_keywords),
    ):
        yield item

    async for item in collect_call(
        "map_food",
        "地图美食",
        async_query_map_pois(destination, food_keywords),
    ):
        yield item

    async for item in collect_call(
        "weather",
        "天气信息",
        async_query_weather(destination, departure_date),
    ):
        yield item

    async for item in collect_call(
        "train_12306",
        "12306 火车票",
        async_query_train_tickets(
            preferences.origin,
            destination,
            departure_date,
            preferences.trainSeatPreference,
        ),
        timeout=25,
    ):
        yield item

    async for item in collect_call(
        "hotel_mcp",
        "酒店信息",
        async_query_hotels(
            destination,
            departure_date,
            return_date,
            preferences.hotelPreference,
            preferences.hotelBudgetPerNight,
            preferences.travelers,
        ),
        timeout=25,
    ):
        yield item

    budget_info = estimate_budget(destination, preferences.days, preferences.budgetStyle)
    async for item in collect("budget", "预算估算", budget_info):
        yield item

    route_plan = optimize_daily_route(destination, preferences.days, spot_text)
    async for item in collect("route", "路线优化", route_plan):
        yield item

    analysis_context = (
        f"已整理 {len(travel_data)} 条参考信息。"
        "会优先使用真实地点、天气、车票和住宿信息；"
        "暂未返回的数据只作为待复核条件，不会伪造实时信息。"
    )
    async for item in collect("tool_analysis", "信息整理", analysis_context):
        yield item

    summary = build_key_summary(preferences, travel_data)
    yield event("summary", "关键摘要已生成。", summary)
    yield event("status", "正在按天生成可执行行程，完成一天就会先返回一天。")

    previous_days: list[str] = []
    final_sections = [summary]
    for day_index in range(1, preferences.days + 1):
        yield event("status", f"正在规划 Day {day_index}：时间线、饭点、交通和备选方案。")
        try:
            prompt = build_day_prompt(
                preferences,
                day_index,
                travel_data,
                previous_days,
                current_plan=current_plan,
                feedback=feedback,
            )
            agent_text = await asyncio.wait_for(run_llm_text(prompt), timeout=day_llm_timeout) if llm_status_data["enabled"] else None
            day_text = _extract_day_block(agent_text or "", day_index, preferences) if agent_text else fallback_day_plan(
                preferences,
                day_index,
                travel_data=travel_data,
                feedback=feedback,
            )
        except Exception as exc:
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                yield event("status", f"Day {day_index} 大模型超过 {day_llm_timeout:.0f}s 未返回，已切换本地兜底日程。")
            else:
                yield event("status", f"Day {day_index} Agent 调用失败，已跳过并使用兜底日程：{exc}")
            day_text = fallback_day_plan(preferences, day_index, travel_data=travel_data, feedback=feedback)

        previous_days.append(day_text)
        final_sections.append(day_text)
        yield event(
            "day",
            f"Day {day_index} 已生成。",
            {
                "index": day_index - 1,
                "title": _title_from_day(day_text, day_index),
                "content": day_text,
            },
        )
        await asyncio.sleep(0.05)

    final_plan = "\n\n".join(final_sections)
    yield event("done", "规划完成。", final_plan)


@app.post("/api/trips/plan/stream")
async def plan_trip(request: PlanRequest) -> StreamingResponse:
    return StreamingResponse(
        plan_events(request.preferences),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/trips/refine/stream")
async def refine_trip(request: RefineRequest) -> StreamingResponse:
    return StreamingResponse(
        plan_events(
            request.preferences,
            current_plan=request.currentPlan,
            feedback=request.feedback,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/tts")
async def tts(request: TtsRequest) -> Response:
    try:
        audio = await synthesize_tts(request)
        return Response(content=audio, media_type="audio/wav")
    except Exception as exc:
        return Response(
            content=_json({"error": str(exc)}),
            status_code=502,
            media_type="application/json",
        )
