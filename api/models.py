"""Pydantic response models for all API endpoints."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class TableInfo(BaseModel):
    name: str
    file: str
    row_count: int


class ManifestResponse(BaseModel):
    schema_version: str
    generated_at: str
    tables: list[TableInfo]


class HealthResponse(BaseModel):
    status: str
    data_dir: str
    manifest: Optional[ManifestResponse] = None


class HealthSnapshotRow(BaseModel):
    hostname: str
    timestamp: str
    overall_status: str
    operational_risk: str
    cpu_5s_used_percent: Optional[str] = None
    cpu_1m_percent: Optional[str] = None
    cpu_5m_percent: Optional[str] = None
    memory_used_percent: Optional[str] = None
    memory_free_bytes: Optional[str] = None
    interfaces_up: Optional[str] = None
    interfaces_admin_down: Optional[str] = None
    interfaces_other: Optional[str] = None
    interface_errors_status: Optional[str] = None
    ntp_status: Optional[str] = None
    ntp_unsynchronized: Optional[str] = None
    probe_failures: Optional[str] = None
    ios_version: Optional[str] = None

    model_config = {"extra": "allow"}


class HealthCheckRow(BaseModel):
    hostname: str
    timestamp: str
    section: str
    check_name: str
    status: str
    details: Optional[str] = None

    model_config = {"extra": "allow"}


class ComplianceSnapshotRow(BaseModel):
    hostname: str
    timestamp: str
    compliance_score: Optional[str] = None
    compliance_status: Optional[str] = None
    total_controls: Optional[str] = None
    passed_controls_count: Optional[str] = None
    failed_controls_count: Optional[str] = None
    controls_evaluated_count: Optional[str] = None
    compliance_risk: Optional[str] = None

    model_config = {"extra": "allow"}


class ComplianceControlRow(BaseModel):
    hostname: str
    timestamp: str
    control_name: str
    control_status: str
    compliance_score: Optional[str] = None
    compliance_status: Optional[str] = None

    model_config = {"extra": "allow"}


class ListResponse(BaseModel):
    count: int
    data: list[Any]
