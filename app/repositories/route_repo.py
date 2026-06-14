from __future__ import annotations

from typing import List, Optional

from sqlalchemy import delete as sa_delete, select
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
            select(Route).where(Route.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def list_stopped_routes(self) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(Route.is_active.is_(False))
        )
        return list(result.scalars().all())

    async def list_routes_for_source(self, source_id: int) -> List[Route]:
        result = await self.session.execute(
            select(Route).where(
                Route.source_id == source_id,
                Route.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_all_routes(self) -> List[Route]:
        result = await self.session.execute(select(Route))
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

    async def delete_route(self, route_id: int) -> bool:
        result = await self.session.execute(
            sa_delete(Route).where(Route.id == route_id)
        )
        await self.session.flush()
        return result.rowcount > 0
