import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

from integrations.web_search import get_web_search_service
from rag.rag_service import RagSummarizeService
from utils.logger_handler import logger


load_dotenv()

AMAP_BASE_URL = "https://restapi.amap.com"
DEFAULT_ROUTE_MODE = "mixed"
_rag_service_lock = Lock()
_rag_service: RagSummarizeService | None = None


def _get_rag_service() -> RagSummarizeService:
    global _rag_service

    if _rag_service is not None:
        return _rag_service

    with _rag_service_lock:
        if _rag_service is None:
            _rag_service = RagSummarizeService()
        return _rag_service


_SEARCH_RESULT_PREFIX = "联网搜索结果："  # 与 WebSearchService._format_results 的开头保持一致
_RAG_INSUFFICIENT_MESSAGE = "参考资料不足，无法完整总结。"


def _hide_rag_insufficient_message(result: str) -> str:
    """Do not expose the RAG no-match fallback to the outer agent's answer."""
    if result.strip() == _RAG_INSUFFICIENT_MESSAGE:
        logger.info("[rag]本地知识库未命中，隐藏内部兜底提示")
        return ""
    return result


def _search_fallback(query: str, city: str | None = None) -> str:
    """本地知识库不可用时，用联网搜索结果作为参考资料，经模型总结后再返回，避免照搬原文。"""
    search_query = f"{city} {query}" if city else query
    try:
        raw_results = get_web_search_service().search(search_query)
    except Exception as exc:
        logger.warning(f"[rag_fallback]联网搜索兜底失败: {str(exc)}")
        return (
            f"暂时没有{city or ''}相关的参考资料，请基于已有对话信息和常规旅游规划原则生成保守建议，"
            "并提醒用户出发前再次确认细节。"
        )

    # 没有命中有效结果时，raw_results 本身就是一句可直接展示的说明文字，无需再总结
    if not raw_results.startswith(_SEARCH_RESULT_PREFIX):
        return raw_results

    try:
        return _get_rag_service().summarize_text(query, raw_results)
    except Exception as exc:
        logger.warning(f"[rag_fallback]总结联网搜索结果失败: {str(exc)}")
        return raw_results


def _get_amap_key() -> str | None:
    return os.getenv("AMAP_API_KEY") or os.getenv("GAODE_API_KEY")


def _validate_date(date_text: str | None) -> str | None:
    if not date_text:
        return None

    try:
        datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD format") from exc

    return date_text


def _request_amap(path: str, params: dict[str, Any]) -> dict[str, Any]:
    api_key = _get_amap_key()
    if not api_key:
        raise RuntimeError("missing AMAP_API_KEY or GAODE_API_KEY")

    query = {key: value for key, value in params.items() if value not in (None, "")}
    query["key"] = api_key
    url = f"{AMAP_BASE_URL}{path}?{urllib.parse.urlencode(query)}"

    with urllib.request.urlopen(url, timeout=10) as response:
        payload = response.read().decode("utf-8")

    data = json.loads(payload)
    if data.get("status") != "1":  # 高德通用返回字段：status=1表示成功
        message = data.get("info") or data.get("infocode") or "unknown error"  # 高德错误信息字段
        raise RuntimeError(f"amap api error: {message}")

    return data


def _geocode(address: str, city: str | None = None) -> dict[str, str]:
    data = _request_amap(
        "/v3/geocode/geo",
            {
            "address": address,  # 高德地理编码入参：结构化地址
            "city": city,  # 高德地理编码入参：指定查询城市
        },
    )
    geocodes = data.get("geocodes") or []  # 高德地理编码返回字段：匹配到的地址列表
    if not geocodes:
        raise RuntimeError(f"cannot geocode address: {address}")

    first = geocodes[0]
    return {
        "formatted_address": first.get("formatted_address", address),  # 高德字段：完整地址
        "province": first.get("province", ""),  # 高德字段：省份
        "city": first.get("city") or city or "",  # 高德字段：城市
        "district": first.get("district", ""),  # 高德字段：区县
        "adcode": first.get("adcode", ""),  # 高德字段：行政区编码
        "location": first.get("location", ""),  # 高德字段：经纬度，格式为lng,lat
    }


