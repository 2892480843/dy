"use client";

import {
  type CSSProperties,
  type FormEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import {
  ArrowLeft,
  BedDouble,
  CalendarDays,
  Camera,
  CarFront,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  ClipboardPaste,
  Clock3,
  Compass,
  Heart,
  Hotel,
  Info,
  Link2,
  Loader2,
  LocateFixed,
  Map,
  MapPin,
  Navigation,
  Pause,
  Plus,
  RefreshCcw,
  Route,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  TrainFront,
  Utensils,
  Users,
  Volume2,
  WalletCards,
  X,
} from "lucide-react";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

function getApiBaseUrl() {
  const configuredApiBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configuredApiBase) return configuredApiBase.replace(/\/$/, "");
  return "";
}

const API_BASE = getApiBaseUrl();
const ORIGIN_CITY_CACHE_KEY = "doutrip_origin_city_cache";
const ORIGIN_CITY_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

type Step = "entry" | "parsing" | "confirm" | "transport" | "preferences" | "review" | "planning" | "result";
type GeoStatus = "idle" | "locating" | "success" | "failed";

type PlaceOption = {
  id: string;
  name: string;
  type: "spot" | "food" | "hotel" | "shopping" | "area" | "other";
  reason: string;
  source: "blogger" | "nearby";
  selected: boolean;
};

type VideoAnalysisResult = {
  videoId: string;
  cacheHit: boolean;
  status: "success" | "partial" | "needs_manual_input";
  title: string;
  destination: string;
  summary: string;
  transcript: string;
  audioSaved: boolean;
  audioLocalPath: string;
  audioUrl: string;
  spots: string[];
  foods: string[];
  budgetText: string;
  budgetAmount: number | null;
  bloggerPlaces: PlaceOption[];
  nearbyPlaces: PlaceOption[];
  needsManualInput: boolean;
  message: string;
};

type TransportSummaryItem = {
  label: string;
  value: string;
  detail: string;
};

type TransportSummary = {
  status: "success" | "partial" | "needs_manual_input";
  origin: string;
  destination: string;
  mode: TripPreferences["transportMode"];
  items: TransportSummaryItem[];
  message: string;
};

type GeoCityResponse = {
  status: "success" | "needs_manual_input";
  city: string;
  message?: string;
};

type PlanEvent = {
  type: "status" | "tool" | "content" | "summary" | "day" | "done" | "error";
  message?: string;
  payload?: string | Record<string, unknown>;
};

type TripPreferences = {
  link: string;
  videoId: string;
  videoTitle: string;
  videoSummary: string;
  videoTranscript: string;
  videoBudgetText: string;
  videoBudgetAmount: number | null;
  videoFoods: string[];
  routeReferencePlaces: string[];
  origin: string;
  destination: string;
  spots: string[];
  departureDate: string;
  returnDate: string;
  startDateRange: string;
  days: number;
  travelers: number;
  budgetStyle: "budget" | "comfort" | "luxury";
  transportMode: "train" | "any" | "car";
  trainSeatPreference: string;
  hotelPreference: string;
  hotelBudgetPerNight: number | null;
  travelInterests: string[];
  spotTypes: string[];
  notes: string;
};

type DayPlan = {
  title: string;
  content: string;
};

type DayPlanPayload = {
  index?: number;
  title?: string;
  content?: string;
};

type TimelinePoint = {
  id: string;
  time: string;
  title: string;
  summary: string;
  detail: string;
  kind: "spot" | "food" | "transport" | "hotel" | "rest";
};

const appSteps: Array<{ id: Step; label: string }> = [
  { id: "entry", label: "入口" },
  { id: "confirm", label: "分析" },
  { id: "transport", label: "交通" },
  { id: "preferences", label: "偏好" },
  { id: "planning", label: "规划" },
  { id: "result", label: "方案" },
];

const analysisStages = [
  { key: "fetch", label: "读取视频链接", hint: "校验链接与视频信息" },
  { key: "download", label: "下载并保存音频", hint: "提取视频里的声音线索" },
  { key: "asr", label: "语音转写", hint: "识别视频中的地点与表达" },
  { key: "llm", label: "提取地点 / 美食 / 预算", hint: "整理可复刻路线" },
  { key: "nearby", label: "补充周边可玩地点", hint: "补齐顺路备选点" },
] as const;

const analysisStageIndexByName: Record<string, number> = {
  fetch: 0,
  cache: 4,
  download: 1,
  asr: 2,
  llm: 3,
  nearby: 4,
  done: 4,
};

const estimatedAnalysisStageThresholds = [
  { progress: 0, stageIndex: 0 },
  { progress: 22, stageIndex: 1 },
  { progress: 44, stageIndex: 2 },
  { progress: 72, stageIndex: 3 },
  { progress: 88, stageIndex: 4 },
] as const;

function stageIndexFromAnalysisProgress(progress: number) {
  return estimatedAnalysisStageThresholds.reduce(
    (current, item) => (progress >= item.progress ? item.stageIndex : current),
    0,
  );
}

function estimateNextAnalysisProgress(current: number) {
  if (current >= 96) return current;
  if (current < 18) return current + 2;
  if (current < 44) return current + 1.5;
  if (current < 72) return current + 1;
  if (current < 88) return current + 0.7;
  return current + 0.35;
}

// 各阶段对应的彩色图标与点缀文案，仅用于解析中页面的视觉表达
const analysisStageVisuals: Record<
  (typeof analysisStages)[number]["key"],
  { Icon: typeof Link2; tone: "blue" | "orange" | "violet" | "green" | "gold"; tagline: string }
> = {
  fetch: { Icon: Link2, tone: "blue", tagline: "建立连接" },
  download: { Icon: Volume2, tone: "orange", tagline: "保存声音" },
  asr: { Icon: Sparkles, tone: "violet", tagline: "听懂视频" },
  llm: { Icon: MapPin, tone: "green", tagline: "整理线索" },
  nearby: { Icon: Compass, tone: "gold", tagline: "顺路探索" },
};

const interestOptions = ["美食", "摄影", "人文", "亲子", "情侣", "轻徒步", "夜生活", "避开人群"];
const spotTypeOptions = ["自然风光", "古镇街区", "博物馆", "网红打卡", "城市漫步", "主题乐园", "小众路线", "当地市集"];
const trainSeatOptions = ["不限", "二等座", "一等座", "商务座", "硬卧", "软卧"];
const hotelOptions = ["交通方便", "舒适型酒店", "亲子友好", "设计感民宿", "靠近景区", "安静好睡"];

const dayImageUrls = [
  "/images/fallback/day-1.jpg",
  "/images/fallback/day-2.jpg",
  "/images/fallback/day-3.jpg",
  "/images/fallback/day-4.jpg",
  "/images/fallback/day-5.jpg",
];

const foodImageUrls = ["/images/fallback/food-1.jpg", "/images/fallback/food-2.jpg", "/images/fallback/food-3.jpg"];
const transportImageUrls = ["/images/fallback/transport-2.jpg", "/images/fallback/transport-3.jpg"];
const hotelImageUrls = ["/images/fallback/hotel-1.jpg", "/images/fallback/hotel-2.jpg"];

const foodKeywordHints = [
  "西湖醋鱼",
  "龙井虾仁",
  "片儿川",
  "葱包桧",
  "茶点",
  "火锅",
  "小面",
  "烧烤",
  "海鲜",
  "小吃",
  "夜市",
  "本地菜",
];

const placeSuffixes = [
  "风景名胜区",
  "景区",
  "景点",
  "公园",
  "广场",
  "博物馆",
  "美术馆",
  "艺术馆",
  "纪念馆",
  "古镇",
  "古城",
  "步行街",
  "夜市",
  "商圈",
  "码头",
  "市场",
  "市集",
  "酒店",
  "民宿",
  "餐厅",
  "饭店",
  "酒家",
  "小馆",
  "寺",
  "塔",
  "山",
  "湖",
  "岛",
  "桥",
  "路",
  "街",
  "巷",
  "园",
  "馆",
  "楼",
  "村",
];

function localDateIso(date: Date) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localDate.toISOString().slice(0, 10);
}

function daysFromNowIso(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return localDateIso(date);
}

function addDaysIso(dateIso: string, days: number) {
  const date = dateIso ? new Date(`${dateIso}T00:00:00`) : new Date();
  if (Number.isNaN(date.getTime())) return daysFromNowIso(days);
  date.setDate(date.getDate() + days);
  return localDateIso(date);
}

function createInitialPreferences(): TripPreferences {
  return {
    link: "",
    videoId: "",
    videoTitle: "",
    videoSummary: "",
    videoTranscript: "",
    videoBudgetText: "",
    videoBudgetAmount: null,
    videoFoods: [],
    routeReferencePlaces: [],
    origin: "",
    destination: "",
    spots: [],
    departureDate: daysFromNowIso(1),
    returnDate: "",
    startDateRange: "",
    days: 3,
    travelers: 2,
    budgetStyle: "comfort",
    transportMode: "train",
    trainSeatPreference: "不限",
    hotelPreference: "交通方便",
    hotelBudgetPerNight: null,
    travelInterests: ["美食", "摄影"],
    spotTypes: ["自然风光", "城市漫步"],
    notes: "",
  };
}

function parseSseLine(line: string): PlanEvent | null {
  if (!line.startsWith("data:")) return null;
  const raw = line.slice(5).trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PlanEvent;
  } catch {
    return { type: "content", message: raw };
  }
}

function stepIndex(step: Step) {
  if (step === "entry" || step === "parsing") return 0;
  if (step === "confirm") return 1;
  if (step === "transport") return 2;
  if (step === "preferences" || step === "review") return 3;
  if (step === "planning") return 4;
  return 5;
}

function budgetLabel(style: TripPreferences["budgetStyle"]) {
  if (style === "budget") return "穷游";
  if (style === "luxury") return "富游";
  return "舒适";
}

function budgetDescription(style: TripPreferences["budgetStyle"]) {
  if (style === "budget") return "节省为主，体验在地";
  if (style === "luxury") return "品质优先，深度体验";
  return "品质体验，轻松自在";
}

function transportLabel(mode: TripPreferences["transportMode"]) {
  if (mode === "car") return "自驾";
  if (mode === "any") return "不限";
  return "高铁 / 火车";
}

function placeTypeLabel(type: PlaceOption["type"]) {
  if (type === "food") return "美食";
  if (type === "hotel") return "住宿";
  if (type === "shopping") return "购物";
  if (type === "area") return "街区";
  if (type === "other") return "其他";
  return "景点";
}

function inferBudgetStyleFromAmount(amount: number | null): TripPreferences["budgetStyle"] {
  if (!amount) return "comfort";
  if (amount <= 900) return "budget";
  if (amount >= 2600) return "luxury";
  return "comfort";
}

function compactDate(preferences: TripPreferences) {
  const departure = preferences.departureDate || daysFromNowIso(1);
  const returnDate = addDaysIso(departure, Math.max(preferences.days - 1, 0));
  return `${departure} 至 ${returnDate}`;
}

