import json
from celery import shared_task
from google.cloud import pubsub_v1
from django.conf import settings
from .gmail_services import handle_gmail_history
from google.api_core.exceptions import DeadlineExceeded
from google.auth.exceptions import DefaultCredentialsError

@shared_task
def renew_gmail_watches():
    from .gmail_services import renew_all_watches
    renew_all_watches()

@shared_task
def pull_pubsub_messages():
    try:
        subscriber = pubsub_v1.SubscriberClient()
    except DefaultCredentialsError:
        print("[PubSub Pull] Google Cloud credentials not found. Skipping Pub/Sub pull.")
        print("[PubSub Pull] To enable Pub/Sub, configure Application Default Credentials:")
        print("[PubSub Pull]   gcloud auth application-default login")
        print("[PubSub Pull]   OR set GOOGLE_APPLICATION_CREDENTIALS environment variable")
        return
    
    try:
        sub_path = subscriber.subscription_path(
            settings.GCLOUD_PROJECT,
            settings.PUBSUB_SUBSCRIPTION_ID
        )
    except (AttributeError, ValueError) as e:
        print(f"[PubSub Pull] Invalid configuration: {e}. Skipping Pub/Sub pull.")
        return
    
    try:
        response = subscriber.pull(
            request={"subscription": sub_path, "max_messages": 10}
        )
    except DeadlineExceeded:
        print("[PubSub Pull] No messages before timeout")
        return
    except Exception as e:
        print(f"[PubSub Pull] Error pulling messages: {e}")
        return

    ack_ids = []
    for received in response.received_messages:
        payload = json.loads(received.message.data)
        handle_gmail_history(
            email_address=payload["emailAddress"],
            new_history_id=payload["historyId"]
        )
        ack_ids.append(received.ack_id)

    if ack_ids:
        subscriber.acknowledge(
            request={"subscription": sub_path, "ack_ids": ack_ids}
        )
        print(f"[PubSub Pull] Acknowledged {len(ack_ids)} messages")