def _format_duration(seconds_text: str | int | None) -> str:
    if seconds_text in (None, ""):
        return "未知"

    seconds = int(float(seconds_text))
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes}分钟"

    hours = minutes // 60
    rest_minutes = minutes % 60
    if rest_minutes == 0:
        return f"{hours}小时"
    return f"{hours}小时{rest_minutes}分钟"


def _fallback_weather(city: str, date: str | None) -> str:
    date_part = f"{date}的" if date else ""
    return (
        f"暂时无法获取{city}{date_part}天气预报。建议按常规季节规划，并在出发前再次确认天气；"
        "若遇到降雨、高温、大风或台风预警，应优先安排室内景点、商圈、博物馆和餐饮体验。"
    )


_WEEKDAY_NAMES = {
    "1": "周一",
    "2": "周二",
    "3": "周三",
    "4": "周四",
    "5": "周五",
    "6": "周六",
    "7": "周日",
}

_RAIN_KEYWORDS = ("雨", "雪", "冰雹", "雷")


def _format_cast(cast: dict[str, Any]) -> str:
    """把高德单日预报格式化成一行中文描述。"""
    date_text = cast.get("date", "")  # 高德预报字段：预报日期YYYY-MM-DD
    weekday = _WEEKDAY_NAMES.get(str(cast.get("week", "")), "")  # 高德预报字段：星期1-7
    return (
        f"{date_text} {weekday} "
        f"白天{cast.get('dayweather', '未知')}{cast.get('daytemp', '未知')}℃ / "  # 高德预报字段：白天天气与温度
        f"夜间{cast.get('nightweather', '未知')}{cast.get('nighttemp', '未知')}℃，"  # 高德预报字段：夜间天气与温度
        f"{cast.get('daywind', '未知')}风{cast.get('daypower', '未知')}级"  # 高德预报字段：白天风向与风力
    ).strip()


def _format_cast_brief(cast: dict[str, Any]) -> str:
    """把高德单日预报压缩成一段短描述，用于罗列其余可选日期。"""
    date_text = str(cast.get("date", ""))[5:] or str(cast.get("date", ""))
    return f"{date_text} {cast.get('dayweather', '未知')}{cast.get('daytemp', '未知')}℃"


def _weather_advice(cast: dict[str, Any]) -> str:
    """根据单日预报给出室内外安排建议，避免模型自行编造结论。"""
    day_weather = str(cast.get("dayweather", ""))
    night_weather = str(cast.get("nightweather", ""))
    weather_text = f"{day_weather}{night_weather}"

    if any(keyword in weather_text for keyword in _RAIN_KEYWORDS):
        return "该日有降水，建议优先安排博物馆、商圈等室内项目，并准备雨具。"

    try:
        day_temp = int(float(cast.get("daytemp", "")))
    except (TypeError, ValueError):
        return "该日无明显降水，可正常安排室外行程。"

    if day_temp >= 33:
        return "该日白天高温，建议避开正午户外活动，做好防晒补水。"
    if day_temp <= 5:
        return "该日气温偏低，建议做好保暖并缩短户外停留时间。"
    return "该日无明显降水，气温适宜，适合安排室外行程。"


def _fetch_forecast(city: str) -> tuple[list[dict[str, Any]], str]:
    """请求高德预报天气，返回未来数日预报列表和数据发布时间。"""
    city_info = _geocode(city)
    weather_data = _request_amap(
        "/v3/weather/weatherInfo",
        {
            "city": city_info["adcode"],  # 高德天气入参：城市adcode
            "extensions": "all",  # 高德天气入参：all为预报天气（今天+未来3天）
        },
    )
    forecasts = weather_data.get("forecasts") or []  # 高德天气返回字段：预报天气列表
    if not forecasts:
        return [], ""

    first = forecasts[0]
    casts = first.get("casts") or []  # 高德预报字段：逐日预报数组
    return casts, first.get("reporttime", "")  # 高德预报字段：数据发布时间


@tool(
    description=(
        "从本地向量库中检索并总结旅游攻略参考资料。"
        "query为用户问题或检索关键词；"
        "city为该问题针对的单个城市名（如'成都'），只查一个城市时必须填写，"
        "可显著提高资料准确度；跨城市比较或问题不限定城市时留空"
    )
)
def rag_summarize(query: str, city: str | None = None) -> str:
    """检索本地旅游知识库，并把相关资料总结成攻略参考。"""
    try:
        result = _get_rag_service().rag_summarize(query, city)
    except Exception as exc:
        logger.error(f"[rag_summarize]检索本地知识库失败: {str(exc)}", exc_info=True)
        result = _search_fallback(query, city)
    return _hide_rag_insufficient_message(result)


