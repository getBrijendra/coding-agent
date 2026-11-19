import os

import pytest

from coding_agent.config import Settings
from coding_agent.llm import create_model


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("CODING_AGENT_LIVE_SMOKE") != "1"
    or not os.getenv("OPENAI_API_KEY")
    or not os.getenv("CODING_AGENT_MODEL"),
    reason="Set CODING_AGENT_LIVE_SMOKE=1 plus model credentials to make a paid smoke request",
)
def test_live_model_can_return_structured_plan() -> None:
    model = create_model(Settings())
    plan = model.create_plan(
        {
            "task": "Add a test for add()",
            "repository_summary": "Files: calculator.py, test_calculator.py",
            "relevant_files": ["calculator.py", "test_calculator.py"],
            "context": {
                "calculator.py": "def add(a, b): return a + b\n",
                "test_calculator.py": "",
            },
        }
    )
    assert plan.intended_files
    assert plan.verification_steps
