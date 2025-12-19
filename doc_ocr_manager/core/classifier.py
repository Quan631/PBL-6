
from __future__ import annotations
import re


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def classify_document(ocr_text: str) -> str:
    """
    3 loại:
    - Invoice
    - Government Telegram
    - Normal
    """
    t = normalize_text(ocr_text)

    # Government Telegram
    gov_keywords = [
        "cộng hòa xã hội chủ nghĩa việt nam",
        "độc lập - tự do - hạnh phúc",
        "công điện",
        "kính gửi",
        "số:",
        "khẩn",
        "hỏa tốc",
        "bộ ",
        "ủy ban nhân dân",
        "thủ tướng",
        "chính phủ",
    ]
    gov_hits = sum(1 for k in gov_keywords if k in t)
    if gov_hits >= 2:
        return "Government Telegram"

    # Invoice / Receipt
    invoice_keywords = [
        "invoice", "receipt", "vat", "tax", "subtotal", "total", "amount",
        "cashier", "change", "paid", "payment",
        "hóa đơn", "hoá đơn", "mã số thuế", "tổng cộng", "thành tiền", "tiền mặt",
        "số hóa đơn", "số hoá đơn", "ngày bán", "đơn giá", "số lượng"
    ]
    inv_hits = sum(1 for k in invoice_keywords if k in t)
    # heuristic: invoice thường có số tiền + total/vat
    money_like = bool(re.search(r"(\d{1,3}([.,]\d{3})+|\d+)\s*(vnd|đ|usd|\$)", t))
    if inv_hits >= 2 or (inv_hits >= 1 and money_like):
        return "Invoice"

    return "Normal"
