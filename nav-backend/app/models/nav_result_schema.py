# -*- coding: utf-8 -*-
"""导航结果数据模型。"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class RouteStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(..., description="导航指令")
    distance: Optional[str] = None
    duration: Optional[str] = None


class POICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    address: Optional[str] = None
    location: Optional[str] = None
    cityname: Optional[str] = None
    tel: Optional[str] = None
    type_name: Optional[str] = None
    distance: Optional[str] = None


class NeedSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["need_selection"]
    origin_candidates: List[POICandidate] = Field(default_factory=list)
    destination_candidates: List[POICandidate] = Field(default_factory=list)
    origin_name: Optional[str] = None
    origin_location: Optional[str] = None
    destination_name: Optional[str] = None
    destination_location: Optional[str] = None


class RouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "success"]
    origin_name: str
    destination_name: str
    origin_location: str
    destination_location: str
    route_mode: Optional[str] = None
    waypoints: List[str] = Field(default_factory=list)
    waypoint_locations: List[str] = Field(default_factory=list)
    distance: Optional[str] = None
    duration: Optional[str] = None
    taxi_cost: Optional[str] = None
    steps: List[RouteStep] = Field(default_factory=list)
    polyline: Optional[str] = None


class ErrorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["error"]
    message: str


StrictNavResult = Union[NeedSelectionResult, RouteResult, ErrorResult]
