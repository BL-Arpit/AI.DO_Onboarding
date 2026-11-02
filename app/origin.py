"""Compare browser origins without disabling cross-site request protection."""
import os
from urllib.parse import urlsplit

LOOPBACK={'localhost','127.0.0.1','::1'}

def normalize_origin(value):
    try:
        url=urlsplit(value)
        if (url.scheme not in ('http','https') or not url.hostname or url.username or
                url.password or url.path not in ('','/') or url.query or url.fragment):
            return None
        return (url.scheme,url.hostname.lower(),url.port or (443 if url.scheme=='https' else 80))
    except (ValueError,TypeError):
        return None

def origin_allowed(received):
    expected=normalize_origin(os.getenv('APP_URL','http://localhost:8000'))
    actual=normalize_origin(received)
    if not actual or not expected:return False
    if actual==expected:return True
    # Development aliases only: scheme and port must still match.
    return actual[1] in LOOPBACK and expected[1] in LOOPBACK and actual[0]==expected[0] and actual[2]==expected[2]
