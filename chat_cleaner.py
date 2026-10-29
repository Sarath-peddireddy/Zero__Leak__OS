"""
ZeroLeak OS - Wipe a Telegram chat's message history (the /clear command).

The Bot API cannot list a chat's history, so we send a tiny probe message to
learn the newest message_id, then delete every id from the last cleared point
up to it, 100 at a time. Telegram's rules decide what can go:
  * private chats: the bot can delete both sides of the conversation;
  * groups: the bot can delete its own messages, and everyone's only if it is
    an admin with the "Delete messages" right;
  * either way, only messages less than 48 hours old.
Ids that no longer exist are skipped by Telegram. If a batch contains a message
the bot may not delete, that batch is retried one message at a time.
"""

import asyncio
import logging

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, RetryAfter, TelegramError

logger = logging.getLogger("zeroleak.cleaner")

BATCH = 100  # deleteMessages accepts at most 100 ids

# (bot id, chat id, can delete everyone's messages) -> highest id already cleared
_cleared_upto: dict[tuple[int, int, bool], int] = {}


async def can_delete_all(bot: Bot, chat_id: int) -> bool:
    """True if the bot is a group admin allowed to delete other people's messages."""
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
    except TelegramError:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    return member.status == ChatMemberStatus.ADMINISTRATOR and bool(getattr(member, "can_delete_messages", False))


async def _call(coro_factory):
    """Run one API call, waiting out a flood limit once."""
    try:
        return await coro_factory()
    except RetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 1)) + 1)
        return await coro_factory()


async def wipe_chat(bot: Bot, chat_id: int, delete_all: bool = True) -> int:
    """Delete the bot's deletable history in `chat_id`. Returns the number of single deletes needed."""
    probe = await bot.send_message(chat_id, "🧹")
    top = probe.message_id
    key = (bot.id, chat_id, delete_all)
    singles = 0
    for start in range(_cleared_upto.get(key, 0) + 1, top + 1, BATCH):
        ids = list(range(start, min(start + BATCH, top + 1)))
        try:
            await _call(lambda: bot.delete_messages(chat_id, ids))
        except BadRequest:  # at least one message here is not deletable by this bot
            for mid in ids:
                try:
                    if await _call(lambda: bot.delete_message(chat_id, mid)):
                        singles += 1
                except TelegramError:
                    pass
        except TelegramError:
            logger.warning("Clearing chat %s stopped at id %s", chat_id, start, exc_info=True)
            break
    else:
        _cleared_upto[key] = top
    logger.info("Cleared chat %s with @%s up to id %s", chat_id, bot.username, top)
    return singles
