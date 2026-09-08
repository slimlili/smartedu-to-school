# -*- coding: utf-8 -*-
"""sget: fetch json/file from basic.smartedu.cn with ND-UC MAC auth header.
Reads token from secret/nd_auth.json. Usage:
  python sget.py <url> [-o outfile]
prints status + body (or writes binary to outfile).
"""
import json, os, sys, urllib.request

TOK = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret/nd_auth.json"), encoding="utf-8"))
AUTH = 'MAC id="%s",nonce="0",mac="0"' % TOK["access_token"]
HDRS = {"x-nd-auth": AUTH,
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "User-Agent": "Mozilla/5.0"}

def fetch(url, timeout=25, retries=2):
    last=None
    for a in range(retries+1):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            last=e; 
        except Exception as e:
            last=e
    raise last

if __name__ == "__main__":
    url=sys.argv[1]
    out = sys.argv[sys.argv.index("-o")+1] if "-o" in sys.argv else None
    st,b = fetch(url)
    print("HTTP", st, len(b), "bytes")
    if out:
        open(out,"wb").write(b); print("saved", out)
    else:
        sys.stdout.buffer.write(b[:4000]); print()
