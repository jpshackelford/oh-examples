#!/usr/bin/env python3
"""Create a custom agent with a funny custom tool (Rubber Duck Debugger).

This example demonstrates how to:
  1. Define a custom tool using the OpenHands SDK
  2. Create an agent that includes your custom tool
  3. Run a conversation where the agent can use your tool

The custom tool in this example is a "Rubber Duck Debugger" — inspired by
the classic debugging technique where you explain your code to a rubber duck.
When called, it provides whimsical debugging wisdom.

**IMPORTANT**: This example uses the OpenHands SDK directly (not the Cloud API)
because custom tools require code to be available in the agent's runtime.
For Cloud deployments, custom tools must be uploaded via the automation system
or included in a custom base image.

Run this example:
    pip install openhands-sdk openhands-tools
    export LLM_API_KEY=...       # your LLM API key (OpenAI, Anthropic, etc.)
    export LLM_MODEL=...         # e.g., "gpt-4" or "anthropic/claude-3-5-sonnet"
    python agent_with_custom_tool.py

The script will:
  1. Define a RubberDuckTool that provides debugging wisdom
  2. Create an agent with terminal, file_editor, AND our custom tool
  3. Run a conversation where the agent creates buggy code
  4. Ask the agent to debug using the rubber duck
  5. Show the agent using the custom tool!
"""

import os
import sys
from collections.abc import Sequence

from pydantic import Field, SecretStr

# Check dependencies before importing
try:
    from openhands.sdk import Action, Agent, Conversation, LLM, Observation, Tool
    from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool
except ImportError:
    print("Error: openhands-sdk not installed.")
    print("Install with: pip install openhands-sdk openhands-tools")
    sys.exit(1)


# --- Action / Observation ---


class RubberDuckAction(Action):
    """Action for rubber duck debugging."""

    code: str | None = Field(
        default=None, description="Code snippet to debug (optional)"
    )
    problem: str | None = Field(
        default=None, description="Description of the problem (optional)"
    )


class RubberDuckObservation(Observation):
    """Observation returned by the rubber duck tool."""

    advice: str = Field(description="The duck's debugging wisdom")


# --- Executor ---


class RubberDuckExecutor(ToolExecutor[RubberDuckAction, RubberDuckObservation]):
    """Executor for the rubber duck debugging tool."""

    def __call__(
        self, action: RubberDuckAction, conversation=None  # noqa: ARG002
    ) -> RubberDuckObservation:
        """Execute the rubber duck debugging session.

        Args:
            action: The rubber duck action with code/problem
            conversation: The conversation (unused)

        Returns:
            Wise rubber duck debugging advice
        """
        if not action.code and not action.problem:
            return RubberDuckObservation.from_text(
                text=(
                    "🦆 *Quack!* Please provide either 'code' to debug "
                    "or 'problem' to discuss!"
                ),
                advice="Please provide code or problem to debug.",
            )

        # Build the response
        response = ["🦆 *Quack!* Let me think about this...\n"]

        if action.code:
            response.append("📝 You've shown me this code:")
            response.append(f"```\n{action.code}\n```\n")

        if action.problem:
            response.append(f"🤔 The problem you're facing: {action.problem}\n")

        # Add some debugging wisdom
        response.append("🦆 *nods thoughtfully*\n")
        response.append("Here's what the Rubber Duck notices:")
        response.append("  • Have you checked for off-by-one errors?")
        response.append("  • Are all your variables initialized?")
        response.append(
            "  • Have you printed the values to see what's actually happening?"
        )
        response.append("  • Could it be a typo in a variable name?")
        response.append("  • What assumptions are you making that might be wrong?")
        response.append("\n🦆 *quacks encouragingly*")
        response.append(
            "Sometimes just explaining it out loud helps! What do you think?"
        )

        advice_text = "\n".join(response)
        return RubberDuckObservation.from_text(text=advice_text, advice=advice_text)


# Tool description
_RUBBER_DUCK_DESCRIPTION = """Rubber Duck Debugger - Explain code or problems for debugging clarity.
* Use when stuck on a bug or need to think through logic
* Provide 'code' parameter with a code snippet to analyze
* Provide 'problem' parameter with a description of the issue
* The duck will listen attentively and provide wise debugging guidance
* Based on the classic debugging technique of explaining code out loud
"""


# --- Tool Definition ---


class RubberDuckTool(ToolDefinition[RubberDuckAction, RubberDuckObservation]):
    """A custom tool that provides rubber duck debugging wisdom."""

    @classmethod
    def create(cls, conv_state) -> Sequence["RubberDuckTool"]:  # noqa: ARG003
        """Create RubberDuckTool instance with a RubberDuckExecutor.

        Args:
            conv_state: Conversation state (unused for this simple tool).

        Returns:
            A sequence containing a single RubberDuckTool instance.
        """
        executor = RubberDuckExecutor()

        return [
            cls(
                description=_RUBBER_DUCK_DESCRIPTION,
                action_type=RubberDuckAction,
                observation_type=RubberDuckObservation,
                executor=executor,
            )
        ]


# Register the tool so it can be referenced by name
register_tool(RubberDuckTool.name, RubberDuckTool)


def main() -> None:
    # Check required environment variables
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL", "anthropic/claude-3-5-sonnet-20241022")

    if not api_key:
        print("Error: LLM_API_KEY environment variable not set")
        print("\nSet your API key:")
        print("  export LLM_API_KEY=your-api-key-here")
        print("  export LLM_MODEL=gpt-4  # or anthropic/claude-3-5-sonnet, etc.")
        sys.exit(1)

    print("=== Custom Agent with Rubber Duck Debugger ===\n")

    # 1. Configure the LLM
    print(f"Using model: {model}")
    llm = LLM(model=model, api_key=SecretStr(api_key))

    # 2. Create agent with standard tools + our custom tool
    print("\nCreating agent with tools:")
    print("  ✓ terminal")
    print("  ✓ file_editor")
    print("  🦆 rubber_duck (custom!)")

    agent = Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=RubberDuckTool.name),  # ← Our custom tool!
        ],
        agent_context=(
            "You have a special debugging tool: the Rubber Duck! "
            "When you're debugging code or stuck on a problem, you can use the "
            "'rubber_duck' tool to get debugging insights. "
            "The duck is wise and will help you think through issues."
        ),
    )

    # 3. Create a conversation
    workspace = "/tmp/rubber-duck-demo"
    print(f"\nWorkspace: {workspace}")
    conversation = Conversation(agent=agent, workspace=workspace)

    # 4. Send a task that will benefit from the rubber duck
    task = (
        "Create a Python script called 'buggy_calculator.py' that has a function "
        "to calculate the average of a list of numbers. Intentionally introduce "
        "a subtle bug (like dividing by len(numbers)-1 instead of len(numbers)). "
        "Then use the rubber_duck tool to help debug it. "
        "Show the duck the buggy code and see what it suggests!"
    )

    print(f"\n=== Task ===")
    print(f"{task}\n")
    print("=" * 60)

    conversation.send_message(task)
    conversation.run()

    print("\n" + "=" * 60)
    print("=== Conversation Complete ===\n")
    print("The agent:")
    print("  1. ✓ Created buggy code")
    print("  2. 🦆 Used the Rubber Duck tool to debug")
    print("  3. ✓ (Hopefully) Fixed the bug!")
    print(f"\nCheck {workspace}/buggy_calculator.py for the result")
    print("\nThe key point: The agent had access to our custom 'rubber_duck' tool")
    print("and used it just like any built-in tool! 🦆")


if __name__ == "__main__":
    main()
