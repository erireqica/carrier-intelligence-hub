from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.integrations.gmail.client import GmailMailbox, mailbox_from_credential
from app.integrations.gmail.errors import (
    GmailLabelBindingInvalid,
    GmailLabelPermanentError,
    GmailModifyPermissionRequired,
    GmailReauthorizationRequired,
    GmailThreadNotFound,
    GmailTransientError,
)
from app.models.enums import GmailConnectionStatus, GmailLabelKey, GmailLabelSyncStatus
from app.models.gmail_labels import GmailManagedLabel, GmailThreadLabelSync
from app.models.operations import CarrierMessage
from app.models.organization import GmailConnection, GmailOAuthCredential
from app.services.audit import record_audit_event
from app.services.gmail_labels import (
    MANAGED_LABEL_NAMES,
    RECONCILABLE_LABEL_NAMES,
    MailboxFactory,
    can_apply_workflow_labels,
    claim_label_sync,
    desired_labels_for_thread,
    enqueue_thread_label_sync,
    process_claimed_label_sync,
)


@dataclass
class GmailLabelMigrationResult:
    dry_run: bool
    mailboxes_inspected: int = 0
    threads_inspected: int = 0
    threads_changed: int = 0
    labels_added: int = 0
    labels_removed: int = 0
    obsolete_processed_assignments_removed: int = 0
    retained_label_definitions: int = 0
    label_definitions_to_create: int = 0
    label_definitions_created: int = 0
    obsolete_definitions_to_delete: int = 0
    obsolete_definitions_deleted: int = 0
    stored_legacy_bindings_removed: int = 0
    failures: int = 0
    failure_codes: Counter[str] = field(default_factory=Counter)

    def add_failure(self, code: str) -> None:
        self.failures += 1
        self.failure_codes[code] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "mailboxes_inspected": self.mailboxes_inspected,
            "threads_inspected": self.threads_inspected,
            "threads_changed": self.threads_changed,
            "labels_added": self.labels_added,
            "labels_removed": self.labels_removed,
            "obsolete_processed_assignments_removed": (self.obsolete_processed_assignments_removed),
            "retained_label_definitions": self.retained_label_definitions,
            "label_definitions_to_create": self.label_definitions_to_create,
            "label_definitions_created": self.label_definitions_created,
            "obsolete_definitions_to_delete": self.obsolete_definitions_to_delete,
            "obsolete_definitions_deleted": self.obsolete_definitions_deleted,
            "stored_legacy_bindings_removed": self.stored_legacy_bindings_removed,
            "failures": self.failures,
            "failure_codes": dict(sorted(self.failure_codes.items())),
        }


def _known_thread_ids(db: Session, connection_id: int) -> list[str]:
    message_threads = set(
        db.scalars(
            select(CarrierMessage.gmail_thread_id).where(
                CarrierMessage.gmail_connection_id == connection_id,
                CarrierMessage.gmail_thread_id.is_not(None),
                CarrierMessage.gmail_thread_id != "",
            )
        ).all()
    )
    synchronized_threads = set(
        db.scalars(
            select(GmailThreadLabelSync.gmail_thread_id).where(
                GmailThreadLabelSync.gmail_connection_id == connection_id
            )
        ).all()
    )
    return sorted(message_threads | synchronized_threads)


def _listed_managed_labels(mailbox: GmailMailbox) -> dict[GmailLabelKey, str]:
    response = mailbox.list_labels()
    by_name: dict[str, str] = {}
    for item in response.get("labels", []) or []:
        if not isinstance(item, Mapping) or item.get("type") != "user":
            continue
        name = item.get("name")
        label_id = item.get("id")
        if isinstance(name, str) and isinstance(label_id, str):
            by_name[name] = label_id
    return {key: by_name[name] for key, name in RECONCILABLE_LABEL_NAMES.items() if name in by_name}


