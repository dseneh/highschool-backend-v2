"""
Background tasks for transaction processing and payment summary recalculation
Requires Celery or similar task queue system
"""

from datetime import datetime, timezone
import csv
import io
import json
import logging
import threading
from typing import Dict, Any

from django.core.cache import cache
from django.core.mail import EmailMessage
from django.conf import settings
from django.db.models import QuerySet

# Uncomment if using Celery
# from celery import shared_task

from finance.models import Transaction
from finance.serializers import TransactionStudentSerializer
from users.models import User

logger = logging.getLogger(__name__)


# @shared_task(bind=True)
def export_transactions_task(
    self,
    task_id: str,
    query_params: Dict[str, Any],
    user_id: int,
    export_format: str = "json",
):
    """
    Background task to export large transaction datasets

    Args:
        task_id: Unique identifier for this export task
        query_params: Django query parameters to reconstruct the queryset
        user_id: ID of the user who requested the export
        export_format: Format for export (json, csv, excel)
    """

    try:
        # Update task status
        update_task_status(task_id, "processing", progress=0)

        # Reconstruct the queryset from query parameters
        transactions = reconstruct_transaction_queryset(query_params)
        total_count = transactions.count()

        # Process in chunks to avoid memory issues
        chunk_size = 1000
        processed = 0
        export_data = []

        for i in range(0, total_count, chunk_size):
            chunk = transactions[i : i + chunk_size]

            if export_format.lower() == "csv":
                chunk_data = serialize_transactions_for_csv(chunk)
            else:
                # Default to JSON serialization
                serializer = TransactionStudentSerializer(chunk, many=True)
                chunk_data = serializer.data

            export_data.extend(chunk_data)
            processed += len(chunk)

            # Update progress
            progress = (processed / total_count) * 100
            update_task_status(task_id, "processing", progress=progress)

            # Allow task cancellation
            if is_task_cancelled(task_id):
                update_task_status(task_id, "cancelled")
                return

        # Generate the export file
        file_content, filename = generate_export_file(export_data, export_format)

        # Save file and update task with download link
        file_url = save_export_file(file_content, filename, user_id)

        # Send notification email
        user = User.objects.get(id=user_id)
        send_export_notification(user, filename, file_url, total_count)

        # Mark task as completed
        update_task_status(
            task_id, "completed", progress=100, download_url=file_url, filename=filename
        )

    except Exception as e:
        # Handle errors
        update_task_status(task_id, "failed", error=str(e))
        # Log the error
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Export task {task_id} failed: {str(e)}")


