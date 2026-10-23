"""Creates a Vertex AI Agent Engine instance used for persistent Sessions and
Memory Bank (rubric 2.3).

The deployed Cloud Run service points at it with:
  --session_service_uri=agentengine://<ID>  --memory_service_uri=agentengine://<ID>

Run once (Cloud Shell, after `terraform apply`):
  pip install "google-adk[gcp]==2.11.0"
  python scripts/create_agent_engine.py --project YOUR_PROJECT_ID
"""

import argparse

import vertexai


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    args = parser.parse_args()

    client = vertexai.Client(project=args.project, location=args.location)
    agent_engine = client.agent_engines.create(
        config={"display_name": "park-concierge-sessions-memory"}
    )
    resource_name = agent_engine.api_resource.name
    engine_id = resource_name.split("/")[-1]
    print(f"Agent Engine resource: {resource_name}")
    print(f"AGENT_ENGINE_ID={engine_id}")


if __name__ == "__main__":
    main()
