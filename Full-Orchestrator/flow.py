"""
Crew flow: one orchestrator agent, one task to generate and validate from requirements.
This file defines *what* the crew does (the task) and *how* it runs (sequential, one agent).
"""

# --- CrewAI building blocks ---
# Crew = the runnable "team"; Task = one job with a description; Process = how tasks are ordered.
from crewai import Crew, Process, Task

# --- Our local modules: the agent (who does the work) and the tools (what they can call) ---
from agents import create_orchestrator_agent
from tools import create_orchestrator_tools


def create_orchestrator_crew(output_dir: str, requirements: dict) -> Crew:
    """
    Create a crew that:
    1. Generates bootstrap, platform, dev env, prod env, app, deploy, workflows.
    2. Validates Terraform (bootstrap, dev, prod) and Docker (app).
    3. Writes RUN_ORDER.md with the command sequence.
    """
    # --- Build the tools and agent (both are bound to this run's output_dir and requirements) ---
    tools = create_orchestrator_tools(output_dir, requirements)   # List of tools that write files under output_dir and run validate.
    agent = create_orchestrator_agent(tools)   # One agent with role "Full Stack DevOps Orchestrator" that can use those tools.

    # --- Define the single task: the instructions we give to the agent ---
    # The LLM will read this and decide which tool to call and in what order (we suggest the order in the text).
    task = Task(
        description=f"""Generate the full deployment project into the output directory: {output_dir}.

Do the following in order:

1. Generate Terraform bootstrap: call the generate_bootstrap tool.
2. Generate platform module: call the generate_platform tool.
3. Generate dev environment: call the generate_dev_env tool.
4. Generate prod environment: call the generate_prod_env tool.
5. Generate app (Node.js + Dockerfile): call the generate_app tool.
6. Generate deploy: call the generate_deploy tool (produces both CodeDeploy bundle deploy/ and Ansible ansible/ for deploy option codedeploy or ansible).
7. Generate GitHub Actions workflows: call the generate_workflows tool.

8. Validate: run terraform validate in infra/bootstrap, then infra/envs/dev, then infra/envs/prod. If Terraform is not installed, report that and continue.
9. Validate: run docker build in the app directory. If Docker is not installed, report that and continue.
10. Write the run order: call the tool_write_run_order tool with a short summary of what was generated and any notes (e.g. "Fill backend.hcl and tfvars with bootstrap outputs before running dev/prod apply").

Summarize at the end: list what was generated, which validations passed or were skipped, and where the user should look (RUN_ORDER.md) for the exact commands to run next.""",
        expected_output="A clear summary: (1) All generated components listed, (2) Terraform and Docker validation results, (3) Pointer to RUN_ORDER.md and the recommended next steps for the user.",
        agent=agent,   # This task is assigned to our single orchestrator agent.
    )

    # --- Assemble and return the Crew (ready for crew.kickoff() in run.py) ---
    return Crew(
        agents=[agent],           # One agent in the crew.
        tasks=[task],             # One task: do all the steps above.
        process=Process.sequential,   # Run the task once, in order (no branching or multi-step process).
        verbose=True,             # Print what the agent is doing (tool calls, etc.) to the console.
    )
