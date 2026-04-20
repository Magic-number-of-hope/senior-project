# -*- coding: utf-8 -*-
"""高德地图 API 工具函数"""
import json
import time
import urllib.parse
from typing import Optional

import aiohttp
from agentscope import logger
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from config.settings import AMAP_API_KEY

AMAP_BASE = "https://restapi.amap.com"
_AMAP_SESSION: Optional[aiohttp.ClientSession] = None


async def _get_amap_session() -> aiohttp.ClientSession:
    """复用 HTTP 会话，降低 TLS/连接建立开销。"""
    global _AMAP_SESSION
    if _AMAP_SESSION is None or _AMAP_SESSION.closed:
        timeout = aiohttp.ClientTimeout(total=10)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        _AMAP_SESSION = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        )
    return _AMAP_SESSION


async def close_amap_session() -> None:
    """关闭复用会话，供应用 shutdown 时调用。"""
    global _AMAP_SESSION
    if _AMAP_SESSION is not None and not _AMAP_SESSION.closed:
        await _AMAP_SESSION.close()
    _AMAP_SESSION = None


async def _amap_get(path: str, params: dict) -> dict:
    """发送高德API GET请求，带错误日志"""
    request_params = dict(params)
    request_params["key"] = AMAP_API_KEY

    # 在实际请求前打印请求参数（隐藏 key），便于终端排查。
    log_params = dict(request_params)
    if "key" in log_params:
        log_params["key"] = "***"
    logger.info(
        "[AMAP] REQUEST path=%s params=%s",
        path,
        json.dumps(log_params, ensure_ascii=False, sort_keys=True),
    )

    url = f"{AMAP_BASE}{path}?{urllib.parse.urlencode(request_params)}"
    logger.info("[AMAP] GET %s", url.replace(AMAP_API_KEY, "***"))
    t0 = time.perf_counter()
    session = await _get_amap_session()
    async with session.get(url) as resp:
        data = await resp.json(content_type=None)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("[AMAP] DONE path=%s elapsed=%.1fms", path, elapsed_ms)
    if data.get("status") == "0":
        logger.error("[AMAP] API错误: %s (infocode=%s) path=%s",
                     data.get("info", ""), data.get("infocode", ""), path)
    return data


def _text_response(text: str) -> ToolResponse:
    """将字符串包装为 ToolResponse"""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _is_ambiguous_poi_query(address: str, pois: list[dict]) -> bool:
    """判断地名是否歧义（例如同名校区/医院/商圈）。"""
    if len(pois) <= 1:
        return False

    addr = (address or "").strip()

    # 首个候选名称与查询完全匹配 → 认为用户意图明确，非歧义
    first_name = (pois[0].get("name") or "").strip()
    if first_name and first_name == addr:
        return False

    # 简短地名或常见多分支地点，优先要求用户二次确认
    hint_words = ("大学", "医院", "校区", "车站", "广场", "公园")
    short_or_generic = len(addr) <= 8 or any(w in addr for w in hint_words)

    if not short_or_generic:
        return False

    names = []
    for poi in pois[:3]:
        name = (poi.get("name") or "").strip()
        if name:
            names.append(name)

    # 前几个候选有不止一个不同名称，视为歧义
    return len(set(names)) > 1


# ────────────────── POI 搜索 ──────────────────

async def search_poi(keywords: str, city: str = "", types: str = "", page: int = 1) -> ToolResponse:
    """在高德地图搜索POI地点。

    Args:
        keywords: 搜索关键词，如"火锅店""加油站"
        city: 城市名称或编码，如"北京""武汉"
        types: POI类型编码，如"050000"(餐饮)
        page: 页码，默认1

    Returns:
        搜索结果，包含pois列表
    """
    params = {"keywords": keywords, "page": str(page), "page_size": "10"}
    if city:
        params["region"] = city
    if types:
        params["types"] = types

    data = await _amap_get("/v5/place/text", params)
    if data.get("status") == "1" and data.get("pois"):
        pois = []
        for p in data["pois"][:5]:
            pois.append({
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "location": p.get("location", ""),
                "tel": p.get("tel", ""),
                "type": p.get("type", ""),
                "distance": p.get("distance", ""),
                "cityname": p.get("cityname", ""),
            })
        return _text_response(json.dumps({"status": "ok", "count": len(pois), "pois": pois}, ensure_ascii=False))

    return _text_response(json.dumps({
        "status": "no_result",
        "count": 0,
        "pois": [],
        "api_info": data.get("info", ""),
    }, ensure_ascii=False))


# ────────────────── 周边搜索 ──────────────────

