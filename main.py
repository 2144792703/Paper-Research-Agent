import argparse

from graph.graph_compile import graph
from models import _resolve_provider
from config import clamp_search_count, clamp_keep_papers, SEARCH_MIN, SEARCH_MAX, KEEP_MIN, KEEP_MAX

def main():
    parser = argparse.ArgumentParser(description="论文研究报告 Agent")
    parser.add_argument("--topic", type=str, help="研究主题，不填则交互输入")
    parser.add_argument("--papers", type=int, default=None,
                        help=f"最终保留论文数量（{KEEP_MIN}-{KEEP_MAX}，不填则取 .env 的 KEEP_PAPERS）")
    parser.add_argument("--search-count", type=int, default=None,
                        help=f"单次搜索拉取的论文数量（{SEARCH_MIN}-{SEARCH_MAX}，不填则取 .env 的 SEARCH_MAX_RESULTS）")
    parser.add_argument("--max-retries", type=int, default=2, help="最大评审轮数（默认为2）")
    args = parser.parse_args()

    topic = args.topic
    if not topic:
        topic = input("请输入研究主题：\n").strip()
        if not topic:
            print("错误，主题不能为空")
            return

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

    result = graph.invoke({
        "topic": topic,
        "critique_times": args.max_retries,
        "search_max_results": search_count,
        "keep_papers": keep_papers,
    })

    print("\n" + "=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(result.get("summary", "（无报告）"))

    print(f"\n--- 评审意见 ---")
    print(result.get('critique', '无'))

    print(f"\n--- 评审意见历史 ---")
    print(result.get('critique_history', '无'))

    print(f"\n--- 追问推荐 ---")
    print(result.get('followup', '无'))


if __name__ == "__main__":
    main()