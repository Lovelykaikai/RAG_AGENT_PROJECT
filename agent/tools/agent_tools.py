import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

from rag.rag_service import RagSummarizeService


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
    date_part = f"{date} " if date else ""
    return (
        f"暂时无法获取{city}{date_part}实时天气。建议按常规季节规划，并在出发前再次确认天气；"
        "若遇到降雨、高温、大风或台风预警，应优先安排室内景点、商圈、博物馆和餐饮体验。"
    )


@tool(description="从本地向量库中检索并总结旅游攻略参考资料，入参为用户问题或检索关键词")
def rag_summarize(query: str) -> str:
    """检索本地旅游知识库，并把相关资料总结成攻略参考。"""
    try:
        return _get_rag_service().rag_summarize(query)
    except Exception as exc:
        logger.error(f"[rag_summarize]检索本地知识库失败: {str(exc)}", exc_info=True)
        return (
            "暂时无法读取本地旅游知识库。请基于已有对话信息和常规旅游规划原则生成保守攻略，"
            "并提醒用户部分景点、天气、交通和开放信息需要出发前再次确认。"
        )


@tool(description="获取指定中国城市的天气信息。date必须使用YYYY-MM-DD格式，可为空；返回简洁中文字符串")
def get_weather(city: str, date: str | None = None) -> str:
    """获取目的地城市天气，用于判断行程是否需要避雨、防晒或调整室内外安排。"""
    try:
        normalized_date = _validate_date(date)
        city_info = _geocode(city)
        weather_data = _request_amap(
            "/v3/weather/weatherInfo",
            {
                "city": city_info["adcode"],  # 高德天气入参：城市adcode
                "extensions": "base",  # 高德天气入参：base为实况天气
            },
        )
        lives = weather_data.get("lives") or []  # 高德天气返回字段：实况天气列表
        if not lives:
            return _fallback_weather(city, normalized_date)

        live = lives[0]
        date_part = f"{normalized_date}计划出行，" if normalized_date else ""
        return (
            f"{date_part}{city}当前天气：{live.get('weather', '未知')}，"  # 高德字段：weather天气现象
            f"气温{live.get('temperature', '未知')}℃，"  # 高德字段：temperature实时气温
            f"{live.get('winddirection', '未知')}风{live.get('windpower', '未知')}级，"  # 高德字段：风向/风力
            f"湿度{live.get('humidity', '未知')}%。"  # 高德字段：humidity空气湿度
            "天气预报可能变化，建议出发前再次确认。"
        )
    except Exception:
        return _fallback_weather(city, date)


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
    except Exception:
        return f"暂时无法获取{city or ''}{keyword}的地图信息，建议根据RAG资料和用户偏好先做保守规划。"


@tool(description="查询城市内交通建议。用于生成旅游攻略中的市内交通、机场车站衔接和避坑提醒")
def get_city_transport(city: str) -> str:
    """总结目的地城市的市内交通方式、景区衔接和出行注意事项。"""
    query = f"{city} 市内交通 地铁 机场 火车站 景点 出行建议"
    try:
        summary = _get_rag_service().rag_summarize(query)
        if summary:
            return summary
    except Exception:
        pass

    return (
        f"{city}市内旅行建议优先使用地铁、公交、步行和必要时打车的混合方式。"
        "景点距离较远时优先选择耗时较短且换乘较少的路线；早晚高峰、节假日和热门景区周边应预留排队与拥堵时间。"
    )


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
    except Exception:
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

    route_results: list[tuple[str, int, str]] = []

    if mode in ("mixed", "transit"):
        try:
            transit_data = _request_amap(
                "/v3/direction/transit/integrated",
                {
                    "origin": origin_location,  # 高德公交路径入参：起点经纬度
                    "destination": destination_location,  # 高德公交路径入参：终点经纬度
                    "city": city or origin_geo.get("adcode"),  # 高德公交路径入参：起点城市
                    "cityd": city or destination_geo.get("adcode"),  # 高德公交路径入参：终点城市
                    "strategy": 0,  # 高德公交路径入参：推荐策略
                },
            )
            transits = (transit_data.get("route") or {}).get("transits") or []  # 高德公交路径返回字段：公交方案
            if transits:
                duration = int(float(transits[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
                route_results.append(("公共交通", duration, f"预计耗时{_format_duration(duration)}"))
        except Exception:
            pass

    if mode in ("mixed", "driving"):
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
            if paths:
                duration = int(float(paths[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
                distance = paths[0].get("distance", "未知")  # 高德路径字段：距离，单位米
                route_results.append(("打车/驾车", duration, f"预计耗时{_format_duration(duration)}，距离约{distance}米"))
        except Exception:
            pass

    if mode in ("mixed", "walking"):
        try:
            walking_data = _request_amap(
                "/v3/direction/walking",
                {
                    "origin": origin_location,  # 高德步行路径入参：起点经纬度
                    "destination": destination_location,  # 高德步行路径入参：终点经纬度
                },
            )
            paths = (walking_data.get("route") or {}).get("paths") or []  # 高德步行路径返回字段：路线列表
            if paths:
                duration = int(float(paths[0].get("duration", 0)))  # 高德路径字段：耗时，单位秒
                distance = paths[0].get("distance", "未知")  # 高德路径字段：距离，单位米
                route_results.append(("步行", duration, f"预计耗时{_format_duration(duration)}，距离约{distance}米"))
        except Exception:
            pass

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


TOOLS = [
    rag_summarize,
    get_weather,
    get_user_location,
    search_poi,
    get_city_transport,
    plan_route,
    fill_context_for_report,
]
