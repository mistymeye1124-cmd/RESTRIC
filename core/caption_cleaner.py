# language: Python, file: core/caption_cleaner.py, target: Python 3.10+
"""
Smart Caption Cleaner, Credit Stripper & Template Engine:
Removes competitor promotions, Telegram links, usernames, credit lines, and junk watermarks
while preserving the genuine lecture titles, file names, and descriptions.
Supports custom Find & Replace rules, custom templates, and complete caption removal.
"""

import re
from typing import Optional, List, Dict, Any, Union


def strip_competitor_ads(
    raw_caption: str,
    channel_title: Optional[str] = None,
    channel_username: Optional[str] = None,
    custom_words: Optional[List[str]] = None,
) -> str:
    """
    Intelligently strips competitor Telegram channel handles (@...), Telegram links (t.me/...),
    invite links, credit attributions, channel brand names, and promo banners while strictly PRESERVING genuine
    course/lecture resources (Medium, Quora, Drive, Docs, YouTube, GitHub, websites, etc.)
    and markdown hyperlinks [Text](https://...).
    """
    if not raw_caption:
        return ""

    text = raw_caption

    # 1. Strip Markdown links that point specifically to Telegram channels, bots, or invites
    text = re.sub(r"\[([^\]]*)\]\((?:https?://(?:t\.me|telegram\.me|telegram\.dog)/|t\.me/|tg://)[^\)]+\)", "", text)

    # 2. Tokenize & protect legitimate non-Telegram markdown links and URLs
    protected_urls = []

    def _save_token(match):
        token = f"QQQURLTOKEN{len(protected_urls)}ZZZ"
        protected_urls.append(match.group(0))
        return token

    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", _save_token, text)

    def _protect_raw_url(match):
        url = match.group(0)
        if re.search(r"(?:t\.me|telegram\.me|telegram\.dog)/|tg://", url, re.IGNORECASE):
            return ""  # Remove Telegram URL directly
        return _save_token(match)

    text = re.sub(r"https?://\S+", _protect_raw_url, text)

    # 3. Aggressively remove ANY remaining Telegram URLs (even if adjacent to emojis, colons, brackets)
    text = re.sub(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/[^\s\)\],]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"tg://[^\s\)\],]+", " ", text, flags=re.IGNORECASE)

    # 4. Remove competitor channel branding and specific custom words
    if channel_title and channel_title.strip():
        ct = channel_title.strip()
        text = re.sub(re.escape(ct), " ", text, flags=re.IGNORECASE)
        # Also strip significant words of channel title (min 3 chars, except essential keywords)
        for part in ct.split():
            part_clean = part.strip()
            if len(part_clean) >= 3 and part_clean.lower() not in ("the", "and", "for", "with", "from"):
                text = re.sub(rf"(?i)\b{re.escape(part_clean)}\b", " ", text)

    if channel_username and channel_username.strip():
        cu = channel_username.lstrip("@").strip()
        if cu:
            text = re.sub(rf"(?i)@?{re.escape(cu)}\b", " ", text)

    if custom_words:
        for cw in custom_words:
            if cw and cw.strip():
                text = re.sub(re.escape(cw.strip()), " ", text, flags=re.IGNORECASE)

    # 5. Remove standalone Telegram channel handles (@channel_name), preserving email addresses
    text = re.sub(r"(?<![\w\d._%+-])@[\w\d_]{3,}\b", " ", text)

    # 6. Multi-pattern Credit, Promo Banners & Call-to-Action stripper
    lines = text.split("\n")
    cleaned_lines = []
    prev_blank = False

    # Regex for lines that are full promotional banners, headers, or call-to-actions
    full_promo_line_patterns = [
        r"(?i)^\s*.*(?:join|subscribe|follow)\s+(?:our|my|the|this)?\s*(?:telegram|tg|vip|official|backup|main)?\s*(?:channel|channels|group|groups|chat|community|updates|now|here)?.*$",
        r"(?i)^\s*.*(?:telegram|tg)\s+(?:channel|channels|group|groups|link|links|community).*$",
        r"(?i)^\s*.*(?:আমাদের\s*চ্যানেলে\s*যুক্ত\s*হন|যুক্ত\s*হন|সাবস্ক্রাইব\s*করুন|টেলিগ্রাম\s*চ্যানেল).*$",
        r"(?i)^\s*(?:exclusive\s*content|copyright\s*reserved|all\s*rights\s*reserved|dm\s*for|contact\s*admin).*",
    ]

    promo_line_prefixes = (
        r"(?i)^\s*(?:"
        r"credit|credits|source|from|by|uploaded\s*by|uploaded\s*in|uploaded\s*at|uploaded\s*on|"
        r"provided\s*by|owner|channel|main\s*channel|backup\s*channel|vip\s*channel|official\s*channel|"
        r"shared\s*by|shared\s*in|leaked\s*by|courtesy|join|join\s*us|join\s*channel|subscribe|follow|"
        r"follow\s*us|link|channel\s*link|telegram|telegram\s*channel|tg|backup|discussion|discussion\s*group|"
        r"group|chat|course\s*by|file\s*by|file\s*uploaded\s*in|downloaded\s*from|joined\s*at|"
        r"contact|contact\s*admin|admin|dm\s*for|exclusive\s*content|"
        r"ক্রেডিট|উৎস|সোর্স|আপলোডার|আপলোড|আপলোড\s*বাই|চ্যানেল|মূল\s*চ্যানেল|ব্যাকআপ\s*চ্যানেল|"
        r"আমাদের\s*চ্যানেলে\s*যুক্ত\s*হন|যুক্ত\s*হন|সাবস্ক্রাইব\s*করুন"
        r")\s*[:►👉\-—=\|]+"
    )

    orphaned_label_regex = re.compile(
        r"^(?:"
        r"(?:main|backup|vip|official|discussion|chat|support|community)?\s*"
        r"(?:channel|group|discussion|chat|link|bot|credits?|source|uploaded|uploaded\s*by|uploaded\s*in|by|from|telegram|tg|contact|admin|download|download\s*link|join|join\s*us|subscribe|follow)|"
        r"(?:ক্রেডিট|উৎস|সোর্স|আপলোডার|আপলোড|চ্যানেল)"
        r")\s*[:►👉\-—=\|]*$",
        re.IGNORECASE
    )

    for line in lines:
        stripped = line.strip(" \t-►👉*━═~_=•#|┌┐└┘├┤┼│")
        if not stripped or (len(set(stripped)) == 1 and stripped[0] in "-=_~*#"):
            if not prev_blank and cleaned_lines:
                cleaned_lines.append("")
                prev_blank = True
            continue

        # Check full promo banner lines (e.g. "🔥 JOIN OUR TELEGRAM CHANNELS 🔥")
        is_banner = False
        for banner_pat in full_promo_line_patterns:
            if re.match(banner_pat, stripped):
                is_banner = True
                break
        if is_banner:
            continue

        # If a line matches promo prefix and has no other substantial text
        if re.search(promo_line_prefixes, line):
            after_prefix = re.sub(promo_line_prefixes, "", line).strip(" \t-►👉*━═~_=•#|")
            if not after_prefix or not re.search(r"[\w\d\u0980-\u09FF]", after_prefix):
                continue
            if re.match(r"^[\w\d_\s\.\-]{1,30}$", after_prefix) and any(w in line.lower() for w in ("credit", "uploaded", "channel", "join", "by", "telegram", "link", "backup", "source", "discussion", "group")):
                continue

        # If line is an orphaned label (e.g. "Link:", "Channel:", "Credit:", "Join us:", "Discussion Group:")
        if orphaned_label_regex.match(stripped):
            continue

        # If line has no alphanumeric characters (e.g. only orphaned emoji like 🔥 or symbols)
        if not re.search(r"[\w\d\u0980-\u09FF]", stripped):
            continue

        # Strip promo sentence fragments left by deleted links, e.g. "Join for daily updates!"
        stripped = re.sub(r"(?i)^\s*(?:join|subscribe|follow)\s+(?:for|to)?\s*(?:daily|more)?\s*(?:updates|content|leaks|courses)?[\s!.]*$", "", stripped).strip()
        if not stripped:
            continue

        # Strip orphaned label suffixes at the end of a line
        stripped = re.sub(
            r"(?i)\b(?:"
            r"course\s+by|file\s+uploaded\s+in|downloaded\s+from|joined\s+at|join|subscribe|from|by|"
            r"credit|credits|channel\s*link|telegram|backup|link|discussion\s*group|discussion|group"
            r")\s*[:►👉\-—=\|]*$",
            "",
            stripped
        ).strip(" \t-►👉*━═~_=•#|")

        if not stripped or not re.search(r"[\w\d\u0980-\u09FF]", stripped):
            continue

        cleaned_lines.append(stripped)
        prev_blank = False

    result = "\n".join(cleaned_lines).strip()

    # 7. Restore all protected URLs and markdown links
    for idx, orig_val in enumerate(protected_urls):
        result = result.replace(f"QQQURLTOKEN{idx}ZZZ", orig_val)

    return result.strip()


