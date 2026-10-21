from graph.graph_compile import graph
from tools.arxiv_tool import search_papers

if __name__ == "__main__":
    # print(f"{'*' * 15} 调用 search_papers {'*' * 15}")
    # results = search_papers("RAG retrieval", max_results=3)
    # for p in results:
    #     print(p.title)
    #     print(p.authors)
    #     print(p.published)
    #     print(p.url)
    #     print("-" * 40)

    print(f"{'*' * 15} 调用 graph {'*' * 15}")
    results_graph = graph.invoke({
        "topic": "RAG retrieval",
        "papers": [],
        "summary": "",
        "next": "",
        "followup":"",
        "critique":"",
        "critique_times": 3,
        "revision_count": 0,
    })
    print(results_graph if results_graph else None)
    print(results_graph["summary"])
    print(results_graph["followup"])