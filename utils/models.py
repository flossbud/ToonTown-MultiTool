from dataclasses import dataclass, field
from typing import List

@dataclass
class AccountCredential:
    id: str
    label: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    game: str = "ttr"

    @classmethod
    def from_dict(cls, data: dict, password: str = "") -> 'AccountCredential':
        return cls(
            id=data.get("id", ""),
            label=data.get("label", ""),
            username=data.get("username", ""),
            password=password,
            game=data.get("game", "ttr"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "username": self.username,
            "game": self.game,
        }

@dataclass
class ToonProfile:
    name: str = ""
    enabled_toons: List[bool] = field(default_factory=lambda: [False]*4)
    movement_modes: List[str] = field(default_factory=lambda: ["Default"]*4)
    keep_alive: List[bool] = field(default_factory=lambda: [False]*4)
    rapid_fire: List[bool] = field(default_factory=lambda: [False]*4)

    @classmethod
    def from_dict(cls, data: dict) -> 'ToonProfile':
        return cls(
            name=data.get("name", ""),
            enabled_toons=data.get("enabled_toons", [False]*4),
            movement_modes=data.get("movement_modes", ["Default"]*4),
            keep_alive=data.get("keep_alive", [False]*4),
            rapid_fire=data.get("rapid_fire", [False]*4),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled_toons": self.enabled_toons,
            "movement_modes": self.movement_modes,
            "keep_alive": self.keep_alive,
            "rapid_fire": self.rapid_fire,
        }
