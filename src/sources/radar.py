import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from src.sources.base import Message, Source

logger = logging.getLogger(__name__)

RADAR_BASE = "https://api.cloudflare.com/client/v4/radar"


class RadarSource(Source):
    """Polls Cloudflare Radar for traffic anomalies and cloud origin outages."""

    def __init__(self, api_token: str, countries: dict[str, str] | None = None):
        self.api_token = api_token
        self.countries = countries or {}
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        self._session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        })
        if self.countries:
            logger.info("[RADAR] Source started (monitoring %d countries: %s)",
                        len(self.countries), ", ".join(self.countries.values()))
        else:
            logger.info("[RADAR] Source started (monitoring global outages only)")

    async def _fetch_traffic_anomalies(self) -> list[Message]:
        """Fetch internet traffic anomalies for configured countries (one request per country)."""
        if not self.countries:
            return []

        messages = []
        url = f"{RADAR_BASE}/traffic_anomalies"
        for i, (country_code, country_name) in enumerate(self.countries.items()):
            if i > 0:
                await asyncio.sleep(1)  # rate limit: 1 req/sec
            try:
                params = {
                    "location": country_code,
                    "dateRange": "1d",
                    "status": "VERIFIED",
                    "limit": 10,
                    "format": "json",
                }
                async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                for a in data.get("result", {}).get("trafficAnomalies", []):
                    asn_details = a.get("asnDetails") or {}
                    asn = asn_details.get("name", "")
                    status = a.get("status", "")
                    event_type = a.get("type", "")
                    start_date = a.get("startDate", "")

                    parts = [f"Location: {country_name}"]
                    if asn:
                        parts.append(f"Network: {asn}")
                    if status:
                        parts.append(f"Status: {status}")
                    if event_type:
                        parts.append(f"Type: {event_type}")

                    ts = None
                    if start_date:
                        try:
                            ts = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    msg_id = a.get("uuid", "") or f"{country_code}-{start_date}"
                    messages.append(Message(
                        source="radar",
                        source_id=f"anomaly-{msg_id}",
                        author=f"Traffic Anomaly — {country_name}",
                        content=" | ".join(parts),
                        url=f"https://radar.cloudflare.com/outage-center?location={country_code}",
                        timestamp=ts,
                    ))
            except Exception:
                logger.exception("[RADAR] Error fetching anomalies for %s", country_code)

        return messages

    async def _fetch_origin_outages(self) -> list[Message]:
        """Fetch cloud provider outages/anomalies from Radar annotations."""
        messages = []
        try:
            url = f"{RADAR_BASE}/annotations/outages"
            params = {
                "dateRange": "1d",
                "limit": 20,
                "format": "json",
            }
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("[RADAR] Outages returned %d: %s", resp.status, body[:200])
                    return []

                data = await resp.json()
                outages = data.get("result", {}).get("annotations", [])

                for o in outages:
                    data_source = o.get("dataSource", "")
                    locations = o.get("locationsDetails", []) or []
                    location_codes = [loc.get("code", "") for loc in locations]
                    asns = o.get("asnsDetails", []) or []

                    # If countries are configured, filter for matching locations or origin outages
                    # If no countries configured, include all origin outages
                    is_monitored = any(code in self.countries for code in location_codes) if self.countries else False
                    is_origin = data_source in ("ORIGIN", "origin")

                    if not is_monitored and not is_origin:
                        continue

                    description = o.get("description", "")
                    event_type = o.get("eventType", "")
                    start_date = o.get("startDate", "")
                    end_date = o.get("endDate", "")

                    parts = [description] if description else []
                    if event_type:
                        parts.append(f"Type: {event_type}")
                    if location_codes:
                        loc_names = [self.countries.get(c, c) for c in location_codes]
                        parts.append(f"Locations: {', '.join(loc_names)}")
                    if asns:
                        asn_names = [a.get("name", str(a.get("asn", ""))) for a in asns]
                        parts.append(f"Networks: {', '.join(asn_names)}")
                    if end_date:
                        parts.append("(Resolved)" if end_date else "(Ongoing)")

                    content = " | ".join(parts) if parts else "Outage detected"

                    ts = None
                    if start_date:
                        try:
                            ts = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    msg_id = o.get("id", "") or f"outage-{start_date}"

                    label = "Cloud Outage" if is_origin else f"Outage — {', '.join(self.countries.get(c, c) for c in location_codes)}"

                    messages.append(Message(
                        source="radar",
                        source_id=f"outage-{msg_id}",
                        author=label,
                        content=content,
                        url="https://radar.cloudflare.com/outage-center",
                        timestamp=ts,
                    ))

        except Exception:
            logger.exception("Error fetching Radar outages")

        return messages

    async def poll(self) -> list[Message]:
        logger.debug("[RADAR] Polling traffic anomalies + outages...")
        messages = []
        messages.extend(await self._fetch_traffic_anomalies())
        await asyncio.sleep(2)
        messages.extend(await self._fetch_origin_outages())
        logger.info("[RADAR] Poll complete: %d anomalies/outages", len(messages))
        return messages

    async def stop(self):
        if self._session:
            await self._session.close()
