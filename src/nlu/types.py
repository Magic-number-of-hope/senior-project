from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class IntentUnit:
    intent: str
    confidence: float = 0.0
    text_span: Optional[str] = None


@dataclass
class ParseResult:
    query: str
    intents: List[IntentUnit] = field(default_factory=list)
    slots: Dict[str, object] = field(default_factory=dict)
    json_valid: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        result = asdict(self)
        result["intents"] = [asdict(item) for item in self.intents]
        return result
