import os
import sys
import re
import ast
import inspect

sys.path.insert(0, os.path.abspath("."))
from database import Database

def main():
    # 1. Get all public methods of Database
    db_methods = {
        name for name, val in inspect.getmembers(Database)
        if inspect.isfunction(val) or inspect.iscoroutinefunction(val)
    }
    print(f"Total Database methods: {len(db_methods)}")

    missing_methods = []
    long_callbacks = []
    regex_errors = []

    # 2. Walk through handlers and core
    for check_dir in ["handlers", "core", "."]:
        for root, dirs, files in os.walk(check_dir):
            if any(p in root for p in ["__pycache__", ".git", "sessions", "downloads", "scratch"]):
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as s:
                    content = s.read()

                # Check db.xxx calls
                for m in re.finditer(r"\bdb\.([a-zA-Z0-9_]+)\(", content):
                    m_name = m.group(1)
                    if m_name not in db_methods and not m_name.startswith("_") and m_name not in ("execute", "commit", "rollback"):
                        missing_methods.append((path, m_name))

                # Check callback_data length
                for m in re.finditer(r'callback_data\s*=\s*["\']([^"\']+)["\']', content):
                    cb = m.group(1)
                    if len(cb.encode("utf-8")) > 64:
                        long_callbacks.append((path, cb, len(cb.encode("utf-8"))))

                # Check regex in Pyrogram filters
                for m in re.finditer(r'filters\.regex\(r?["\']([^"\']+)["\']\)', content):
                    pat = m.group(1)
                    try:
                        re.compile(pat)
                    except Exception as e:
                        regex_errors.append((path, pat, str(e)))

    print("\n" + "=" * 50)
    print("RESULTS:")
    print("=" * 50)
    if missing_methods:
        print(f"[!] Missing DB methods ({len(missing_methods)}):")
        for p, m in set(missing_methods):
            print(f"  - {p} -> db.{m}")
    else:
        print("[+] All db.xxx calls map to valid Database methods!")

    if long_callbacks:
        print(f"[!] Callbacks > 64 bytes ({len(long_callbacks)}):")
        for p, cb, l in long_callbacks:
            print(f"  - {p} -> {cb} ({l} bytes)")
    else:
        print("[+] All inline callback_data are within Telegram 64-byte limit!")

    if regex_errors:
        print(f"[!] Regex errors ({len(regex_errors)}):")
        for p, pat, err in regex_errors:
            print(f"  - {p} -> {pat} ({err})")
    else:
        print("[+] All Pyrogram filter regexes are syntactically valid!")

if __name__ == "__main__":
    main()
