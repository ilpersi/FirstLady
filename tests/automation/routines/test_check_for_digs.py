"""Tests for CheckForDigsRoutine - a TimeCheckRoutine gated on
DISCORD_WEBHOOK_URL, using an async DiscordNotifier internally."""
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest

from src.automation.routines.checkForDigs import CheckForDigsRoutine


def _make_routine(is_home=True):
    automation = SimpleNamespace(game_state={"is_home": is_home})
    routine = CheckForDigsRoutine("device1", interval=999, automation=automation)
    return routine, automation


class TestDisabledWithoutWebhook:
    def test_disabled_when_no_webhook_env_var(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        routine, _ = _make_routine()
        assert routine.is_enabled is False

    def test_execute_short_circuits_true_when_disabled(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        routine, _ = _make_routine()
        with patch("src.automation.routines.checkForDigs.find_and_tap_template") as mock_tap:
            assert routine._execute() is True
        mock_tap.assert_not_called()


class TestEnabledWithWebhook:
    def test_enabled_when_webhook_env_var_set(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
        routine, _ = _make_routine()
        assert routine.is_enabled is True

    def test_dig_found_sends_notification_and_clears_is_home(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
        routine, automation = _make_routine(is_home=True)

        with patch("src.automation.routines.checkForDigs.find_and_tap_template", return_value=True) as mock_tap, \
             patch.object(routine.discord, "send_notification", new_callable=AsyncMock, return_value=True) as mock_send:
            result = routine._execute()

        assert result is True
        mock_tap.assert_called_once()
        assert mock_tap.call_args[0][:2] == ("device1", "dig")
        assert automation.game_state["is_home"] is False
        mock_send.assert_awaited_once()
        # First positional arg is the dig content string, second is a discord.Embed.
        args, kwargs = mock_send.call_args
        assert isinstance(args[0], str) and len(args[0]) > 0
        assert kwargs.get("username")

    def test_dig_not_found_returns_true_without_touching_discord(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
        routine, automation = _make_routine(is_home=True)

        with patch("src.automation.routines.checkForDigs.find_and_tap_template", return_value=False) as mock_tap, \
             patch.object(routine.discord, "send_notification", new_callable=AsyncMock) as mock_send:
            result = routine._execute()

        assert result is True
        mock_tap.assert_called_once()
        mock_send.assert_not_awaited()
        # is_home is untouched on the "nothing found" path.
        assert automation.game_state["is_home"] is True

    @pytest.mark.asyncio
    async def test_send_notification_builds_embed_from_config(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
        routine, _ = _make_routine()

        with patch.object(routine.discord, "send_notification", new_callable=AsyncMock, return_value=True) as mock_send:
            result = await routine.send_notification()

        assert result is True
        mock_send.assert_awaited_once()
        args, kwargs = mock_send.call_args
        content, embed = args[0], args[1]
        assert isinstance(content, str)
        assert embed.fields  # embed_title/embed_value were added as a field
        assert "username" in kwargs

    @pytest.mark.asyncio
    async def test_send_notification_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        routine, _ = _make_routine()
        with patch.object(routine.discord, "send_notification", new_callable=AsyncMock) as mock_send:
            result = await routine.send_notification()
        assert result is True
        mock_send.assert_not_awaited()
