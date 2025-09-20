import asyncio
import json
import random
import logging
import os
import pathlib
import traceback
from typing import List, Optional, Tuple
import sys

import dotenv
from mcp import ClientSession
from tqdm import tqdm
import argparse
import uuid

# Add ainara to path
# The script is in external/LiveMCPBench/baseline/run_conversation.py
# ainara is at the root of the project.
# So we need to go up 3 levels from the file's directory.
script_dir = pathlib.Path(__file__).resolve().parent
project_root = script_dir.parents[2]
sys.path.insert(0, str(project_root))

from ainara.framework.config import ConfigManager
from ainara.framework.llm.litellm import LiteLLM
from ainara.framework.matcher.transformers import OrakleMatcherTransformers
from ainara.framework.template_manager import TemplateManager

from utils.clogger import _set_logger
from utils.llm_api import ChatModel
from utils.mcp_client import MCPClient

_set_logger(
    exp_dir=pathlib.Path("./logs"),
    logging_level_stdout=logging.INFO,
    logging_level=logging.DEBUG,
    file_name="baseline.log",
)
dotenv.load_dotenv()
logger = logging.getLogger(__name__)

INPUT_QUERIES_FILE = "./baseline/data/example_queries.json"
CONVERSATION_RESULTS_FILE = f"./baseline/output/{os.getenv('MODEL', 'None').replace('/', '_')}_{os.getenv('EMBEDDING_MODEL', 'None').replace('/', '_')}.json"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_path",
        type=str,
        default=INPUT_QUERIES_FILE,
        help="Path to the input queries file.",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        default=CONVERSATION_RESULTS_FILE,
        help="Path to the output conversation results file.",
    )
    parser.add_argument(
        "--sample_size",
        type=int,
        default=None,
        help="Number of random queries to sample from the input file. Runs all if not specified.",
    )
    return parser.parse_args()


class LoggingMCPClient(MCPClient):
    def __init__(self, matcher, llm_backend):
        super().__init__(timeout=180, max_sessions=9999)
        self.matcher = matcher
        self.llm = llm_backend
        self.template_manager = TemplateManager()
        self.system_message = "You are a helpful AI assistant that processes user requests."

    async def process_query(
        self,
        query: str,
        history: Optional[list] = None,
        max_tool_tokens: int = 10000,
    ) -> Tuple[str, List[dict]]:
        messages = history.copy() if history else []
        messages.append({"role": "user", "content": query})
        final_text = []

        try:
            # 1. Match skills with Orakle
            matches = self.matcher.match(query, threshold=0.15, top_k=5)
            if not matches:
                final_text.append("I'm sorry, I couldn't find a tool to help with that.")
                messages.append({"role": "assistant", "content": final_text[-1]})
                return "\n".join(final_text), messages

            # 2. Format candidate skills for LLM selection
            candidate_skills = []
            for match in matches:
                skill_id = match["skill_id"]
                skill_info = self.matcher.skills_registry[skill_id]
                candidate_skills.append({
                    "name": skill_id,
                    "description": skill_info["description"],
                    "input_schema": skill_info["metadata"]["input_schema"]
                })

            # 3. Use LLM for skill selection and parameter extraction
            selection_prompt = self.template_manager.render(
                "framework.chat_manager.orakle_select_and_params",
                {
                    "query": query,
                    "candidate_skills": candidate_skills,
                },
            )

            chat_result = self.llm.chat(
                chat_history=self.llm.prepare_chat(
                    system_message=self.system_message, 
                    new_message=selection_prompt
                ),
                stream=False,
            )

            # Handle both tuple and string returns
            if isinstance(chat_result, tuple):
                selection_response = chat_result[0]
            else:
                selection_response = chat_result

            # Parse LLM response
            selection_data = json.loads(selection_response)
            tool_name = selection_data.get("skill_id")
            tool_args = selection_data.get("parameters", {})

            if not tool_name:
                final_text.append("I couldn't determine which tool to use for your request.")
                messages.append({"role": "assistant", "content": final_text[-1]})
                return "\n".join(final_text), messages

            # Get server info for the selected tool
            tool_info = self.matcher.skills_registry[tool_name]
            server_id = tool_info["metadata"]["server_name"]

            # 3. Execute the tool
            tool_call_id = str(uuid.uuid4())
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ],
                }
            )

            try:
                session = self.sessions[server_id]
                logger.info(f"Orakle is calling tool: {tool_name}({tool_args}) on server {server_id}")
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, tool_args), timeout=300
                )
            except asyncio.TimeoutError:
                logger.error(f"Tool call {tool_name} timed out.")
                result = "Tool call timed out."
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}")
                result = f"Error: {str(e)}"

            result = str(result)[:max_tool_tokens]
            messages.append(
                {"role": "tool", "tool_call_id": tool_call_id, "content": result}
            )

            # 4. Synthesize final response
            synthesis_history = messages.copy()
            synthesis_history.append(
                {
                    "role": "system",
                    "content": "Based on the conversation and the result from the tool call, provide a final answer to the user.",
                }
            )
            final_response = self.llm.chat(synthesis_history)
            final_text.append(final_response)
            messages.append({"role": "assistant", "content": final_response})
        except Exception as e:
            logger.error(f"Error processing query '{query}': {e}")
            final_text.append(f"Error: {str(e)}")
            messages.append({"role": "assistant", "content": str(e)})
        self.history = messages
        return "\n".join(final_text), messages


