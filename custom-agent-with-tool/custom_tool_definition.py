#!/usr/bin/env python3
"""Custom tool definition - Rubber Duck Debugger.

This file contains a complete custom tool implementation using the OpenHands SDK.
We'll attempt to upload this to agent-server and use it, demonstrating the
architectural limitations of the current system.
"""

from typing import ClassVar

from pydantic import Field

from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool


# ============================================================================
# Custom Tool: Rubber Duck Debugger
# ============================================================================


class RubberDuckAction(Action):
    """Input for the rubber duck debugging tool."""
    
    code: str | None = Field(
        default=None,
        description="The code snippet to debug (optional)",
    )
    problem: str = Field(
        ...,
        description="Description of the problem or bug",
    )


class RubberDuckObservation(Observation):
    """Output from the rubber duck debugging tool."""
    
    advice: str = Field(
        ...,
        description="Debugging advice and suggestions",
    )


class RubberDuckExecutor(ToolExecutor[RubberDuckAction, RubberDuckObservation]):
    """Executor that implements the rubber duck debugging logic."""
    
    def __call__(
        self,
        action: RubberDuckAction,
        conversation: "Conversation | None" = None,
    ) -> RubberDuckObservation:
        """Execute rubber duck debugging."""
        
        advice_parts = [
            "🦆 *Quack!* Let's debug this together!",
            "",
            f"Problem: {action.problem}",
            "",
        ]
        
        if action.code:
            advice_parts.extend([
                "Code provided:",
                "```",
                action.code,
                "```",
                "",
            ])
        
        advice_parts.extend([
            "Debugging suggestions:",
            "1. Check your assumptions - print intermediate values",
            "2. Verify inputs - are they what you expect?",
            "3. Test edge cases - empty lists, None values, etc.",
            "4. Read error messages carefully - they're usually helpful!",
            "5. Add logging to track execution flow",
            "",
            "💡 Remember: Explaining the problem out loud often reveals the solution!",
        ])
        
        advice = "\n".join(advice_parts)
        
        return RubberDuckObservation.from_text(
            text=advice,
            advice=advice,
        )


class RubberDuckTool(ToolDefinition[RubberDuckAction, RubberDuckObservation]):
    """Tool definition for the rubber duck debugger."""
    
    name: ClassVar[str] = "rubber_duck"
    
    @classmethod
    def create(
        cls,
        conv_state: "ConversationState | None" = None,
    ) -> list["ToolDefinition"]:
        """Create the rubber duck tool instance."""
        return [
            cls(
                description=(
                    "A rubber duck debugging assistant. Helps debug code by "
                    "providing systematic debugging suggestions. Pass the code "
                    "snippet and describe the problem you're trying to solve."
                ),
                action_type=RubberDuckAction,
                observation_type=RubberDuckObservation,
                executor=RubberDuckExecutor(),
            )
        ]


# Auto-register when this module is imported
register_tool("rubber_duck", RubberDuckTool)


if __name__ == "__main__":
    print("✅ Rubber Duck Tool defined successfully!")
    print("   Tool name: rubber_duck")
    print("   Module: custom_tool_definition")
