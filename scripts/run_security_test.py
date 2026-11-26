"""安全测试纯脚本驱动（不依赖 pytest 也能跑；pytest 环境下亦可由 conftest 注入 graph）。

用法（项目根目录）：
    python scripts/run_security_test.py

用例说明：
    - case1 直接注入：topic 套取系统提示词，走完整 graph.invoke
    - case2 间接注入窃凭证：恶意摘要经完整链路；case2b 直连 summarize_one 节点
    - case3 间接注入篡改数字：恶意摘要要求编造具体百分比（样本不预埋目标数值）
    - baseline 正常主题：确认不误杀

任一用例断言失败即中断并抛出错误信息。真实 LLM 调用按 .env 的 MODEL_PROVIDER 走。
"""

import os
import sys

# 把项目根目录加入 sys.path，保证从任意工作目录运行都能导入包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.graph_compile import graph  # noqa: E402
import tests.security_injection_test as sec  # noqa: E402


def main() -> None:
    sec.test_case1_direct_injection(graph)
    sec.test_case2_indirect_leak_via_graph(graph)
    sec.test_case2_indirect_leak_via_summary_node()
    sec.test_case3_indirect_number_tampering(graph)
    sec.test_baseline_not_false_positive(graph)
    print("\n全部安全用例通过")


if __name__ == "__main__":
    main()
