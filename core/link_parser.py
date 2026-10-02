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


def normalize_link_input(text: str) -> str:
    """
    Normalizes human-friendly variations of Telegram links into standard slash/range formats.
    Examples:
      - /range https://t.me/c/12345 5 8 -> https://t.me/c/12345/5-8
      - https://t.me/c/12345 5 8 -> https://t.me/c/12345/5-8
      - https://t.me/c/12345/5 8 -> https://t.me/c/12345/5-8
      - https://t.me/c/12345 5-8 -> https://t.me/c/12345/5-8
      - https://t.me/c/12345 5 -> https://t.me/c/12345/5
      - https://t.me/mychannel 5 8 -> https://t.me/mychannel/5-8
      - https://t.me/mychannel/5 8 -> https://t.me/mychannel/5-8
      - https://t.me/mychannel 5-8 -> https://t.me/mychannel/5-8
      - https://t.me/mychannel 5 -> https://t.me/mychannel/5
    """
    if not text:
        return ""

    # Strip command prefixes if passed directly into parser
    text = re.sub(r'^\s*/(?:range|topic|batch|clone)\s+', '', text, flags=re.IGNORECASE)

    # 1. Private topic with 3 numbers: /c/chan topic start end -> /c/chan/topic/start-end
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/c/\d+)[/\s]+(\d+)\s+(\d+)\s+(?:to\s+|-)?(\d+)', r'\1/\2/\3-\4', text)

    # 2. Private channel with 2 numbers: /c/chan start end -> /c/chan/start-end
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/c/\d+)[/\s]+(\d+)\s+(?:to\s+|-)?(\d+)', r'\1/\2-\3', text)

    # 3. Private channel with dash range: /c/chan 5-8 -> /c/chan/5-8
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/c/\d+)\s+(\d+-\d+)', r'\1/\2', text)

    # 4. Private channel with 1 number: /c/chan 5 -> /c/chan/5
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/c/\d+)\s+(\d+)(?!\s*\d)', r'\1/\2', text)

    # 5. Public topic with 3 numbers: /user/topic start end -> /user/topic/start-end
    def pub_topic_sub(m):
        if m.group(2).lower() in ('c', 'joinchat', 'addstickers', 'share', 'login', 's', 'iv', 'proxy'):
            return m.group(0)
        return f'{m.group(1)}/{m.group(3)}/{m.group(4)}-{m.group(5)}'
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/([a-zA-Z0-9_]+))[/\s]+(\d+)\s+(\d+)\s+(?:to\s+|-)?(\d+)', pub_topic_sub, text)

    # 6. Public channel with 2 numbers: /user start end -> /user/start-end
    def pub_range_sub(m):
        if m.group(2).lower() in ('c', 'joinchat', 'addstickers', 'share', 'login', 's', 'iv', 'proxy'):
            return m.group(0)
        return f'{m.group(1)}/{m.group(3)}-{m.group(4)}'
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/([a-zA-Z0-9_]+))[/\s]+(\d+)\s+(?:to\s+|-)?(\d+)', pub_range_sub, text)

    # 7. Public channel with dash range: /user 5-8 -> /user/5-8
    def pub_dash_sub(m):
        if m.group(2).lower() in ('c', 'joinchat', 'addstickers', 'share', 'login', 's', 'iv', 'proxy'):
            return m.group(0)
        return f'{m.group(1)}/{m.group(3)}'
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/([a-zA-Z0-9_]+))\s+(\d+-\d+)', pub_dash_sub, text)

    # 8. Public channel with 1 number: /user 5 -> /user/5
    def pub_single_sub(m):
        if m.group(2).lower() in ('c', 'joinchat', 'addstickers', 'share', 'login', 's', 'iv', 'proxy'):
            return m.group(0)
        return f'{m.group(1)}/{m.group(3)}'
    text = re.sub(r'((?:https?://)?(?:t|telegram)\.me/([a-zA-Z0-9_]+))\s+(\d+)(?!\s*\d)', pub_single_sub, text)

    return text


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

    # Pre-normalize any human-friendly space-separated or range notations
    normalized_text = normalize_link_input(text)

    # Split text by whitespace and newlines to inspect each candidate token or URL
    tokens = normalized_text.split()
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
            if start_id > end_id:
                start_id, end_id = end_id, start_id
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
            if start_id > end_id:
                start_id, end_id = end_id, start_id
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
                if start_id > end_id:
                    start_id, end_id = end_id, start_id
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
                if start_id > end_id:
                    start_id, end_id = end_id, start_id
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
