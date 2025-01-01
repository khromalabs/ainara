from abc import ABC, abstractmethod


 class LLMBackend(ABC):
     """Abstract base class for LLM backends"""

     @abstractmethod
     def process_text(self, text: str, system_message: str = "") -> str:
         """Process text using the LLM backend"""
         pass


 class LiteLLMBackend(LLMBackend):
     """LiteLLM implementation of LLM backend"""

     def __init__(self):
         from litellm import completion
         import os

         self.completion = completion
         self.provider = {
             "model": os.environ.get("AI_API_MODEL"),
             "api_base": os.environ.get("OPENAI_API_BASE"),
             "api_key": os.environ.get("OPENAI_API_KEY"),
         }

     def process_text(self, text: str, system_message: str = "") -> str:
         """Process text using LiteLLM"""
         messages = [
             {"role": "system", "content": system_message},
             {"role": "user", "content": text}
         ]

         try:
             completion_kwargs = {
                 "model": self.provider["model"],
                 "messages": messages,
                 "temperature": 0.2,
                 "stream": False,
                 "api_base": self.provider["api_base"],
                 "api_key": self.provider["api_key"]
             }

             response = self.completion(**completion_kwargs)

             if hasattr(response.choices[0], "message"):
                 answer = response.choices[0].message.content
             else:
                 answer = response.choices[0].text

             return answer.rstrip("\n")

         except Exception as e:
             print(f"\nError: Unable to get a response from the AI: {str(e)}")
             return ""
