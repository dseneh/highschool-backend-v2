from django.db import migrations, models
import django.db.models.deletion


def _resolve_year(academic_year_model, posting_date):
    year = (
        academic_year_model.objects.filter(
            start_date__lte=posting_date,
            end_date__gte=posting_date,
        )
        .order_by("-start_date")
        .first()
    )
    if year:
        return year

    current = academic_year_model.objects.filter(current=True).first()
    if current:
        return current

    return academic_year_model.objects.order_by("-start_date").first()


def forwards_populate_academic_year(apps, schema_editor):
    AcademicYear = apps.get_model("academics", "AcademicYear")
    JournalEntry = apps.get_model("accounting", "AccountingJournalEntry")
    PayrollBatch = apps.get_model("accounting", "AccountingPayrollPostingBatch")

    for entry in JournalEntry.objects.all().iterator():
        year = _resolve_year(AcademicYear, entry.posting_date)
        if year is None:
            raise RuntimeError("Cannot migrate journal entries: no AcademicYear records exist")
        entry.academic_year_id = year.id
        entry.save(update_fields=["academic_year"])

    for batch in PayrollBatch.objects.all().iterator():
        year = _resolve_year(AcademicYear, batch.posting_date)
        if year is None:
            raise RuntimeError("Cannot migrate payroll posting batches: no AcademicYear records exist")
        batch.academic_year_id = year.id
        batch.save(update_fields=["academic_year"])


def backwards_noop(apps, schema_editor):
    # Backward data restoration is intentionally omitted.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0011_rename_school_cale_event_t_2908fb_idx_calendar_ev_event_t_3e18c8_idx_and_more"),
        ("accounting", "0004_rename_accounting__transac_type_status_idx_accounting__transac_b65014_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingjournalentry",
            name="academic_year",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounting_journal_entries",
                to="academics.academicyear",
            ),
        ),
        migrations.AddField(
            model_name="accountingpayrollpostingbatch",
            name="academic_year",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="academics.academicyear",
            ),
        ),
        migrations.RunPython(forwards_populate_academic_year, backwards_noop),
        migrations.AlterField(
            model_name="accountingjournalentry",
            name="academic_year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounting_journal_entries",
                to="academics.academicyear",
            ),
        ),
        migrations.AlterField(
            model_name="accountingpayrollpostingbatch",
            name="academic_year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="academics.academicyear",
            ),
        ),
        migrations.RemoveField(
            model_name="accountingjournalentry",
            name="fiscal_period",
        ),
        migrations.RemoveField(
            model_name="accountingpayrollpostingbatch",
            name="fiscal_period",
        ),
        migrations.DeleteModel(
            name="AccountingFiscalPeriod",
        ),
    ]
