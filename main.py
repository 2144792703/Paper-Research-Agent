import argparse
import time

from diskcache import Cache

from graph.graph_compile import graph
from models import _resolve_provider
from config import clamp_search_count, clamp_keep_papers, SEARCH_MIN, SEARCH_MAX, KEEP_MIN, KEEP_MAX, LANGFUSE_ENABLED, CACHE_DIR
from observability import trace_config, trace_id, flush
from security import sanitize_topic, flag_injection, MAX_TOPIC_LEN
from logger import logger
import usage
import report_check
from cache import reset_stats as reset_cache_stats, stats as cache_stats

def main():
    parser = argparse.ArgumentParser(description="论文研究报告 Agent")
    parser.add_argument("--topic", type=str, help="研究主题，不填则交互输入")
    parser.add_argument("--papers", type=int, default=None,
                        help=f"最终保留论文数量（{KEEP_MIN}-{KEEP_MAX}，不填则取 .env 的 KEEP_PAPERS）")
    parser.add_argument("--search-count", type=int, default=None,
                        help=f"单次搜索拉取的论文数量（{SEARCH_MIN}-{SEARCH_MAX}，不填则取 .env 的 SEARCH_MAX_RESULTS）")
    parser.add_argument("--max-retries", type=int, default=2, help="最大评审轮数（默认为2）")
    parser.add_argument("--clear-cache", action="store_true",
                        help="清空本地 LLM 磁盘缓存后退出（改 prompt/模型后旧坏结果回放时用）")
    args = parser.parse_args()

    # 方案8：清缓存入口（用 Cache.clear()，别手动删 .cache/cache.db——Windows 文件锁会出问题）
    if args.clear_cache:
        Cache(CACHE_DIR).clear()
        print(f"🧹 已清空本地 LLM 缓存：{CACHE_DIR}")
        return

    topic = args.topic
    if not topic:
        topic = input("请输入研究主题：\n")

    # 步骤3：入口校验 —— 控制字符清理 + 空值/长度校验（与 API 端策略一致：超长拒绝）
    topic = sanitize_topic(topic)
    if not topic:
        print("错误，主题为空或清理后为空")
        return
    if len(topic) > MAX_TOPIC_LEN:
        print(f"错误，主题过长（{len(topic)} 字符，上限 {MAX_TOPIC_LEN}），请精简后重试")
        return

    # 步骤3：危险标记（不硬拦截，避免误杀正常论文标题；命中仅打 warning 供人工复核）
    for flag in flag_injection(topic):
        logger.warning(f"[sec] topic 含注入可疑短语 '{flag}'，正常处理但请人工核对后续报告")

    search_count = clamp_search_count(args.search_count)
    keep_papers = clamp_keep_papers(args.papers)
    if args.search_count is not None and args.search_count != search_count:
        print(f"⚠️  搜索数量 {args.search_count} 超出范围，已修正为 {search_count}")
    if args.papers is not None and args.papers != keep_papers:
        print(f"⚠️  保留数量 {args.papers} 超出范围，已修正为 {keep_papers}")

    provider = _resolve_provider()

    print(f"🚀 开始研究：{topic}")
    print(f"   搜索论文数：{search_count}，保留论文数：{keep_papers}，评审轮数：{args.max_retries}")
    print(f"   模型提供方：{provider}")
    print(f"   Langfuse 观测：{'已启用' if LANGFUSE_ENABLED else '未配置（跳过上报）'}")

    config = trace_config(topic)
    usage.reset()
    reset_cache_stats()
    started = time.perf_counter()
    result = graph.invoke({
        "topic": topic,
        "critique_times": args.max_retries,
        "search_max_results": search_count,
        "keep_papers": keep_papers,
    }, config=config)
    elapsed = time.perf_counter() - started
    flush()

    trace = trace_id(config)
    if trace:
        print(f"\n🔗 Langfuse trace：{trace}")

    print("\n" + "=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(result.get("summary", "（无报告）"))

    # 方案7：报告数字事后校验（百分比须来自喂给模型的原始摘要）
    missing_nums = report_check.check_report(result.get("summary", ""), report_check.build_corpus(result))
    if missing_nums:
        print(f"\n⚠️  数字校验：报告出现摘要语料中不存在的百分比 {missing_nums}，疑似编造，请人工核对")
    else:
        print("\n✅ 数字校验：报告中百分比均来自摘要语料")

    print(f"\n--- 评审意见 ---")
    print(result.get('critique', '无'))

    print(f"\n--- 评审意见历史 ---")
    print(result.get('critique_history', '无'))

    print(f"\n--- 追问推荐 ---")
    print(result.get('followup', '无'))

    cs = cache_stats()
    print("\n" + "=" * 60)
    print("💰 本次 run 统计")
    print("=" * 60)
    print(f"  总耗时        = {elapsed:.2f}s")
    print(f"  缓存          = hit {cs['hit']} 次 / miss {cs['miss']} 次")
    print(usage.format_summary())


if __name__ == "__main__":
    main()
