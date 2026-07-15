from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import Route


class RouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_route(self, source_id: int, destination_id: int) -> Optional[Route]:
        result = await self.session.execute(
            select(Route).where(
                Route.source_id == source_id,
                Route.destination_id == destination_id,
                Route.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_route_by_id(self, route_id: int) -> Optional[Route]:
        result = await self.session.execute(
            select(Route).where(Route.id == route_id)
        )
        return result.scalar_one_or_none()

    async def list_active_routes(self) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(Route.is_active.is_(True), Route.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def list_stopped_routes(self) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(Route.is_active.is_(False), Route.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def list_routes_for_source(self, source_id: int) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(
                Route.source_id == source_id,
                Route.is_active.is_(True),
                Route.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def list_all_routes(self) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(Route.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def list_deleted_routes(self) -> List[Route]:
        result = await self.session.execute(
            select(Route)
            .where(Route.deleted_at.is_not(None))
            .order_by(Route.deleted_at.desc())
        )
        return list(result.scalars().all())

    async def list_recently_added(self, limit: int = 20) -> List[Route]:
        result = await self.session.execute(
            select(Route)
            .where(Route.deleted_at.is_(None))
            .order_by(Route.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_route(self, source_id: int, destination_id: int) -> Route:
        route = Route(source_id=source_id, destination_id=destination_id)
        self.session.add(route)
        await self.session.flush()
        await self.session.refresh(route)
        return route

    async def deactivate_route(self, route_id: int) -> bool:
        result = await self.session.execute(
            select(Route).where(Route.id == route_id)
        )
        route = result.scalar_one_or_none()
        if route is None:
            return False
        route.is_active = False
        await self.session.flush()
        return True

    async def activate_route(self, route_id: int) -> bool:
        result = await self.session.execute(
            select(Route).where(Route.id == route_id)
        )
        route = result.scalar_one_or_none()
        if route is None:
            return False
        route.is_active = True
        await self.session.flush()
        return True

    async def toggle_strip_footer(self, route_id: int) -> Optional[bool]:
        """Toggle strip_footer flag. Returns new value, or None if not found."""
        result = await self.session.execute(select(Route).where(Route.id == route_id))
        route = result.scalar_one_or_none()
        if route is None:
            return None
        route.strip_footer = not route.strip_footer
        await self.session.flush()
        return route.strip_footer

    async def toggle_media_only(self, route_id: int) -> Optional[bool]:
        """Toggle media_only flag. Returns new value, or None if not found."""
        result = await self.session.execute(select(Route).where(Route.id == route_id))
        route = result.scalar_one_or_none()
        if route is None:
            return None
        route.media_only = not route.media_only
        await self.session.flush()
        return route.media_only

    async def delete_route(self, route_id: int) -> bool:
        """Soft delete — keeps the route in DB for archive."""
        result = await self.session.execute(
            select(Route).where(Route.id == route_id)
        )
        route = result.scalar_one_or_none()
        if route is None:
            return False
        route.deleted_at = datetime.now(timezone.utc)
        route.is_active = False
        await self.session.flush()
        return True
