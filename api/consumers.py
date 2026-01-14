from channels.generic.websocket import AsyncJsonWebsocketConsumer
import logging

logger = logging.getLogger(__name__)

class EmailConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        
        if not user or user.is_anonymous:
            logger.warning(f"[WebSocket] Connection rejected: user is anonymous")
            print(f"[WebSocket] Connection rejected: user is anonymous")
            await self.close(code=4001)  # Custom code for unauthorized
            return
        
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"[WebSocket] User {user.id} ({user.username}) connected")
        print(f"[WebSocket] User {user.id} ({user.username}) connected to group {self.group_name}")

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(f"[WebSocket] User disconnected from group {self.group_name}, code: {code}")
            print(f"[WebSocket] User disconnected from group {self.group_name}, code: {code}")

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