def _error_code(error: Exception) -> str:
    if isinstance(error, GmailModifyPermissionRequired):
        return "GMAIL_MODIFY_SCOPE_REQUIRED"
    if isinstance(error, GmailReauthorizationRequired):
        return "GMAIL_REAUTH_REQUIRED"
    if isinstance(error, GmailThreadNotFound):
        return "GMAIL_THREAD_NOT_FOUND"
    if isinstance(error, GmailLabelBindingInvalid):
        return "GMAIL_LABEL_BINDING_INVALID"
    if isinstance(error, GmailLabelPermanentError):
        return "GMAIL_LABEL_PERMANENT_FAILURE"
    if isinstance(error, GmailTransientError):
        return "GMAIL_LABEL_TRANSIENT_FAILURE"
    return "GMAIL_LABEL_MIGRATION_UNEXPECTED"


def _inspect_thread(
    db: Session,
    mailbox: GmailMailbox,
    connection_id: int,
    thread_id: str,
    bindings: dict[GmailLabelKey, str],
) -> tuple[int, int, int]:
    desired = desired_labels_for_thread(
        db,
        gmail_connection_id=connection_id,
        gmail_thread_id=thread_id,
    )
    actual = mailbox.get_thread_label_state(thread_id)
    if not actual.labelable_message_count:
        return 0, 0, 0
    desired_existing_ids = {bindings[key] for key in desired if key in bindings}
    missing_desired = desired - bindings.keys()
    add_count = len(desired_existing_ids - actual.all_label_ids) + len(missing_desired)
    managed_ids = set(bindings.values())
    remove_ids = (actual.any_label_ids & managed_ids) - desired_existing_ids
    legacy_id = bindings.get(GmailLabelKey.PROCESSED)
    obsolete_count = int(legacy_id is not None and legacy_id in remove_ids)
    return add_count, len(remove_ids), obsolete_count


