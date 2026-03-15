from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
import json
import os
from pathlib import Path
from collections import OrderedDict
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass
class POIRecord:
    name: str
    city: str
    address: str


class POIIndex:
    """In-memory POI index for retrieval-enhanced slot normalization."""

    def __init__(self, poi_records: Optional[List[POIRecord]] = None):
        self._records = poi_records or []
        self._name_to_record: Dict[str, POIRecord] = {record.name.lower(): record for record in self._records}

    def add(self, record: POIRecord) -> None:
        self._records.append(record)
        self._name_to_record[record.name.lower()] = record

    def search(self, query: str, top_k: int = 3) -> List[POIRecord]:
        keys = list(self._name_to_record.keys())
        candidates = get_close_matches(query.lower(), keys, n=top_k, cutoff=0.4)
        return [self._name_to_record[name] for name in candidates]


class AMapPOIResolver:
    """AMap Web API resolver for online POI calibration."""

    def __init__(
        self,
        api_key: str,
        city: str = "",
        timeout: float = 2.0,
        score_threshold: float = 0.45,
        cache_size: int = 512,
        strict_city: bool = True,
    ):
        self.api_key = api_key
        self.city = city
        self.timeout = timeout
        self.score_threshold = score_threshold
        self.strict_city = strict_city
        self.cache_size = cache_size
        self.request_count = 0
        self.success_count = 0
        self.cache_hit_count = 0
        self.last_status = "not_called"
        self._cache: "OrderedDict[str, Optional[POIRecord]]" = OrderedDict()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().lower().replace(" ", "")

    @staticmethod
    def _normalize_city(city: str) -> str:
        normalized = city.strip()
        normalized = normalized.replace("市", "")
        normalized = normalized.replace("省", "")
        return normalized

    def _city_matches(self, required_city: str, poi_city: str) -> bool:
        required = self._normalize_city(required_city)
        actual = self._normalize_city(poi_city)
        if not required or not actual:
            return True
        return required in actual or actual in required

    def _score_candidate(self, query: str, poi_name: str, poi_address: str, required_city: str, poi_city: str) -> float:
        name_sim = SequenceMatcher(None, self._normalize_text(query), self._normalize_text(poi_name)).ratio()
        query_in_address = 1.0 if self._normalize_text(query) in self._normalize_text(poi_address) else 0.0
        city_match = 1.0 if self._city_matches(required_city, poi_city) else 0.0

        if self.strict_city and required_city and city_match < 1.0:
            return -1.0

        return 0.75 * name_sim + 0.15 * query_in_address + 0.10 * city_match

    def _cache_get(self, key: str) -> tuple:
        if key not in self._cache:
            return False, None
        self._cache.move_to_end(key)
        self.cache_hit_count += 1
        self.last_status = "cache_hit"
        return True, self._cache[key]

    def _cache_put(self, key: str, value: Optional[POIRecord]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def search_one(self, query: str, city: str = "") -> Optional[POIRecord]:
        effective_city = city or self.city
        cache_key = f"{self._normalize_text(query)}::{self._normalize_city(effective_city)}"
        cached_found, cached_value = self._cache_get(cache_key)
        if cached_found:
            return cached_value

        self.request_count += 1
        params = {
            "key": self.api_key,
            "keywords": query,
            "city": effective_city,
            "offset": 10,
            "page": 1,
            "extensions": "base",
        }
        url = "https://restapi.amap.com/v3/place/text?" + urlencode(params)
        try:
            with urlopen(url, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            self.last_status = "request_failed"
            self._cache_put(cache_key, None)
            return None

        if str(payload.get("status", "")) != "1":
            self.last_status = "api_error"
            self._cache_put(cache_key, None)
            return None

        pois = payload.get("pois") or []
        if not pois:
            self.last_status = "no_result"
            self._cache_put(cache_key, None)
            return None

        best = None
        best_score = -1.0
        for candidate in pois:
            candidate_name = str(candidate.get("name", "")).strip()
            candidate_city = str(candidate.get("cityname", effective_city)).strip()
            candidate_address = str(candidate.get("address", "")).strip()
            score = self._score_candidate(
                query=query,
                poi_name=candidate_name,
                poi_address=candidate_address,
                required_city=effective_city,
                poi_city=candidate_city,
            )
            if score > best_score:
                best = candidate
                best_score = score

        if best is None or best_score < self.score_threshold:
            self.last_status = "low_confidence"
            self._cache_put(cache_key, None)
            return None

        self.success_count += 1
        self.last_status = "ok"
        record = POIRecord(
            name=str(best.get("name", "")).strip(),
            city=str(best.get("cityname", effective_city)).strip(),
            address=str(best.get("address", "")).strip(),
        )
        self._cache_put(cache_key, record)
        return record


def _load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


DEFAULT_POIS = [
    POIRecord(name="People Square", city="Shanghai", address="Huangpu District"),
    POIRecord(name="The Bund", city="Shanghai", address="Zhongshan East 1st Rd"),
    POIRecord(name="Shanghai Railway Station", city="Shanghai", address="Jing'an District"),
    POIRecord(name="Capital Airport", city="Beijing", address="Chaoyang District"),
]


def build_default_index() -> POIIndex:
    return POIIndex(DEFAULT_POIS)


def build_amap_resolver_from_env(default_city: str = "") -> Optional[AMapPOIResolver]:
    project_root = Path(__file__).resolve().parents[2]
    _load_env_file(project_root / ".env")

    api_key = os.getenv("AMAP_API_KEY", "").strip()
    if not api_key:
        return None
    city = os.getenv("AMAP_CITY", default_city).strip()
    return AMapPOIResolver(api_key=api_key, city=city)


def calibrate_location_slot(value: str, index: POIIndex) -> str:
    matches = index.search(value, top_k=1)
    if not matches:
        return value
    return matches[0].name


def calibrate_location_slot_with_amap(
    value: str,
    index: POIIndex,
    resolver: Optional[AMapPOIResolver] = None,
    city: str = "",
) -> str:
    """Prefer AMap calibration and fallback to local in-memory index."""
    if resolver is not None:
        online = resolver.search_one(value, city=city)
        if online and online.name:
            return online.name
    return calibrate_location_slot(value, index)
