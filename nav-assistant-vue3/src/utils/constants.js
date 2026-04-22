// Intent labels and CSS class mapping
export const INTENT_LABELS = {
  basic_navigation: '基础导航',
  life_service: '生活服务',
  multi_destination: '多目的地',
  compound_constraint: '复合约束',
}

export const INTENT_CSS = {
  basic_navigation: 'basic',
  life_service: 'life',
  multi_destination: 'multi',
  compound_constraint: 'compound',
}

export const MODE_LABELS = {
  driving: '驾车',
  walking: '步行',
  transit: '公交',
  bicycling: '骑行',
}

export const SLOT_LABELS = {
  origin: '出发地',
  destination: '目的地',
  waypoints: '途经点',
  travel_mode: '出行方式',
  time_constraint: '时间约束',
  preference: '偏好',
  poi_type: 'POI类型',
  poi_constraint: 'POI约束',
  sequence: '顺序',
}

export const MODE_OPTIONS = [
  { value: 'driving', label: '🚗 驾车' },
  { value: 'walking', label: '🚶 步行' },
  { value: 'transit', label: '🚌 公交' },
  { value: 'bicycling', label: '🚲 骑行' },
]

export const QUICK_COMMANDS = [
  { icon: '🚗', label: '去光谷广场（避堵）', text: '从武汉理工大学到光谷广场，开车避开拥堵' },
  { icon: '🍲', label: '附近火锅店', text: '帮我找附近评分高的火锅店' },
  { icon: '⛽', label: '先加油再去机场', text: '先去加油站，再去天河机场' },
  { icon: '🚶', label: '步行去最近地铁站', text: '步行去最近地铁站' },
]

// Fatigue detection constants
export const FATIGUE = {
  NORMAL_FPS: 1,
  ALERT_FPS: 1,
  ATTENTION_SCORE: 0.45,
  DROWSY_SCORE: 0.72,
  ATTENTION_HOLD_MS: 6000,
  DROWSY_HOLD_MS: 8000,
  HIGH_FPS_HOLD_MS: 15000,
}
