from models import Step, format_checklist, parse_steps
from planner import make_plan


async def run_plan_phase(
    prompt: str, tools: list, tool_map: dict, model, logger
) -> list[Step]:
    plan_text = await make_plan(prompt, tools, tool_map, model)
    steps = parse_steps(plan_text)
    logger.info(f"[plan]\n{format_checklist(steps)}")
    return steps
