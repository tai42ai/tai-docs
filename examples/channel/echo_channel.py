"""A minimal fictional channel: deliver a question to a chat API over HTTPS.

``deliver`` sends the question and its answer path to the medium and returns
``None``; ``notify`` sends a fire-and-forget message the same way. Every failure
raises ``ChannelDeliveryError`` — neither method returns a bool, so an
undeliverable question cannot read as a silent pass while the asking tool blocks
on an answer that would never arrive. Credentials and the recipient come from the
environment, never from tool parameters, so no secret or address rides an
LLM-visible value.

A ``confirm``/``external`` question (Tier 1) is answered at the callback door
itself, so it ships the ``callback_url`` as a tappable link and needs no reply on
the medium. A ``text``/``select`` question (Tier 2) is answered by typing, so a
real channel would deliver a reply affordance and correlate the typed answer back
to the ``callback_url`` through its own inbound route; this example keeps to the
link shape for both.
"""

import os

import httpx
from tai_contract.app import tai_app
from tai_contract.channels import ChannelDelivery, ChannelDeliveryError, ChannelNotification


class EchoChannel:
    """Delivers to a fictional chat API as a message carrying an answer link."""

    async def _send(self, text: str, recipient: str | None, context: str) -> None:
        token = os.environ["CHANNEL_ECHO_TOKEN"]
        # The caller-requested recipient is validated against the operator
        # allowlist; an unset one falls back to the operator default. Both come
        # from the environment, never from a tool parameter.
        chat_id = self._resolve_recipient(recipient)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://chat.example.com/api/send",
                    json={"chat": chat_id, "text": text},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"echo channel delivery failed for {context}: {exc}") from exc

    @staticmethod
    def _resolve_recipient(recipient: str | None) -> str:
        if recipient is None:
            return os.environ["CHANNEL_ECHO_DEFAULT_RECIPIENT"]
        allowed = os.environ.get("CHANNEL_ECHO_ALLOWED_RECIPIENTS", "").split(",")
        if recipient not in {entry.strip() for entry in allowed if entry.strip()}:
            raise ChannelDeliveryError(
                f"recipient {recipient!r} is not on CHANNEL_ECHO_ALLOWED_RECIPIENTS; refusing to send"
            )
        return recipient

    async def deliver(self, delivery: ChannelDelivery) -> None:
        text = f"{delivery.question}\nAnswer here: {delivery.callback_url}"
        await self._send(text, delivery.recipient, f"interaction {delivery.interaction_id}")

    async def notify(self, notification: ChannelNotification) -> None:
        await self._send(notification.message, notification.recipient, "notification")


tai_app.channels.register("echo", EchoChannel())