@tool(
    description=(
        "获取指定中国城市的天气预报，覆盖今天及未来3天。"
        "date可为空，为空时返回全部可查日期，便于挑选适合出行的时段；"
        "date必须使用YYYY-MM-DD格式，超出预报范围时会明确说明无法提供该日天气"
    )
)
def get_weather(city: str, date: str | None = None) -> str:
    """获取目的地城市天气预报，用于判断行程是否需要避雨、防晒或调整室内外安排。"""
    try:
        normalized_date = _validate_date(date)
    except ValueError:
        return f"日期格式不正确：{date}。请使用YYYY-MM-DD格式，例如2026-08-10。"

    try:
        casts, report_time = _fetch_forecast(city)
    except Exception as exc:
        logger.warning(f"[get_weather]获取{city}天气预报失败: {str(exc)}")
        return _fallback_weather(city, normalized_date)

    if not casts:
        logger.warning(f"[get_weather]高德未返回{city}的预报数据")
        return _fallback_weather(city, normalized_date)

    available_dates = [str(cast.get("date", "")) for cast in casts]
    report_part = f"（数据发布于{report_time}）" if report_time else ""
    tail = "预报每天更新3次，出发前请再次确认。"

    # 未指定日期：返回全部可查日期，供模型挑选天气较好的时段。
    if normalized_date is None:
        lines = [f"{city}未来天气预报{report_part}："]
        lines.extend(f"  {_format_cast(cast)}" for cast in casts)
        lines.append(f"  {tail}")
        return "\n".join(lines)

    matched = next(
        (cast for cast in casts if str(cast.get("date", "")) == normalized_date),
        None,
    )

    # 指定日期超出预报范围：明确说明无法提供，避免模型编造确定性结论。
    if matched is None:
        range_text = f"{available_dates[0]}至{available_dates[-1]}" if available_dates else "暂无"
        lines = [
            f"{normalized_date}超出高德预报范围（仅覆盖{range_text}），"
            "无法提供该日实际天气，请勿据此给出确定性结论，并提醒用户临近出发时再查询。",
            f"可参考的近期天气趋势{report_part}：",
        ]
        lines.extend(f"  {_format_cast(cast)}" for cast in casts)
        return "\n".join(lines)

    others = [cast for cast in casts if cast is not matched]
    lines = [
        f"【{_format_cast(matched)}】{report_part}",
        f"  {_weather_advice(matched)}",
    ]
    if others:
        lines.append("  其余可查日期：" + " / ".join(_format_cast_brief(cast) for cast in others))
    lines.append(f"  {tail}")
    return "\n".join(lines)


@tool(description="获取用户起始位置。优先使用用户输入位置；其次使用浏览器传入的经纬度；都没有则返回目的地核心区域兜底")
def get_user_location(
    destination_city: str,
    user_location: str | None = None,
    browser_lat: float | None = None,
    browser_lng: float | None = None,
) -> str:
    """确定路线规划起点，优先使用用户输入，其次使用浏览器定位，最后使用默认起点。"""
    if user_location:
        return f"用户起始位置：{user_location}"

    if browser_lat is not None and browser_lng is not None:
        return (
            f"用户浏览器定位坐标：{browser_lat},{browser_lng}。"
            "该坐标来自前端浏览器定位，后续可通过地图逆地理编码转换为具体地址。"
        )

    return f"用户未提供起始位置，默认以{destination_city}核心商圈或主要交通枢纽作为行程起点。"


