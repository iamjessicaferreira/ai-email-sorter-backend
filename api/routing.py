from django.urls import re_path
from .consumers import EmailConsumer

websocket_urlpatterns = [
    re_path(r"ws/emails/$", EmailConsumer.as_asgi()),
]
