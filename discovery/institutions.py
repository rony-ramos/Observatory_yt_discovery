from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .dictionary import PROJECT_ROOT, normalize_text


DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "institutions" / "manifest.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError(f"La raiz de {path} debe ser un objeto YAML.")
    return data


@dataclass(frozen=True)
class OfficialChannel:
    name: str | None
    channel_id: str | None
    url: str | None
    verification_status: str


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    country: str
    aliases: tuple[str, ...]
    licensed: bool
    qs_ranked: bool
    verification_status: str
    official_channels: tuple[OfficialChannel, ...]

    @property
    def is_eligible(self) -> bool:
        return self.licensed and self.qs_ranked

    @property
    def official_channel_names(self) -> tuple[str, ...]:
        return tuple(channel.name for channel in self.official_channels if channel.name)

    @property
    def official_channel_ids(self) -> tuple[str, ...]:
        return tuple(
            channel.channel_id for channel in self.official_channels if channel.channel_id
        )


class InstitutionRegistry:
    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self.data = data
        self.path = path
        self.version = str(data["registry"]["version"])
        self._institutions = {
            normalize_text(item["id"]): _parse_institution(item)
            for item in data.get("institutions", [])
        }

    @classmethod
    def load(cls, path: str | Path | None = None) -> "InstitutionRegistry":
        if path is None:
            manifest = _load_yaml(DEFAULT_MANIFEST)
            active_version = manifest["active_version"]
            active_file = next(
                item["file"]
                for item in manifest["versions"]
                if item["version"] == active_version
            )
            registry_path = DEFAULT_MANIFEST.parent / active_file
        else:
            registry_path = Path(path)
            if not registry_path.is_absolute():
                registry_path = PROJECT_ROOT / registry_path

        registry_path = registry_path.resolve()
        return cls(_load_yaml(registry_path), registry_path)

    def get(self, institution_id: str, *, require_eligible: bool = True) -> Institution:
        key = normalize_text(institution_id)
        if key not in self._institutions:
            available = ", ".join(sorted(item.id for item in self._institutions.values()))
            raise ValueError(f"Institucion no registrada: {institution_id}. Opciones: {available}")

        institution = self._institutions[key]
        if require_eligible and not institution.is_eligible:
            raise ValueError(
                f"{institution.name} no cumple licensed=true y qs_ranked=true "
                "en el padron de instituciones."
            )
        return institution


def _parse_institution(item: dict[str, Any]) -> Institution:
    eligibility = item.get("eligibility") or {}
    channels = tuple(
        OfficialChannel(
            name=channel.get("name"),
            channel_id=channel.get("channel_id"),
            url=channel.get("url"),
            verification_status=channel.get("verification_status", "unknown"),
        )
        for channel in item.get("official_channels", [])
    )
    return Institution(
        id=str(item["id"]),
        name=str(item["name"]),
        country=str(item["country"]).upper(),
        aliases=tuple(item.get("aliases", [])),
        licensed=bool(eligibility.get("licensed")),
        qs_ranked=bool(eligibility.get("qs_ranked")),
        verification_status=str(eligibility.get("verification_status", "unknown")),
        official_channels=channels,
    )
