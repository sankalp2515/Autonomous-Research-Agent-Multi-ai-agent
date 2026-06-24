"""LangGraph topology v2.

The v1 fix is visible right here in the edges: draft_sections has a
conditional edge BACK to plan (bounded by per-sub-question replan budgets
inside the nodes), and assemble only ships gate-verified claims.
"""

from langgraph.graph import END, StateGraph

from app.agents import nodes
from app.agents.state import PipelineState, new_state
from app.core.logging import get_logger, run_id_var
from app.db.models import Run
from app.db.session import session_scope
from app.stores.redis_store import publish_progress

logger = get_logger("graph")


def build_pipeline():
    graph = StateGraph(PipelineState)
    graph.add_node("clarify", nodes.clarify_node)
    graph.add_node("plan", nodes.plan_node)
    graph.add_node("research", nodes.research_node)
    graph.add_node("outline", nodes.outline_node)
    graph.add_node("draft_sections", nodes.draft_sections_node)
    graph.add_node("assemble", nodes.assemble_node)
    graph.add_node("build_graph", nodes.build_graph_node)

    graph.set_entry_point("clarify")
    graph.add_conditional_edges(
        "clarify", nodes.clarify_route, {"plan": "plan", "end": END},
    )
    graph.add_edge("plan", "research")
    graph.add_edge("research", "outline")
    graph.add_edge("outline", "draft_sections")
    graph.add_conditional_edges(
        "draft_sections", nodes.should_replan,
        {"plan": "plan", "assemble": "assemble"},
    )
    graph.add_edge("assemble", "build_graph")
    graph.add_edge("build_graph", END)
    return graph.compile()


_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline


async def execute_run(run_id: str) -> None:
    """Entry point called by the worker. Resumes from checkpoint if the
    run was interrupted; recursion_limit bounds total graph steps as the
    last-resort loop guard above the in-state budgets."""
    run_id_var.set(run_id)
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            logger.error("run not found", extra={"run_id": run_id})
            return
        if run.checkpoint:
            state: PipelineState = run.checkpoint  # resume
            logger.info("resuming run from checkpoint",
                        extra={"node": run.current_node})
        else:
            state = new_state(run_id, run.project_id, run.query)
        run.status = "running"

    try:
        await get_pipeline().ainvoke(state, {"recursion_limit": 40})
    except Exception as exc:
        logger.exception("run failed", extra={"run_id": run_id})
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            if run:
                run.status = "failed"
                run.error = str(exc)[:1000]
        await publish_progress(run_id, {"node": "failed", "status": "failed",
                                        "error": str(exc)[:300]})
        raise
