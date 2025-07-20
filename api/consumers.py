 
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer

class EmailConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous:
            return await self.close()
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # this method name must match the "type" you send in group_send
    async def new_email(self, event):
        await self.send_json({
            "id":          event["id"],
            "subject":     event["subject"],
            "body":        event["body"],
            "summary":     event["summary"],
            "received_at": event["received_at"],
            "category":    event["category"],
            "account":     event["account"],
        })