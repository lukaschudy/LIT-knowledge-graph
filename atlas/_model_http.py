"""Isolated stdlib HTTP transport; the parent enforces the total deadline.

Run only as a helper process. Request credentials arrive through stdin, never
command arguments or diagnostics. Successful stdout is bounded response bytes.
"""
import json
import sys
import urllib.error
import urllib.request


def main():
    value = json.load(sys.stdin)
    request = urllib.request.Request(value["url"], data=value["data"].encode("utf-8"),
                                     headers=value["headers"], method="POST")
    try:
        with urllib.request.urlopen(request, timeout=value["timeout"]) as response:
            chunks, size = [], 0
            limit = value["max_response_bytes"]
            while True:
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    return 5
                chunks.append(chunk)
            sys.stdout.buffer.write(b"".join(chunks))
    except urllib.error.HTTPError as exc:
        # Provider bodies can contain secrets or sensitive request echoes.
        sys.stderr.write(str(exc.code))
        exc.close()
        return 2
    except (TimeoutError, urllib.error.URLError) as exc:
        return 3 if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError) else 4
    except Exception:
        return 4
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        code = 4
    raise SystemExit(code)
