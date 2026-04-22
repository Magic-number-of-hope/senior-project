# -*- coding: utf-8 -*-
"""用户画像数据模型。"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class FrequentPlace(BaseModel):
    label: str = Field(..., description="标签，如 家、公司")
    name: str = Field(..., description="地点名称")
    address: Optional[str] = None
    location: Optional[str] = Field(None, description="经纬度 lng,lat")


class UserProfile(BaseModel):
    user_id: str = Field(default="default")
    frequent_places: List[FrequentPlace] = Field(default_factory=list)
    preferred_travel_mode: Optional[str] = Field(None, description="偏好出行方式")
    food_preferences: List[str] = Field(default_factory=list, description="饮食偏好")
    food_dislikes: List[str] = Field(default_factory=list, description="忌口")
    route_preferences: List[str] = Field(default_factory=list, description="路线偏好")
    dialect_mappings: Dict[str, str] = Field(default_factory=dict, description="方言映射")
    custom_notes: List[str] = Field(default_factory=list, description="自定义备注")
