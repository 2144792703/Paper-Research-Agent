import argparse
import sys
import time

from diskcache import Cache

from graph.graph_compile import graph
from models import _resolve_provider
from models.remote import chaos_stats, reset_chaos_stats
from config import (
    clamp_search_count, clamp_keep_papers, SEARCH_MIN, SEARCH_MAX, KEEP_MIN, KEEP_MAX,
    LANGFUSE_ENABLED, CACHE_DIR, CHAOS_FAILURE_RATE, RECURSION_LIMIT, validate_config,
)
from observability import trace_config, trace_id, flush
from security import sanitize_topic, flag_injection, MAX_TOPIC_LEN
from logger import logger
import usage
import report_check
from cache import reset_stats as reset_cache_stats, stats as cache_stats


def _print_chaos_summary(report_ok: bool):
    """开关打开时打印混沌对照数字；关闭时保持零输出"""
    if CHAOS_FAILURE_RATE <= 0:
        return
    s = chaos_stats()
    print("\n🧪 混沌统计")
    print(f"   注入失败   = {s['injected']} 次")
    print(f"   真实请求调用 = {s['calls']} 次（其中重试 {s['calls_retried']} 次）")
    print(f"   请求尝试   = {s['attempts']} 次")
    print(f"   重试次数   = {s['retries']} 次（尝试 - 调用）")
    print(f"   最终出报告 = {'是' if report_ok else '否'}")


def main():
    parser = argparse.ArgumentParser(description="论文研究报告 Agent")
    parser.add_argument("--topic", type=str, help="研究主题，不填则交互输入")
    parser.add_argument("--papers", type=int, default=None,
                        help=f"最终保留论文数量（{KEEP_MIN}-{KEEP_MAX}，不填则取 .env 的 KEEP_PAPERS）")
    parser.add_argument("--search-count", type=int, default=None,
                        help=f"单次搜索拉取的论文数量（{SEARCH_MIN}-{SEARCH_MAX}，不填则取 .env 的 SEARCH_MAX_RESULTS）")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="最大评审轮数（1-5，默认 2）")
    parser.add_argument("--clear-cache", action="store_true",
                        help="清空本地 LLM 磁盘缓存后退出（改 prompt/模型后旧坏结果回放时用）")
    args = parser.parse_args()

    # 清缓存入口（用 Cache.clear()，别手动删 .cache/cache.db——Windows 文件锁会出问题）
    if args.clear_cache:
        Cache(CACHE_DIR).clear()
        print(f"🧹 已清空本地 LLM 缓存：{CACHE_DIR}")
        return

    # 启动校验放在清缓存之后：缺 key/模型时 --clear-cache 仍可用
    validate_config()

    max_retries = max(1, min(args.max_retries, 5))
    if args.max_retries != max_retries:
        print(f"⚠️  评审轮数 {args.max_retries} 超出范围，已修正为 {max_retries}")

    topic = args.topic
    if not topic:
        topic = input("请输入研究主题：\n")

    # 入口校验 —— 控制字符清理 + 空值/长度校验（与 API 端策略一致：超长拒绝）
    topic = sanitize_topic(topic)
    if not topic:
        print("错误，主题为空或清理后为空")
        sys.exit(2)
    if len(topic) > MAX_TOPIC_LEN:
        print(f"错误，主题过长（{len(topic)} 字符，上限 {MAX_TOPIC_LEN}），请精简后重试")
        sys.exit(2)

    # 危险标记（不硬拦截，避免误杀正常论文标题；命中仅打 warning 供人工复核）
    for flag in flag_injection(topic):
        logger.warning(f"[sec] topic 含注入可疑短语 '{flag}'，正常处理但请人工核对后续报告")

    search_count = clamp_search_count(args.search_count)
    keep_papers = clamp_keep_papers(args.papers)
    if args.search_count is not None and args.search_count != search_count:
        print(f"⚠️  搜索数量 {args.search_count} 超出范围，已修正为 {search_count}")
    if args.papers is not None and args.papers != keep_papers:
        print(f"⚠️  保留数量 {args.papers} 超出范围，已修正为 {keep_papers}")

    provider = _resolve_provider()
    if CHAOS_FAILURE_RATE > 0 and provider != "remote":
        print("⚠️  CHAOS_FAILURE_RATE 仅远程模式生效，当前为本地模式，混沌注入已跳过")

    print(f"🚀 开始研究：{topic}")
    print(f"   搜索论文数：{search_count}，保留论文数：{keep_papers}，评审轮数：{max_retries}")
    print(f"   模型提供方：{provider}")
    print(f"   Langfuse 观测：{'已启用' if LANGFUSE_ENABLED else '未配置（跳过上报）'}")

    config = trace_config(topic)
    config["recursion_limit"] = RECURSION_LIMIT
    usage.reset()
    reset_cache_stats()
    reset_chaos_stats()
    started = time.perf_counter()
    try:
        result = graph.invoke({
            "topic": topic,
            "critique_times": max_retries,
            "search_max_results": search_count,
            "keep_papers": keep_papers,
        }, config=config)
    except Exception as e:
        elapsed = time.perf_counter() - started
        flush()
        # 终端不输出原始 traceback：只给类型名和友好提示，详情留在 debug 日志
        logger.error(f"研究流程异常：{type(e).__name__}")
        logger.debug("研究流程异常详情：%r", e)
        print("\n⚠️ 研究未能完成：模型连续失败或服务异常，已中止（未生成报告）。")
        print("   建议稍后重试；混沌测试时可降低 CHAOS_FAILURE_RATE。")
        _print_chaos_summary(False)
        print("\n" + "=" * 60)
        print("💰 本次 run 统计")
        print("=" * 60)
        print(f"  总耗时        = {elapsed:.2f}s")
        cs = cache_stats()
        print(f"  缓存          = hit {cs['hit']} 次 / miss {cs['miss']} 次")
        print(usage.format_summary())
        return
    elapsed = time.perf_counter() - started
    flush()

    trace = trace_id(config)
    if trace:
        print(f"\n🔗 Langfuse trace：{trace}")

    # 主题无效或连续检索失败时 graph 返回 end，且没有报告：用非 0 退出码区分“正常完成”
    if result.get("next") == "end" and not (result.get("summary") or "").strip():
        print("\n❌ 研究终止：主题无效或连续多次未检索到论文。")
        sys.exit(2)

    print("\n" + "=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(result.get("summary", "（无报告）"))

    # 报告数字事后校验（量化数字须来自喂给模型的原始摘要）
    missing_nums = report_check.check_report(result.get("summary", ""), report_check.build_corpus(result))
    if missing_nums:
        print(f"\n⚠️  数字校验：报告出现摘要语料中不存在的量化数字 {missing_nums}，疑似编造，请人工核对")
    else:
        print("\n✅ 数字校验：报告中的量化数字均来自摘要语料")

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
    _print_chaos_summary(bool((result.get("summary") or "").strip()))


if __name__ == "__main__":
    main()
