# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A04 — Refactoring snippets (good / medium / bad).

Domain: Extracting services, decomposing god classes, improving separation of concerns.
"""

GOOD: dict = {
    "eval_score": 8.8,
    "output": "Extracted NotificationService from UserController. 3 notification channels (email, SMS, push) behind a common interface.",
    "code": '''\
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
import logging

logger = logging.getLogger(__name__)


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


@dataclass(frozen=True)
class Notification:
    recipient: str
    subject: str
    body: str
    channel: Channel


class NotificationSender(ABC):
    """Abstract notification sender — one implementation per channel."""

    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        ...


class EmailSender(NotificationSender):
    def __init__(self, smtp_client):
        self._smtp = smtp_client

    async def send(self, notification: Notification) -> bool:
        await self._smtp.send_message(
            to=notification.recipient,
            subject=notification.subject,
            body=notification.body,
        )
        logger.info("Email sent to %s: %s", notification.recipient, notification.subject)
        return True


class SMSSender(NotificationSender):
    def __init__(self, sms_gateway):
        self._gw = sms_gateway

    async def send(self, notification: Notification) -> bool:
        await self._gw.send(to=notification.recipient, message=notification.body)
        logger.info("SMS sent to %s", notification.recipient)
        return True


class NotificationService:
    """Dispatches notifications through configured channels.

    Extracted from UserController to decouple user management from
    notification delivery. Each channel is independently testable.
    """

    def __init__(self, senders: dict[Channel, NotificationSender]) -> None:
        self._senders = senders

    async def notify(self, notification: Notification) -> bool:
        sender = self._senders.get(notification.channel)
        if not sender:
            logger.warning("No sender configured for channel %s", notification.channel)
            return False
        try:
            return await sender.send(notification)
        except Exception:
            logger.exception("Failed to send %s notification", notification.channel)
            return False

    async def notify_all_channels(self, recipient: str, subject: str, body: str) -> dict[Channel, bool]:
        results = {}
        for channel, sender in self._senders.items():
            n = Notification(recipient=recipient, subject=subject, body=body, channel=channel)
            results[channel] = await self.notify(n)
        return results
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Moved notification methods out of UserController.",
    "code": '''\
class NotificationService:
    def __init__(self, email_client, sms_client):
        self.email = email_client
        self.sms = sms_client

    def send_email(self, to, subject, body):
        self.email.send(to=to, subject=subject, body=body)

    def send_sms(self, to, message):
        self.sms.send(to=to, message=message)

    def notify_user(self, user, message):
        if user.email:
            self.send_email(user.email, "Notification", message)
        if user.phone:
            self.send_sms(user.phone, message)
''',
}

BAD: dict = {
    "eval_score": 3.0,
    "output": "split controller",
    "code": '''\
# just moved the methods, still tightly coupled
class NotifHelper:
    def do_notify(self, user_controller, user_id, msg):
        user = user_controller.get_user(user_id)
        user_controller.email_client.send(user.email, msg)
        user_controller.sms_client.send(user.phone, msg)
''',
}
