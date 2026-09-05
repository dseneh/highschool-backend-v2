from django.conf import settings
from django.core.mail import send_mail


def send_application_verification_email(*, application, code):
    send_mail(
        subject=f"Verify your application to {application.cycle.name}",
        message=(
            f"Your EzySchool verification code is {code}. "
            "It expires in 15 minutes. If you did not begin this application, ignore this message."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[application.applicant_email],
        fail_silently=False,
    )
