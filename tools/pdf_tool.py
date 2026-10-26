import requests
import pdfplumber

from io import BytesIO
from logger import logger

def extract_pdf_text(pdf_url: str, max_chars: int = 3000) -> str:
    """
    输入：PDF 链接（arXiv 的 pdf_url）
    输出：清洗后的纯文本（截断到 max_chars）
    """
    logger.info(f"下载 PDF：{pdf_url[:80]}")

    try:
        resp = requests.get(pdf_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"PDF 下载失败：{e}")
        return ""

    text_parts = []

    try:
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            for page in pdf.pages[:5]:
                t = page.extract_text() or ""
                text_parts.append(t)
    except Exception as e:
        logger.error(f"PDF 解析失败：{e}")
        return ""

    full_text = "\n".join(text_parts)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    cleaned = "\n".join(lines)
    return cleaned[:max_chars]


    