@tool(description="查询城市内地点或景点信息。keyword为地点名称，city为城市名；优先调用高德POI搜索")
def search_poi(keyword: str, city: str | None = None) -> str:
    """查询景点、商圈、车站等地点信息，辅助确认位置和候选目的地。"""
    try:
        data = _request_amap(
            "/v3/place/text",
            {
                "keywords": keyword,  # 高德POI入参：搜索关键词
                "city": city,  # 高德POI入参：限定城市
                "offset": 5,  # 高德POI入参：每页返回数量
                "page": 1,  # 高德POI入参：页码
                "extensions": "base",  # 高德POI入参：base返回基础信息
            },
        )
        pois = data.get("pois") or []  # 高德POI返回字段：地点列表
        if not pois:
            return f"没有查询到{city or ''}{keyword}的明确地图信息，建议换一个更具体的地点名称。"

        lines = []
        for poi in pois[:5]:
            address = poi.get("address") or "地址未知"  # 高德POI字段：地址
            name = poi.get("name") or keyword  # 高德POI字段：地点名称
            district = poi.get("adname") or ""  # 高德POI字段：所属区县
            location = poi.get("location") or "坐标未知"  # 高德POI字段：经纬度
            lines.append(f"- {name}：{district}，{address}，坐标 {location}")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning(f"[search_poi]查询{city or ''}{keyword}的POI失败: {str(exc)}")
        return f"暂时无法获取{city or ''}{keyword}的地图信息，建议根据RAG资料和用户偏好先做保守规划。"


@tool(description="联网搜索最新旅游信息，如景点开放时间、临时活动、近期天气和出行提醒；返回标题、链接和摘要")
def search_web(query: str) -> str:
    """搜索公开网页，补充本地知识库和地图接口无法覆盖的时效性信息。"""
    try:
        return get_web_search_service().search(query)
    except Exception as exc:
        logger.warning(f"[search_web]联网搜索“{query}”失败: {str(exc)}")
        return "当前联网搜索暂时不可用，请基于已有资料和常规旅游规划原则提供保守建议。"


@tool(description="查询城市内交通建议。用于生成旅游攻略中的市内交通、机场车站衔接和避坑提醒")
def get_city_transport(city: str) -> str:
    """总结目的地城市的市内交通方式、景区衔接和出行注意事项。"""
    query = f"{city} 市内交通 地铁 机场 火车站 景点 出行建议"
    try:
        summary = _get_rag_service().rag_summarize(query, city)
        if summary.strip() == _RAG_INSUFFICIENT_MESSAGE:
            return _hide_rag_insufficient_message(summary)
        if summary:
            return summary
        logger.warning(f"[get_city_transport]本地知识库未返回{city}的交通资料")
    except Exception as exc:
        logger.warning(f"[get_city_transport]检索{city}交通资料失败: {str(exc)}")

    return _hide_rag_insufficient_message(_search_fallback(query))


