"""HTTP API настроек организации.

Ручки тонкие: разобрать запрос → вызвать сервис → отдать ответ. Все проверки
прав живут в сервисах, поэтому прямой запрос в обход UI упирается в ту же
проверку и получает 403.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.enums import AccessSubjectType, UserRole, UserStatus
from backend.db.publics import Public
from backend.db.regions import Region
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.store import (
    JobKind,
    ProgressReporter,
    create_job,
    run_job_in_background,
)
from backend.modules.organization.schemas import (
    CommunityBrief,
    CommunityGroupResponse,
    CommunityGroupWriteRequest,
    DataHealthResponse,
    EffectiveAccessItem,
    GrantItem,
    GrantMatrixResponse,
    GrantReplaceRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportResultResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    PublicImportConfirmRequest,
    PublicImportJobResponse,
    PublicImportPreviewResponse,
    UserCreateRequest,
    UserGroupResponse,
    UserGroupWriteRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from backend.modules.organization.services.organization_service import OrganizationService
from backend.modules.organization.services.access_grant_service import AccessGrantService
from backend.modules.organization.services.authorization_service import AuthorizationService
from backend.modules.organization.services.group_service import (
    CommunityGroupService,
    UserGroupService,
)
from backend.modules.organization.services.data_health_service import DataHealthService
from backend.modules.organization.services.import_service import UserImportService
from backend.modules.organization.services.public_import_runner import (
    revalidate,
    run_public_import,
)
from backend.modules.organization.services.public_import_service import PublicImportService
from backend.modules.organization.services.user_service import UserService


def _public_base_url(request: Request) -> str:
    """Origin браузера — фактический адрес фронтенда, включая порт."""
    return request.headers.get("origin") or str(request.base_url).rstrip("/")


async def _region_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(Region.id, Region.name).where(Region.id.in_(ids)))
    ).all()
    return {row.id: row.name for row in rows}


async def _organization_response(
    db: AsyncSession,
    org,
    *,
    user_count: int = 0,
    community_count: int = 0,
) -> OrganizationResponse:
    region_name = None
    if org.region_id:
        region_name = await db.scalar(select(Region.name).where(Region.id == org.region_id))
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        type=org.type,
        description=org.description,
        region_id=org.region_id,
        region_name=region_name,
        municipality_name=org.municipality_name,
        is_active=org.is_active,
        created_at=org.created_at,
        user_count=user_count,
        community_count=community_count,
    )


router = APIRouter(prefix="/api/organizations", tags=["organization"])


# ── организации ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationResponse]:
    """Суперадмин видит все организации, админ — только свою."""
    rows = await OrganizationService(db).list_organizations(current_user)
    names = await _region_names(
        db,
        {org.region_id for org, _, _ in rows if org.region_id},
    )
    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            type=org.type,
            description=org.description,
            region_id=org.region_id,
            region_name=names.get(org.region_id) if org.region_id else None,
            municipality_name=org.municipality_name,
            is_active=org.is_active,
            created_at=org.created_at,
            user_count=users,
            community_count=communities,
        )
        for org, users, communities in rows
    ]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: Request,
    payload: OrganizationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    """Заводит организацию. Только суперадмин (проверка в сервисе → 403)."""
    org = await OrganizationService(db).create(
        current_user,
        name=payload.name,
        org_type=payload.type,
        description=payload.description,
        region_id=payload.region_id,
        municipality_name=payload.municipality_name,
        admin_email=payload.admin_email,
        admin_first_name=payload.admin_first_name,
        admin_last_name=payload.admin_last_name,
        public_base_url=_public_base_url(request),
    )
    return await _organization_response(
        db,
        org,
        user_count=1 if payload.admin_email else 0,
    )


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удаляет организацию со всем содержимым. Только суперадмин (403 иначе)."""
    await OrganizationService(db).delete(current_user, organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    org = await OrganizationService(db).update(
        current_user,
        organization_id,
        name=payload.name,
        org_type=payload.type,
        description=payload.description,
        region_id=payload.region_id,
        region_id_set="region_id" in payload.model_fields_set,
        municipality_name=payload.municipality_name,
        municipality_name_set="municipality_name" in payload.model_fields_set,
        is_active=payload.is_active,
    )
    return await _organization_response(db, org)


async def _user_to_response(service: UserService, user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        groups=[{"id": g.id, "name": g.name} for g in user.groups],
        accessible_communities_count=await service.count_accessible_communities(user),
    )


# ── пользователи ────────────────────────────────────────────────────────────

@router.get("/{organization_id}/users", response_model=UserListResponse)
async def list_users(
    organization_id: uuid.UUID,
    search: str | None = Query(None),
    role: UserRole | None = Query(None),
    user_status: UserStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    service = UserService(db)
    users, total = await service.list_users(
        organization_id,
        search=search,
        role=role,
        user_status=user_status,
        page=page,
        page_size=page_size,
    )
    return UserListResponse(
        items=[await _user_to_response(service, u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{organization_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    organization_id: uuid.UUID,
    payload: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = UserService(db)
    user = await service.create_user(
        current_user,
        organization_id,
        payload,
        public_base_url=_public_base_url(request),
    )
    return await _user_to_response(service, user)


@router.patch("/{organization_id}/users/{user_id}", response_model=UserResponse)
async def update_user(
    request: Request,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = UserService(db)
    user = await service.update_user(
        current_user,
        organization_id,
        user_id,
        payload,
        public_base_url=_public_base_url(request),
    )
    return await _user_to_response(service, user)


@router.post("/{organization_id}/users/{user_id}/resend-invitation", status_code=status.HTTP_204_NO_CONTENT)
async def resend_invitation(
    request: Request,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await UserService(db).resend_invitation(
        current_user,
        organization_id,
        user_id,
        public_base_url=_public_base_url(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{organization_id}/users/{user_id}/block", response_model=UserResponse)
async def block_user(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = UserService(db)
    user = await service.set_blocked(current_user, organization_id, user_id, True)
    return await _user_to_response(service, user)


@router.post("/{organization_id}/users/{user_id}/unblock", response_model=UserResponse)
async def unblock_user(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = UserService(db)
    user = await service.set_blocked(current_user, organization_id, user_id, False)
    return await _user_to_response(service, user)


@router.delete("/{organization_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await UserService(db).delete_user(current_user, organization_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{organization_id}/users/{user_id}/effective-access",
    response_model=list[EffectiveAccessItem],
)
async def effective_access(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EffectiveAccessItem]:
    """Итоговые доступы с источником: лично или через группу."""
    authz = AuthorizationService(db)
    authz.require_organization_admin(current_user, organization_id)

    user = await UserService(db).get_user(organization_id, user_id)
    items = await authz.describe_effective_access(user)
    if not items:
        return []

    names = {
        row.id: row.name
        for row in (
            await db.execute(
                select(Public.id, Public.name).where(
                    Public.id.in_({i.community_id for i in items})
                )
            )
        ).all()
    }
    return [
        EffectiveAccessItem(
            community_id=item.community_id,
            community_name=names.get(item.community_id, "—"),
            permission=item.permission,
            source_type=item.source_type,
            source_name=item.source_name,
        )
        for item in items
        if item.community_id in names
    ]


# ── группы пользователей ────────────────────────────────────────────────────

@router.get("/{organization_id}/user-groups", response_model=list[UserGroupResponse])
async def list_user_groups(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserGroupResponse]:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    rows = await UserGroupService(db).list_groups(organization_id)
    return [
        UserGroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
            member_count=members,
            grant_count=grants,
        )
        for g, members, grants in rows
    ]


@router.post(
    "/{organization_id}/user-groups",
    response_model=UserGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_group(
    organization_id: uuid.UUID,
    payload: UserGroupWriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserGroupResponse:
    group = await UserGroupService(db).create(
        current_user,
        organization_id,
        name=payload.name,
        description=payload.description,
        member_ids=payload.member_ids,
    )
    return UserGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        member_count=len(payload.member_ids),
    )


@router.put("/{organization_id}/user-groups/{group_id}", response_model=UserGroupResponse)
async def update_user_group(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: UserGroupWriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserGroupResponse:
    group = await UserGroupService(db).update(
        current_user,
        organization_id,
        group_id,
        name=payload.name,
        description=payload.description,
        member_ids=payload.member_ids,
    )
    return UserGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        member_count=len(payload.member_ids),
    )


@router.get("/{organization_id}/user-groups/{group_id}/members", response_model=list[uuid.UUID])
async def user_group_members(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[uuid.UUID]:
    service = UserGroupService(db)
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    await service.get(organization_id, group_id)
    return await service.get_member_ids(group_id)


@router.delete(
    "/{organization_id}/user-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_user_group(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await UserGroupService(db).delete(current_user, organization_id, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── группы сообществ ────────────────────────────────────────────────────────

@router.get("/{organization_id}/communities", response_model=list[CommunityBrief])
async def list_communities(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommunityBrief]:
    """Сообщества организации — для мультивыбора в формах."""
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    rows = (
        await db.execute(
            select(Public)
            .where(Public.organization_id == organization_id)
            .order_by(Public.name.asc())
        )
    ).scalars().all()
    return [CommunityBrief.model_validate(r) for r in rows]


@router.get("/{organization_id}/data-health", response_model=DataHealthResponse)
async def data_health(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataHealthResponse:
    """Свежесть спарсенных данных и классификации комментариев."""

    return DataHealthResponse.model_validate(
        await DataHealthService(db).get(current_user, organization_id)
    )


@router.get(
    "/{organization_id}/community-groups", response_model=list[CommunityGroupResponse]
)
async def list_community_groups(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommunityGroupResponse]:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    rows = await CommunityGroupService(db).list_groups(organization_id)
    return [
        CommunityGroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
            community_count=members,
            grant_count=grants,
        )
        for g, members, grants in rows
    ]


@router.post(
    "/{organization_id}/community-groups",
    response_model=CommunityGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_group(
    organization_id: uuid.UUID,
    payload: CommunityGroupWriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityGroupResponse:
    group = await CommunityGroupService(db).create(
        current_user,
        organization_id,
        name=payload.name,
        description=payload.description,
        community_ids=payload.community_ids,
    )
    return CommunityGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        community_count=len(payload.community_ids),
    )


@router.put(
    "/{organization_id}/community-groups/{group_id}",
    response_model=CommunityGroupResponse,
)
async def update_community_group(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: CommunityGroupWriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityGroupResponse:
    group = await CommunityGroupService(db).update(
        current_user,
        organization_id,
        group_id,
        name=payload.name,
        description=payload.description,
        community_ids=payload.community_ids,
    )
    return CommunityGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        community_count=len(payload.community_ids),
    )


@router.get(
    "/{organization_id}/community-groups/{group_id}/communities",
    response_model=list[uuid.UUID],
)
async def community_group_members(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[uuid.UUID]:
    service = CommunityGroupService(db)
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    await service.get(organization_id, group_id)
    return await service.get_community_ids(group_id)


@router.delete(
    "/{organization_id}/community-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_community_group(
    organization_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await CommunityGroupService(db).delete(current_user, organization_id, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── права ───────────────────────────────────────────────────────────────────

@router.get("/{organization_id}/grants", response_model=GrantMatrixResponse)
async def get_grants(
    organization_id: uuid.UUID,
    subject_type: AccessSubjectType = Query(...),
    subject_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrantMatrixResponse:
    grants = await AccessGrantService(db).get_matrix(
        current_user, organization_id, subject_type, subject_id
    )
    return GrantMatrixResponse(
        subject_type=subject_type,
        subject_id=subject_id,
        grants=[
            GrantItem(
                resource_type=g.resource_type,
                resource_id=g.resource_id,
                permission=g.permission,
            )
            for g in grants
        ],
    )


@router.put("/{organization_id}/grants", response_model=GrantMatrixResponse)
async def replace_grants(
    organization_id: uuid.UUID,
    payload: GrantReplaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrantMatrixResponse:
    grants = await AccessGrantService(db).replace(
        current_user,
        organization_id,
        payload.subject_type,
        payload.subject_id,
        payload.grants,
    )
    return GrantMatrixResponse(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        grants=[
            GrantItem(
                resource_type=g.resource_type,
                resource_id=g.resource_id,
                permission=g.permission,
            )
            for g in grants
        ],
    )


# ── импорт ──────────────────────────────────────────────────────────────────

@router.get("/{organization_id}/users/export")
async def export_users(
    organization_id: uuid.UUID,
    fmt: str = Query("csv", pattern="^(csv|xlsx)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Выгрузка таблицы пользователей теми же колонками, что принимает импорт.

    Пагинацию здесь НЕ применяем: выгружать половину таблицы — хуже, чем не
    выгружать вовсе. Ограничение — та же верхняя планка, что у импорта.
    """
    AuthorizationService(db).require_organization_admin(current_user, organization_id)

    users = await UserService(db).list_for_export(organization_id)
    content = UserImportService.build_export(users, fmt=fmt)

    if fmt == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "users.xlsx"
    else:
        media_type = "text/csv; charset=utf-8"
        filename = "users.csv"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{organization_id}/users/import/template")
async def import_template(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    return Response(
        content=UserImportService.build_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="users_template.csv"'},
    )


@router.post(
    "/{organization_id}/users/import/preview", response_model=ImportPreviewResponse
)
async def import_preview(
    organization_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewResponse:
    content = await file.read()
    return await UserImportService(db).preview(
        current_user, organization_id, content, file.filename or ""
    )


@router.post(
    "/{organization_id}/users/import/confirm", response_model=ImportResultResponse
)
async def import_confirm(
    organization_id: uuid.UUID,
    payload: ImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportResultResponse:
    return await UserImportService(db).confirm(
        current_user, organization_id, payload.rows
    )


@router.post("/{organization_id}/users/import/error-report")
async def import_error_report(
    organization_id: uuid.UUID,
    payload: ImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CSV с ошибочными строками — пользователь чинит его и грузит заново."""
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    return Response(
        content=UserImportService.build_error_report(payload.rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="import_errors.csv"'},
    )


# ── импорт площадок ────────────────────────────────────────────────────────

@router.get("/{organization_id}/publics/import/template")
async def public_import_template(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    return Response(
        content=PublicImportService.build_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="publics_template.csv"'},
    )


@router.post(
    "/{organization_id}/publics/import/preview",
    response_model=PublicImportPreviewResponse,
)
async def public_import_preview(
    organization_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublicImportPreviewResponse:
    content = await file.read()
    return await PublicImportService(db).preview(
        current_user, organization_id, content, file.filename or ""
    )


@router.post(
    "/{organization_id}/publics/import/confirm",
    response_model=PublicImportJobResponse,
)
async def public_import_confirm(
    organization_id: uuid.UUID,
    payload: PublicImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublicImportJobResponse:
    """Запускает импорт фоновой задачей и возвращает job_id для поллинга.

    Каждая площадка создаётся штатным ingest-ом, а это поход в API соцсети,
    поэтому синхронно уложиться в таймаут запроса нельзя.
    """
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    rows = revalidate(payload.rows)

    job = await create_job(JobKind.publics_import, message="Подготовка импорта…")

    async def runner(reporter: ProgressReporter) -> dict:
        result = await run_public_import(
            user=current_user,
            organization_id=organization_id,
            rows=rows,
            date_from=payload.date_from,
            date_to=payload.date_to,
            reporter=reporter,
        )
        return result.model_dump()

    run_job_in_background(job, runner)
    return PublicImportJobResponse(job_id=job.id)


@router.post("/{organization_id}/publics/import/error-report")
async def public_import_error_report(
    organization_id: uuid.UUID,
    payload: PublicImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    AuthorizationService(db).require_organization_admin(current_user, organization_id)
    return Response(
        content=PublicImportService.build_error_report(payload.rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="publics_import_errors.csv"'},
    )
