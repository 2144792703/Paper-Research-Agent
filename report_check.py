"""
报告数字事后校验。

比对报告中的量化数字是否存在于喂给模型的原始摘要语料，拦截"摘要里没有、模型编出来"的数字。
覆盖形态：百分比（1.5%）、时间（12ms / 3 秒）、倍数（3 倍）、小数（0.62）。
纯整数（年份 2020、篇数等）不检——误报率太高，收益低。
语料只取 state.papers 的原始摘要 + 标题——不含 LLM 生成的二次总结，避免以讹传讹。
只告警不阻断：结果由调用方决定打日志/写进响应，流程照常走完。
缓存回放的报告同样会被检查（校验在报告产出统一层，见 main.py / server.py）。
"""

import re

# 量化数字形态，按优先级排列（前面的匹配会吞掉后面的重叠部分）
_PATTERNS = [
    re.compile(r"\d+(?:\.\d+)?\s*%"),                                      # 1.5%
    re.compile(r"\d+(?:\.\d+)?\s*(?:ms|sec(?:onds?)?|s)\b"),                # 12ms / 3s / 2 sec
    re.compile(r"\d+(?:\.\d+)?\s*(?:毫秒|秒)"),                              # 3 秒 / 200 毫秒
    re.compile(r"\d+(?:\.\d+)?\s*倍"),                                      # 3 倍
    # 前面是字母/数字/点/连字符时不匹配：避免把 GPT-3.5、v1.5 这类版本号当成量化结论
    re.compile(r"(?<![\w.-])\d+\.\d+"),                                      # 0.62 / 3.2
]

# 年份/年代（1990s、2020s）不是量化实验结论，跳过
_YEAR_LIKE = re.compile(r"(?:19|20)\d{2}s")


def _field(p, name: str) -> str:
    """兼容 PaperMeta 对象与 dict 两种论文形态取值，取不到返回空串"""
    if isinstance(p, dict):
        return str(p.get(name, "") or "")
    return str(getattr(p, name, "") or "")


def _find_numbers(text: str) -> list[str]:
    """提取所有量化数字 token（去空格），重叠匹配只保留最长的那个"""
    hits: list[tuple[int, int, str]] = []
    for pat in _PATTERNS:
        for m in pat.finditer(text or ""):
            hits.append((m.start(), m.end(), m.group()))
    hits.sort(key=lambda h: (h[0], -h[1]))  # 起点升序；同起点时长匹配优先（1.5% 优于 1.5）

    tokens: list[str] = []
    last_end = -1
    for start, end, raw in hits:
        if start < last_end:  # 落在上一个匹配内部（如 1.5% 里的 1.5），跳过
            continue
        token = raw.replace(" ", "")
        if _YEAR_LIKE.fullmatch(token):  # 2020s 不是实验数字
            continue
        tokens.append(token)
        last_end = end
    return tokens


def build_corpus(result) -> str:
    """从最终 state 里收集原始摘要语料（PaperMeta.summary + 标题）"""
    texts = []
    for p in result.get("papers") or []:
        texts.append(_field(p, "summary"))
        texts.append(_field(p, "title"))
    return " ".join(texts)


def check_report(report: str, corpus: str) -> list[str]:
    """返回报告中摘要语料未出现的量化数字列表（如 '1.5%'、'12ms'），空列表 = 通过"""
    corpus_norm = corpus.replace(" ", "")
    missing: list[str] = []
    for token in _find_numbers(report):
        if token not in missing and token not in corpus_norm:
            missing.append(token)
    return missing
