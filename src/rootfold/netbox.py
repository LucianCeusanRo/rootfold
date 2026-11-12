"""Import sites, devices, cables and circuits from a NetBox REST API.

The mapper understands NetBox 3.x/4.x payload shapes. Tests and the CLI can run
fully offline against a recorded fixture JSON so Luci never needs a live NetBox.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from rootfold.config import Settings
from rootfold.importer import import_payload

PAGE_SIZE = 1000
RESOURCES = (
    ("sites", "/api/dcim/sites/"),
    ("devices", "/api/dcim/devices/"),
    ("cables", "/api/dcim/cables/"),
    ("circuits", "/api/circuits/circuits/"),
)

MEDIA = {
    "smf": "fiber",
    "mmf": "fiber",
    "fiber": "fiber",
    "singlemode": "fiber",
    "multimode": "fiber",
    "dac": "copper",
    "cat5": "copper",
    "cat5e": "copper",
    "cat6": "copper",
    "cat6a": "copper",
    "copper": "copper",
    "twinax": "copper",
    "microwave": "microwave",
    "mw": "microwave",
    "wireless": "microwave",
    "radio": "microwave",
    "lte": "lte",
}


class NetBoxError(RuntimeError):
    pass


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "object"


def _label(obj: Any, *keys: str) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, dict):
                found = _label(val, *keys)
                if found:
                    return found
            elif val:
                return str(val)
    return None


def _media(raw: str | None) -> str:
    if not raw:
        return "fiber"
    token = re.sub(r"[^a-z0-9]+", "", raw.lower())
    for key, media in MEDIA.items():
        if key in token or token in key:
            return media
    return "fiber"


def _ip(device: dict) -> str | None:
    for key in ("primary_ip4", "primary_ip", "primary_ip6"):
        addr = _label(device.get(key), "address")
        if addr:
            return addr.split("/")[0]
    return None


def _as_site_slug(site: dict | None) -> str | None:
    if not isinstance(site, dict):
        return None
    if site.get("slug"):
        return str(site["slug"])
    if site.get("name"):
        return slugify(str(site["name"]))
    return None


def _site_slug(obj: dict | None) -> str | None:
    """Walk NetBox nested termination/device objects until a site is found."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("site"), dict):
        return _as_site_slug(obj["site"])
    if isinstance(obj.get("object"), dict):
        found = _site_slug(obj["object"])
        if found:
            return found
    if isinstance(obj.get("device"), dict):
        return _site_slug(obj["device"])
    return None


def _device_name(obj: dict | None) -> str | None:
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("device"), dict):
        return _label(obj["device"], "name")
    if isinstance(obj.get("object"), dict):
        return _device_name(obj["object"]) or _label(obj["object"], "name")
    return None


def _terminations(row: dict, side: str) -> list[dict]:
    """Normalize NetBox 4.x lists and 3.x singular termination fields."""
    values: list[dict] = []
    seen = set()
    for key in (f"{side}_terminations", f"termination_{side}"):
        raw = row.get(key)
        items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        for item in items:
            marker = id(item)
            if marker in seen:
                continue
            seen.add(marker)
            values.append(item)
    return values


def _termination_site_and_device(term: dict) -> tuple[str | None, str | None]:
    site = _site_slug(term) or _site_slug((term.get("object") or {}) if isinstance(term.get("object"), dict) else None)
    if not site and isinstance(term.get("object"), dict):
        device = term["object"].get("device")
        if isinstance(device, dict):
            site = _site_slug(device)
    device = _device_name(term)
    if not site and isinstance(term.get("device"), dict):
        site = _site_slug(term["device"])
    return site, device


