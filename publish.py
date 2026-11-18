#!/usr/bin/env python3
"""Samsun Doktorum Instagram günlük paylaşım.

Kullanım:
  python3 .instagram/publish.py post      # sıradaki postu paylaşır
  python3 .instagram/publish.py story     # bugünün story'sini paylaşır
  python3 .instagram/publish.py status    # sırayı ve görsel adreslerini kontrol eder (paylaşmaz)
  ... --dry                               # paylaşmadan ne yapılacağını gösterir
  ... --force                             # skip_dates'e rağmen paylaşır

Erişim anahtarı ortamın ağ ayarlarında saklıdır; graph.facebook.com isteklerine
proxy tarafından eklenir. Bu dosyada ya da depoda anahtar yoktur.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.parse
import zoneinfo

API = "https://graph.facebook.com/v21.0"
HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = json.load(open(os.path.join(HERE, "plan.json"), encoding="utf-8"))
TZ = zoneinfo.ZoneInfo(PLAN["timezone"])
IG = PLAN["ig_user_id"]


def curl(method, url, data=None):
    cmd = ["curl", "-sS", "--max-time", "60", "-X", method, url]
    for k, v in (data or {}).items():
        cmd += ["--data-urlencode", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    try:
        body = json.loads(out.stdout or "{}")
    except json.JSONDecodeError:
        body = {"raw": out.stdout[:500], "stderr": out.stderr[:300]}
    if isinstance(body, dict) and "error" in body:
        raise RuntimeError(f"Instagram hatası: {body['error'].get('message')} ({body['error'].get('code')})")
    return body


def head_ok(url):
    out = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code} %{content_type}", "--max-time", "30", url],
                         capture_output=True, text=True).stdout
    return out.startswith("200") and "image/jpeg" in out, out


def first_line(s):
    return (s or "").strip().split("\n")[0].strip()


def next_post():
    media = curl("GET", f"{API}/{IG}/media?fields=caption,timestamp&limit=100").get("data", [])
    done = {first_line(m.get("caption")) for m in media}
    for p in PLAN["posts"]:
        if first_line(p["caption"]) not in done:
            return p, media
    return None, media


def today_story():
    start = dt.date.fromisoformat(PLAN["story_start"])
    idx = (dt.datetime.now(TZ).date() - start).days
    return (PLAN["stories"][idx] if 0 <= idx < len(PLAN["stories"]) else None), idx


def publish(image_url, caption=None, story=False, dry=False):
    ok, info = head_ok(image_url)
    if not ok:
        raise RuntimeError(f"Görsel açılamıyor ({info}): {image_url} — samsundoktorum-instagram deposunda var mı?")
    if dry:
        return "(deneme — paylaşılmadı)"
    data = {"image_url": image_url}
    if story:
        data["media_type"] = "STORIES"
    else:
        data["caption"] = caption
    cid = curl("POST", f"{API}/{IG}/media", data)["id"]
    for _ in range(30):  # görsel işlenene kadar bekle (en fazla ~2,5 dk)
        st = curl("GET", f"{API}/{cid}?fields=status_code,status").get("status_code")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram görseli işleyemedi: {st}")
        time.sleep(5)
    mid = curl("POST", f"{API}/{IG}/media_publish", {"creation_id": cid})["id"]
    link = curl("GET", f"{API}/{mid}?fields=permalink").get("permalink", "")
    return f"paylaşıldı: {mid} {link}"


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "status"
    dry = "--dry" in sys.argv
    base = PLAN["image_base"]
    today = dt.datetime.now(TZ).date().isoformat()
    if what in ("post", "story") and not dry and "--force" not in sys.argv and today in PLAN.get("skip_dates", {}).get(what, []):
        print(f"Bugünün {what} paylaşımı daha önce elle/erken yapıldı; bugün otomatik paylaşım yok.")
        return 0
    if what == "post":
        p, _ = next_post()
        if not p:
            print("BİTTİ: Plandaki 27 postun hepsi paylaşılmış. Yeni post eklenmeli.")
            return 0
        n = PLAN["posts"].index(p) + 1
        print(f"Post {n}/{len(PLAN['posts'])} ({p['image']}): {first_line(p['caption'])}")
        print(publish(base + p["image"], p["caption"], dry=dry))
    elif what == "story":
        s, idx = today_story()
        if not s:
            print(f"Bugün için story yok (gün {idx + 1}, planda {len(PLAN['stories'])} story var).")
            return 0
        recent = curl("GET", f"{API}/{IG}/stories?fields=timestamp").get("data", [])
        now = dt.datetime.now(dt.timezone.utc)
        if any(now - dt.datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < dt.timedelta(minutes=90) for r in recent):
            print("Son 90 dakikada zaten bir story paylaşılmış; tekrar paylaşılmadı.")
            return 0
        print(f"Story {idx + 1}/{len(PLAN['stories'])} ({s['image']})")
        print(publish(base + s["image"], story=True, dry=dry))
    else:
        acc = curl("GET", f"{API}/{IG}?fields=username,media_count,followers_count")
        print(f"Hesap: @{acc.get('username')} · {acc.get('media_count')} gönderi · {acc.get('followers_count')} takipçi")
        p, _ = next_post()
        s, idx = today_story()
        print("Sıradaki post:", p["image"] + " · " + first_line(p["caption"]) if p else "yok")
        print("Bugünün story'si:", s["image"] if s else f"yok (gün {idx + 1})")
        bad = [x["image"] for x in PLAN["posts"] + PLAN["stories"] if not head_ok(base + x["image"])[0]]
        print("Açılamayan görseller:", ", ".join(bad) if bad else "yok, hepsi erişilebilir")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("HATA:", e)
        sys.exit(1)
