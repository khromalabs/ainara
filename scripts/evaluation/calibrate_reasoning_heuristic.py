import csv
import json
import logging
import os
import sys
from typing import Any, Dict, List

from ainara.framework.chat_manager import ChatManager
from ainara.framework.config import config
from ainara.framework.llm import create_llm_backend

# Add project root to Python path
project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, project_root)


# --- Configuration ---
# Set the LLM provider and model you want to use for generation and evaluation
# Ensure this model is configured in your config.yaml
LLM_PROVIDER = "ollama"
LLM_MODEL = "qwen3:14b"
# Number of sample queries to generate
NUM_SAMPLES = 50
# Output file for the results
OUTPUT_FILE = "reasoning_heuristic_calibration_data.csv"

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def generate_test_queries(llm, num_samples: int) -> List[str]:
    """Uses an LLM to generate a diverse set of user queries."""
    logger.info(f"Generating {num_samples} test queries using {LLM_MODEL}...")
    prompt = f"""
You are an expert test case generator for conversational AI. Your mission is to create a diverse and balanced dataset of {num_samples} user queries for an advanced AI assistant. The dataset must cover the full spectrum of complexity, from simple chitchat to deep, analytical requests.

Please generate queries that fall into the following categories, ensuring a good mix of each:

1.  **Simple Interactions (Low Reasoning):**
    *   Greetings and chitchat (e.g., "hello", "how are you?")
    *   Direct factual questions (e.g., "what is the capital of France?")
    *   Simple commands (e.g., "set a timer for 5 minutes")

2.  **Informational Queries (Medium Reasoning):**
    *   Explanations of concepts (e.g., "Explain what a black hole is.")
    *   Comparisons (e.g., "Compare Python and JavaScript for web development.")
    *   Summaries (e.g., "Summarize the plot of Hamlet.")

3.  **Complex & Analytical Queries (High Reasoning):**
    *   In-depth analysis (e.g., "Analyze the economic impact of Brexit on the UK.")
    *   Hypothetical scenarios (e.g., "What if the Roman Empire had access to modern technology?")
    *   Creative and generative tasks (e.g., "Write a short story in the style of Edgar Allan Poe.")
    *   Multi-step instructions (e.g., "Find the top 3 rated sci-fi books from the last decade and give me a brief summary of each.")

4.  **Explicitly Demanding Queries (Very High Reasoning):**
    *   These queries should explicitly use keywords that demand deep thought, evaluation, and synthesis.
    *   Use words like: "critique", "evaluate", "synthesize", "develop a detailed plan for", "conduct a thorough analysis of", "scrutinize", "predict the long-term consequences of".
    *   Examples:
        *   "Critique the main arguments in 'Sapiens: A Brief History of Humankind'."
        *   "Develop a detailed marketing plan for a new sustainable energy startup."
        *   "Synthesize the latest research on quantum computing and explain its potential impact on cryptography."
        *   "Please do a full analysis of my mail inbox"
        *   "Describe in detail, carefully the relevant issues detailed in the attached document"

Ensure the final list is varied in topic and phrasing.

The output must be a single JSON array of strings, with each string being one query. Provide only the JSON array and nothing else.

Example format:
[
  "Hello there!",
  "What is the boiling point of water?",
  "Explain the theory of relativity in simple terms.",
  ...
]
"""
    try:
        response = llm.chat(
            chat_history=[{"role": "user", "content": prompt}],
            stream=False,  # , reasoning_level=1
        )
        # Clean up the response to extract JSON
        json_str = (
            response.strip().replace("```json", "").replace("```", "").strip()
        )
        queries = json.loads(json_str)
        logger.info(f"Successfully generated {len(queries)} queries.")
        return queries
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.error(f"Raw response:\n{response}")
        return []
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during query generation: {e}"
        )
        return []


