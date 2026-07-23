from django.db import migrations, models


def set_action_outcomes(apps, schema_editor):
    DisciplinaryActionType = apps.get_model("students", "DisciplinaryActionType")

    code_to_outcome = {
        # Curated defaults
        "verbal-warning": "warning",
        "written-warning": "warning",
        "parent-guardian-notification": "warning",
        "behavior-reflection-assignment": "warning",
        "counseling-referral": "counseling",
        "lunch-detention": "detention",
        "after-school-detention": "detention",
        "loss-of-privileges": "detention",
        "classroom-removal-temporary": "detention",
        "behavior-contract": "probation",
        "in-school-suspension": "suspension",
        "out-of-school-suspension-short": "suspension",
        "out-of-school-suspension-extended": "suspension",
        "restorative-conference": "no_action",
        "academic-integrity-violation-record": "warning",
        "disciplinary-probation": "probation",
        "emergency-safety-removal": "suspension",
        "enrollment-withdrawal-recommendation": "withdrawal",
        "final-enrollment-withdrawal": "withdrawal",
        "action-reversal-cleared-record": "no_action",
        # Legacy defaults still present in some tenants
        "detention": "detention",
        "in-school-suspension": "suspension",
        "out-school-suspension": "suspension",
        "expulsion": "expulsion",
        "expulsion-recommendation": "expulsion",
        "disciplinary-probation": "probation",
        "counseling-session": "counseling",
        "counseling-referral": "counseling",
        "no-disciplinary-action": "no_action",
        "action-overturned": "no_action",
        "recommended-transfer": "withdrawal",
    }

    for action in DisciplinaryActionType.objects.all():
        outcome = code_to_outcome.get(action.code)
        if not outcome:
            if action.category in {"suspension", "severe"}:
                outcome = "suspension"
            elif action.category == "supportive":
                outcome = "counseling"
            elif action.category == "administrative":
                outcome = "no_action"
            else:
                outcome = "warning"

        action.action_outcome = outcome

        # Keep non time-bound actions constrained to same-day defaults.
        if outcome not in {"detention", "suspension", "expulsion", "probation"}:
            action.default_duration_days = 1
            action.max_duration_days = 1
        elif action.max_duration_days < action.default_duration_days:
            action.max_duration_days = action.default_duration_days

        action.save(update_fields=["action_outcome", "default_duration_days", "max_duration_days"])


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0015_curated_default_disciplinary_action_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="disciplinaryactiontype",
            name="action_outcome",
            field=models.CharField(
                choices=[
                    ("no_action", "No Action"),
                    ("warning", "Warning"),
                    ("detention", "Detention"),
                    ("suspension", "Suspension"),
                    ("expulsion", "Expulsion"),
                    ("probation", "Probation"),
                    ("counseling", "Counseling"),
                    ("withdrawal", "Withdrawal"),
                ],
                default="warning",
                max_length=24,
            ),
        ),
        migrations.RunPython(set_action_outcomes, migrations.RunPython.noop),
    ]
