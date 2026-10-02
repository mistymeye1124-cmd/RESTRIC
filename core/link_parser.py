# language: Python, file: core/link_parser.py, target: Python 3.10+
"""
Parser for extracting Telegram message IDs, channel identifiers, and forum topic IDs from links.
"""

import re
from typing import Optional, Dict, Any, List


class TelegramLink:
    def __init__(
        self,
        raw_url: str,
        is_private: bool,
        chat_identifier: Any,  # int for private (-100...), str for public username
        message_id: int,
        topic_id: Optional[int] = None,
    ):
        self.raw_url = raw_url
        self.is_private = is_private
        self.chat_identifier = chat_identifier
        self.message_id = message_id
        self.topic_id = topic_id

    def __repr__(self):
        return f"<TelegramLink chat={self.chat_identifier} msg={self.message_id} topic={self.topic_id} private={self.is_private}>"


def parse_telegram_link(text: str, max_per_link: int = 50) -> List[TelegramLink]:
    """
    Parses any text containing one or more Telegram links, ranges, or forum topics.
    Supports:
      - Private topic: https://t.me/c/2459862936/2/1019 or range 1019-1025
      - Private normal: https://t.me/c/2459862936/1019 or range 1019-1025
      - Public topic: https://t.me/groupname/2/1019 or range 1019-1025
      - Public normal: https://t.me/channelname/1019 or range 1019-1025
    max_per_link: max messages to expand per link token (50 for free, up to 200 for VIP).
    Returns a deduplicated, numerically sorted list of TelegramLink objects.
    """
    results: List[TelegramLink] = []
    seen = set()

    # Split text by whitespace and newlines to inspect each candidate token or URL
    tokens = text.split()
    for token in tokens:
        token = token.strip().rstrip(".,;:)>]}")
        if not ("t.me/" in token or "telegram.me/" in token):
            continue

        # 1. Private channel with forum topic (e.g., t.me/c/12345/2/1019 or range 1019-1025)
        m_priv_topic = re.search(r"(?:t|telegram)\.me/c/(\d+)/(\d+)/(\d+)(?:-(\d+))?", token)
        if m_priv_topic:
            chan_id_raw, topic_id_str, start_s, end_s = m_priv_topic.groups()
            channel_id = -int(chan_id_raw) if (chan_id_raw.startswith('100') and len(chan_id_raw) >= 13) else int(f'-100{chan_id_raw}')
            topic_id = int(topic_id_str)
            start_id = int(start_s)
            end_id = int(end_s) if end_s else start_id
            max_batch = min(end_id, start_id + max_per_link - 1)
            for msg_id in range(start_id, max_batch + 1):
                key = (channel_id, msg_id)
                if key not in seen:
                    seen.add(key)
                    results.append(TelegramLink(token, True, channel_id, msg_id, topic_id))
            continue

        # 2. Private channel without topic (e.g., t.me/c/12345/1019 or range 1019-1025)
        m_priv = re.search(r"(?:t|telegram)\.me/c/(\d+)/(\d+)(?:-(\d+))?", token)
        if m_priv:
            chan_id_raw, start_s, end_s = m_priv.groups()
            channel_id = -int(chan_id_raw) if (chan_id_raw.startswith('100') and len(chan_id_raw) >= 13) else int(f'-100{chan_id_raw}')
            start_id = int(start_s)
            end_id = int(end_s) if end_s else start_id
            max_batch = min(end_id, start_id + max_per_link - 1)
            for msg_id in range(start_id, max_batch + 1):
                key = (channel_id, msg_id)
                if key not in seen:
                    seen.add(key)
                    results.append(TelegramLink(token, True, channel_id, msg_id, None))
            continue

        # 3. Public group with forum topic (e.g., t.me/mygroup/2/1019 or range 1019-1025)
        m_pub_topic = re.search(r"(?:t|telegram)\.me/([a-zA-Z0-9_]+)/(\d+)/(\d+)(?:-(\d+))?", token)
        if m_pub_topic:
            username, topic_id_str, start_s, end_s = m_pub_topic.groups()
            if username.lower() not in ("c", "joinchat", "addstickers", "share", "login", "s", "iv", "proxy"):
                topic_id = int(topic_id_str)
                start_id = int(start_s)
                end_id = int(end_s) if end_s else start_id
                max_batch = min(end_id, start_id + max_per_link - 1)
                for msg_id in range(start_id, max_batch + 1):
                    key = (username.lower(), msg_id)
                    if key not in seen:
                        seen.add(key)
                        results.append(TelegramLink(token, False, username, msg_id, topic_id))
                continue

        # 4. Public channel without topic (e.g., t.me/channel/1019 or range 1019-1025)
        m_pub = re.search(r"(?:t|telegram)\.me/([a-zA-Z0-9_]+)/(\d+)(?:-(\d+))?", token)
        if m_pub:
            username, start_s, end_s = m_pub.groups()
            if username.lower() not in ("c", "joinchat", "addstickers", "share", "login", "s", "iv", "proxy"):
                start_id = int(start_s)
                end_id = int(end_s) if end_s else start_id
                max_batch = min(end_id, start_id + max_per_link - 1)
                for msg_id in range(start_id, max_batch + 1):
                    key = (username.lower(), msg_id)
                    if key not in seen:
                        seen.add(key)
                        results.append(TelegramLink(token, False, username, msg_id, None))
                continue

    # Strict serial sorting: order by message_id ascending so downloads & uploads execute sequentially
    results.sort(key=lambda x: x.message_id)
    return results
