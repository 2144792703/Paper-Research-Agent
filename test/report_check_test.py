"""report_check 数字事后校验的本地单元测试（不调 LLM）。

运行：python -m pytest test/report_check_test.py -q
"""

from tools.arxiv_tool import PaperMeta
from report_check import build_corpus, check_report


def _paper_obj() -> PaperMeta:
    return PaperMeta(
        title="Vision Transformer",
        authors=["A"],
        published="2020-10-01",
        summary="在 ImageNet 上准确率 88.5%，推理延迟 12ms",
        url="http://x/1",
    )


def _paper_dict() -> dict:
    return {
        "title": "Retrieval Augmented Generation",
        "authors": ["B"],
        "published": "2023-01-01",
        "summary": "召回率 76%，F1 0.62",
        "url": "http://x/2",
    }


def test_corpus_keeps_object_fields():
    corpus = build_corpus({"papers": [_paper_obj()]})
    assert "88.5%" in corpus
    assert "Vision Transformer" in corpus


def test_corpus_keeps_dict_fields():
    # dict 形态下不能只靠 getattr，否则摘要语料丢失会误报编造
    corpus = build_corpus({"papers": [_paper_dict()]})
    assert "76%" in corpus
    assert "Retrieval Augmented Generation" in corpus


def test_corpus_mixed_object_and_dict():
    corpus = build_corpus({"papers": [_paper_obj(), _paper_dict()]})
    assert "88.5%" in corpus and "76%" in corpus


def test_in_corpus_percentage_not_flagged():
    corpus = build_corpus({"papers": [_paper_obj()]})
    assert check_report("准确率 88.5%", corpus) == []


def test_fabricated_percentage_flagged():
    corpus = build_corpus({"papers": [_paper_obj()]})
    missing = check_report("编造了 42% 的提升", corpus)
    assert missing == ["42%"]


def test_empty_report_passes():
    assert check_report("", "任意语料") == []


def test_ms_unit_flagged():
    corpus = build_corpus({"papers": [_paper_obj()]})  # 语料只有 12ms
    assert check_report("延迟降低到 200ms", corpus) == ["200ms"]
    assert check_report("延迟 12ms", corpus) == []


def test_times_chinese_unit_flagged():
    corpus = build_corpus({"papers": [_paper_obj()]})
    assert check_report("耗时 3 秒", corpus) == ["3秒"]


def test_multiple_times_flagged():
    corpus = build_corpus({"papers": [_paper_obj()]})
    assert check_report("速度提升 3 倍", corpus) == ["3倍"]


def test_decimal_flagged_and_matched():
    corpus = build_corpus({"papers": [_paper_dict()]})  # 语料含 F1 0.62
    assert check_report("F1 达到 0.62", corpus) == []
    assert check_report("F1 达到 0.85", corpus) == ["0.85"]


def test_percentage_not_split_into_decimal():
    # 1.5% 不应额外产出 "1.5" 造成重复告警
    assert check_report("提升 1.5%", "语料无关") == ["1.5%"]


def test_plain_integer_not_flagged():
    # 年份、篇数等纯整数不检，避免误报
    assert check_report("2020 年以来共 5 篇", "语料无关") == []
