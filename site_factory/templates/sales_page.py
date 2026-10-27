from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlparse


def _text(value: Any, default: str = "") -> str:
    return html.escape(str(value if value is not None else default).strip())


def _safe_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return html.escape(raw, quote=True)


def _items(value: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            out.append(item)
        elif item:
            out.append({"title": str(item)})
    return out


def render_sales_page(spec: dict[str, Any], title: str = "JWIZ Sales Page") -> str:
    brand = _text(spec.get("brand") or "JWIZ")
    eyebrow = _text(spec.get("eyebrow") or "CURATED FOR YOUR EVERYDAY")
    headline = _text(spec.get("headline") or title)
    subheadline = _text(spec.get("subheadline") or "ข้อมูลชัดเจน เลือกง่าย และคุยกับทีมได้ทันที")
    price = _text(spec.get("price"))
    compare_at = _text(spec.get("compare_at"))
    currency = _text(spec.get("currency") or "บาท")
    cta_label = _text(spec.get("cta_label") or "คุยกับ JWIZ ใน LINE")
    cta_url = _safe_url(spec.get("cta_url")) or "#contact"
    hero_image = _safe_url(spec.get("hero_image_url"))
    lifestyle_images = [_safe_url(x) for x in (spec.get("lifestyle_images") or [])[:3] if _safe_url(x)]
    features = _items(spec.get("features")) or [
        {"kicker": "01", "title": "ข้อมูลชัดเจน", "body": "แสดงข้อมูลสำคัญของสินค้าโดยไม่โอ้อวดเกินจริง"},
        {"kicker": "02", "title": "เลือกง่าย", "body": "สรุปสิ่งที่ควรรู้ก่อนคุยกับทีมขาย"},
        {"kicker": "03", "title": "คุยต่อได้ทันที", "body": "ปุ่มหลักพากลับไป LINE OA พร้อมติดตามแหล่งที่มา"},
    ]
    trust_items = _items(spec.get("trust_items"), 4) or [
        {"title": "ข้อมูลที่อนุมัติ", "body": "ใช้ข้อมูลสินค้าและแคมเปญที่ผ่านการตรวจ"},
        {"title": "Mobile-first", "body": "ออกแบบเพื่อการดูบนโทรศัพท์เป็นหลัก"},
        {"title": "LINE-ready", "body": "กดแล้วเริ่มบทสนทนาต่อได้ทันที"},
    ]
    offers = _items(spec.get("offers"), 4)
    education = _items(spec.get("education"), 6)
    faq = _items(spec.get("faq"), 10)
    disclaimer = _text(spec.get("disclaimer") or "โปรดอ่านฉลากและข้อมูลผลิตภัณฑ์ก่อนตัดสินใจ ผลลัพธ์อาจแตกต่างกันในแต่ละบุคคล")

    feature_html = "".join(
        f'<article class="feature"><span>{_text(x.get("kicker") or i + 1)}</span><h3>{_text(x.get("title"))}</h3><p>{_text(x.get("body"))}</p></article>'
        for i, x in enumerate(features)
    )
    trust_html = "".join(
        f'<div class="trust"><strong>{_text(x.get("title"))}</strong><small>{_text(x.get("body"))}</small></div>'
        for x in trust_items
    )
    offer_html = "".join(
        f'<article class="offer {"best" if x.get("featured") else ""}"><span>{_text(x.get("badge") or ("RECOMMENDED" if x.get("featured") else "OPTION"))}</span><h3>{_text(x.get("title"))}</h3><p>{_text(x.get("body"))}</p><div class="offer-price">{_text(x.get("price") or "—")} <small>{currency}</small></div><a href="{cta_url}" rel="noopener">{cta_label}</a></article>'
        for x in offers
    )
    education_html = "".join(
        f'<article class="note"><span>{_text(x.get("kicker") or "SAVE THIS")}</span><h3>{_text(x.get("title"))}</h3><p>{_text(x.get("body"))}</p></article>'
        for x in education
    )
    faq_html = "".join(
        f'<details><summary>{_text(x.get("question") or x.get("title"))}</summary><p>{_text(x.get("answer") or x.get("body"))}</p></details>'
        for x in faq
    )
    image_html = (
        f'<img src="{hero_image}" alt="{headline}" loading="eager">'
        if hero_image
        else '<div class="hero-art"><span>JWIZ PREMIUM PAGE</span></div>'
    )
    lifestyle_html = ""
    if lifestyle_images:
        lifestyle_html = '<div class="lifestyle-grid">' + "".join(
            f'<figure><img src="{url}" alt="ภาพประกอบการใช้งาน" loading="lazy"></figure>'
            for url in lifestyle_images
        ) + "</div>"

    price_html = ""
    if price:
        compare = f"<del>{compare_at}</del>" if compare_at else ""
        price_html = f'<div class="price"><strong>{price}</strong><span>{currency}</span>{compare}</div>'

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#16090b"><meta name="description" content="{subheadline}"><title>{headline}</title>
<style>
:root{{--bg:#16090b;--ink:#fff7f1;--muted:#c9b9b3;--gold:#c9a56a;--line:#3d2a2d;--card:#211215;--paper:#f4eee8;--dark:#16090b}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Noto Sans Thai",sans-serif;line-height:1.65}}
a{{color:inherit}}.wrap{{max-width:1180px;margin:auto;padding:0 24px}}header{{display:flex;justify-content:space-between;gap:20px;padding:24px 0;border-bottom:1px solid var(--line);font-size:.76rem;letter-spacing:.14em;color:var(--muted)}}
.hero{{display:grid;grid-template-columns:1.08fr .92fr;gap:58px;align-items:center;padding:72px 0 62px}}.eyebrow,.kicker{{font-size:.74rem;font-weight:900;letter-spacing:.18em;color:var(--gold);text-transform:uppercase}}
h1{{font-size:clamp(3.2rem,8vw,7rem);line-height:.94;letter-spacing:-.055em;margin:18px 0 24px}}.lead{{font-size:1.15rem;color:var(--muted);max-width:680px}}
.price{{display:flex;align-items:baseline;gap:9px;margin:26px 0}}.price strong{{font-size:3.1rem;line-height:1}}.price span{{color:var(--gold);font-weight:800}}.price del{{color:#806f70;margin-left:8px}}
.cta{{display:inline-flex;align-items:center;justify-content:center;min-height:50px;padding:14px 22px;border-radius:999px;background:var(--gold);color:#16090b;text-decoration:none;font-weight:900}}
.hero-media{{min-height:550px;border-radius:32px;overflow:hidden;border:1px solid var(--line);background:radial-gradient(circle at 78% 16%,#83565a 0,transparent 34%),linear-gradient(145deg,#2a1518,#0d0809)}}.hero-media img{{width:100%;height:100%;min-height:550px;object-fit:cover;display:block}}.hero-art{{min-height:550px;display:flex;align-items:flex-end;padding:32px;background:radial-gradient(circle at 20% 80%,#d2b07a55 0,transparent 32%)}}.hero-art span{{font-size:.72rem;letter-spacing:.16em;color:var(--gold)}}
.trust-grid{{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}.trust{{padding:26px;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:6px}}.trust:last-child{{border-right:0}}.trust small{{color:var(--muted)}}
.section{{padding:100px 0}}.section-head{{display:grid;grid-template-columns:.75fr 1.25fr;gap:48px;align-items:end;margin-bottom:46px}}h2{{font-size:clamp(2.7rem,6vw,5.4rem);line-height:.96;letter-spacing:-.045em;margin:8px 0}}.copy{{color:var(--muted);max-width:600px}}
.features{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}}.feature{{background:var(--card);padding:32px;min-height:235px}}.feature span,.note span,.offer>span{{font-size:.72rem;color:var(--gold);font-weight:900;letter-spacing:.12em}}.feature h3,.note h3,.offer h3{{font-size:1.35rem;margin:30px 0 10px}}.feature p,.note p,.offer p{{color:var(--muted);margin:0}}
.lifestyle{{background:var(--paper);color:var(--dark)}}.lifestyle .copy{{color:#716562}}.lifestyle-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-top:30px}}.lifestyle-grid figure{{margin:0;border-radius:26px;overflow:hidden;min-height:390px;background:#ddd1c8}}.lifestyle-grid img{{width:100%;height:100%;object-fit:cover;display:block}}
.offers{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.offer{{border:1px solid var(--line);border-radius:24px;padding:30px;background:var(--card)}}.offer.best{{border-color:var(--gold)}}.offer-price{{font-size:2.4rem;font-weight:900;margin:22px 0}}.offer-price small{{font-size:.85rem;color:var(--muted)}}.offer a{{color:var(--gold);font-weight:800;text-decoration:none;border-bottom:1px solid var(--gold)}}
.notes{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.note{{padding:28px;border-top:1px solid var(--gold);background:#1d1114}}
.faq details{{border-top:1px solid var(--line);padding:20px 0}}.faq details:last-child{{border-bottom:1px solid var(--line)}}summary{{font-weight:800;cursor:pointer}}details p{{color:var(--muted);max-width:760px}}
.final{{padding:90px 0 120px;text-align:center}}.final h2{{max-width:820px;margin:10px auto 24px}}.final p{{max-width:720px;margin:0 auto 28px;color:var(--muted)}}.disclaimer{{font-size:.8rem;color:#8f7d7d;border-top:1px solid var(--line);padding:26px 0 42px}}
.mobile-cta{{display:none}}
@media(max-width:820px){{.hero,.section-head{{grid-template-columns:1fr;gap:26px}}.hero{{padding-top:44px}}.hero-media,.hero-media img,.hero-art{{min-height:410px}}.trust-grid,.features,.offers,.notes,.lifestyle-grid{{grid-template-columns:1fr}}.trust{{border-right:0;border-bottom:1px solid var(--line)}}.section{{padding:72px 0}}h1{{font-size:clamp(3rem,16vw,5.2rem)}}.mobile-cta{{display:block;position:sticky;bottom:12px;z-index:10;padding:0 12px 12px;pointer-events:none}}.mobile-cta a{{display:flex;pointer-events:auto;justify-content:center;padding:15px;border-radius:999px;background:var(--gold);color:#16090b;text-decoration:none;font-weight:900}}}}
</style></head>
<body><div class="wrap"><header><strong>{brand}</strong><span>PREMIUM SALES PAGE · JWIZ</span></header>
<section class="hero"><div><div class="eyebrow">{eyebrow}</div><h1>{headline}</h1><p class="lead">{subheadline}</p>{price_html}<a class="cta" href="{cta_url}" rel="noopener">{cta_label}</a></div><div class="hero-media">{image_html}</div></section>
<div class="trust-grid">{trust_html}</div></div>
<main><section class="section"><div class="wrap"><div class="section-head"><div><div class="kicker">THE DETAILS</div><h2>{_text(spec.get("features_heading") or "ครบพอดี ไม่ต้องซับซ้อน")}</h2></div><p class="copy">{_text(spec.get("features_intro") or "สิ่งสำคัญถูกจัดให้อ่านง่าย เพื่อช่วยให้ตัดสินใจจากข้อมูลที่ชัดเจน")}</p></div><div class="features">{feature_html}</div></div></section>
<section class="section lifestyle"><div class="wrap"><div class="section-head"><div><div class="kicker">YOUR EVERYDAY RITUAL</div><h2>{_text(spec.get("lifestyle_heading") or "เข้ากับชีวิตจริง")}</h2></div><p class="copy">{_text(spec.get("lifestyle_intro") or "สินค้าที่ดีควรเข้าไปอยู่ในชีวิตประจำวันได้อย่างเป็นธรรมชาติ")}</p></div>{lifestyle_html}</div></section>
<section class="section"><div class="wrap"><div class="section-head"><div><div class="kicker">CHOOSE YOUR SET</div><h2>{_text(spec.get("offers_heading") or "เริ่มแบบที่พอดีกับคุณ")}</h2></div><p class="copy">{_text(spec.get("offers_intro") or "เลือกตัวเลือกที่เหมาะ แล้วคุยกับ JWIZ ใน LINE เพื่อเช็กข้อมูลล่าสุดก่อนสั่ง")}</p></div><div class="offers">{offer_html or f'<article class="offer best"><span>START HERE</span><h3>{headline}</h3><p>{subheadline}</p>{price_html}<a href="{cta_url}" rel="noopener">{cta_label}</a></article>'}</div></div></section>
<section class="section"><div class="wrap"><div class="section-head"><div><div class="kicker">SAVE THIS</div><h2>{_text(spec.get("education_heading") or "ข้อมูลที่อ่านแล้วอยากเก็บไว้")}</h2></div><p class="copy">{_text(spec.get("education_intro") or "สั้น ชัด และซื่อสัตย์ เพื่อช่วยให้ลูกค้าเข้าใจมากกว่าถูกเร่งให้ซื้อ")}</p></div><div class="notes">{education_html or '<article class="note"><span>REAL TALK</span><h3>ตัดสินใจจากข้อมูลจริง</h3><p>ตรวจข้อมูล ราคา และเงื่อนไขล่าสุดกับ JWIZ ก่อนสั่งซื้อ</p></article>'}</div></div></section>
<section class="section faq"><div class="wrap"><div class="section-head"><div><div class="kicker">FAQ / BEFORE YOU START</div><h2>คำถามที่ควรรู้</h2></div><p class="copy">คำตอบควรมาจากข้อมูลที่ได้รับอนุมัติและไม่กล่าวอ้างเกินจริง</p></div>{faq_html or '<details><summary>ต้องการข้อมูลล่าสุดทำอย่างไร?</summary><p>กดปุ่มคุยกับ JWIZ ใน LINE เพื่อเช็กราคา โปรโมชั่น และรายละเอียดล่าสุด</p></details>'}</div></section>
<section class="final"><div class="wrap"><div class="kicker">READY WHEN YOU ARE</div><h2>{_text(spec.get("final_heading") or "พร้อมคุยต่อเมื่อคุณพร้อม")}</h2><p>{_text(spec.get("final_copy") or "ไม่มีแรงกดดัน ถามข้อมูลเพิ่มเติมใน LINE แล้วค่อยตัดสินใจ")}</p><a class="cta" href="{cta_url}" rel="noopener">{cta_label}</a></div></section></main>
<div class="wrap disclaimer">{disclaimer}</div><div class="mobile-cta"><a href="{cta_url}" rel="noopener">{cta_label}</a></div></body></html>"""
