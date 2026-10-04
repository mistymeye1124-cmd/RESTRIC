# language: Python, file: core/caption_cleaner.py, target: Python 3.10+
"""
Smart Caption Cleaner, Credit Stripper & Template Engine:
Removes competitor promotions, Telegram links, usernames, credit lines, and junk watermarks
while preserving the genuine lecture titles, file names, and descriptions.
Supports custom Find & Replace rules, custom templates, and complete caption removal.
"""

import re
from typing import Optional, List, Dict, Any, Union


def strip_competitor_ads(raw_caption: str) -> str:
    """
    Intelligently strips competitor Telegram channel handles (@...), Telegram links (t.me/...),
    invite links, credit attributions, and spam dividers while strictly PRESERVING genuine
    course/lecture resources (Medium, Quora, Drive, Docs, YouTube, GitHub, websites, etc.)
    and markdown hyperlinks [Text](https://...).
    """
    if not raw_caption:
        return ""

    text = raw_caption

    # 1. Strip Markdown links that point specifically to Telegram channels, bots, or invites
    # e.g. [Join Channel](https://t.me/xyz) or [VIP](tg://join?invite=...)
    text = re.sub(r"\[([^\]]*)\]\((?:https?://(?:t\.me|telegram\.me|telegram\.dog)/|t\.me/|tg://)[^\)]+\)", "", text)

    # 2. Tokenize & protect legitimate non-Telegram markdown links and URLs
    # so they are never damaged by handle stripping or ad cleansers
    protected_urls = []

    def _save_token(match):
        token = f"QQQURLTOKEN{len(protected_urls)}ZZZ"
        protected_urls.append(match.group(0))
        return token

    # Protect [Text](https://example.com)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", _save_token, text)

    # Protect raw http/https URLs that are NOT Telegram
    def _protect_raw_url(match):
        url = match.group(0)
        if re.search(r"(?:t\.me|telegram\.me|telegram\.dog)/", url, re.IGNORECASE):
            return ""  # Remove Telegram URL directly
        return _save_token(match)

    text = re.sub(r"https?://\S+", _protect_raw_url, text)

    # 3. Remove any remaining raw Telegram URLs & protocol links (e.g. t.me/xyz, tg://...)
    text = re.sub(r"(?:^|\s)(?:t\.me|telegram\.me|telegram\.dog)/\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"tg://\S+", " ", text, flags=re.IGNORECASE)

    # 4. Remove standalone Telegram channel handles (@channel_name), preserving email addresses
    text = re.sub(r"(?:^|\s)@[\w\d_]{3,}", " ", text)

    # 5. Remove common promo buzzwords, credit lines & call-to-actions (multilingual: EN + BN)
    credit_line_patterns = [
        # Full credit attributions
        r"(?im)^\s*(?:credit|credits|source|from|by|uploaded\s*by|provided\s*by|owner|channel|main\s*channel|backup\s*channel|vip\s*channel)\s*[:►👉-].*$",
        r"(?im)^\s*(?:ক্রেডিট|উৎস|সোর্স|আপলোডার|আপলোড|চ্যানেল|আপলোড\s*বাই|মূল\s*চ্যানেল|ব্যাকআপ\s*চ্যানেল)\s*[:►👉-].*$",
        # Join / subscribe spam lines
        r"(?im)^\s*(?:join|subscribe|follow)\s*(?:our|now|here|channel|group|fast|us)?\s*[:►👉-]?.*$",
        r"(?im)^\s*(?:আমাদের\s*চ্যানেলে\s*যুক্ত\s*হন|সাবস্ক্রাইব\s*করুন).*$",
        # Generic promo phrases
        r"(?i)exclusive\s*(?:content|course|leak|batch|lecture)?[\s:►👉-]*",
        r"(?i)copyright\s*reserved.*",
        r"(?i)all\s*rights\s*reserved.*",
        r"(?i)dm\s*for\s*(?:paid|course|admission).*",
        r"(?i)contact\s*admin\s*[:►👉-].*",
        # Trailing inline credit tags
        r"(?i)\(?(?:credit|credits)\s*[:\-]?\s*[\w\d_ ]+\)?",
    ]
    for pattern in credit_line_patterns:
        text = re.sub(pattern, "", text)

    # 6. Clean up decorative divider symbols and empty lines
    lines = text.split("\n")
    cleaned_lines = []
    prev_blank = False

    for line in lines:
        # Strip common ornamental border characters
        stripped = line.strip(" \t-►👉*━═~_=•#|┌┐└┘├┤┼│")
        # Check if line was purely decorative (e.g. ━━━━━━━━━━━━━ or ----------)
        if not stripped or (len(set(stripped)) == 1 and stripped[0] in "-=_~*#"):
            if not prev_blank and cleaned_lines:
                cleaned_lines.append("")
                prev_blank = True
            continue

        # Check if line was left as an orphaned label (e.g. "Source:", "Credit:", "সোর্স:", "আপলোডার:")
        orphaned = re.match(r"^(?:credit|credits|source|from|by|uploaded\s*by|owner|channel|সোর্স|উৎস|আপলোডার|ক্রেডিট)\s*[:►👉\-—=]*$", stripped, re.IGNORECASE)
        if orphaned:
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
            # Perform case-insensitive replacement while preserving other text
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
    base = strip_competitor_ads(original_caption) if clean_ads else (original_caption or "")

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
