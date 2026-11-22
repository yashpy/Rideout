from typing import Any

from fastapi import HTTPException, status


def out(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Mongo `_id` → `id` on the wire."""
    if doc is None:
        return None
    return {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}


def not_yet(feature: str) -> HTTPException:
    """Endpoint is in the contract but not built yet. Replace the raise with the real thing."""
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"not implemented yet: {feature}")


# ── Try it: the visitor's own address ────────────────────────────────────────────
VISITOR_MAX_MOVE_M = 2500.0  # the typed address must be near the house we picked for it (same street area)


async def place_visitor(db, hh: dict, address: str | None, lon: float | None, lat: float | None) -> dict:
    """Try it with a typed address: the picked house (the nearest one) moves to the visitor's real
    address, so the map, the call and the drivers all use it. → the updated household.
    Rejects an address far from that house (outside the warning zone)."""
    if not address or lon is None or lat is None:
        return hh
    from api.sim.geo import meters

    here = tuple((hh.get("location") or {}).get("coordinates") or ())
    if len(here) != 2 or meters((float(here[0]), float(here[1])), (lon, lat)) > VISITOR_MAX_MOVE_M:
        from fastapi import HTTPException

        raise HTTPException(422, "that address is outside the warning zone; pick a house on the map instead")
    loc = {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}
    clean = " ".join(address.split())[:160]
    await db.households.update_one({"_id": hh["_id"]}, {"$set": {"location": loc, "address": clean}})
    return {**hh, "location": loc, "address": clean}
