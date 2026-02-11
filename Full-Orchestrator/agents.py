"""
Orchestrator agent: generates full infra + app from requirements and validates.
Agent is created with tools bound to output_dir and requirements (see flow.py).
"""
from crewai import Agent


def create_orchestrator_agent(tools: list) -> Agent:
    """Create the single orchestrator agent with the given tools."""
    return Agent(
        role="Full Stack DevOps Orchestrator",
        goal="Generate a complete deployment project (Terraform bootstrap, platform module, dev/prod envs, Node.js app, CodeDeploy bundle, GitHub Actions) from user requirements, then validate Terraform and Docker and write a RUN_ORDER.md with the exact command sequence for the user.",
        backstory="You are an expert DevOps engineer. You take a structured requirements input and produce a full, runnable repo: infrastructure as code, application code, deploy scripts, and CI workflows. You always generate components in the correct order (bootstrap first, then platform module, then dev then prod envs, then app and deploy and workflows), then run terraform validate in infra/bootstrap, infra/envs/dev, infra/envs/prod, and docker build in app, and finally write RUN_ORDER.md so the user knows the exact steps to run.",
        tools=tools,
        verbose=True,
        allow_delegation=False,
    ) 