async def search_nearby_pois(longitude: str, latitude: str, keyword: str, radius: int = 3000) -> ToolResponse:
    """搜索给定坐标附近的POI地点。

    Args:
        longitude: 中心点经度，如"114.304569"
        latitude: 中心点纬度，如"30.593354"
        keyword: 目标POI关键字，如"麦当劳""咖啡"
        radius: 搜索半径(米)，默认3000

    Returns:
        周边搜索结果
    """
    params = {
        "keywords": keyword,
        "location": f"{longitude},{latitude}",
        "radius": str(radius),
    }
    data = await _amap_get("/v5/place/around", params)
    if data.get("status") == "1" and data.get("pois"):
        pois = []
        for p in data["pois"][:5]:
            pois.append({
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "location": p.get("location", ""),
                "distance": p.get("distance", ""),
                "tel": p.get("tel", ""),
                "type": p.get("type", ""),
            })
        return _text_response(json.dumps({"status": "ok", "count": len(pois), "pois": pois}, ensure_ascii=False))

    return _text_response(json.dumps({
        "status": "no_result",
        "count": 0,
        "pois": [],
        "api_info": data.get("info", ""),
    }, ensure_ascii=False))


# ────────────────── 地理编码 ──────────────────

async def geocode(address: str, city: str = "") -> ToolResponse:
    """将地址或地名转换为经纬度坐标。先尝试POI搜索(更灵活)，再用地理编码。

    Args:
        address: 地址文本或地名，如"武汉理工大学""北京市朝阳区望京SOHO"
        city: 城市名称

    Returns:
        地理编码结果
    """
    # 先用 POI 搜索（更灵活，支持模糊地名）。
    # 这里优先返回 need_selection，而不是强行选第一个，避免“同名地点误导航”。
    poi_params = {"keywords": address}
    if city:
        poi_params["region"] = city
    poi_data = await _amap_get("/v5/place/text", poi_params)
    if poi_data.get("status") == "1" and poi_data.get("pois"):
        pois = poi_data["pois"]
        if _is_ambiguous_poi_query(address, pois):
            candidates = []
            for p in pois[:5]:
                candidates.append({
                    "name": p.get("name", ""),
                    "address": p.get("address", ""),
                    "location": p.get("location", ""),
                    "cityname": p.get("cityname", ""),
                })
            return _text_response(json.dumps({
                "status": "need_selection",
                "message": f"地名 '{address}' 存在歧义，请选择具体地点",
                "candidates": candidates,
            }, ensure_ascii=False))

        poi = pois[0]
        return _text_response(json.dumps({
            "status": "ok",
            "location": poi.get("location", ""),
            "formatted_address": poi.get("name", "") + " " + poi.get("address", ""),
            "name": poi.get("name", ""),
            "cityname": poi.get("cityname", ""),
        }, ensure_ascii=False))

    # 如果 POI 完全查不到，再降级到 geocode v3（偏地址解析，不擅长模糊场景）。
    geo_params = {"address": address}
    if city:
        geo_params["city"] = city
    data = await _amap_get("/v3/geocode/geo", geo_params)
    if data.get("status") == "1" and data.get("geocodes"):
        geo = data["geocodes"][0]
        return _text_response(json.dumps({
            "status": "ok",
            "location": geo.get("location", ""),
            "formatted_address": geo.get("formatted_address", ""),
            "level": geo.get("level", ""),
        }, ensure_ascii=False))

    return _text_response(json.dumps({
        "status": "no_result",
        "api_info": data.get("info", ""),
    }, ensure_ascii=False))


# ────────────────── 逆地理编码 ──────────────────

async def reverse_geocode(location: str) -> ToolResponse:
    """将经纬度坐标转换为地址。

    Args:
        location: 经纬度，格式"lng,lat"，如"116.397428,39.90923"

    Returns:
        逆地理编码结果
    """
    params = {"location": location, "extensions": "base"}
    data = await _amap_get("/v3/geocode/regeo", params)
    if data.get("status") == "1":
        rc = data.get("regeocode", {})
        return _text_response(json.dumps({
            "status": "ok",
            "formatted_address": rc.get("formatted_address", ""),
            "address_component": {
                "province": rc.get("addressComponent", {}).get("province", ""),
                "city": rc.get("addressComponent", {}).get("city", ""),
                "district": rc.get("addressComponent", {}).get("district", ""),
            },
        }, ensure_ascii=False))

    return _text_response(json.dumps({
        "status": "no_result",
        "api_info": data.get("info", ""),
    }, ensure_ascii=False))