function estimatedTripCost(preferences: TripPreferences) {
  const dailyBase = { budget: 240, comfort: 520, luxury: 980 }[preferences.budgetStyle];
  const defaultHotel = { budget: 220, comfort: 520, luxury: 1200 }[preferences.budgetStyle];
  const hotelPerNight = preferences.hotelBudgetPerNight || defaultHotel;
  const nights = Math.max(preferences.days - 1, 0);
  const localLow = dailyBase * preferences.days;
  const localHigh = Math.round(localLow * 1.35);
  const hotelLow = nights * hotelPerNight;
  const hotelHigh = Math.round(hotelLow * 1.25);
  const personLow = localLow + hotelLow;
  const personHigh = localHigh + hotelHigh;
  return {
    person: `约 ${personLow.toLocaleString("zh-CN")}-${personHigh.toLocaleString("zh-CN")} 元/人`,
    total: `约 ${(personLow * preferences.travelers).toLocaleString("zh-CN")}-${(personHigh * preferences.travelers).toLocaleString("zh-CN")} 元`,
    detail: `按 ${preferences.days} 天、${nights} 晚、${preferences.travelers} 人估算，不含实时大交通票价。`,
  };
}

function readOriginCityCache() {
  if (typeof window === "undefined") return "";
  try {
    const raw = window.localStorage.getItem(ORIGIN_CITY_CACHE_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw) as { city?: string; expiresAt?: number };
    if (!parsed.city || !parsed.expiresAt || parsed.expiresAt < Date.now()) {
      window.localStorage.removeItem(ORIGIN_CITY_CACHE_KEY);
      return "";
    }
    return parsed.city;
  } catch {
    return "";
  }
}

function writeOriginCityCache(city: string) {
  if (typeof window === "undefined" || !city.trim()) return;
  try {
    window.localStorage.setItem(
      ORIGIN_CITY_CACHE_KEY,
      JSON.stringify({ city: city.trim(), expiresAt: Date.now() + ORIGIN_CITY_CACHE_TTL_MS }),
    );
  } catch {
    // Local storage can be unavailable in private mode.
  }
}

function clearOriginCityCache() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ORIGIN_CITY_CACHE_KEY);
  } catch {
    // Ignore cache cleanup failures.
  }
}

function uniqueValues(values: string[], limit = 12) {
  const result: string[] = [];
  values.forEach((value) => {
    const next = value.trim();
    if (!next) return;
    if (result.some((item) => item === next || item.includes(next) || next.includes(item))) return;
    result.push(next);
  });
  return result.slice(0, limit);
}

function fallbackPlacesFromAnalysis(data: VideoAnalysisResult | null): PlaceOption[] {
  if (!data) return [];
  return uniqueValues([...(data.spots || []), ...(data.foods || [])], 10).map((name, index) => ({
    id: `fallback-${index}-${name}`,
    name,
    type: data.foods.includes(name) ? "food" : "spot",
    reason: data.foods.includes(name) ? "视频里提到的美食线索" : "视频里提到的路线点",
    source: "blogger",
    selected: true,
  }));
}

function planEventText(event: PlanEvent) {
  if (typeof event.payload === "string") return event.payload;
  return event.message || "";
}

function dayPayload(payload: PlanEvent["payload"]): DayPlanPayload | null {
  if (!payload || typeof payload === "string") return null;
  const content = typeof payload.content === "string" ? payload.content : "";
  if (!content) return null;
  return {
    index: typeof payload.index === "number" ? payload.index : undefined,
    title: typeof payload.title === "string" ? payload.title : undefined,
    content,
  };
}

function dayImageUrl(index: number) {
  return dayImageUrls[index % dayImageUrls.length];
}

function fallbackPointImage(point: TimelinePoint, index: number) {
  if (point.kind === "food") return foodImageUrls[index % foodImageUrls.length];
  if (point.kind === "transport") return transportImageUrls[index % transportImageUrls.length];
  if (point.kind === "hotel") return hotelImageUrls[index % hotelImageUrls.length];
  if (point.kind === "rest") return dayImageUrls[(index + 2) % dayImageUrls.length];
  return dayImageUrls[index % dayImageUrls.length];
}