def update_task_status(task_id: str, status: str, progress: int = 0, **kwargs):
    """Update task status in cache"""
    task_data = cache.get(f"export_task_{task_id}", {})
    task_data.update(
        {
            "status": status,
            "progress": progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
    )
    cache.set(f"export_task_{task_id}", task_data, timeout=3600)


def is_task_cancelled(task_id: str) -> bool:
    """Check if task has been cancelled"""
    task_data = cache.get(f"export_task_{task_id}", {})
    return task_data.get("status") == "cancelled"


def reconstruct_transaction_queryset(query_params: Dict[str, Any]) -> QuerySet:
    """Reconstruct the transaction queryset from stored parameters"""
    from django.db.models import Q
    from common.filter import get_transaction_queryparams

    school_id = query_params.get("school_id")

    # Base filter for school
    f = (
        Q(account__school__id=school_id)
        | Q(account__school__id_number=school_id)
        | Q(account__school__workspace=school_id)
    )

    transactions = Transaction.objects.filter(f).select_related(
        "student",
        "academic_year",
        "account",
        "type",
        "payment_method",
    )

    # Apply ordering
    ordering = query_params.get("ordering", "-updated_at")
    transactions = transactions.order_by(ordering)

    # Apply additional filters
    filter_params = query_params.get("filters", {})
    query = get_transaction_queryparams(filter_params)
    if query:
        transactions = transactions.filter(query)

    return transactions


def serialize_transactions_for_csv(transactions: QuerySet) -> list:
    """Convert transactions to CSV-friendly format"""
    csv_data = []
    for transaction in transactions:
        csv_data.append(
            {
                "ID": transaction.id,
                "Transaction ID": transaction.transaction_id,
                "Student": (
                    transaction.student.get_full_name() if transaction.student else ""
                ),
                "Student ID": (
                    transaction.student.id_number if transaction.student else ""
                ),
                "Account": transaction.account.name,
                "Type": transaction.type.name,
                "Amount": float(transaction.amount),
                "Status": transaction.status,
                "Date": transaction.date.isoformat() if transaction.date else "",
                "Payment Method": (
                    transaction.payment_method.name
                    if transaction.payment_method
                    else ""
                ),
                "Reference": transaction.reference or "",
                "Description": transaction.description or "",
                "Notes": transaction.notes or "",
                "Academic Year": (
                    transaction.academic_year.name if transaction.academic_year else ""
                ),
                "Created At": transaction.created_at.isoformat(),
                "Updated At": transaction.updated_at.isoformat(),
            }
        )
    return csv_data


def generate_export_file(data: list, export_format: str) -> tuple:
    """Generate export file content and filename"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if export_format.lower() == "csv":
        # Generate CSV
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        filename = f"transactions_export_{timestamp}.csv"
        return output.getvalue(), filename

    elif export_format.lower() == "json":
        # Generate JSON
        json_content = json.dumps(data, indent=2, default=str)
        filename = f"transactions_export_{timestamp}.json"
        return json_content, filename

    else:
        raise ValueError(f"Unsupported export format: {export_format}")


def save_export_file(content: str, filename: str, user_id: int) -> str:
    """Save export file and return download URL"""
    # This is a simplified example - you'd typically use cloud storage
    import os
    from django.conf import settings

    # Create exports directory if it doesn't exist
    exports_dir = os.path.join(settings.MEDIA_ROOT, "exports", str(user_id))
    os.makedirs(exports_dir, exist_ok=True)

    # Save file
    file_path = os.path.join(exports_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Return download URL
    return f"{settings.MEDIA_URL}exports/{user_id}/{filename}"


def send_export_notification(
    user: User, filename: str, file_url: str, record_count: int
):
    """Send email notification when export is complete"""
    subject = f"Transaction Export Complete - {record_count} records"
    message = f"""
    Hello {user.get_full_name()},
    
    Your transaction export has been completed successfully.
    
    Details:
    - File: {filename}
    - Records: {record_count:,}
    - Download: {file_url}
    
    The file will be available for download for 24 hours.
    
    Best regards,
    Finance Team
    """

    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.send()


# @shared_task
def cleanup_expired_exports():
    """Periodic task to clean up expired export files"""
    import os
    import time
    from django.conf import settings

    exports_dir = os.path.join(settings.MEDIA_ROOT, "exports")
    if not os.path.exists(exports_dir):
        return

    # Remove files older than 24 hours
    cutoff_time = time.time() - (24 * 60 * 60)

    for root, dirs, files in os.walk(exports_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.getctime(file_path) < cutoff_time:
                os.remove(file_path)


# ========================================
# PAYMENT SUMMARY RECALCULATION TASKS
# ========================================


def recalc_payment_summaries_async(academic_year_id: str):
    """
    Queue asynchronous task to recalculate payment summaries for all enrollments
    in an academic year. Uses threading (can be upgraded to Celery later).

    Args:
        academic_year_id: Academic year ID to recalculate summaries for
    """

    def background_work():
        try:
            logger.info(
                f"Background thread started: recalculating payment summaries "
                f"for academic year {academic_year_id}"
            )
            recalc_payment_summaries_for_academic_year(academic_year_id)
            logger.info(
                f"Background thread completed: payment summaries recalculated "
                f"for academic year {academic_year_id}"
            )
        except Exception as e:
            logger.error(
                f"Error in background payment summary recalculation for "
                f"academic year {academic_year_id}: {e}",
                exc_info=True,
            )

    # Start background thread
    thread = threading.Thread(target=background_work)
    thread.daemon = True
    thread.start()
    logger.info(
        f"Started background thread to recalculate payment summaries "
        f"for academic year {academic_year_id}"
    )


def recalc_payment_summaries_for_academic_year(academic_year_id: str):
    """
    Recalculate payment summaries for all active enrollments in an academic year.
    Processes in batches to avoid memory issues.

    Args:
        academic_year_id: Academic year ID
    """
    from students.models import Enrollment
    from finance.utils import calculate_student_payment_summary
    from academics.models import AcademicYear

    try:
        academic_year = AcademicYear.objects.get(id=academic_year_id)
    except AcademicYear.DoesNotExist:
        logger.error(f"Academic year {academic_year_id} not found")
        return

    # Get all active enrollments for this academic year
    enrollments = Enrollment.objects.filter(
        academic_year=academic_year, status="active"
    ).select_related("student", "academic_year")

    total_count = enrollments.count()
    logger.info(
        f"Starting payment summary recalculation for {total_count} enrollments "
        f"in academic year {academic_year.name}"
    )

    if total_count == 0:
        logger.info("No enrollments to process")
        return

    # Process in batches to avoid memory issues
    batch_size = 100
    processed = 0
    errors = 0

    for i in range(0, total_count, batch_size):
        batch = enrollments[i : i + batch_size]

        for enrollment in batch:
            try:
                calculate_student_payment_summary(enrollment, academic_year)
                processed += 1
            except Exception as e:
                errors += 1
                logger.warning(
                    f"Failed to calculate payment summary for enrollment "
                    f"{enrollment.id}: {e}"
                )

        # Log progress every batch
        if (i + batch_size) % (batch_size * 10) == 0 or (i + batch_size) >= total_count:
            logger.info(
                f"Payment summary recalculation progress: {processed}/{total_count} "
                f"processed, {errors} errors"
            )

    logger.info(
        f"Completed payment summary recalculation for academic year "
        f"{academic_year.name}: {processed} processed, {errors} errors"
    )