def _query_transit(
    origin_location: str,
    destination_location: str,
    city: str | None,
    origin_adcode: str,
    destination_adcode: str,
) -> tuple[str, int, str] | None:
    try:
        transit_data = _request_amap(
            "/v3/direction/transit/integrated",
            {
                "origin": origin_location,  # 高德公交路径入参：起点经纬度
                "destination": destination_location,  # 高德公交路径入参：终点经纬度
                "city": city or origin_adcode,  # 高德公交路径入参：起点城市
                "cityd": city or destination_adcode,  # 高德公交路径入参：终点城市
                "strategy": 0,  # 高德公交路径入参：推荐策略
            },
        )
        transits = (transit_data.get("route") or {}).get("transits") or []  # 高德公交路径返回字段：公交方案
        if not transits:
            return None
        duration = int(float(transits[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
        return "公共交通", duration, f"预计耗时{_format_duration(duration)}"
    except Exception:
        return None


def _query_driving(origin_location: str, destination_location: str) -> tuple[str, int, str] | None:
    try:
        driving_data = _request_amap(
            "/v3/direction/driving",
            {
                "origin": origin_location,  # 高德驾车路径入参：起点经纬度
                "destination": destination_location,  # 高德驾车路径入参：终点经纬度
                "strategy": 10,  # 高德驾车路径入参：返回速度优先方案
            },
        )
        paths = (driving_data.get("route") or {}).get("paths") or []  # 高德驾车路径返回字段：路线列表
        if not paths:
            return None
        duration = int(float(paths[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
        distance = paths[0].get("distance", "未知")  # 高德路径字段：距离，单位米
        return "打车/驾车", duration, f"预计耗时{_format_duration(duration)}，距离约{distance}米"
    except Exception:
        return None


def _query_walking(origin_location: str, destination_location: str) -> tuple[str, int, str] | None:
    try:
        walking_data = _request_amap(
            "/v3/direction/walking",
            {
                "origin": origin_location,  # 高德步行路径入参：起点经纬度
                "destination": destination_location,  # 高德步行路径入参：终点经纬度
            },
        )
        paths = (walking_data.get("route") or {}).get("paths") or []  # 高德步行路径返回字段：路线列表
        if not paths:
            return None
        duration = int(float(paths[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
        distance = paths[0].get("distance", "未知")  # 高德路径字段：距离，单位米
        return "步行", duration, f"预计耗时{_format_duration(duration)}，距离约{distance}米"
    except Exception:
        return None


@tool(description="规划两个地点之间的路线。城市内默认按耗时最短思路；跨城市优先建议铁路/高铁")
def plan_route(
    origin: str,
    destination: str,
    city: str | None = None,
    mode: str = DEFAULT_ROUTE_MODE,
) -> str:
    """规划起点到终点的交通路线，城市内优先耗时最短，跨城市优先铁路。"""
    try:
        origin_geo = _geocode(origin, city)
        destination_geo = _geocode(destination, city)
    except Exception as exc:
        logger.warning(f"[plan_route]解析地点失败 {origin} -> {destination}: {str(exc)}")
        return (
            f"暂时无法解析起点或终点：{origin} -> {destination}。"
            "建议用户补充更具体的地址、景点名称或城市名称。"
        )

    origin_city = origin_geo.get("city") or city or ""
    destination_city = destination_geo.get("city") or city or ""
    if origin_city and destination_city and origin_city != destination_city:
        return (
            f"从{origin_geo['formatted_address']}到{destination_geo['formatted_address']}属于跨城市出行，"
            "优先考虑铁路/高铁；若无合适铁路班次，再考虑飞机、长途汽车或包车。"
            "具体班次和票价建议接入铁路查询API或出发前在官方购票平台确认。"
        )

    origin_location = origin_geo["location"]
    destination_location = destination_geo["location"]

    tasks: list = []
    if mode in ("mixed", "transit"):
        tasks.append(
            lambda: _query_transit(
                origin_location,
                destination_location,
                city,
                origin_geo.get("adcode", ""),
                destination_geo.get("adcode", ""),
            )
        )
    if mode in ("mixed", "driving"):
        tasks.append(lambda: _query_driving(origin_location, destination_location))
    if mode in ("mixed", "walking"):
        tasks.append(lambda: _query_walking(origin_location, destination_location))

    with ThreadPoolExecutor(max_workers=max(len(tasks), 1)) as executor:
        results = [future.result() for future in [executor.submit(task) for task in tasks]]
    route_results: list[tuple[str, int, str]] = [result for result in results if result]

    if not route_results:
        return (
            f"暂时无法获取{origin}到{destination}的实时路线。"
            "建议按耗时最短原则，优先选择地铁/公交和必要时打车的组合，并预留拥堵时间。"
        )

    route_results.sort(key=lambda item: item[1])
    best_mode, _, best_desc = route_results[0]
    alternatives = "；".join(f"{name}：{desc}" for name, _, desc in route_results[1:])
    alt_text = f"。备选方案：{alternatives}" if alternatives else ""

    return (
        f"从{origin_geo['formatted_address']}到{destination_geo['formatted_address']}，"
        f"按耗时最短优先推荐{best_mode}，{best_desc}{alt_text}。"
        "实际耗时会受天气、拥堵和排队影响。"
    )


@tool(description="无需入参，只在用户明确需要生成旅游攻略报告时调用，用于通知中间件切换到报告生成提示词")
def fill_context_for_report() -> str:
    """标记当前对话进入报告生成场景，后续模型调用会切换为报告提示词。"""
    return "fill_context_for_report已调用"


def warmup_services() -> None:
    """启动时预热RAG和联网搜索单例，避免首个用户请求承担初始化延迟。

    预热失败不阻断启动：两个工具内部都有降级分支，运行时会再尝试初始化。
    """
    try:
        _get_rag_service()
        logger.info("[warmup]RAG服务预热完成")
    except Exception as exc:
        logger.warning(f"[warmup]RAG服务预热失败，将在首次调用时重试: {str(exc)}")

    try:
        get_web_search_service()
        logger.info("[warmup]联网搜索服务预热完成")
    except Exception as exc:
        logger.warning(f"[warmup]联网搜索服务预热失败，将在首次调用时重试: {str(exc)}")


TOOLS = [
    rag_summarize,
    get_weather,
    get_user_location,
    search_poi,
    search_web,
    get_city_transport,
    plan_route,
    fill_context_for_report,
]
