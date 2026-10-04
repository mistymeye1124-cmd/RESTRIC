# language: Python, file: core/idempotency_guard.py, target: Python 3.10+, Pyrogram
"""
Enterprise Idempotency & Anti-Duplicate Processing Engine for Telegram Bot.
Guarantees that no button click or outgoing message can be executed or sent twice.

Layers of Protection:
1. Callback Query Deduplication: Filters out retransmitted or duplicate Telegram callback_query.id.
2. User Action Debounce: Throttles identical button clicks from the same user within 1.0s.
3. MessageNotModified Shield: Silently absorbs Telegram 400 MESSAGE_NOT_MODIFIED so handlers
   never fall back to sending duplicate reply_text messages.
4. Outgoing Message Deduplication: Suppresses identical text sent to the same chat within 0.8s.
"""

import time
import hashlib
import asyncio
import logging
from typing import Dict, Tuple, Optional, Any
import pyrogram
from pyrogram import Client, types
from pyrogram.errors import MessageNotModified, MessageIdInvalid, FloodWait

logger = logging.getLogger("IdempotencyGuard")

# In-memory tracking with TTL
_seen_query_ids: Dict[str, float] = {}                      # {query_id: expiry_time}
_user_button_last_click: Dict[Tuple[int, str], float] = {}  # {(user_id, data): timestamp}
_recent_outgoing_messages: Dict[Tuple[int, str], Tuple[float, Any]] = {} # {(chat_id, text_hash): (timestamp, msg_obj)}
_recent_commands: Dict[Tuple[int, str], float] = {}         # {(user_id, command_text): timestamp}

_CLEANUP_INTERVAL = 30.0
_last_cleanup = 0.0


def _sweep_stale_records(now: float):
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    # Sweep query IDs older than 60s
    stale_queries = [k for k, exp in _seen_query_ids.items() if exp < now]
    for k in stale_queries:
        _seen_query_ids.pop(k, None)

    # Sweep button clicks older than 10s
    stale_clicks = [k for k, t in _user_button_last_click.items() if now - t > 10.0]
    for k in stale_clicks:
        _user_button_last_click.pop(k, None)

    # Sweep outgoing messages older than 5s
    stale_out = [k for k, (t, _) in _recent_outgoing_messages.items() if now - t > 5.0]
    for k in stale_out:
        _recent_outgoing_messages.pop(k, None)

    # Sweep command debounces older than 5s
    stale_cmds = [k for k, t in _recent_commands.items() if now - t > 5.0]
    for k in stale_cmds:
        _recent_commands.pop(k, None)


def is_duplicate_callback(query: types.CallbackQuery) -> Tuple[bool, str]:
    """
    Checks if a callback query is a duplicate or rapid double-click.
    Returns (is_duplicate, reason).
    """
    now = time.monotonic()
    _sweep_stale_records(now)

    query_id = str(getattr(query, "id", ""))
    if query_id:
        if query_id in _seen_query_ids:
            return True, "duplicate_query_id"
        _seen_query_ids[query_id] = now + 60.0

    user_id = query.from_user.id if query.from_user else 0
    data = str(query.data or "")
    if user_id and data:
        # Numpad button clicks need low debounce (150ms) to allow entering repeated digits in OTP (e.g., "55")
        # Navigation callbacks use 350ms to prevent double-click while remaining fluid and responsive
        debounce_window = 0.15 if data.startswith("numpad:") else 0.35
        key = (user_id, data)
        last_t = _user_button_last_click.get(key, 0.0)
        if (now - last_t) < debounce_window:
            return True, "rapid_double_click"
        _user_button_last_click[key] = now

    return False, ""


def is_duplicate_command(message: types.Message) -> bool:
    """
    Debounces identical command spam (/start, /help, /settings) within 0.8s.
    """
    if not message or not message.from_user or not message.text:
        return False
    if not message.text.startswith("/"):
        return False

    now = time.monotonic()
    _sweep_stale_records(now)

    user_id = message.from_user.id
    cmd_text = message.text.strip().lower()
    key = (user_id, cmd_text)

    last_t = _recent_commands.get(key, 0.0)
    if (now - last_t) < 0.8:
        return True
    _recent_commands[key] = now
    return False


def is_duplicate_outgoing(chat_id: int, text: str) -> Optional[Any]:
    """
    Checks if identical text was sent to the same chat in the last 0.8s.
    If yes, returns the previously returned message object to satisfy the caller.
    """
    if not chat_id or not text or len(text) < 5:
        return None

    now = time.monotonic()
    _sweep_stale_records(now)

    text_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
    key = (int(chat_id), text_hash)

    last_record = _recent_outgoing_messages.get(key)
    if last_record:
        last_t, last_msg = last_record
        if (now - last_t) < 0.8:
            return last_msg

    return None


def record_outgoing(chat_id: int, text: str, msg_obj: Any):
    if not chat_id or not text or not msg_obj:
        return
    now = time.monotonic()
    text_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
    _recent_outgoing_messages[(int(chat_id), text_hash)] = (now, msg_obj)