def load_fixture(path: Path) -> dict[str, list[dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pages = raw.get("pages") or raw
    out: dict[str, list[dict]] = {}
    for name, url_path in RESOURCES:
        key = url_path
        page = pages.get(key) or pages.get(name) or pages.get(url_path.rstrip("/"))
        if page is None:
            out[name] = []
            continue
        if isinstance(page, list):
            out[name] = page
        else:
            out[name] = list(page.get("results") or [])
    return out


def _path_only(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or url
    if not path.endswith("/"):
        path += "/"
    return path


def fetch_inventory(
    url: str,
    token: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> dict[str, list[dict]]:
    if not url or not token:
        raise NetBoxError("NetBox URL and token are required")
    base = url.rstrip("/")
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    own = client is None
    http = client or httpx.Client(base_url=base, headers=headers, timeout=timeout)
    try:
        inventory: dict[str, list[dict]] = {}
        for name, path in RESOURCES:
            rows: list[dict] = []
            next_url: str | None = path
            params: dict[str, Any] | None = {"limit": PAGE_SIZE}
            while next_url:
                request_url = next_url
                if request_url.startswith(base):
                    request_url = request_url[len(base) :]
                response = http.get(request_url, params=params)
                params = None
                if response.status_code >= 400:
                    raise NetBoxError(
                        f"NetBox {path} returned HTTP {response.status_code}: {response.text[:300]}"
                    )
                body = response.json()
                if isinstance(body, list):
                    rows.extend(body)
                    break
                rows.extend(body.get("results") or [])
                nxt = body.get("next")
                next_url = nxt if nxt else None
            inventory[name] = rows
        return inventory
    except httpx.HTTPError as exc:
        raise NetBoxError(f"NetBox request failed: {exc}") from exc
    finally:
        if own:
            http.close()


def map_inventory(inventory: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Translate a NetBox inventory dump into the Rootfold YAML/JSON payload shape."""
    sites_out: list[dict] = []
    site_slugs: set[str] = set()
    for row in inventory.get("sites") or []:
        slug = row.get("slug") or slugify(row.get("name") or f"site-{row.get('id', '')}")
        sites_out.append(
            {
                "slug": slug,
                "name": row.get("name") or slug,
                "region": _label(row.get("region"), "name", "slug"),
                "notes": row.get("description") or row.get("comments") or None,
            }
        )
        site_slugs.add(slug)

    devices_out: list[dict] = []
    device_slugs: dict[str, str] = {}  # name or slug -> slug
    for row in inventory.get("devices") or []:
        name = row.get("name") or f"device-{row.get('id', '')}"
        slug = row.get("slug") or slugify(name)
        site = _site_slug(row)
        if not site:
            continue
        if site not in site_slugs:
            sites_out.append({"slug": site, "name": site, "region": None, "notes": "Created from a device site"})
            site_slugs.add(site)
        role = _label(row.get("role") or row.get("device_role"), "slug", "name") or "device"
        dtype = row.get("device_type") or {}
        devices_out.append(
            {
                "slug": slug,
                "name": name,
                "role": role.replace(" ", "-").lower() if role else "device",
                "site": site,
                "management_ip": _ip(row),
                "vendor": _label((dtype or {}).get("manufacturer") if isinstance(dtype, dict) else None, "name")
                or _label(row.get("manufacturer"), "name"),
                "model": _label(dtype, "model", "slug") if isinstance(dtype, dict) else None,
            }
        )
        device_slugs[name] = slug
        device_slugs[slug] = slug
        device_slugs[slugify(name)] = slug

    circuits_out: list[dict] = []
    seen_circuits: set[str] = set()

    def add_circuit(**item: Any) -> None:
        slug = item["slug"]
        if slug in seen_circuits:
            return
        if item["a_site"] not in site_slugs or item["z_site"] not in site_slugs:
            return
        if item.get("a_device") and item["a_device"] not in device_slugs.values():
            item["a_device"] = device_slugs.get(item["a_device"], item["a_device"])
        if item.get("z_device") and item["z_device"] not in device_slugs.values():
            item["z_device"] = device_slugs.get(item["z_device"], item["z_device"])
        if item.get("a_device") and item["a_device"] not in device_slugs.values():
            item["a_device"] = None
        if item.get("z_device") and item["z_device"] not in device_slugs.values():
            item["z_device"] = None
        seen_circuits.add(slug)
        circuits_out.append(item)

    skipped_same_site = 0
    for row in inventory.get("cables") or []:
        a_terms = _terminations(row, "a")
        b_terms = _terminations(row, "b")
        if not a_terms or not b_terms:
            continue
        a_site, a_dev = _termination_site_and_device(a_terms[0])
        z_site, z_dev = _termination_site_and_device(b_terms[0])
        if not a_site or not z_site:
            continue
        if a_site == z_site:
            skipped_same_site += 1
            continue
        media = _media(_label(row.get("type"), "value", "label") or row.get("type"))
        cid = slugify(str(row.get("label") or f"cable-{row.get('id', len(circuits_out) + 1)}"))
        add_circuit(
            slug=cid,
            name=row.get("label") or f"Cable {row.get('id')}",
            media=media,
            a_site=a_site,
            z_site=z_site,
            a_device=device_slugs.get(a_dev or "", a_dev and slugify(a_dev)),
            z_device=device_slugs.get(z_dev or "", z_dev and slugify(z_dev)),
            capacity_mbps=None,
            customer=None,
            vendor_circuit_id=str(row.get("id")) if row.get("id") is not None else None,
        )

    for row in inventory.get("circuits") or []:
        cid = row.get("cid") or row.get("slug") or f"circuit-{row.get('id', '')}"
        slug = slugify(str(cid))
        typ = row.get("type")
        media = _media(_label(typ, "slug", "name") or (typ if isinstance(typ, str) else None))
        terms = list(row.get("terminations") or [])
        a_site = z_site = a_dev = z_dev = None
        if terms:
            a_site, a_dev = _termination_site_and_device(terms[0]) if isinstance(terms[0], dict) else (None, None)
            if len(terms) > 1 and isinstance(terms[1], dict):
                z_site, z_dev = _termination_site_and_device(terms[1])
        if not a_site:
            a_site, a_dev = _termination_site_and_device(row.get("termination_a") or {})
        if not z_site:
            z_site, z_dev = _termination_site_and_device(row.get("termination_z") or {})
        if not a_site or not z_site:
            continue
        provider = _label(row.get("provider"), "name")
        add_circuit(
            slug=slug,
            name=row.get("description") or str(cid),
            media=media,
            a_site=a_site,
            z_site=z_site,
            a_device=device_slugs.get(a_dev or "", a_dev and slugify(a_dev)),
            z_device=device_slugs.get(z_dev or "", z_dev and slugify(z_dev)),
            capacity_mbps=int(row["commit_rate"]) if row.get("commit_rate") else None,
            customer=_label(row.get("tenant"), "name"),
            vendor_circuit_id=str(cid) if provider else str(row.get("id") or cid),
        )

    return {
        "sites": sites_out,
        "devices": devices_out,
        "circuits": circuits_out,
        "bundles": [],
        "dependencies": [],
        "_meta": {"cables_skipped_same_site": skipped_same_site},
    }


def import_from_fixture(db: Session, path: Path) -> dict[str, int]:
    payload = map_inventory(load_fixture(path))
    meta = payload.pop("_meta", {})
    stats = import_payload(db, payload)
    stats["cables_skipped_same_site"] = int(meta.get("cables_skipped_same_site") or 0)
    stats["source"] = "netbox-fixture"
    return stats


def import_from_netbox(db: Session, settings: Settings, *, client: httpx.Client | None = None) -> dict[str, int]:
    if settings.netbox_fixture:
        return import_from_fixture(db, Path(settings.netbox_fixture))
    inventory = fetch_inventory(settings.netbox_url, settings.netbox_token, client=client)
    payload = map_inventory(inventory)
    meta = payload.pop("_meta", {})
    stats = import_payload(db, payload)
    stats["cables_skipped_same_site"] = int(meta.get("cables_skipped_same_site") or 0)
    stats["source"] = "netbox"
    return stats