function parseDailyPlans(plan: string, days: number): DayPlan[] {
  const matches = [...plan.matchAll(/^###\s*(Day\s*\d+|第\s*\d+\s*天|D\d+)[^\n]*\n?/gim)];
  if (!matches.length) {
    return Array.from({ length: Math.max(days, 1) }, (_, index) => ({
      title: `Day ${index + 1}`,
      content: index === 0 ? plan : "这一日的详细攻略会跟随完整方案调整。",
    }));
  }

  return matches.map((match, index) => {
    const start = match.index ?? 0;
    const next = matches[index + 1]?.index ?? plan.length;
    const block = plan.slice(start, next).trim();
    const firstLine = block.split("\n")[0]?.replace(/^###\s*/, "").trim() || `Day ${index + 1}`;
    return { title: firstLine, content: block };
  });
}

function splitAlternativeSection(content: string) {
  const match = content.match(/(?:^|\n)#{2,5}\s*备选(?:方案|调整)?[^\n]*\n?/i);
  if (!match || match.index === undefined) return { main: content, alternative: "" };
  const start = match.index + (content[match.index] === "\n" ? 1 : 0);
  return { main: content.slice(0, start).trim(), alternative: content.slice(start).trim() };
}

function stripMarkdown(text: string) {
  return text
    .replace(/#{1,6}\s*/g, "")
    .replace(/\*\*/g, "")
    .replace(/[*_`>]/g, "")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function classifyPoint(text: string): TimelinePoint["kind"] {
  if (/午餐|晚餐|早餐|夜宵|下午茶|咖啡|餐|吃|菜|小吃|美食/.test(text)) return "food";
  if (/酒店|民宿|入住|退房|寄存|住宿/.test(text)) return "hotel";
  if (/休息|小憩/.test(text)) return "rest";
  if (/前往|抵达|返回|高铁|火车|地铁|公交|打车|机场|车站|移动|交通|乘坐|自驾/.test(text)) return "transport";
  return "spot";
}

function summarizePoint(text: string, kind: TimelinePoint["kind"]) {
  const clean = stripMarkdown(text);
  const firstSentence = clean.split(/[。；;]/)[0]?.trim() || clean;
  const summary = firstSentence.replace(/^[：:，,\s-]+/, "");
  const limit = kind === "transport" ? 38 : kind === "food" ? 40 : 44;
  return summary.length <= limit ? summary : `${summary.slice(0, limit)}...`;
}

function normalizePointTitle(rawTitle: string, detail: string) {
  const title = stripMarkdown(rawTitle).replace(/^[：:，,\s-]+/, "").replace(/\s*（.*?）\s*/g, "").trim();
  if (title && title.length <= 34) return title;
  const clean = stripMarkdown(detail);
  const candidates = clean.match(/[\u4e00-\u9fa5A-Za-z0-9·&（）() -]{2,24}/g) || [];
  return candidates.find((item) => !/移动|游玩|约|分钟|小时|建议|推荐/.test(item))?.trim() || title.slice(0, 34) || "行程点";
}

function parseTimelinePoints(content: string): TimelinePoint[] {
  const main = splitAlternativeSection(content).main;
  const lines = main.split("\n");
  const points: TimelinePoint[] = [];
  const timePattern = /(?:\*\*)?(\d{1,2}:\d{2}(?:\s*[-—~至]\s*\d{1,2}:\d{2})?|(?:上午|下午|晚上|中午|傍晚)\s*\d{0,2}:?\d{0,2})(?:\*\*)?[：:]\s*(.+)/;
  let current: { time: string; detail: string } | null = null;

  const pushCurrent = () => {
    if (!current) return;
    const kind = classifyPoint(current.detail);
    const titlePart = current.detail.split(/[。；;]/)[0] || current.detail;
    const title = normalizePointTitle(titlePart, current.detail);
    points.push({
      id: `${points.length}-${current.time}-${title}`,
      time: current.time,
      title,
      summary: summarizePoint(current.detail, kind),
      detail: current.detail,
      kind,
    });
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/^\s*[-*]\s*/, "").trim();
    if (!line) continue;
    const match = line.match(timePattern);
    if (match) {
      pushCurrent();
      current = { time: stripMarkdown(match[1] || ""), detail: match[2] || "" };
    } else if (current && !/^#{1,6}\s/.test(line)) {
      current.detail = `${current.detail} ${line}`;
    }
  }
  pushCurrent();

  if (points.length) return points.slice(0, 8);
  return main
    .split("\n")
    .map((line) => line.replace(/^\s*[-*]\s*/, "").trim())
    .filter((line) => line.length > 8 && !line.startsWith("#"))
    .slice(0, 6)
    .map((line, index) => {
      const kind = classifyPoint(line);
      return {
        id: `fallback-${index}-${line.slice(0, 12)}`,
        time: index === 0 ? "09:00" : `${String(9 + index * 2).padStart(2, "0")}:00`,
        title: normalizePointTitle(line, line),
        summary: summarizePoint(line, kind),
        detail: line,
        kind,
      };
    });
}

function cleanPlaceCandidate(value: string) {
  let candidate = stripMarkdown(value)
    .replace(/^\d{1,2}:\d{2}(?:\s*[-—至]\s*\d{1,2}:\d{2})?[：:\s-]*/, "")
    .replace(/^(上午|下午|晚上|中午|傍晚)\s*\d{0,2}:?\d{0,2}[：:\s-]*/, "")
    .replace(/^[：:，,\s\-—]+/, "")
    .trim();
  candidate = candidate
    .split(/[。；;，,、]/)[0]
    .replace(/（.*?）|\(.*?\)/g, "")
    .replace(/^(游玩|前往|抵达|返回|入住|退房|寄存|夜游|参观|打卡|逛逛|逛|到|在|安排|补玩|继续|先去|去|选择|推荐|午餐|晚餐|早餐|交通|移动)+/, "")
    .replace(/(附近|周边|区域|一带|门口|入口|出口|站点|打卡点|拍照点|游玩|停留|移动|用餐|休息|复核.*$)/, "")
    .replace(/\s+/g, "")
    .trim();
  if (!candidate || candidate.length < 2 || candidate.length > 28) return "";
  if (/分钟|小时|左右|建议|如果|可选|备选|排队|天气|营业|开放|预约|高分/.test(candidate)) return "";
  return candidate;
}

function cleanFoodCandidate(value: string) {
  const candidate = stripMarkdown(value)
    .replace(/^[：:，,\s\-—]+/, "")
    .replace(/^(午餐|晚餐|早餐|夜宵|下午茶|咖啡|推荐|吃|尝试|安排)+/, "")
    .replace(/(附近|周边|区域|一带|复核|用餐|排队|出餐).*$/, "")
    .replace(/\s+/g, "")
    .trim();
  if (!candidate || candidate.length < 2 || candidate.length > 18) return "";
  if (/分钟|小时|左右|建议|如果|可选|备选|排队|天气|营业|开放|预约|高分/.test(candidate)) return "";
  return candidate;
}

function pushUniqueKeyword(target: string[], value: string, cleaner: (value: string) => string = cleanPlaceCandidate) {
  const keyword = cleaner(value);
  if (!keyword) return;
  if (target.some((item) => item === keyword || item.includes(keyword) || keyword.includes(item))) return;
  target.push(keyword);
}

function placeKeywordsForPoint(point: TimelinePoint, destination: string, knownSpots: string[]) {
  const raw = `${point.title}。${point.summary}。${point.detail}`;
  const clean = stripMarkdown(raw);
  const keywords: string[] = [];
  pushUniqueKeyword(keywords, point.title);

  knownSpots.forEach((spot) => {
    if (spot && clean.includes(spot)) pushUniqueKeyword(keywords, spot);
  });
  placeSuffixes.forEach((suffix) => {
    const escapedSuffix = suffix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const matches = clean.match(new RegExp(`[\\u4e00-\\u9fa5A-Za-z0-9·-]{2,24}${escapedSuffix}`, "g")) || [];
    matches.forEach((match) => pushUniqueKeyword(keywords, match));
  });
  const actionMatches = clean.matchAll(/(?:游玩|前往|抵达|入住|退房|寄存|夜游|参观|打卡|逛逛|逛|到|在|补玩|继续)([\u4e00-\u9fa5A-Za-z0-9·-]{2,24})/g);
  for (const match of actionMatches) pushUniqueKeyword(keywords, match[1] || "");
  const quotedMatches = raw.matchAll(/[“「《]([^”」》]{2,24})[”」》]/g);
  for (const match of quotedMatches) pushUniqueKeyword(keywords, match[1] || "");

  if (point.kind === "food") {
    const foodMatches = clean.matchAll(/([\u4e00-\u9fa5]{2,16}(?:菜|粉|面|鱼|肉|虾|鸡|鸭|糕|饼|汤|粥|饭|茶|酒|咖啡|火锅|烧烤|小吃|餐厅|饭店|酒家|小馆|店|馆|楼))/g);
    for (const match of foodMatches) pushUniqueKeyword(keywords, match[1] || "", cleanFoodCandidate);
  }
  if (destination && keywords.length === 0) keywords.push(destination);
  return keywords.slice(0, 5);
}

function imageKeywordForPoint(point: TimelinePoint) {
  const clean = stripMarkdown(`${point.title}。${point.summary}。${point.detail}`);
  if (point.kind === "food") {
    const hinted = foodKeywordHints.find((item) => clean.includes(item));
    if (hinted) return hinted;
    const quoted = clean.match(/[“「《]([^”」》]{2,16})[”」》]/)?.[1];
    if (quoted) return quoted;
    const foodPhrase = clean.match(/([\u4e00-\u9fa5]{2,12}(?:菜|粉|面|鱼|肉|虾|鸡|鸭|糕|饼|汤|粥|饭|茶|酒|咖啡|火锅|烧烤|小吃))/)?.[1];
    return `${foodPhrase || point.title} 美食`;
  }
  if (point.kind === "hotel") return `${point.title} 酒店`;
  return point.title;
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ children, href }) => (
          <a className="text-[#12385a] underline underline-offset-4" href={href} rel="noreferrer" target="_blank">
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function ProgressTracker({ step }: { step: Step }) {
  const active = stepIndex(step);
  return (
    <div className="dt-progress">
      <div className="dt-progress-line" style={{ "--active-step": active } as CSSProperties} />
      {appSteps.map((item, index) => {
        const state = index < active ? "done" : index === active ? "active" : "todo";
        return (
          <div className="dt-progress-item" data-state={state} key={item.id}>
            <span className="dt-progress-dot">{state === "done" ? <Check className="size-3" /> : null}</span>
            <span>{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function AppShell({ step, children }: { step: Step; children: React.ReactNode }) {
  const screenRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    window.scrollTo(0, 0);
    if (screenRef.current) screenRef.current.scrollTop = 0;
    const frame = window.requestAnimationFrame(() => {
      window.scrollTo(0, 0);
      if (screenRef.current) screenRef.current.scrollTop = 0;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [step]);

  return (
    <main className="dt-page">
      <div className="dt-phone">
        <div className="dt-screen" ref={screenRef}>
          <div className="dt-shell-top">
            <div className="dt-safe-top" aria-hidden="true" />
            <header className="dt-app-header">
              <div className="dt-brand">DouTrip Agent</div>
              <button className="dt-help-button" type="button" aria-label="旅行灵感">
                <Compass className="size-5" aria-hidden="true" />
              </button>
            </header>
            <ProgressTracker step={step} />
          </div>
          {children}
        </div>
      </div>
    </main>
  );
}

function BottomAction({
  primaryLabel,
  primaryIcon,
  onPrimary,
  primaryDisabled,
  secondaryLabel,
  onSecondary,
  secondaryIcon,
  secondaryDisabled,
  danger,
}: {
  primaryLabel: string;
  primaryIcon?: React.ReactNode;
  onPrimary: () => void;
  primaryDisabled?: boolean;
  secondaryLabel?: string;
  onSecondary?: () => void;
  secondaryIcon?: React.ReactNode;
  secondaryDisabled?: boolean;
  danger?: boolean;
}) {
  return (
    <div className="dt-bottom-action">
      {secondaryLabel && onSecondary ? (
        <button className="dt-secondary-button" type="button" onClick={onSecondary} disabled={secondaryDisabled}>
          {secondaryIcon}
          {secondaryLabel}
        </button>
      ) : null}
      <button
        className={cn("dt-primary-button", danger && "dt-primary-button-danger")}
        type="button"
        onClick={onPrimary}
        disabled={primaryDisabled}
      >
        {primaryIcon}
        {primaryLabel}
      </button>
    </div>
  );
}

function Pill({ children, tone = "default" }: { children: React.ReactNode; tone?: "default" | "green" | "orange" | "blue" }) {
  return (
    <span className="dt-pill" data-tone={tone}>
      {children}
    </span>
  );
}

function SegmentedOption<T extends string>({
  value,
  options,
  onChange,
  columns,
}: {
  value: T;
  options: Array<{ value: T; label: string; icon?: React.ReactNode; description?: string }>;
  onChange: (value: T) => void;
  columns?: number;
}) {
  return (
    <div className="dt-segmented" style={{ gridTemplateColumns: `repeat(${columns ?? options.length}, minmax(0, 1fr))` }}>
      {options.map((option) => (
        <button
          className="dt-segmented-item"
          data-active={value === option.value}
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
        >
          {option.icon ? <span className="dt-segmented-icon">{option.icon}</span> : null}
          <span>{option.label}</span>
          {option.description ? <small>{option.description}</small> : null}
        </button>
      ))}
    </div>
  );
}

function ChipGroup({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <div className="dt-chip-grid">
      {options.map((item) => {
        const selected = value.includes(item);
        return (
          <button
            className="dt-choice-chip"
            data-selected={selected}
            key={item}
            type="button"
            onClick={() => onChange(selected ? value.filter((next) => next !== item) : [...value, item])}
          >
            {item}
            {selected ? <CheckCircle2 className="size-4" /> : null}
          </button>
        );
      })}
    </div>
  );
}

function PreferenceSelect({
  value,
  options,
  labelId,
  onChange,
}: {
  value: string;
  options: string[];
  labelId: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedIndex = Math.max(0, options.indexOf(value));

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function updateByStep(step: number) {
    const nextIndex = (selectedIndex + step + options.length) % options.length;
    onChange(options[nextIndex]);
    setOpen(true);
  }

  return (
    <div className="dt-select" data-open={open} ref={rootRef}>
      <button
        className="dt-select-trigger"
        type="button"
        aria-controls={`${selectId}-menu`}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby={`${labelId} ${selectId}-value`}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            updateByStep(1);
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            updateByStep(-1);
          }
        }}
      >
        <span id={`${selectId}-value`}>{value}</span>
        <ChevronDown className="dt-select-chevron size-4" />
      </button>
      {open ? (
        <div className="dt-select-menu" id={`${selectId}-menu`} role="listbox" aria-labelledby={labelId}>
          {options.map((item) => {
            const selected = item === value;
            return (
              <button
                className="dt-select-option"
                data-selected={selected}
                key={item}
                role="option"
                type="button"
                aria-selected={selected}
                onClick={() => {
                  onChange(item);
                  setOpen(false);
                }}
              >
                <span>{item}</span>
                {selected ? <CheckCircle2 className="size-4" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function Stepper({
  value,
  min,
  max,
  onChange,
  suffix,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  suffix: string;
}) {
  return (
    <div className="dt-stepper">
      <button type="button" onClick={() => onChange(Math.max(min, value - 1))} disabled={value <= min}>
        -
      </button>
      <strong>
        <span className="dt-stepper-num" key={value}>{value}</span> <span>{suffix}</span>
      </strong>
      <button type="button" onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max}>
        +
      </button>
    </div>
  );
}

function PlaceCard({
  place,
  checked,
  imageIndex,
  onToggle,
}: {
  place: PlaceOption;
  checked: boolean;
  imageIndex: number;
  onToggle: () => void;
}) {
  const image = place.type === "food" ? foodImageUrls[imageIndex % foodImageUrls.length] : dayImageUrls[imageIndex % dayImageUrls.length];
  return (
    <button className="dt-place-card" data-selected={checked} type="button" onClick={onToggle}>
      <img alt={place.name} src={image} />
      <span className="dt-place-check">{checked ? <Check className="size-4" /> : <Plus className="size-4" />}</span>
      <strong>{place.name}</strong>
      <small>
        {placeTypeLabel(place.type)} · {place.source === "blogger" ? "博主线索" : "周边推荐"}
      </small>
    </button>
  );
}

function KindIcon({ kind }: { kind: TimelinePoint["kind"] }) {
  if (kind === "food") return <Utensils className="size-4" />;
  if (kind === "transport") return <TrainFront className="size-4" />;
  if (kind === "hotel") return <BedDouble className="size-4" />;
  if (kind === "rest") return <Clock3 className="size-4" />;
  return <MapPin className="size-4" />;
}

function TimelineTime({ time }: { time: string }) {
  const [start, end] = time.split(/\s*[-—~至]\s*/).map((part) => part.trim()).filter(Boolean);

  if (!start || !end) {
    return (
      <div className="dt-timeline-time">
        <span>{time}</span>
      </div>
    );
  }

  return (
    <div className="dt-timeline-time" aria-label={time}>
      <span>{start}</span>
      <span>{end}</span>
    </div>
  );
}

function TimelinePointList({
  points,
  destination,
  imageMap,
  onNeedImage,
}: {
  points: TimelinePoint[];
  destination: string;
  imageMap: Record<string, string>;
  onNeedImage: (point: TimelinePoint, index: number) => void;
}) {
  const [openId, setOpenId] = useState("");

  useEffect(() => {
    points.slice(0, 6).forEach((point, index) => onNeedImage(point, index));
  }, [onNeedImage, points]);

  if (!points.length) {
    return <div className="dt-empty">当前这一天还没有拆出清晰时间线，完整 Markdown 方案仍可在下方查看。</div>;
  }

  return (
    <div className="dt-timeline">
      {points.map((point, index) => {
        const open = openId === point.id;
        const imageUrl = imageMap[point.id] || fallbackPointImage(point, index);
        return (
          <article className="dt-timeline-row" key={point.id}>
            <TimelineTime time={point.time} />
            <button
              aria-expanded={open}
              className={cn("dt-timeline-card", open && "dt-timeline-card-open")}
              type="button"
              onClick={() => setOpenId(open ? "" : point.id)}
            >
              <img alt={`${destination || "旅行"} ${point.title}`} src={imageUrl} />
              <div className="dt-timeline-main">
                <div className="dt-timeline-copy">
                  <span className="dt-kind-icon">
                    <KindIcon kind={point.kind} />
                  </span>
                  <div className="dt-timeline-text">
                    <h3>{point.title}</h3>
                    <p>{point.summary}</p>
                  </div>
                </div>
              </div>
              <ChevronDown className={cn("size-5 shrink-0 transition-transform", open && "rotate-180")} />
              {open ? <div className="dt-timeline-detail">{stripMarkdown(point.detail)}</div> : null}
            </button>
          </article>
        );
      })}
    </div>
  );
}

export default function Home() {
  const [step, setStep] = useState<Step>("entry");
  const [entryValue, setEntryValue] = useState("");
  const [videoAnalysis, setVideoAnalysis] = useState<VideoAnalysisResult | null>(null);
  const [selectedPlaceIds, setSelectedPlaceIds] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<TripPreferences>(() => createInitialPreferences());
  const [isParsing, setIsParsing] = useState(false);
  const [analysisStageIndex, setAnalysisStageIndex] = useState(0);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStatusMessage, setAnalysisStatusMessage] = useState("正在读取视频链接。");
  const [analysisEvents, setAnalysisEvents] = useState<PlanEvent[]>([]);
  const [transportSummary, setTransportSummary] = useState<TransportSummary | null>(null);
  const [isLoadingTransport, setIsLoadingTransport] = useState(false);
  const [geoStatus, setGeoStatus] = useState<GeoStatus>("idle");
  const [geoMessage, setGeoMessage] = useState("");
  const [rememberOriginCity, setRememberOriginCity] = useState(true);
  const [preferDriving, setPreferDriving] = useState(false);
  const [isPlanning, setIsPlanning] = useState(false);
  const [plan, setPlan] = useState("");
  const [planSummary, setPlanSummary] = useState("");
  const [streamedDays, setStreamedDays] = useState<DayPlan[]>([]);
  const [events, setEvents] = useState<PlanEvent[]>([]);
  const [refineText, setRefineText] = useState("");
  const [error, setError] = useState("");
  const [isReadingClipboard, setIsReadingClipboard] = useState(false);
  const [activeDayIndex, setActiveDayIndex] = useState(0);
  const [showAlternative, setShowAlternative] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [audioUrl, setAudioUrl] = useState("");
  const [pointImages, setPointImages] = useState<Record<string, string>>({});

  const entryInputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const latestPlanRef = useRef("");
  const locatingRef = useRef(false);
  const autoLocateAttemptedRef = useRef(false);
  const pointImagesRef = useRef<Record<string, string>>({});
  const imageLoadingRef = useRef<Set<string>>(new Set());

  const allAnalysisPlaces = useMemo(() => {
    const fromApi = videoAnalysis ? [...videoAnalysis.bloggerPlaces, ...videoAnalysis.nearbyPlaces] : [];
    return fromApi.length ? fromApi : fallbackPlacesFromAnalysis(videoAnalysis);
  }, [videoAnalysis]);

  const selectedRoutePlaces = useMemo(
    () => allAnalysisPlaces.filter((place) => selectedPlaceIds.includes(place.id)).map((place) => place.name),
    [allAnalysisPlaces, selectedPlaceIds],
  );

  const planForResult = plan.trim() ? plan : planSummary.trim();
  const hasGeneratedContent = Boolean(planForResult.trim() || streamedDays.some((day) => day?.content.trim()));
  const parsedDayPlans = useMemo(() => parseDailyPlans(planForResult, preferences.days), [planForResult, preferences.days]);
  const dayPlans = streamedDays.length > 0 ? streamedDays : planForResult ? parsedDayPlans : [];
  const safeActiveDayIndex = Math.min(activeDayIndex, Math.max(dayPlans.length - 1, 0));
  const activeDayContent = dayPlans[safeActiveDayIndex]?.content || planForResult;
  const activeDaySections = useMemo(() => splitAlternativeSection(activeDayContent), [activeDayContent]);
  const activeTimelinePoints = useMemo(() => parseTimelinePoints(activeDayContent), [activeDayContent]);
  const costEstimate = useMemo(() => estimatedTripCost(preferences), [preferences]);
  const latestStatus = [...events].reverse().find((item) => item.type === "status" || item.type === "tool");
  const visibleEvents = events.filter((event) => event.type === "status" || event.type === "tool" || event.type === "error");
  const isPlanningStopped = step === "planning" && !isPlanning;
  const autoReturnDate = useMemo(
    () => addDaysIso(preferences.departureDate || daysFromNowIso(1), Math.max(preferences.days - 1, 0)),
    [preferences.days, preferences.departureDate],
  );
  const canPlan = Boolean(preferences.origin.trim() && preferences.destination.trim() && preferences.days > 0 && preferences.travelers > 0);

  const requestPointImage = useCallback(
    (point: TimelinePoint, index: number) => {
      if (pointImagesRef.current[point.id] || imageLoadingRef.current.has(point.id)) return;
      imageLoadingRef.current.add(point.id);

      const finish = (imageUrl: string) => {
        const nextUrl = imageUrl || fallbackPointImage(point, index);
        pointImagesRef.current = { ...pointImagesRef.current, [point.id]: nextUrl };
        setPointImages(pointImagesRef.current);
        imageLoadingRef.current.delete(point.id);
      };

      const placeKeywords = placeKeywordsForPoint(point, preferences.destination, preferences.spots);
      const imageKeyword = imageKeywordForPoint(point);
      const placeKeywordQueue = placeKeywords.length ? placeKeywords : [point.title];

      const placeImage = async (keyword: string) => {
        const placeParams = new URLSearchParams({ destination: preferences.destination, keyword });
        const response = await fetch(`${API_BASE}/api/places/photo?${placeParams.toString()}`);
        if (!response.ok) throw new Error(`places/photo ${response.status}`);
        return (await response.json()) as { status: string; imageUrl?: string };
      };

      const searchImage = async () => {
        const searchParams = new URLSearchParams({ destination: preferences.destination, keyword: imageKeyword });
        const response = await fetch(`${API_BASE}/api/images/search?${searchParams.toString()}`);
        if (!response.ok) throw new Error(`images/search ${response.status}`);
        return (await response.json()) as { status: string; imageUrl?: string };
      };

      const load = async () => {
        for (const keyword of placeKeywordQueue) {
          try {
            const data = await placeImage(keyword);
            if (data.status === "success" && data.imageUrl) return finish(data.imageUrl);
          } catch {
            // Try the next local place keyword before falling back to image search.
          }
        }
        try {
          const data = await searchImage();
          finish(data.status === "success" && data.imageUrl ? data.imageUrl : "");
        } catch {
          finish("");
        }
      };

      void load();
    },
    [preferences.destination, preferences.spots],
  );

  useEffect(() => {
    const cachedCity = readOriginCityCache();
    if (cachedCity) {
      setPreferences((prev) => (prev.origin ? prev : { ...prev, origin: cachedCity }));
      setGeoStatus("success");
      setGeoMessage(`已使用常驻城市：${cachedCity}`);
    }
  }, []);

  useEffect(() => {
    pointImagesRef.current = pointImages;
  }, [pointImages]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  function updatePreference<K extends keyof TripPreferences>(key: K, value: TripPreferences[K]) {
    setPreferences((prev) => ({ ...prev, [key]: value }));
  }

  function updateOrigin(value: string) {
    setPreferences((prev) => ({ ...prev, origin: value }));
    if (rememberOriginCity && value.trim()) writeOriginCityCache(value);
  }

  function focusEntryInput() {
    entryInputRef.current?.focus({ preventScroll: true });
  }

  function updateEntryValue(value: string) {
    setEntryValue(value);
    if (value.trim()) setError("");
  }

  function applyEntryClipboardText(text: string) {
    const value = text.trim();
    if (!value) return false;

    updateEntryValue(value);
    window.requestAnimationFrame(() => {
      focusEntryInput();
      entryInputRef.current?.setSelectionRange(value.length, value.length);
    });
    return true;
  }

  async function pasteEntryFromClipboard() {
    if (isReadingClipboard) return;

    focusEntryInput();
    setError("");

    if (!window.isSecureContext || !navigator.clipboard?.readText) {
      return;
    }

    setIsReadingClipboard(true);
    try {
      const text = await navigator.clipboard.readText();
      if (!applyEntryClipboardText(text)) {
        setError("剪贴板里没有可粘贴的链接。");
      }
    } catch {
      focusEntryInput();
    } finally {
      setIsReadingClipboard(false);
    }
  }

  async function fetchGeoCity(path: string, params?: URLSearchParams) {
    const query = params?.toString();
    const response = await fetch(`${API_BASE}${path}${query ? `?${query}` : ""}`);
    if (!response.ok) throw new Error(`定位解析失败：${response.status}`);
    const data = (await response.json()) as GeoCityResponse;
    const city = (data.city || "").trim();
    if (data.status !== "success" || !city) throw new Error(data.message || "未识别到城市");
    return city;
  }

  function getBrowserGeoUnavailableReason() {
    if (typeof window === "undefined" || typeof navigator === "undefined") return "当前环境不支持浏览器定位";
    if (!window.isSecureContext) return "当前页面不是 localhost/HTTPS，浏览器禁止精确定位";
    if (!navigator.geolocation) return "当前浏览器不支持定位";
    return "";
  }

  function describeBrowserGeoError(exc: unknown) {
    const error = exc as { code?: number; message?: string };
    if (error?.code === 1) return "浏览器定位权限被拒绝";
    if (error?.code === 2) return "浏览器暂时无法获取当前位置";
    if (error?.code === 3) return "浏览器定位超时";
    if (exc instanceof Error && exc.message) return exc.message;
    if (error?.message) return error.message;
    return "浏览器定位失败";
  }

  async function detectOriginCity() {
    if (locatingRef.current) return;
    locatingRef.current = true;
    setGeoStatus("locating");
    setGeoMessage("正在获取当前位置。");

    let browserFailureReason = getBrowserGeoUnavailableReason();
    try {
      if (!browserFailureReason) {
        const position = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: false, timeout: 9000 });
        });
        const params = new URLSearchParams({
          latitude: String(position.coords.latitude),
          longitude: String(position.coords.longitude),
        });
        const city = await fetchGeoCity("/api/geo/reverse", params);
        updateOrigin(city);
        setGeoStatus("success");
        setGeoMessage(`已识别出发城市：${city}`);
        return;
      }
    } catch (exc) {
      browserFailureReason = describeBrowserGeoError(exc);
    }

    setGeoMessage(`${browserFailureReason}，正在尝试按网络位置识别城市。`);
    try {
      const city = await fetchGeoCity("/api/geo/ip");
      updateOrigin(city);
      setGeoStatus("success");
      setGeoMessage(`已按网络位置识别出发城市：${city}`);
    } catch (exc) {
      const ipFailureReason = exc instanceof Error && exc.message ? exc.message : "网络位置识别失败";
      setGeoStatus("failed");
      setGeoMessage(`${browserFailureReason}；${ipFailureReason}。请手动输入出发城市。`);
    } finally {
      locatingRef.current = false;
    }
  }

  useEffect(() => {
    if (step !== "transport" || preferences.origin.trim() || autoLocateAttemptedRef.current) return;
    autoLocateAttemptedRef.current = true;
    void detectOriginCity();
  }, [step, preferences.origin]);

  useEffect(() => {
    if (step !== "parsing" || !isParsing) return;

    const progressTimer = window.setInterval(() => {
      setAnalysisProgress((current) => {
        const nextProgress = Math.min(96, estimateNextAnalysisProgress(current));
        return Math.max(current, nextProgress);
      });
    }, 650);

    return () => window.clearInterval(progressTimer);
  }, [step, isParsing]);

  useEffect(() => {
    if (step !== "parsing" || !isParsing) return;
    const estimatedStageIndex = stageIndexFromAnalysisProgress(analysisProgress);
    setAnalysisStageIndex((current) => Math.max(current, estimatedStageIndex));
  }, [analysisProgress, step, isParsing]);

  function updateAnalysisProgress(event: PlanEvent) {
    const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
    const stage = typeof payload.stage === "string" ? payload.stage : "";
    const progress = typeof payload.progress === "number" ? Math.max(0, Math.min(100, payload.progress)) : null;
    const nextIndex = analysisStageIndexByName[stage];
    if (typeof nextIndex === "number") {
      setAnalysisStageIndex((current) => Math.max(current, nextIndex));
    }
    if (progress !== null) {
      setAnalysisProgress((current) => Math.max(current, progress));
    }
    if (stage && typeof nextIndex === "number" && analysisStages[nextIndex]) {
      setAnalysisStatusMessage(analysisStages[nextIndex].hint);
    } else if (event.message) {
      setAnalysisStatusMessage(event.message);
    }
  }

  function applyVideoAnalysisResult(data: VideoAnalysisResult, link: string) {
    const fallbackNames = data.spots.length ? data.spots : data.destination ? [data.destination] : [];
    const fallbackPlaces = fallbackPlacesFromAnalysis(data);
    const apiPlaces = [...data.bloggerPlaces, ...data.nearbyPlaces];
    const places = apiPlaces.length ? apiPlaces : fallbackPlaces;
    const defaultSelected = places.filter((place) => place.selected || place.source === "blogger").map((place) => place.id);
    const selectedNames = places.filter((place) => defaultSelected.includes(place.id)).map((place) => place.name);
    const routeNames = selectedNames.length ? selectedNames : fallbackNames;

    setVideoAnalysis(data);
    setSelectedPlaceIds(defaultSelected.length ? defaultSelected : places.slice(0, 4).map((place) => place.id));
    setPreferences((prev) => ({
      ...prev,
      link,
      videoId: data.videoId || prev.videoId,
      videoTitle: data.title || prev.videoTitle,
      videoSummary: data.summary || prev.videoSummary,
      videoTranscript: data.transcript || prev.videoTranscript,
      videoBudgetText: data.budgetText || prev.videoBudgetText,
      videoBudgetAmount: data.budgetAmount ?? prev.videoBudgetAmount,
      videoFoods: data.foods || [],
      destination: data.destination || prev.destination,
      spots: routeNames,
      routeReferencePlaces: routeNames,
      budgetStyle: inferBudgetStyleFromAmount(data.budgetAmount),
    }));
  }

  async function readAnalysisStream(response: Response): Promise<VideoAnalysisResult> {
    if (!response.body) throw new Error("浏览器未收到分析流。");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalData: VideoAnalysisResult | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const event = parseSseLine(line);
        if (!event) continue;
        setAnalysisEvents((prev) => [...prev.slice(-8), event]);
        if (event.type === "status") updateAnalysisProgress(event);
        if (event.type === "done" && event.payload && typeof event.payload === "object") {
          finalData = event.payload as VideoAnalysisResult;
          setAnalysisProgress(100);
          setAnalysisStageIndex(analysisStages.length - 1);
          setAnalysisStatusMessage("视频路线分析完成。");
        }
        if (event.type === "error") throw new Error(event.message || "视频解析失败");
      }
    }

    if (!finalData) throw new Error("分析完成但没有返回结果。");
    return finalData;
  }

  async function handleEntrySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = entryValue.trim();
    if (!value) {
      setError("请先粘贴抖音视频链接。");
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setError("");
    setIsParsing(true);
    setStep("parsing");
    setAnalysisStageIndex(0);
    setAnalysisProgress(0);
    setAnalysisStatusMessage("正在读取视频链接。");
    setAnalysisEvents([]);

    try {
      const response = await fetch(`${API_BASE}/api/douyin/analyze/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: value }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`视频解析请求失败：${response.status}`);
      const data = await readAnalysisStream(response);
      applyVideoAnalysisResult(data, value);
      setAnalysisProgress(100);
      await new Promise((resolve) => window.setTimeout(resolve, 450));
      if (controller.signal.aborted) return;
      setStep("confirm");
    } catch (exc) {
      if ((exc as Error).name === "AbortError") return;
      setError(exc instanceof Error ? exc.message : "视频解析失败，请稍后重试。");
      setStep("entry");
    } finally {
      setIsParsing(false);
      abortRef.current = null;
    }
  }

  async function loadTransportSummary(nextPreferences = preferences) {
    setIsLoadingTransport(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/trips/transport/summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: nextPreferences.origin,
          destination: nextPreferences.destination,
          firstSpot: nextPreferences.routeReferencePlaces[0] || nextPreferences.spots[0] || "",
          departureDate: nextPreferences.departureDate,
          transportMode: nextPreferences.transportMode,
          seatPreference: nextPreferences.trainSeatPreference,
        }),
      });
      if (!response.ok) throw new Error(`交通摘要请求失败：${response.status}`);
      const data = (await response.json()) as TransportSummary;
      setTransportSummary(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "交通摘要加载失败，仍可继续填写偏好。");
    } finally {
      setIsLoadingTransport(false);
    }
  }

  function confirmVideoAnalysis() {
    const routeNames = selectedRoutePlaces.length
      ? selectedRoutePlaces
      : preferences.destination
        ? [preferences.destination]
        : preferences.spots;
    const nextPreferences = {
      ...preferences,
      spots: routeNames,
      routeReferencePlaces: routeNames,
    };
    setPreferences(nextPreferences);
    setStep("transport");
    void loadTransportSummary(nextPreferences);
  }

  function setDrivingDefault(checked: boolean) {
    setPreferDriving(checked);
    const nextMode: TripPreferences["transportMode"] = checked ? "car" : "train";
    const nextPreferences = { ...preferences, transportMode: nextMode };
    setPreferences(nextPreferences);
    void loadTransportSummary(nextPreferences);
  }

  function commitPlan(nextPlan: string) {
    latestPlanRef.current = nextPlan;
    setPlan(nextPlan);
  }

  function appendPlanningStatus(message: string) {
    setEvents((prev) => {
      const last = prev[prev.length - 1];
      if (last?.type === "status" && last.message === message) return prev;
      return [...prev, { type: "status", message }];
    });
  }

  function stopPlanning() {
    if (!isPlanning) return;
    abortRef.current?.abort();
    setIsPlanning(false);
    appendPlanningStatus("已停止生成。");
  }

  async function readPlanStream(response: Response) {
    if (!response.body) throw new Error("浏览器未收到规划流。");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalPlan = "";
    let summaryText = "";
    const daySections: string[] = [];

    const publishPartialPlan = () => {
      const nextPlan = [summaryText, ...daySections.filter(Boolean)].filter(Boolean).join("\n\n");
      if (nextPlan) commitPlan(nextPlan);
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const event = parseSseLine(line);
        if (!event) continue;
        if (event.type === "status" || event.type === "tool" || event.type === "error") {
          setEvents((prev) => [...prev.slice(-18), event]);
        }
        if (event.type === "summary") {
          const message = typeof event.payload === "string" ? event.payload : event.message;
          summaryText = message || "";
          setPlanSummary(summaryText);
          publishPartialPlan();
        }
        if (event.type === "day") {
          const payload = dayPayload(event.payload);
          if (payload?.content) {
            const index = payload.index ?? daySections.length;
            const title = payload.title || payload.content.split("\n")[0]?.replace(/^###\s*/, "").trim() || `Day ${index + 1}`;
            daySections[index] = payload.content;
            setStreamedDays((prev) => {
              const next = [...prev];
              next[index] = { title, content: payload.content || "" };
              return next.filter(Boolean);
            });
            publishPartialPlan();
          }
        }
        if (event.type === "done") {
          const message = typeof event.payload === "string" ? event.payload : event.message;
          finalPlan = message || [summaryText, ...daySections.filter(Boolean)].filter(Boolean).join("\n\n");
          commitPlan(finalPlan);
        }
        if (event.type === "error") throw new Error(event.message || "规划失败");
      }
    }

    return finalPlan || [summaryText, ...daySections.filter(Boolean)].filter(Boolean).join("\n\n");
  }

  async function startPlan(endpoint: "/api/trips/plan/stream" | "/api/trips/refine/stream", payload: Record<string, unknown>) {
    abortRef.current?.abort();
    const controller = new AbortController();
    const shouldKeepExistingPlan = endpoint === "/api/trips/refine/stream";
    abortRef.current = controller;
    latestPlanRef.current = shouldKeepExistingPlan ? planForResult : "";
    setError("");
    setIsPlanning(true);
    setStep("planning");
    setEvents([]);
    setStreamedDays([]);
    setPlanSummary("");
    if (!shouldKeepExistingPlan) setPlan("");
    setPointImages({});
    pointImagesRef.current = {};
    imageLoadingRef.current.clear();
    setActiveDayIndex(0);
    setShowAlternative(false);

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`规划请求失败：${response.status}`);
      const finalPlan = await readPlanStream(response);
      if (!finalPlan.trim()) throw new Error("规划完成但没有返回内容。");
      setStep("result");
    } catch (exc) {
      if ((exc as Error).name === "AbortError") {
        appendPlanningStatus("已停止生成。");
        return;
      }
      setError(exc instanceof Error ? exc.message : "生成失败，请稍后重试。");
      setStep(latestPlanRef.current.trim() ? "result" : "review");
    } finally {
      setIsPlanning(false);
      abortRef.current = null;
    }
  }

  function startPlanning() {
    const preparedPreferences: TripPreferences = {
      ...preferences,
      returnDate: autoReturnDate,
      startDateRange: preferences.departureDate,
      routeReferencePlaces: preferences.routeReferencePlaces.length ? preferences.routeReferencePlaces : preferences.spots,
    };
    setPreferences(preparedPreferences);
    void startPlan("/api/trips/plan/stream", { preferences: preparedPreferences });
  }

  function handleRefine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const feedback = refineText.trim();
    if (!feedback || !planForResult || isPlanning) return;
    setRefineText("");
    void startPlan("/api/trips/refine/stream", {
      preferences,
      currentPlan: planForResult,
      feedback,
    });
  }

  async function speakCurrentDay() {
    const currentContent = dayPlans[safeActiveDayIndex]?.content || planForResult;
    const text = stripMarkdown(splitAlternativeSection(currentContent).main || currentContent).slice(0, 3800);
    if (!text || isSpeaking) return;
    stopSpeaking();
    setIsSpeaking(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          style: "用清晰、温和、像旅行向导一样的语气朗读，语速适中，重点信息稍作停顿。",
        }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `语音播报失败：${response.status}`);
      }
      const blob = await response.blob();
      const nextUrl = URL.createObjectURL(blob);
      setAudioUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return nextUrl;
      });
      setTimeout(() => {
        void audioRef.current?.play();
      }, 60);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "语音播报失败。");
    } finally {
      setIsSpeaking(false);
    }
  }

  function stopSpeaking() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
  }

  function resetFlow() {
    abortRef.current?.abort();
    stopSpeaking();
    setStep("entry");
    setEntryValue("");
    setVideoAnalysis(null);
    setSelectedPlaceIds([]);
    setPreferences(createInitialPreferences());
    setTransportSummary(null);
    setGeoStatus("idle");
    setGeoMessage("");
    setPlan("");
    setPlanSummary("");
    setStreamedDays([]);
    setEvents([]);
    setAnalysisEvents([]);
    setError("");
    setIsReadingClipboard(false);
    setRefineText("");
    setPointImages({});
    latestPlanRef.current = "";
    autoLocateAttemptedRef.current = false;
    pointImagesRef.current = {};
    imageLoadingRef.current.clear();
  }

  if (step === "entry") {
    return (
      <AppShell step={step}>
        <section className="dt-entry-hero">
          <div className="dt-hero-image" />
          <form className="dt-entry-card" onSubmit={handleEntrySubmit}>
            <h1>复刻抖音旅游攻略视频里的路线和玩法</h1>
            <p>粘贴抖音链接，自动提取地点、美食、预算与可复刻线路。</p>
            <label className="dt-link-input">
              <span className="dt-douyin-mark">♪</span>
              <input
                ref={entryInputRef}
                value={entryValue}
                onChange={(event) => updateEntryValue(event.target.value)}
                onPaste={(event) => {
                  const text = event.clipboardData.getData("text");
                  if (!text.trim()) return;
                  event.preventDefault();
                  applyEntryClipboardText(text);
                }}
                placeholder="粘贴抖音链接到这里"
                aria-label="抖音链接"
                inputMode="url"
              />
              <button
                aria-label="读取剪贴板"
                disabled={isReadingClipboard}
                type="button"
                onClick={pasteEntryFromClipboard}
              >
                {isReadingClipboard ? <Loader2 className="size-5 animate-spin" /> : <ClipboardPaste className="size-5" />}
              </button>
            </label>
            <button className="dt-inline-tip" type="button" onClick={pasteEntryFromClipboard} disabled={isReadingClipboard}>
              <Info className="size-4" />
              检测到剪贴板内容后，可直接点击粘贴
              <ChevronDown className="size-4 -rotate-90" />
            </button>
            {error ? <div className="dt-error">{error}</div> : null}
            <button className="dt-primary-button" disabled={isParsing || !entryValue.trim()} type="submit">
              {isParsing ? <Loader2 className="size-5 animate-spin" /> : <Sparkles className="size-5" />}
              分析视频路线
            </button>
            <div className="dt-entry-note">
              <Clock3 className="size-4" />
              视频越长，解析越久；解析时会保留真实接口调用。
            </div>
          </form>
        </section>
      </AppShell>
    );
  }

  if (step === "parsing") {
    const ringProgress = Math.max(0, Math.min(100, analysisProgress));
    const isAnalysisComplete = ringProgress >= 100;
    // 给 CSS 用：环的描边长度与领头光点角度都从 --progress 派生
    const ringStyle = { "--progress": ringProgress } as CSSProperties;
    const activeStage = analysisStages[analysisStageIndex];
    // 粗粒度的"剩余时间"提示：按 progress 分档，不引入实时计时
    const etaHint =
      ringProgress >= 88
        ? "即将完成"
        : ringProgress >= 55
          ? "约几十秒"
          : ringProgress >= 20
            ? "约一两分钟"
            : "正在准备…";
    return (
      <AppShell step={step}>
        <section className="dt-parsing">
            {/* 1. 顶部圆环：单色深蓝弧 + 虚线底环 + 领头光点；中心大号百分比 */}
            <div
              className="dt-parsing-ring"
              style={ringStyle}
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(ringProgress)}
              aria-label="视频解析进度"
            >
              <svg className="dt-parsing-ring-svg" viewBox="0 0 120 120" aria-hidden>
                <defs>
                  <linearGradient id="dt-parsing-ring-grad" x1="50%" y1="0%" x2="50%" y2="100%">
                    <stop offset="0%" stopColor="#1a5277" />
                    <stop offset="100%" stopColor="#0d3150" />
                  </linearGradient>
                </defs>
                <circle className="dt-parsing-ring-track" cx="60" cy="60" r="52" />
                <circle className="dt-parsing-ring-fill" cx="60" cy="60" r="52" />
              </svg>
              {/* 领头光点：随 --progress 沿环移动，营造"正在前进"的体感 */}
              <span className="dt-parsing-ring-lead" aria-hidden />
              <div className="dt-parsing-ring-center">
                <strong>
                  {Math.round(ringProgress)}
                  <em>%</em>
                </strong>
                <small>{isAnalysisComplete ? "分析完成" : activeStage?.label ? `${activeStage.label}中` : "分析中"}</small>
              </div>
            </div>

            {/* 剩余时间药丸 */}
            <div className="dt-parsing-eta">
              <Clock3 className="size-3.5" />
              <span>预计剩余：{etaHint}</span>
            </div>

            {/* 2. 阶段时间线卡片：单张 dt-card 内的 5 行，左侧用 timeline 连接 */}
            <div className="dt-card dt-parsing-timeline">
              {analysisStages.map((item, index) => {
                const state =
                  isAnalysisComplete || index < analysisStageIndex ? "done" : index === analysisStageIndex ? "active" : "todo";
                const visual = analysisStageVisuals[item.key];
                const StageIcon = visual.Icon;
                const isLast = index === analysisStages.length - 1;
                return (
                  <div
                    className="dt-parsing-timeline-row"
                    data-state={state}
                    data-tone={visual.tone}
                    data-last={isLast ? "1" : "0"}
                    key={item.key}
                  >
                    <span className="dt-parsing-timeline-dot" aria-hidden>
                      {state === "done" ? <Check className="size-3.5" /> : null}
                    </span>
                    <span className="dt-parsing-timeline-icon" aria-hidden>
                      <StageIcon className="size-[18px]" />
                    </span>
                    <div className="dt-parsing-timeline-meta">
                      <strong>{item.label}</strong>
                      {state === "active" ? <small>处理中</small> : null}
                    </div>
                    <em className="dt-parsing-timeline-status">
                      {state === "done" ? (
                        "已完成"
                      ) : state === "active" ? (
                        <span className="dt-parsing-timeline-loader" aria-hidden>
                          <i />
                          <i />
                          <i />
                        </span>
                      ) : (
                        "等待中"
                      )}
                    </em>
                  </div>
                );
              })}
            </div>

            {/* 3. 信息说明 */}
            <div className="dt-parsing-note">
              <Info className="size-4" />
              <span>解析完成后，将智能生成路线与入选项</span>
            </div>

            <BottomAction
              primaryLabel="取消解析"
              primaryIcon={<X className="size-5" />}
              onPrimary={() => {
                abortRef.current?.abort();
                setStep("entry");
                setIsParsing(false);
              }}
              danger
            />
        </section>
      </AppShell>
    );
  }

  if (step === "confirm") {
    const bloggerPlaces = allAnalysisPlaces.filter((place) => place.source === "blogger");
    const nearbyPlaces = allAnalysisPlaces.filter((place) => place.source === "nearby");
    return (
      <AppShell step={step}>
        <section className="dt-stack">
          <div className="dt-analysis-card">
            <img alt={preferences.destination || "旅行封面"} src="/images/fallback/hero.jpg" />
            <div>
              <h1>{preferences.videoTitle || videoAnalysis?.title || "视频路线分析结果"}</h1>
              <p>视频内容已整理为可确认的目的地、路线点和预算线索。</p>
            </div>
          </div>

          <div className="dt-card">
            <div className="dt-section-title">
              <div>
                <h2>博主路线点</h2>
                <p>选择你想复刻的主线地点。</p>
              </div>
              <button className="dt-link-button" type="button" onClick={() => setSelectedPlaceIds(bloggerPlaces.map((place) => place.id))}>
                全选
              </button>
            </div>
            <div className="dt-place-grid">
              {(bloggerPlaces.length ? bloggerPlaces : allAnalysisPlaces).slice(0, 8).map((place, index) => (
                <PlaceCard
                  checked={selectedPlaceIds.includes(place.id)}
                  imageIndex={index}
                  key={place.id}
                  place={place}
                  onToggle={() =>
                    setSelectedPlaceIds((prev) => (prev.includes(place.id) ? prev.filter((id) => id !== place.id) : [...prev, place.id]))
                  }
                />
              ))}
            </div>
          </div>

          {nearbyPlaces.length ? (
            <div className="dt-card">
              <div className="dt-section-title">
                <div>
                  <h2>周边推荐点</h2>
                  <p>可作为顺路备选，后续规划会控制路程。</p>
                </div>
                <button className="dt-link-button" type="button" onClick={() => setSelectedPlaceIds((prev) => uniqueValues([...prev, ...nearbyPlaces.map((place) => place.id)], 30))}>
                  加入
                </button>
              </div>
              <div className="dt-place-grid">
                {nearbyPlaces.slice(0, 6).map((place, index) => (
                  <PlaceCard
                    checked={selectedPlaceIds.includes(place.id)}
                    imageIndex={index + 3}
                    key={place.id}
                    place={place}
                    onToggle={() =>
                      setSelectedPlaceIds((prev) => (prev.includes(place.id) ? prev.filter((id) => id !== place.id) : [...prev, place.id]))
                    }
                  />
                ))}
              </div>
            </div>
          ) : null}

          {error ? <div className="dt-error">{error}</div> : null}
          <BottomAction
            secondaryLabel="重新输入"
            secondaryIcon={<ArrowLeft className="size-5" />}
            onSecondary={resetFlow}
            primaryLabel="确认地点，进入交通页"
            primaryIcon={<Sparkles className="size-5" />}
            primaryDisabled={!preferences.destination.trim()}
            onPrimary={confirmVideoAnalysis}
          />
        </section>
      </AppShell>
    );
  }

  if (step === "transport") {
    const transportOptions: Array<{ value: TripPreferences["transportMode"]; label: string; icon: React.ReactNode }> = [
      { value: "train", label: "高铁", icon: <TrainFront className="size-6" /> },
      { value: "car", label: "自驾", icon: <CarFront className="size-6" /> },
      { value: "any", label: "不限", icon: <Route className="size-6" /> },
    ];
    return (
      <AppShell step={step}>
        <section className="dt-stack">
          <div className="dt-title-block">
            <h1>
              {preferences.origin || "出发地"} <span>→</span> {preferences.destination || "目的地"}
            </h1>
            <p>确认出发城市和交通偏好，后续会继续使用真实交通摘要接口。</p>
          </div>

          <div className="dt-card">
            <label className="dt-field">
              <span>出发城市</span>
              <div className="dt-field-with-button">
                <input value={preferences.origin} onChange={(event) => updateOrigin(event.target.value)} placeholder="例如：武汉" />
                <button type="button" onClick={detectOriginCity} disabled={geoStatus === "locating"}>
                  {geoStatus === "locating" ? <Loader2 className="size-5 animate-spin" /> : <LocateFixed className="size-5" />}
                  定位
                </button>
              </div>
            </label>
            <div className="dt-toggle-list">
              <button
                className="dt-toggle-row"
                data-on={rememberOriginCity}
                type="button"
                onClick={() => {
                  const next = !rememberOriginCity;
                  setRememberOriginCity(next);
                  if (!next) clearOriginCityCache();
                  if (next && preferences.origin) writeOriginCityCache(preferences.origin);
                }}
              >
                <span>
                  <strong>设为常驻城市</strong>
                  <small>下次使用自动填充</small>
                </span>
                <i />
              </button>
              <button className="dt-toggle-row" data-on={preferDriving} type="button" onClick={() => setDrivingDefault(!preferDriving)}>
                <span>
                  <strong>默认自驾</strong>
                  <small>下次优先推荐自驾路线</small>
                </span>
                <i />
              </button>
            </div>
            {geoMessage ? <div className={cn("dt-quiet-note", geoStatus === "failed" && "dt-quiet-note-warn")}>{geoMessage}</div> : null}
          </div>

          <div className="dt-card">
            <div className="dt-section-title">
              <div>
                <h2>选择交通方式</h2>
                <p>会影响交通摘要和最终路线密度。</p>
              </div>
            </div>
            <SegmentedOption
              columns={3}
              value={preferences.transportMode}
              options={transportOptions}
              onChange={(value) => {
                const nextPreferences = { ...preferences, transportMode: value };
                setPreferences(nextPreferences);
                void loadTransportSummary(nextPreferences);
              }}
            />
            {preferences.transportMode === "train" || preferences.transportMode === "any" ? (
              <div className="mt-4">
                <div className="dt-mini-label">火车席别</div>
                <ChipGroup options={trainSeatOptions} value={[preferences.trainSeatPreference]} onChange={(value) => updatePreference("trainSeatPreference", value.at(-1) || "不限")} />
              </div>
            ) : null}
          </div>

          <div className="dt-card">
            <div className="dt-section-title">
              <div>
                <h2>交通信息概览</h2>
                <p>{isLoadingTransport ? "正在查询交通参考..." : transportSummary?.message || "填写出发城市后可刷新摘要。"}</p>
              </div>
              <button className="dt-icon-button" type="button" onClick={() => void loadTransportSummary()} disabled={isLoadingTransport}>
                {isLoadingTransport ? <Loader2 className="size-5 animate-spin" /> : <RefreshCcw className="size-5" />}
              </button>
            </div>
            <div className="dt-summary-list">
              {transportSummary?.items?.length ? (
                transportSummary.items.map((item) => (
                  <div className="dt-summary-row" key={`${item.label}-${item.value}`}>
                    <span className="dt-kind-icon">
                      <Navigation className="size-4" />
                    </span>
                    <div>
                      <strong>{item.label}</strong>
                      <p>{item.detail || "出发前仍需复核实时余票和路况。"}</p>
                    </div>
                    <em>{item.value}</em>
                  </div>
                ))
              ) : (
                <div className="dt-empty">暂无交通摘要。输入出发城市后点击刷新，或继续填写偏好。</div>
              )}
            </div>
          </div>

          {error ? <div className="dt-error">{error}</div> : null}
          <BottomAction
            secondaryLabel="返回分析"
            secondaryIcon={<ArrowLeft className="size-5" />}
            onSecondary={() => setStep("confirm")}
            primaryLabel="继续设置偏好"
            primaryIcon={<Sparkles className="size-5" />}
            primaryDisabled={!preferences.origin.trim() || !preferences.destination.trim()}
            onPrimary={() => setStep("preferences")}
          />
        </section>
      </AppShell>
    );
  }

  if (step === "preferences") {
    return (
      <AppShell step={step}>
        <section className="dt-stack">
          <div className="dt-card dt-preference-card">
            <div className="dt-section-title">
              <div>
                <h2 data-step="1/3">你想玩几天？</h2>
                <p>天数会影响路线密度、住宿晚数和预算估算。</p>
              </div>
            </div>
            <Stepper value={preferences.days} min={1} max={14} suffix="天" onChange={(value) => updatePreference("days", value)} />
            <div className="dt-shortcuts">
              {[2, 3, 5].map((day) => (
                <button className="dt-shortcut" data-selected={preferences.days === day} key={day} type="button" onClick={() => updatePreference("days", day)}>
                  {day}天
                </button>
              ))}
            </div>
            <div className="dt-form-grid">
              <label className="dt-field">
                <span>出发日期</span>
                <input type="date" value={preferences.departureDate} onChange={(event) => updatePreference("departureDate", event.target.value)} />
              </label>
              <label className="dt-field">
                <span>人数</span>
                <input type="number" min={1} max={20} value={preferences.travelers} onChange={(event) => updatePreference("travelers", Number(event.target.value) || 1)} />
              </label>
            </div>
          </div>

          <div className="dt-card dt-preference-card">
            <div className="dt-section-title">
              <div>
                <h2 data-step="2/3">这趟更偏哪种预算？</h2>
                <p>用于影响酒店、餐饮与交通取舍。</p>
              </div>
            </div>
            <SegmentedOption
              columns={3}
              value={preferences.budgetStyle}
              options={[
                { value: "budget", label: "穷游", icon: <WalletCards className="size-6" />, description: "人均 ¥600-1200" },
                { value: "comfort", label: "舒适", icon: <Hotel className="size-6" />, description: "人均 ¥1200-2500" },
                { value: "luxury", label: "富游", icon: <Sparkles className="size-6" />, description: "人均 ¥2500+" },
              ]}
              onChange={(value) => updatePreference("budgetStyle", value)}
            />
            <div className="dt-form-grid mt-4">
              <div className="dt-field">
                <span id="hotel-preference-label">住宿偏好</span>
                <PreferenceSelect
                  labelId="hotel-preference-label"
                  value={preferences.hotelPreference}
                  options={hotelOptions}
                  onChange={(value) => updatePreference("hotelPreference", value)}
                />
              </div>
              <label className="dt-field">
                <span>每晚酒店预算</span>
                <input
                  type="number"
                  min={0}
                  placeholder="不限"
                  value={preferences.hotelBudgetPerNight ?? ""}
                  onChange={(event) => updatePreference("hotelBudgetPerNight", event.target.value ? Number(event.target.value) : null)}
                />
              </label>
            </div>
          </div>

          <div className="dt-card dt-preference-card">
            <div className="dt-section-title">
              <div>
                <h2 data-step="3/3">这趟旅行你更喜欢什么？</h2>
                <p>可多选，推荐越贴心。</p>
              </div>
            </div>
            <div className="dt-mini-label">旅行兴趣</div>
            <ChipGroup options={interestOptions} value={preferences.travelInterests} onChange={(value) => updatePreference("travelInterests", value)} />
            <div className="dt-mini-label mt-5">景点类型</div>
            <ChipGroup options={spotTypeOptions} value={preferences.spotTypes} onChange={(value) => updatePreference("spotTypes", value)} />
            <label className="dt-field mt-5">
              <span>补充要求</span>
              <textarea
                value={preferences.notes}
                onChange={(event) => updatePreference("notes", event.target.value)}
                placeholder="例如：少走路、带老人、想拍日落、不想早起"
              />
            </label>
          </div>

          <BottomAction
            secondaryLabel="上一步"
            secondaryIcon={<ArrowLeft className="size-5" />}
            onSecondary={() => setStep("transport")}
            primaryLabel="下一步"
            primaryIcon={<Sparkles className="size-5" />}
            onPrimary={() => setStep("review")}
          />
        </section>
      </AppShell>
    );
  }

  if (step === "review") {
    return (
      <AppShell step={step}>
        <section className="dt-stack">
          <div className="dt-title-block dt-review-title">
            <h1>
              将为你生成
              <br />从 {preferences.origin || "出发地"} 到 {preferences.destination || "目的地"} 的 {preferences.days} 天方案
            </h1>
            <p>请确认以下信息，确保方案更贴合你的需求。</p>
          </div>
          <div className="dt-review-list">
            <button className="dt-review-item" type="button" onClick={() => setStep("preferences")}>
              <span className="dt-review-icon">
                <CalendarDays className="size-6" />
              </span>
              <div>
                <strong>基础信息 <em>必填</em></strong>
                <p>{preferences.origin || "出发地"} → {preferences.destination || "目的地"} ｜ {preferences.days} 天 {Math.max(preferences.days - 1, 0)} 晚 ｜ {preferences.travelers} 人</p>
              </div>
              <span>编辑</span>
            </button>
            <button className="dt-review-item" type="button" onClick={() => setStep("transport")}>
              <span className="dt-review-icon">
                <TrainFront className="size-6" />
              </span>
              <div>
                <strong>预算交通 <em>必填</em></strong>
                <p>{budgetLabel(preferences.budgetStyle)}预算 ｜ {transportLabel(preferences.transportMode)} ｜ {preferences.trainSeatPreference}</p>
              </div>
              <span>编辑</span>
            </button>
            <button className="dt-review-item" type="button" onClick={() => setStep("preferences")}>
              <span className="dt-review-icon">
                <BedDouble className="size-6" />
              </span>
              <div>
                <strong>住宿 <em>必填</em></strong>
                <p>{preferences.hotelPreference} ｜ {Math.max(preferences.days - 1, 0)} 晚 ｜ {preferences.hotelBudgetPerNight ? `${preferences.hotelBudgetPerNight} 元/晚` : "不限预算"}</p>
              </div>
              <span>编辑</span>
            </button>
            <button className="dt-review-item" type="button" onClick={() => setStep("confirm")}>
              <span className="dt-review-icon">
                <Camera className="size-6" />
              </span>
              <div>
                <strong>视频线索 <em>必填</em></strong>
                <p>{preferences.videoTitle || "抖音视频路线"} ｜ {preferences.routeReferencePlaces.slice(0, 3).join("、") || "已确认路线点"}</p>
              </div>
              <span>编辑</span>
            </button>
            <button className="dt-review-item" type="button" onClick={() => setStep("preferences")}>
              <span className="dt-review-icon">
                <Heart className="size-6" />
              </span>
              <div>
                <strong>偏好 <em>必填</em></strong>
                <p>{[...preferences.travelInterests, ...preferences.spotTypes].slice(0, 5).join(" ｜ ") || "轻松旅行"}</p>
              </div>
              <span>编辑</span>
            </button>
          </div>
          <div className="dt-quiet-note">
            <Info className="size-4" />
            信息仅用于生成方案，不会对外展示。
          </div>
          {error ? <div className="dt-error">{error}</div> : null}
          <BottomAction
            secondaryLabel="返回修改"
            secondaryIcon={<ArrowLeft className="size-5" />}
            onSecondary={() => setStep("preferences")}
            primaryLabel="确认并生成方案"
            primaryIcon={<Sparkles className="size-5" />}
            primaryDisabled={!canPlan || isPlanning}
            onPrimary={startPlanning}
          />
        </section>
      </AppShell>
    );
  }

  if (step === "planning") {
    const planningTasks = [
      { label: "地图路线", icon: <Map className="size-5" />, hint: "规划最优行程路线" },
      { label: "景点 POI", icon: <MapPin className="size-5" />, hint: "匹配热门景点与开放时间" },
      { label: "天气", icon: <Compass className="size-5" />, hint: "获取目的地天气预报" },
      { label: "12306 车次查询", icon: <TrainFront className="size-5" />, hint: "查询高铁 / 动车余票" },
      { label: "酒店", icon: <Hotel className="size-5" />, hint: "匹配合适的住宿" },
      { label: "预算估算", icon: <WalletCards className="size-5" />, hint: "估算总预算与明细" },
      { label: "路线优化", icon: <SlidersHorizontal className="size-5" />, hint: "优化行程顺序与时间" },
    ];
    const progressEvents = visibleEvents.filter((event) => event.message !== "已停止生成。");
    const doneCount = Math.min(progressEvents.length, planningTasks.length);
    const planningSubtitle = isPlanningStopped
      ? hasGeneratedContent
        ? "已停止生成，可查看当前已生成内容。"
        : "已停止生成，尚未收到可展示的方案内容。"
      : latestStatus?.message || "正在整合多源信息，生成最优旅行方案。";
    return (
      <AppShell step={step}>
        <section className="dt-stack">
          <div className="dt-stat-strip">
            <Pill tone="green"><MapPin className="size-3.5" />出发地 {preferences.origin || "-"}</Pill>
            <Pill tone="orange"><Navigation className="size-3.5" />目的地 {preferences.destination || "-"}</Pill>
            <Pill tone="blue"><CalendarDays className="size-3.5" />{preferences.days}天{Math.max(preferences.days - 1, 0)}夜</Pill>
            <Pill><Users className="size-3.5" />{preferences.travelers}人</Pill>
          </div>
          <div className="dt-card">
            <h1 className="dt-planning-title">{isPlanningStopped ? "Agent 已停止" : "Agent 生成中..."}</h1>
            <p className="dt-planning-subtitle">{planningSubtitle}</p>
            <div className="dt-generation-rail">
              {planningTasks.map((task, index) => {
                const state = index < doneCount ? "done" : isPlanning && index === doneCount ? "active" : "todo";
                const statusText = state === "done" ? "已完成" : state === "active" ? "进行中..." : isPlanningStopped && index === doneCount ? "已停止" : "等待中";
                return (
                  <div className="dt-generation-row" data-state={state} key={task.label}>
                    <span>{state === "done" ? <Check className="size-5" /> : task.icon}</span>
                    <div>
                      <strong>{task.label}</strong>
                      <small>{task.hint}</small>
                    </div>
                    <em>{statusText}</em>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="dt-card">
            <div className="dt-section-title">
              <div>
                <h2>逐日方案（预览）</h2>
                <p>完成一天就会先展示一天。</p>
              </div>
              <Pill tone="blue">{streamedDays.length}/{preferences.days}</Pill>
            </div>
            <div className="dt-day-preview-grid">
              {Array.from({ length: Math.max(preferences.days, 1) }, (_, index) => {
                const day = streamedDays[index];
                return (
                  <article className="dt-day-preview" data-ready={Boolean(day)} key={index}>
                    <span>Day {index + 1}</span>
                    <img alt={`Day ${index + 1}`} src={dayImageUrl(index)} />
                    <strong>{day?.title?.replace(/^Day\s*\d+\s*[—-]?/i, "") || (isPlanningStopped ? "未生成" : "生成中...")}</strong>
                    <p>{day ? "已完成" : isPlanningStopped ? "未生成" : index === streamedDays.length ? "生成中..." : "等待中"}</p>
                  </article>
                );
              })}
            </div>
          </div>

          <BottomAction
            secondaryLabel="查看已生成"
            secondaryIcon={<Sparkles className="size-5" />}
            secondaryDisabled={!hasGeneratedContent}
            onSecondary={() => {
              if (hasGeneratedContent) setStep("result");
            }}
            primaryLabel={isPlanning ? "停止生成" : "返回修改"}
            primaryIcon={isPlanning ? <Square className="size-5" /> : <ArrowLeft className="size-5" />}
            onPrimary={isPlanning ? stopPlanning : () => setStep("review")}
            danger={isPlanning}
          />
        </section>
      </AppShell>
    );
  }

  const currentDay = dayPlans[safeActiveDayIndex];
  const heroImage = activeTimelinePoints[0] ? pointImages[activeTimelinePoints[0].id] || fallbackPointImage(activeTimelinePoints[0], safeActiveDayIndex) : dayImageUrl(safeActiveDayIndex);

  return (
    <AppShell step="result">
      <section className="dt-stack dt-result-stack">
        <div className="dt-result-header">
          <div>
            <h1>{preferences.destination || "旅行"} {preferences.days} 天方案</h1>
            <p>{compactDate(preferences)} ｜ {preferences.travelers} 人 ｜ {budgetLabel(preferences.budgetStyle)}</p>
          </div>
          <button className="dt-small-outline" type="button" onClick={() => setStep("review")} disabled={isPlanning}>
            <SlidersHorizontal className="size-4" />
            改信息
          </button>
        </div>

        <div className="dt-day-tabs">
          {dayPlans.map((day, index) => (
            <button
              data-active={safeActiveDayIndex === index}
              key={`${day.title}-${index}`}
              type="button"
              onClick={() => {
                stopSpeaking();
                setActiveDayIndex(index);
                setShowAlternative(false);
              }}
            >
              Day {index + 1}
            </button>
          ))}
        </div>

        <div className="dt-day-hero">
          <img alt={currentDay?.title || "行程封面"} src={heroImage} />
          <div>
            <span>Day {safeActiveDayIndex + 1}</span>
            <strong>{currentDay?.title || "方案详情"}</strong>
            <p>{preferences.destination ? `${preferences.destination}慢游计划` : "湖光山色，人文初遇"}</p>
            <div className="dt-audio-actions">
              <button type="button" onClick={speakCurrentDay} disabled={!planForResult || isSpeaking}>
                {isSpeaking ? <Loader2 className="size-5 animate-spin" /> : <Volume2 className="size-5" />}
                朗读当前计划
              </button>
              <button type="button" onClick={stopSpeaking}>
                <Pause className="size-5" />
                停止朗读
              </button>
            </div>
          </div>
        </div>
        {audioUrl ? <audio ref={audioRef} className="w-full" controls src={audioUrl} /> : <audio ref={audioRef} className="hidden" />}

        {error ? <div className="dt-error">{error}</div> : null}

        <TimelinePointList
          points={activeTimelinePoints}
          destination={preferences.destination}
          imageMap={pointImages}
          onNeedImage={requestPointImage}
        />

        {activeDaySections.alternative ? (
          <div className="dt-card">
            <button className="dt-wide-toggle" type="button" onClick={() => setShowAlternative((value) => !value)}>
              {showAlternative ? "收起备选方案" : "显示备选方案"}
              <ChevronDown className={cn("size-5 transition-transform", showAlternative && "rotate-180")} />
            </button>
            {showAlternative ? (
              <div className="dt-markdown mt-3">
                <MarkdownContent content={activeDaySections.alternative} />
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="dt-card">
          <div className="dt-section-title">
            <div>
              <h2>完整方案</h2>
              <p>保留 Agent 返回的完整 Markdown 内容。</p>
            </div>
          </div>
          <div className="dt-markdown">
            <MarkdownContent content={activeDaySections.main || planForResult || "暂无方案内容。"} />
          </div>
        </div>

        <form className="dt-card dt-refine-card" onSubmit={handleRefine}>
          <h2>快速调整</h2>
          <div className="dt-refine-shortcuts">
            {["降低预算", "增加美食", "少走路", "亲子友好"].map((item) => (
              <button key={item} type="button" onClick={() => setRefineText(item)}>
                {item}
              </button>
            ))}
          </div>
          <label className="dt-refine-input">
            <input value={refineText} onChange={(event) => setRefineText(event.target.value)} placeholder="例如：想去博物馆，喜欢新式茶饮..." disabled={!planForResult || isPlanning} />
            <button disabled={!planForResult || !refineText.trim() || isPlanning} type="submit">
              {isPlanning ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
              发送
            </button>
          </label>
        </form>

        <div className="dt-result-summary">
          <div>
            <WalletCards className="size-5" />
            <span>预算总计</span>
            <strong>{costEstimate.total}</strong>
          </div>
          <div>
            <Users className="size-5" />
            <span>人均预算</span>
            <strong>{costEstimate.person}</strong>
          </div>
          <div>
            <CarFront className="size-5" />
            <span>交通方式</span>
            <strong>{transportLabel(preferences.transportMode)}</strong>
          </div>
          <div>
            <Hotel className="size-5" />
            <span>住宿区域</span>
            <strong>{preferences.hotelPreference}</strong>
          </div>
        </div>

        <button className="dt-reset-button" type="button" onClick={resetFlow} disabled={isPlanning}>
          <RefreshCcw className="size-5" />
          重新开始
        </button>
      </section>
    </AppShell>
  );
}
