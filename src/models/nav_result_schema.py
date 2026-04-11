# -*- coding: utf-8 -*-
"""导航结果数据模型（流程图版）。"""
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class Location(BaseModel):
    """地理坐标"""
    model_config = ConfigDict(extra="forbid")

    lng: float = Field(..., description="经度")
    lat: float = Field(..., description="纬度")
    name: Optional[str] = Field(None, description="名称")
    address: Optional[str] = Field(None, description="地址")


class Waypoint(BaseModel):
    """途经点"""
    model_config = ConfigDict(extra="forbid")

    name: str
    location: Location


class RouteStep(BaseModel):
    """路线步骤"""
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(..., description="导航指令")
    distance: Optional[str] = None
    duration: Optional[str] = None


class RouteInfo(BaseModel):
    """路线信息"""
    model_config = ConfigDict(extra="forbid")

    origin_name: Optional[str] = None
    destination_name: Optional[str] = None
    distance: Optional[str] = Field(None, description="总距离(米)")
    duration: Optional[str] = Field(None, description="总耗时(秒)")
    taxi_cost: Optional[str] = Field(None, description="打车费(元)")
    steps: List[RouteStep] = Field(default_factory=list)
    polyline: Optional[str] = Field(None, description="路线坐标串")


class POICandidate(BaseModel):
    """POI候选项"""
    model_config = ConfigDict(extra="forbid")

    name: str
    address: Optional[str] = None
    location: Optional[str] = None
    cityname: Optional[str] = None
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
    model_config = ConfigDict(extra="forbid")

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


class NeedSelectionResult(BaseModel):
    """前端接口要求的歧义候选结果。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["need_selection"]
    origin_candidates: List[POICandidate] = Field(default_factory=list)
    destination_candidates: List[POICandidate] = Field(default_factory=list)
    origin_name: Optional[str] = None
    origin_location: Optional[str] = None
    destination_name: Optional[str] = None
    destination_location: Optional[str] = None


class RouteResult(BaseModel):
    """前端接口要求的路线规划结果。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "success"]
    origin_name: str
    destination_name: str
    origin_location: str
    destination_location: str
    distance: Optional[str] = None
    duration: Optional[str] = None
    taxi_cost: Optional[str] = None
    steps: List[RouteStep] = Field(default_factory=list)
    polyline: Optional[str] = None


class ErrorResult(BaseModel):
    """前端接口要求的错误结果。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    message: str


StrictNavResult = Union[NeedSelectionResult, RouteResult, ErrorResult]
