#!/usr/bin/env python3
"""Test tool display with sample data from a real conversation."""

import json

# Sample tools from a real SystemPromptEvent
sample_tools = [
    {"title": "terminal", "kind": "TerminalTool", "description": "Execute a shell command"},
    {"title": "file_editor", "kind": "FileEditorTool", "description": "Edit files"},
    {"title": "task_tracker", "kind": "TaskTrackerTool", "description": "Track tasks"},
    {"title": "browser_navigate", "kind": "BrowserNavigateTool", "description": "Navigate to URL"},
    {"title": "browser_click", "kind": "BrowserClickTool", "description": "Click element"},
    {"title": "browser_get_state", "kind": "BrowserGetStateTool", "description": "Get page state"},
    {"title": "default_create_pr", "kind": "MCPToolDefinition", "description": "Open a PR in GitHub"},
    {"title": "default_tavily_tavily_search", "kind": "MCPToolDefinition", "description": "Search the web"},
    {"title": "finish", "kind": "FinishTool", "description": "Signal completion"},
    {"title": "think", "kind": "ThinkTool", "description": "Think about something"},
]


def display_tools(tools: list[dict], show_descriptions: bool = False) -> None:
    """Display tools in a concise, grouped format."""
    if not tools:
        print("  (no tools found)")
        return
    
    # Group tools by category based on title prefix
    categorized = {}
    for tool in tools:
        title = tool.get("title", "unknown")
        
        # Categorize based on title prefix
        if title.startswith("browser_"):
            category = "browser"
        elif title.startswith("default_"):
            # MCP tools like default_create_pr, default_tavily_*
            # Extract the provider name
            parts = title.split("_", 2)
            category = parts[1] if len(parts) > 1 else "default"
        else:
            category = "core"
        
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(tool)
    
    # Display tools by category
    print(f"  total tools: {len(tools)}")
    print()
    
    for category in sorted(categorized.keys()):
        tools_in_cat = categorized[category]
        
        if category == "browser":
            print(f"  📱 Browser tools ({len(tools_in_cat)}):")
        elif category == "core":
            print(f"  🔧 Core tools ({len(tools_in_cat)}):")
        else:
            print(f"  🔌 {category.title()} tools ({len(tools_in_cat)}):")
        
        for tool in tools_in_cat:
            title = tool.get("title", "unknown")
            kind = tool.get("kind", "unknown")
            
            if show_descriptions:
                desc = tool.get("description", "")
                # Get first line of description
                first_line = desc.split("\n")[0] if desc else ""
                print(f"    • {title} ({kind})")
                print(f"      {first_line[:70]}{'...' if len(first_line) > 70 else ''}")
            else:
                print(f"    • {title}")
        print()


def check_browser_tools(tools: list[dict]) -> bool:
    """Check if browser tools are present."""
    for tool in tools:
        title = tool.get("title", "")
        kind = tool.get("kind", "")
        
        if "browser" in title.lower() or "browser" in kind.lower():
            return True
    
    return False


if __name__ == "__main__":
    print("=== Sample Tools Display (with browser) ===\n")
    display_tools(sample_tools)
    
    has_browser = check_browser_tools(sample_tools)
    if has_browser:
        print("  ❌ Browser tools detected!")
    else:
        print("  ✅ No browser tools")
    
    # Show without browser tools
    no_browser_tools = [t for t in sample_tools if not t["title"].startswith("browser_")]
    
    print("\n\n=== Sample Tools Display (without browser) ===\n")
    display_tools(no_browser_tools)
    
    has_browser = check_browser_tools(no_browser_tools)
    if has_browser:
        print("  ❌ Browser tools detected!")
    else:
        print("  ✅ No browser tools")
    
    print("\n\n=== With Descriptions ===\n")
    display_tools(no_browser_tools, show_descriptions=True)
