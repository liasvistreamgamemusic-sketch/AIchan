"""Discord Bot。指定チャンネル/DMの発言を Orchestrator へ流し、応答を返す。

別スレッドで asyncio ループを回す。記憶DBは共有(source=discord)。discord.py が
無い / 未設定なら起動しない(graceful)。
"""
from __future__ import annotations

import asyncio
import logging
import threading

from ..settings import DiscordConfig

log = logging.getLogger(__name__)


class DiscordBot:
    def __init__(self, cfg: DiscordConfig, orchestrator) -> None:
        self.cfg = cfg
        self.orch = orchestrator
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None

    def start(self) -> None:
        if not self.cfg.enabled or not self.cfg.token:
            return
        try:
            import discord  # noqa: F401
        except ImportError:
            log.warning("discord.py 不在 → Discord連携無効")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="discord")
        self._thread.start()

    def stop(self) -> None:
        if self._loop and self._client:
            asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)

    def _run(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready() -> None:  # noqa: ANN202
            log.info("Discord ready as %s", client.user)

        @client.event
        async def on_message(message) -> None:  # noqa: ANN001
            if message.author == client.user:
                return
            allowed = self.cfg.channel_ids
            is_dm = message.guild is None
            if allowed and not is_dm and message.channel.id not in allowed:
                return
            text = message.content.strip()
            if not text:
                return

            loop = asyncio.get_running_loop()

            def reply_cb(reply) -> None:
                # オーケストレータのワーカースレッドから呼ばれる → ループへ投げる
                asyncio.run_coroutine_threadsafe(
                    message.channel.send(reply.speech), loop
                )

            self.orch.handle_discord(text, reply_cb=reply_cb)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(client.start(self.cfg.token))
        except Exception as e:
            log.warning("Discord 起動失敗: %s", e)