async def main(args):
    # Orakle initialization
    config = ConfigManager()
    config.load_config()

    # Setup LLM for Orakle
    llm_backend = LiteLLM(config.get("llm"))

    # Setup Orakle Matcher
    matcher = OrakleMatcherTransformers()

    # Load tools and register them as skills for Orakle
    tools_file = project_root / "external/LiveMCPBench/tools/LiveMCPTool/tools.json"
    with open(tools_file, "r", encoding="utf-8") as f:
        all_tools_data = json.load(f)

    all_server_configs = {}
    for server_info in all_tools_data:
        all_server_configs.update(
            server_info.get("config", {}).get("mcpServers", {})
        )
        for server_name, tool_list_info in server_info.get("tools", {}).items():
            for tool in tool_list_info.get("tools", []):
                skill_id = tool["name"]
                description = tool["description"]
                # For the initial matching prompt, we only need the high-level description.
                # The detailed args, returns, etc., add noise and unnecessary tokens.
                # We keep the full description for the later argument generation step.
                if description:
                    matcher_info_text = description.split("Args:")[0].strip()
                    if not matcher_info_text:
                        matcher_info_text = description
                else:
                    matcher_info_text = ""
                metadata = {
                    "server_name": server_name,
                    "input_schema": tool["inputSchema"]
                }
                matcher.register_skill(skill_id, matcher_info_text, metadata)

    # Patch server configs to replace 'uvx' with direct command execution
    # This is a workaround for environments where pre-compiled wheels are not available
    # for MCP server dependencies, causing 'uvx' to fail during source compilation.
    for server_name, server_config in all_server_configs.items():
        if server_config.get("command") == "uvx" and server_config.get("args"):
            logger.info(
                f"Patching server config for '{server_name}': Replacing 'uvx' with direct command '{server_config['args'][0]}'."
            )
            server_config["command"] = server_config["args"][0]
            server_config["args"] = server_config["args"][1:]

    if not pathlib.Path(args.input_path).exists():
        logger.error(f"Input queries file {args.input_path} does not exist.")
        return
    with open(args.input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if args.sample_size:
        if args.sample_size > len(data):
            logger.warning(f"Sample size {args.sample_size} is larger than the number of queries {len(data)}. Using all queries.")
        else:
            data = random.sample(data, args.sample_size)

    logger.info(f"Registered {len(matcher.skills_registry)} skills with Orakle.")

    # If sampling, determine required servers to avoid connecting to all of them
    if args.sample_size and data:
        required_servers = set()
        for entry in data:
            query = entry["Question"]
            matches = matcher.match(query, top_k=1)
            if matches:
                best_match = matches[0]
                tool_name = best_match["skill_id"]
                tool_info = matcher.skills_registry[tool_name]
                server_id = tool_info["metadata"]["server_name"]
                required_servers.add(server_id)
        logger.info(f"Identified {len(required_servers)} required servers for the sampled queries.")
        mcp_config = {"mcpServers": {server_name: all_server_configs[server_name] for server_name in required_servers if server_name in all_server_configs}}
    else:
        mcp_config = {"mcpServers": all_server_configs}

    logger.info(f"len(queries): {len(data)}")
    client = LoggingMCPClient(matcher=matcher, llm_backend=llm_backend)
    await client.config_connect(config=mcp_config)
    logger.info(f"Connected to {len(client.sessions)} MCP servers.")
    if os.path.exists(args.output_path):
        with open(args.output_path, "r", encoding="utf-8") as f:
            all_results = json.load(f)
        exist_ids = {entry["task_id"] for entry in all_results}
    else:
        all_results = []
        exist_ids = set()
    error_queries = set()
    try:
        for entry in tqdm(data):
            task_id = entry["task_id"]
            if task_id in exist_ids:
                continue
            query = entry["Question"]
            logger.info(f"{query}")
            try:
                response, messages = await client.process_query(query, None)
                logger.info(f"{response}")
                entry["response"] = response
                entry["messages"] = messages
                all_results.append(entry)

            except Exception:
                error_queries.add(query)
                logger.error(traceback.format_exc())
    finally:
        await client.cleanup()
        os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
        with open(args.output_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))
