"""Tests for src.core.discord_bot.DiscordNotifier.

send_notification is a coroutine built on discord.py's Webhook + a raw
aiohttp.ClientSession used as an async context manager. Direct send-path
tests mock both: discord.Webhook.from_url is patched on the class as it's
bound inside discord_bot (`from discord import Webhook, Embed`), and
aiohttp.ClientSession is replaced with a fake async-context-manager class so
no real network I/O ever happens.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core import discord_bot
from src.core.discord_bot import DiscordNotifier


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestInit:
    def test_webhook_url_read_from_env_var(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook/123")
        notifier = DiscordNotifier()
        assert notifier.webhook_url == "https://discord.example/webhook/123"

    def test_webhook_url_falsy_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        notifier = DiscordNotifier()
        assert not notifier.webhook_url


class TestSendNotificationNoWebhook:
    @pytest.mark.asyncio
    async def test_returns_false_without_attempting_network_call(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        notifier = DiscordNotifier()
        assert not notifier.webhook_url

        # Deliberately do NOT patch Webhook.from_url / aiohttp.ClientSession:
        # if the early-return short circuit is broken, this would attempt a
        # real network call and either hang or raise.
        result = await notifier.send_notification("hello")

        assert result is False


class TestSendNotificationSendPath:
    def _patch_session(self, monkeypatch):
        monkeypatch.setattr(discord_bot.aiohttp, "ClientSession", lambda: _FakeSession())

    @pytest.mark.asyncio
    async def test_success_returns_true_and_sends_content_and_username(self, monkeypatch):
        self._patch_session(monkeypatch)
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock()
        monkeypatch.setattr(discord_bot.Webhook, "from_url", lambda url, session: fake_webhook)

        notifier = DiscordNotifier()
        notifier.webhook_url = "https://discord.example/webhook/123"

        result = await notifier.send_notification("hello world", username="Bot Name")

        assert result is True
        fake_webhook.send.assert_awaited_once_with(content="hello world", embeds=None, username="Bot Name")

    @pytest.mark.asyncio
    async def test_single_embed_object_is_wrapped_in_a_list(self, monkeypatch):
        self._patch_session(monkeypatch)
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock()
        monkeypatch.setattr(discord_bot.Webhook, "from_url", lambda url, session: fake_webhook)

        notifier = DiscordNotifier()
        notifier.webhook_url = "https://discord.example/webhook/123"

        single_embed = discord_bot.Embed(title="t")
        result = await notifier.send_notification("hello", embeds=single_embed)

        assert result is True
        sent_kwargs = fake_webhook.send.await_args.kwargs
        assert sent_kwargs["embeds"] == [single_embed]

    @pytest.mark.asyncio
    async def test_list_of_embeds_passed_through_unchanged(self, monkeypatch):
        self._patch_session(monkeypatch)
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock()
        monkeypatch.setattr(discord_bot.Webhook, "from_url", lambda url, session: fake_webhook)

        notifier = DiscordNotifier()
        notifier.webhook_url = "https://discord.example/webhook/123"

        embeds_list = [discord_bot.Embed(title="a"), discord_bot.Embed(title="b")]
        await notifier.send_notification("hello", embeds=embeds_list)

        sent_kwargs = fake_webhook.send.await_args.kwargs
        assert sent_kwargs["embeds"] is embeds_list

    @pytest.mark.asyncio
    async def test_falsy_embeds_normalized_to_none(self, monkeypatch):
        self._patch_session(monkeypatch)
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock()
        monkeypatch.setattr(discord_bot.Webhook, "from_url", lambda url, session: fake_webhook)

        notifier = DiscordNotifier()
        notifier.webhook_url = "https://discord.example/webhook/123"

        await notifier.send_notification("hello", embeds=None)

        sent_kwargs = fake_webhook.send.await_args.kwargs
        assert sent_kwargs["embeds"] is None

    @pytest.mark.asyncio
    async def test_send_exception_is_caught_and_returns_false(self, monkeypatch):
        self._patch_session(monkeypatch)
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock(side_effect=RuntimeError("network exploded"))
        monkeypatch.setattr(discord_bot.Webhook, "from_url", lambda url, session: fake_webhook)

        notifier = DiscordNotifier()
        notifier.webhook_url = "https://discord.example/webhook/123"

        result = await notifier.send_notification("hello")

        assert result is False

    @pytest.mark.asyncio
    async def test_from_url_exception_is_caught_and_returns_false(self, monkeypatch):
        self._patch_session(monkeypatch)

        def raise_from_url(url, session):
            raise ValueError("bad webhook url")

        monkeypatch.setattr(discord_bot.Webhook, "from_url", raise_from_url)

        notifier = DiscordNotifier()
        notifier.webhook_url = "not-a-real-url"

        result = await notifier.send_notification("hello")

        assert result is False
