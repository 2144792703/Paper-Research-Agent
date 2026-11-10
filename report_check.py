"""
报告数字事后校验（方案7）。

比对报告中的百分比是否存在于喂给模型的原始摘要语料，拦截"摘要里没有、模型编出来"的数字。
语料只取 state.papers 的原始摘要 + 标题——不含 LLM 生成的二次总结，避免以讹传讹。
只告警不阻断：结果由调用方决定打日志/写进响应，流程照常走完。
缓存回放的报告同样会被检查（校验在报告产出统一层，见 main.py / server.py）。
"""

import re

# 百分比形态：1.5% / 20 % / 3.20%
_PCT = re.compile(r"\d+(?:\.\d+)?\s*%")


def _field(p, name: str) -> str:
    """兼容 PaperMeta 对象与 dict 两种论文形态取值，取不到返回空串"""
    if isinstance(p, dict):
        return str(p.get(name, "") or "")
    return str(getattr(p, name, "") or "")


def build_corpus(result) -> str:
    """从最终 state 里收集原始摘要语料（PaperMeta.summary + 标题）"""
    texts = []
    for p in result.get("papers") or []:
        texts.append(_field(p, "summary"))
        texts.append(_field(p, "title"))
    return " ".join(texts)


def check_report(report: str, corpus: str) -> list[str]:
    """返回报告中摘要语料未出现的百分比列表（如 '1.5%'），空列表 = 通过"""
    corpus_norm = corpus.replace(" ", "")
    missing: list[str] = []
    for raw in _PCT.findall(report or ""):
        token = raw.replace(" ", "")
        if token not in missing and token not in corpus_norm:
            missing.append(token)
    return missing
