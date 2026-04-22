# -*- coding: utf-8 -*-
"""意图识别和槽位提取的数据模型。"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IntentType(str, Enum):
    BASIC_NAVIGATION = "basic_navigation"
    LIFE_SERVICE = "life_service"
    MULTI_DESTINATION = "multi_destination"
    COMPOUND_CONSTRAINT = "compound_constraint"


class TravelMode(str, Enum):
    DRIVING = "driving"
    WALKING = "walking"
    TRANSIT = "transit"
    BICYCLING = "bicycling"


class NavigationSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Optional[str] = Field(None, description="出发地")
    destination: Optional[str] = Field(None, description="目的地")
    waypoints: List[str] = Field(default_factory=list, description="途经点列表")
    travel_mode: Optional[TravelMode] = Field(None, description="出行方式")
    time_constraint: Optional[str] = Field(None, description="时间约束")
    preference: Optional[str] = Field(None, description="偏好条件")
    poi_type: Optional[str] = Field(None, description="POI类型")
    poi_constraint: Optional[str] = Field(None, description="POI约束条件")
    sequence: List[str] = Field(default_factory=list, description="多目的地顺序")


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_navigation: bool = Field(..., description="是否为导航请求")
    intent_type: Optional[IntentType] = Field(None, description="导航意图类型")
    slots: NavigationSlots = Field(default_factory=NavigationSlots, description="导航槽位信息")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="置信度")
    needs_clarification: bool = Field(False, description="是否需要追问")
    clarification_question: Optional[str] = Field(None, description="追问问题")
    raw_text: Optional[str] = Field(None, description="原始用户输入")
    navigation_result: Optional[dict] = Field(None, description="导航校验智能体返回结果")
