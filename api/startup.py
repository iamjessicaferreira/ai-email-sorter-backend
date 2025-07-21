from django_celery_beat.models import PeriodicTask, IntervalSchedule
import json

def setup_watch_renewal():
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1, period=IntervalSchedule.DAYS
    )
    PeriodicTask.objects.update_or_create(
        name="renew-gmail-watches",
        defaults={
            "interval": schedule,
            "task": "api.tasks.renew_gmail_watches",
            "args": json.dumps([]),
        }
    )