def evaluate_query_reasoning_level(llm, query: str) -> float:
    """Uses an LLM to evaluate the required reasoning level for a query."""
    logger.debug(f"Evaluating reasoning level for query: '{query}'")
    prompt = f"""
You are an expert in natural language understanding. Your task is to evaluate a user's query and determine the level of reasoning and analytical effort required for an AI assistant to provide a high-quality answer.

Rate the query on a scale from 0.0 to 1.0, where:
- 0.0: No reasoning needed. Simple retrieval, greeting, or direct command. (e.g., "hello", "what time is it?")
- 0.2-0.4: Low reasoning. Requires recalling and structuring information, or a simple explanation. (e.g., "who was Albert Einstein?", "explain what a CPU is")
- 0.5-0.7: Medium reasoning. Requires analysis, comparison, elaboration, or explaining cause-and-effect. (e.g., "compare laptops and desktops", "what are the implications of climate change?")
- 0.8-1.0: High reasoning. Requires deep analysis, synthesis of multiple concepts, critical evaluation, or complex hypothetical thinking. (e.g., "Critique the philosophical arguments for and against free will.", "Develop a detailed business plan for a new tech startup.")

User Query: "{query}"

Provide only a single floating-point number as your rating. Do not include any other text or explanation.
"""
    try:
        response = llm.chat(
            chat_history=[{"role": "user", "content": prompt}], stream=False
        )
        rating = float(response.strip())
        logger.debug(f"Query: '{query}' -> LLM-rated reasoning: {rating}")
        return rating
    except (ValueError, TypeError) as e:
        logger.error(f"Could not convert LLM response to float: {e}")
        logger.error(f"Raw response for query '{query}':\n{response}")
        return 0.0
    except Exception as e:
        logger.error(
            "An unexpected error occurred during evaluation for query"
            f" '{query}': {e}"
        )
        return 0.0


def main():
    """Main script execution."""
    logger.info("Starting reasoning heuristic calibration script.")

    # --- 1. Initialize Framework Components ---
    logger.info("Initializing LLM and ChatManager...")
    try:
        # Load configuration and create LLM backend
        config.load_config()
        llm_config = config.get("llm", {})

        # Override with script-specific settings
        llm_config["provider"] = LLM_PROVIDER
        llm_config["model"] = LLM_MODEL

        llm = create_llm_backend(llm_config)

        if not llm:
            logger.error(
                f"Could not create LLM backend for {LLM_PROVIDER}/{LLM_MODEL}."
                " Check your config."
            )
            return

        # We need a ChatManager instance to access the heuristic calculation,
        # which in turn needs the sentence transformer model from the matcher.
        # We can pass minimal dependencies for this script's purpose.
        chat_manager = ChatManager(
            llm=llm,
            orakle_servers=[],
            green_memories=None,
        )
    except Exception as e:
        logger.error(f"Failed to initialize framework components: {e}")
        logger.error(
            "Please ensure your Ainara environment and configuration are set"
            " up correctly."
        )
        return

    # --- 2. Generate Test Data ---
    queries = generate_test_queries(llm, NUM_SAMPLES)
    if not queries:
        logger.error("No queries were generated. Aborting.")
        return

    # --- 3. Evaluate and Collect Data ---
    results: List[Dict[str, Any]] = []
    logger.info("Evaluating queries and calculating similarity scores...")
    for i, query in enumerate(queries):
        logger.info(f"Processing query {i+1}/{len(queries)}: '{query}'")

        # Get the "ideal" reasoning level from the LLM
        llm_reasoning_level = evaluate_query_reasoning_level(llm, query)

        # Get the raw similarity score from our heuristic function
        # This requires the function to be patched to return this value
        reasoning_heuristic = (
            chat_manager._calculate_reasoning_level_heuristic(query)
        )

        results.append(
            {
                "query": query,
                "llm_reasoning_level": llm_reasoning_level,
                "reasoning_heuristic": reasoning_heuristic,
            }
        )

    # --- 4. Save Results ---
    logger.info(f"Saving {len(results)} results to {OUTPUT_FILE}...")
    try:
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "query",
                    "llm_reasoning_level",
                    "reasoning_heuristic",
                ],
            )
            writer.writeheader()
            writer.writerows(results)
        logger.info("Results saved successfully.")
    except IOError as e:
        logger.error(f"Failed to write to output file: {e}")

    logger.info("Script finished.")
    logger.info(
        "You can now analyze the CSV file to find a better formula for mapping"
        " 'raw_similarity' to a reasoning level."
    )
    logger.info(
        "Consider using a Jupyter notebook or a plotting library to visualize"
        " the relationship."
    )
    logger.info(
        "Example command to install matplotlib: pip install matplotlib pandas"
    )


if __name__ == "__main__":
    main()
