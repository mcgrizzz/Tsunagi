# from __future__ import annotations

# from typing import Any, List, Optional, Tuple
# from pydantic import BaseModel, ConfigDict
# from pydantic.fields import Field

# class TodayAmount(BaseModel):
#     day: int
#     amount: int

# class DeckToday(BaseModel):
#     lrnToday: TodayAmount
#     revToday: TodayAmount
#     newToday: TodayAmount
#     timeToday: TodayAmount

# class DeckCommon(BaseModel):
#     id: int
#     mtime: int
#     name: str
#     usn: int
#     sortf: int
#     collapsed: bool
#     browserCollapsed: bool
#     desc: str
#     md: bool
#     dyn: int
#     other: #TODO

# class DeckKind(BaseModel):
#     #TODO

# class Deck(BaseModel):
#     id: int
#     name: str
#     mtime_secs: int
#     usn: int
#     common: DeckCommon
#     kind: 