#!/usr/bin/env python3
"""Create an agent with a custom tool using the OpenHands SDK.

This example demonstrates how to create and register a custom tool that
extends the agent's capabilities. Unlike built-in tools (terminal, file_editor),
custom tools require:

1. Defining Action/Observation/Executor/ToolDefinition classes
2. Registering the tool with register_tool()
3. Including the tool in the Agent's tools list

Key insight: You CANNOT add custom tools via agent-server API calls alone.
Custom tools require Python code that defines the tool's behavior, which
must run inside the agent's execution environment.

This example shows the SDK pattern. To deploy this to a Cloud sandbox,
you would package this code as a tarball and upload it via the automation
preset API (see README.md for details).
"""

import os
from typing import ClassVar

from pydantic import Field

from openhands.sdk import Action, Agent, Conversation, LLM, Observation, Tool
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


# ============================================================================
# Custom Tool Definition - "Rubber Duck Debugger"
# ============================================================================


class RubberDuckAction(Action):
    """Input for the rubber duck debugging tool.
    
    The agent provides code and describes the problem they're trying to solve.
    """
    
    code: str | None = Field(
        default=None,
        description="The code snippet to debug (optional)",
    )
    problem: str = Field(
        ...,
        description="Description of the problem or bug",
    )


class RubberDuckObservation(Observation):
    """Output from the rubber duck debugging tool.
    
    Provides debugging advice and suggestions.
    """
    
    advice: str = Field(
        ...,
        description="Debugging advice and suggestions",
    )


class RubberDuckExecutor(ToolExecutor[RubberDuckAction, RubberDuckObservation]):
    """Executor that implements the rubber duck debugging logic.
    
    This is where the actual tool behavior is implemented. In a real tool,
    you might call external APIs, run analysis, etc. Here we just return
    helpful debugging advice.
    """
    
    def __call__(
        self,
        action: RubberDuckAction,
        conversation: "Conversation | None" = None,
    ) -> RubberDuckObservation:
        """Execute rubber duck debugging."""
        
        # Build advice based on the problem
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
            "💡 Remember: Explaining the problem out loud (or to a rubber duck) "
            "often reveals the solution!",
        ])
        
        advice = "\n".join(advice_parts)
        
        return RubberDuckObservation.from_text(
            text=advice,
            advice=advice,
        )


class RubberDuckTool(ToolDefinition[RubberDuckAction, RubberDuckObservation]):
    """Tool definition for the rubber duck debugger.
    
    This wires together the Action, Observation, and Executor into a complete
    tool that can be used by the agent.
    """
    
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


# Register the tool so it can be referenced by name
register_tool("rubber_duck", RubberDuckTool)


# ============================================================================
# Agent Creation and Execution
# ============================================================================


def main():
    """Create an agent with the custom rubber duck tool and run a task."""
    
    print("=" * 60)
    print("Custom Agent with Rubber Duck Debugger")
    print("=" * 60)
    
    # Get LLM configuration from environment
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("\n❌ Error: LLM_API_KEY environment variable not set")
        print("   Set it with: export LLM_API_KEY=your-api-key")
        return 1
    
    model = os.getenv("LLM_MODEL", "gpt-4")
    base_url = os.getenv("LLM_BASE_URL")
    
    print(f"\nUsing model: {model}")
    
    # Create LLM configuration
    llm_kwargs = {
        "model": model,
        "api_key": api_key,
    }
    if base_url:
        llm_kwargs["base_url"] = base_url
    
    llm = LLM(**llm_kwargs)
    
    # Create agent with built-in tools + custom rubber duck tool
    print("\nCreating agent with tools:")
    tools = [
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name="rubber_duck"),  # Our custom tool!
    ]
    
    for tool in tools:
        if tool.name == "rubber_duck":
            print(f"  🦆 {tool.name} (custom!)")
        else:
            print(f"  ✓ {tool.name}")
    
    agent = Agent(llm=llm, tools=tools)
    
    # Create workspace
    workspace_dir = os.getenv("WORKSPACE_DIR", "/tmp/rubber-duck-demo")
    print(f"\nWorkspace: {workspace_dir}")
    
    # Create conversation
    conversation = Conversation(agent=agent, workspace=workspace_dir)
    
    # Send a task that will trigger use of the rubber duck tool
    task = """
Create a Python script called 'buggy_calculator.py' that has a function
to calculate the average of a list of numbers. Intentionally introduce
a subtle bug (like dividing by len-1 instead of len).

Then use the rubber_duck tool to help debug it by describing the bug
and the code.

After getting the debugging advice, fix the bug and verify the fix works.
""".strip()
    
    print("\n" + "=" * 60)
    print("Task")
    print("=" * 60)
    print(task)
    print("=" * 60)
    
    try:
        conversation.send_message(task)
        conversation.run()
        
        print("\n" + "=" * 60)
        print("Conversation Complete")
        print("=" * 60)
        
        print("\nThe agent:")
        print("  1. ✓ Created buggy code")
        print("  2. 🦆 Used the Rubber Duck tool to debug")
        print("  3. ✓ Fixed the bug!")
        
        print(f"\nCheck {workspace_dir}/buggy_calculator.py for the result")
        
        print("\nThe key point: The agent had access to our custom 'rubber_duck' tool")
        print("and used it just like any built-in tool! 🦆")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during conversation: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        conversation.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