def _remove_stored_legacy_binding(db: Session, connection_id: int) -> int:
    rows = db.scalars(
        select(GmailManagedLabel).where(
            GmailManagedLabel.gmail_connection_id == connection_id,
            GmailManagedLabel.label_key == GmailLabelKey.PROCESSED,
        )
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def _cached_mailbox_factory(mailbox: GmailMailbox) -> MailboxFactory:
    def factory(unused: GmailOAuthCredential) -> tuple[GmailMailbox, bool]:
        return mailbox, False

    return factory


def _delete_obsolete_definition(
    db: Session,
    mailbox: GmailMailbox,
    connection: GmailConnection,
    thread_ids: list[str],
    bindings: dict[GmailLabelKey, str],
    result: GmailLabelMigrationResult,
    *,
    connection_failed: bool,
) -> None:
    legacy_id = bindings.get(GmailLabelKey.PROCESSED)
    if legacy_id is None:
        result.stored_legacy_bindings_removed += _remove_stored_legacy_binding(db, connection.id)
        return
    result.obsolete_definitions_to_delete += 1
    if connection_failed:
        return
    try:
        for thread_id in thread_ids:
            state = mailbox.get_thread_label_state(thread_id)
            if legacy_id in state.any_label_ids:
                result.add_failure("PROCESSED_ASSIGNMENT_REMAINS")
                return
        with suppress(GmailLabelBindingInvalid):
            mailbox.delete_label(legacy_id)
    except Exception as error:
        result.add_failure(_error_code(error))
        return
    result.obsolete_definitions_deleted += 1
    result.stored_legacy_bindings_removed += _remove_stored_legacy_binding(db, connection.id)


def migrate_managed_gmail_labels(
    db: Session,
    *,
    dry_run: bool = True,
    connection_id: int | None = None,
    mailbox_factory: MailboxFactory = mailbox_from_credential,
) -> GmailLabelMigrationResult:
    result = GmailLabelMigrationResult(dry_run=dry_run)
    query = (
        select(GmailConnection)
        .options(joinedload(GmailConnection.oauth_credential))
        .where(GmailConnection.status == GmailConnectionStatus.CONNECTED)
        .order_by(GmailConnection.id)
    )
    if connection_id is not None:
        query = query.where(GmailConnection.id == connection_id)
    connections = db.scalars(query).all()

    for connection in connections:
        result.mailboxes_inspected += 1
        thread_ids = _known_thread_ids(db, connection.id)
        credential: GmailOAuthCredential | None = connection.oauth_credential
        if credential is None or not can_apply_workflow_labels(connection):
            result.add_failure("GMAIL_MODIFY_SCOPE_REQUIRED")
            continue
        try:
            mailbox, refreshed = mailbox_factory(credential)
            if refreshed:
                db.commit()
            initial_bindings = _listed_managed_labels(mailbox)
        except Exception as error:
            db.rollback()
            result.add_failure(_error_code(error))
            continue

        result.retained_label_definitions += len(set(initial_bindings) & set(MANAGED_LABEL_NAMES))
        missing_active = set(MANAGED_LABEL_NAMES) - set(initial_bindings)
        if thread_ids:
            result.label_definitions_to_create += len(missing_active)
        connection_failures_before = result.failures

        if dry_run:
            for thread_id in thread_ids:
                result.threads_inspected += 1
                try:
                    added, removed, obsolete = _inspect_thread(
                        db,
                        mailbox,
                        connection.id,
                        thread_id,
                        initial_bindings,
                    )
                except Exception as error:
                    result.add_failure(_error_code(error))
                    continue
                if added or removed:
                    result.threads_changed += 1
                result.labels_added += added
                result.labels_removed += removed
                result.obsolete_processed_assignments_removed += obsolete
            if GmailLabelKey.PROCESSED in initial_bindings:
                result.obsolete_definitions_to_delete += 1
            continue

        cached_factory = _cached_mailbox_factory(mailbox)
        for thread_id in thread_ids:
            result.threads_inspected += 1
            sync = enqueue_thread_label_sync(
                db,
                agency_id=connection.agency_id,
                gmail_connection_id=connection.id,
                gmail_thread_id=thread_id,
                record_event=False,
            )
            db.commit()
            assert sync is not None
            claim = claim_label_sync(db, sync_id=sync.id)
            if claim is None:
                result.add_failure("GMAIL_LABEL_SYNC_BUSY")
                continue
            try:
                reconciled = process_claimed_label_sync(
                    db,
                    claim,
                    mailbox_factory=cached_factory,
                )
            except Exception as error:
                db.rollback()
                result.add_failure(_error_code(error))
                continue
            if reconciled.status is not GmailLabelSyncStatus.APPLIED:
                result.add_failure(f"GMAIL_LABEL_SYNC_{reconciled.status.value}")
                continue
            if reconciled.added or reconciled.removed:
                result.threads_changed += 1
            result.labels_added += reconciled.added
            result.labels_removed += reconciled.removed
            result.obsolete_processed_assignments_removed += reconciled.obsolete_processed_removed

        try:
            final_bindings = _listed_managed_labels(mailbox)
        except Exception as error:
            result.add_failure(_error_code(error))
            final_bindings = initial_bindings
        result.label_definitions_created += len(
            (set(final_bindings) & set(MANAGED_LABEL_NAMES)) - set(initial_bindings)
        )
        _delete_obsolete_definition(
            db,
            mailbox,
            connection,
            thread_ids,
            final_bindings,
            result,
            connection_failed=result.failures > connection_failures_before,
        )
        record_audit_event(
            db,
            agency_id=connection.agency_id,
            event_type="GMAIL_MANAGED_LABEL_MIGRATION_COMPLETED",
            description="Managed Gmail labels migrated to the live thread model",
            metadata={
                "connection_id": connection.id,
                "threads_inspected": len(thread_ids),
                "failures": result.failures - connection_failures_before,
            },
        )
        db.commit()

    return result