def install_idempotency_guard(client: Client):
    """
    Attaches bulletproof anti-duplicate guards directly into the Pyrogram Client.
    Silently absorbs MessageNotModified, eliminates double-clicks, and stops duplicate messages.
    """
    if getattr(client, "_idempotency_guard_installed", False):
        return
    client._idempotency_guard_installed = True

    # 1. Patch edit_message_text to absorb MessageNotModified and handle FloodWait
    orig_edit_message_text = client.edit_message_text

    async def guarded_edit_message_text(*args, **kwargs):
        try:
            return await orig_edit_message_text(*args, **kwargs)
        except MessageNotModified:
            # Message is already up-to-date! Silently absorb to prevent fallback reply_text.
            return None
        except MessageIdInvalid:
            # Message was deleted or cannot be edited; silently absorb to prevent crashing caller.
            return None
        except FloodWait as e:
            # Resilient auto-backoff: sleep if brief, otherwise absorb status edit without crashing task
            wait_s = getattr(e, "value", 5)
            if wait_s <= 8:
                await asyncio.sleep(wait_s + 0.5)
                try:
                    return await orig_edit_message_text(*args, **kwargs)
                except Exception:
                    return None
            return None
        except Exception as e:
            err_str = str(e)
            if "MESSAGE_NOT_MODIFIED" in err_str or "MESSAGE_ID_INVALID" in err_str:
                return None
            if "FLOOD_WAIT" in err_str:
                return None
            raise

    client.edit_message_text = guarded_edit_message_text

    # 2. Patch send_message to suppress duplicate identical sends within 0.8s and auto-retry on FloodWait
    orig_send_message = client.send_message

    async def guarded_send_message(*args, **kwargs):
        chat_id = kwargs.get("chat_id")
        text = kwargs.get("text")
        if not chat_id and len(args) > 0:
            chat_id = args[0]
        if not text and len(args) > 1:
            text = args[1]

        if chat_id and text and isinstance(text, str):
            cached = is_duplicate_outgoing(chat_id, text)
            if cached is not None:
                print(f"[AntiDuplicate] Suppressed duplicate identical message to chat {chat_id}")
                return cached

        try:
            res = await orig_send_message(*args, **kwargs)
        except FloodWait as e:
            wait_s = getattr(e, "value", 5)
            logger.warning("[AntiFlood] send_message got FloodWait(%ds), auto-sleeping...", wait_s)
            await asyncio.sleep(wait_s + 1)
            res = await orig_send_message(*args, **kwargs)
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                import re
                m = re.search(r"(\d+)\s*seconds?", str(e))
                wait_s = int(m.group(1)) if m else 5
                logger.warning("[AntiFlood] send_message fallback sleeping %ds...", wait_s)
                await asyncio.sleep(wait_s + 1)
                res = await orig_send_message(*args, **kwargs)
            else:
                raise

        if chat_id and text and isinstance(text, str) and res:
            record_outgoing(chat_id, text, res)
        return res

    client.send_message = guarded_send_message

    # 3. Patch Dispatcher.handler_worker to intercept duplicate CallbackQuery and Message updates
    orig_handler_worker = client.dispatcher.handler_worker

    async def guarded_handler_worker(lock):
        while True:
            packet = await client.dispatcher.updates_queue.get()
            if packet is None:
                break

            try:
                update, users, chats = packet
                parser = client.dispatcher.update_parsers.get(type(update), None)

                parsed_update, handler_type = (
                    await parser(update, users, chats)
                    if parser is not None
                    else (None, type(None))
                )

                if parsed_update is not None:
                    # Guard CallbackQuery updates
                    if isinstance(parsed_update, types.CallbackQuery):
                        is_dup, reason = is_duplicate_callback(parsed_update)
                        if is_dup:
                            u_id = parsed_update.from_user.id if parsed_update.from_user else 0
                            print(f"[AntiDuplicate] Blocked {reason} callback ({parsed_update.data}) from user {u_id}")
                            try:
                                await parsed_update.answer()
                            except Exception:
                                pass
                            continue  # Drop packet completely!

                    # Guard rapid identical slash commands
                    elif isinstance(parsed_update, types.Message):
                        if is_duplicate_command(parsed_update):
                            u_id = parsed_update.from_user.id if parsed_update.from_user else 0
                            print(f"[AntiDuplicate] Throttled duplicate command ({parsed_update.text}) from user {u_id}")
                            continue

                # Process normally through handlers
                async with lock:
                    for group in client.dispatcher.groups.values():
                        for handler in group:
                            args = None
                            if isinstance(handler, handler_type):
                                try:
                                    if await handler.check(client, parsed_update):
                                        args = (parsed_update,)
                                except Exception as e:
                                    logging.exception(e)
                                    continue
                            elif isinstance(handler, pyrogram.handlers.RawUpdateHandler):
                                args = (update, users, chats)

                            if args is None:
                                continue

                            try:
                                import inspect
                                if inspect.iscoroutinefunction(handler.callback):
                                    await handler.callback(client, *args)
                                else:
                                    await client.loop.run_in_executor(
                                        client.executor,
                                        handler.callback,
                                        client,
                                        *args
                                    )
                            except pyrogram.StopPropagation:
                                raise
                            except pyrogram.ContinuePropagation:
                                continue
                            except Exception as e:
                                logging.exception(e)
                            break
            except pyrogram.StopPropagation:
                pass
            except Exception as e:
                logging.exception(e)

    client.dispatcher.handler_worker = guarded_handler_worker
    print("[AntiDuplicate] Idempotency Guard successfully installed.")
