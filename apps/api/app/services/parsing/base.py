"""Parser result model shared by all parser implementations."""
from dataclasses import dataclass, field

CURRENT_PARSER_VERSION = "1.0"

# Maximum extracted text length: 2 MB. Longer text is truncated to protect DB and memory.
MAX_TEXT_BYTES = 2 * 1024 * 1024


@dataclass
class ParserResult:
    text: str
    parser_name: str
    parser_version: str
    language: str | None = None
    metadata_json: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None
