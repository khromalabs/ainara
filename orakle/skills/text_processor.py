from orakle.skill import Skill
from orakle.skills.llm_backend import LiteLLMBackend


class TextProcessor(Skill):
    """Skill for processing text using LLM"""
    
    def __init__(self):
        self.llm = LiteLLMBackend()
        self.system_message = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""
        
    def extract_code_blocks(self, text):
        blocks = []
        in_block = False
        current_block = []

        for line in text.split("\n"):
            if line.strip().startswith("```"):
                if in_block:
                    in_block = False
                else:
                    in_block = True
                continue

            if in_block:
                current_block.append(line)
            elif current_block:
                blocks.append("\n".join(current_block))
                current_block = []

        if current_block:
            blocks.append("\n".join(current_block))

        return "\n\n".join(blocks)

    def run(self, text: str, user_profile: str) -> str:
        """Process text according to user profile"""
        task = f"""
Please adapt the content and language of the following text according to these
five instructions:
1. The language and characteristics of the adapted text must be based in
   this user profile description: "{user_profile}".
2. Generate the output text using an easily readable HTML layout.
3. Don't return a full HTML page just a `div` element containing an
   appropriate title and the processed text.
4. Don't introduce placeholder content.
5. Enclose the adapted text in the described HTML layout inside a
   triple backtick block, as the Markdown standard defines for embedding
   multiline blocks of code.
The text to adapt is:
{text}
"""
        result = self.llm.process_text(task, self.system_message)
        if not result:
            return "no answer"
            
        result_strip = self.extract_code_blocks(result)
        return result_strip if result_strip else result
