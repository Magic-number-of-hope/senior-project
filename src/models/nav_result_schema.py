# -*- coding: utf-8 -*-
"""导航结果数据模型（流程图版）"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Location(BaseModel):
    """地理坐标"""
    lng: float = Field(..., description="经度")
    lat: float = Field(..., description="纬度")
    name: Optional[str] = Field(None, description="名称")
    address: Optional[str] = Field(None, description="地址")


class Waypoint(BaseModel):
    """途经点"""
    name: str
    location: Location


class RouteStep(BaseModel):
    """路线步骤"""
    instruction: str = Field(..., description="导航指令")
    distance: Optional[str] = None
    duration: Optional[str] = None


class RouteInfo(BaseModel):
    """路线信息"""
    origin_name: Optional[str] = None
    destination_name: Optional[str] = None
    distance: Optional[str] = Field(None, description="总距离(米)")
    duration: Optional[str] = Field(None, description="总耗时(秒)")
    taxi_cost: Optional[str] = Field(None, description="打车费(元)")
    steps: List[RouteStep] = Field(default_factory=list)
    polyline: Optional[str] = Field(None, description="路线坐标串")


class POICandidate(BaseModel):
    """POI候选项"""
    name: str
    address: Optional[str] = None
    location: Optional[Location] = None
    tel: Optional[str] = None
    type_name: Optional[str] = None
    distance: Optional[str] = None


class NavigationResult(BaseModel):
    """导航完整结果。

    status:
      - ok/success: 已完成校验+规划
      - need_selection: 需要前端让用户选择 POI
      - error: 处理失败
    """
    status: str = Field("success", description="ok|success|need_selection|error")
    intent_result: Optional[Dict[str, Any]] = Field(
        None,
        description="上游意图识别结果(intent+slots)",
    )
    route: Optional[RouteInfo] = Field(None, description="路线规划结果")
    poi_candidates: List[POICandidate] = Field(
        default_factory=list,
        description="POI 候选列表",
    )
    message: Optional[str] = Field(None, description="状态描述信息")
    corrected_slots: Optional[Dict[str, Any]] = Field(
        None,
        description="导航校验后的槽位纠错结果",
    )