def apply_caption_replacements(
    caption: str,
    replacements: Optional[Union[List[Dict[str, str]], List[tuple]]] = None,
) -> str:
    """
    Applies custom search-and-replace rules to the caption text.
    Allows changing old channel credits/words to user-specified text.
    """
    if not caption or not replacements:
        return caption

    res = caption
    for item in replacements:
        if isinstance(item, dict):
            find_w = item.get("find", "")
            repl_w = item.get("replace", "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            find_w = item[0]
            repl_w = item[1]
        else:
            continue

        if find_w:
            pattern = re.compile(re.escape(find_w), re.IGNORECASE)
            res = pattern.sub(repl_w, res)

    return res.strip()


def format_custom_caption(
    template: Optional[str],
    original_caption: str,
    file_name: Optional[str] = None,
    clean_ads: bool = True,
    replacements: Optional[Union[List[Dict[str, str]], List[tuple]]] = None,
    file_size_str: Optional[str] = None,
    file_size: Optional[Union[int, str]] = None,
    channel_title: Optional[str] = None,
    channel_username: Optional[str] = None,
    custom_words: Optional[List[str]] = None,
) -> str:
    """
    Formats the final delivered caption with custom user template variables.
    Supported variables:
      {title}            -> First line or clean video title
      {filename}         -> Full filename (e.g. Lecture_01.mp4)
      {file_name}        -> Alias for {filename}
      {caption}          -> Cleaned original description
      {original_caption} -> Alias for {caption}
      {size}             -> File size (e.g. 142.5 MB)

    Special values for template:
      "none" / "empty" / "off" / "clear" / "0" -> Returns "" (No Caption)
    """
    # Auto-format size if passed as file_size int or str
    if not file_size_str and file_size is not None:
        if isinstance(file_size, (int, float)):
            if file_size >= 1024 * 1024 * 1024:
                file_size_str = f"{file_size / (1024 * 1024 * 1024):.1f} GB"
            elif file_size >= 1024 * 1024:
                file_size_str = f"{file_size / (1024 * 1024):.1f} MB"
            elif file_size >= 1024:
                file_size_str = f"{file_size / 1024:.1f} KB"
            else:
                file_size_str = f"{file_size} B"
        else:
            file_size_str = str(file_size)
    # 1. Check for explicit "No Caption" request
    if template and template.strip().lower() in ("none", "empty", "off", "clear", "0", "no", "null"):
        return ""

    # 2. Strip competitor ads and original credits if enabled
    base = strip_competitor_ads(
        original_caption,
        channel_title=channel_title,
        channel_username=channel_username,
        custom_words=custom_words,
    ) if clean_ads else (original_caption or "")

    # 3. Apply custom find & replace rules
    if replacements:
        base = apply_caption_replacements(base, replacements)

    fname = str(file_name) if file_name is not None else ""
    title = base.split("\n")[0].strip() if base else fname

    # If no custom template provided, return cleaned base caption
    if not template or not template.strip():
        return base

    # 4. Substitute template variables
    formatted = template
    formatted = formatted.replace("{filename}", fname)
    formatted = formatted.replace("{file_name}", fname)
    formatted = formatted.replace("{title}", title)
    formatted = formatted.replace("{clean_title}", title)
    formatted = formatted.replace("{caption}", base)
    formatted = formatted.replace("{original_caption}", base)
    if file_size_str:
        formatted = formatted.replace("{size}", file_size_str)

    # 5. Apply find & replace on final formatted string as well
    if replacements:
        formatted = apply_caption_replacements(formatted, replacements)

    return formatted.strip()
