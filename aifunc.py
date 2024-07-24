import json
import logging
import os
import asyncio
from tenacity import retry, wait_random_exponential, stop_after_attempt
from halo import Halo

# Anthropic imports
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock, ToolUseBlock

# Utility imports (assuming these are from your local modules)
from prompt_toolkit import PromptSession, print_formatted_text

# Import helper functions and decorators
from function_wrapper import tools, callable_registry

from util import custom_style
from prompt_toolkit.formatted_text import FormattedText

# Use the current directory for CyberCog files
CYBERCOG_DIR = os.path.abspath(os.path.dirname(__file__))

# Configure logging
log_dir = os.path.join(CYBERCOG_DIR, 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(filename=os.path.join(log_dir, 'cybercog.log'), level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SYSTEM_PROMPT = "If you don't know what tool to use, just make up a tool name you think you need."

async def execute_function_by_name(function_name, **kwargs):
    logging.info(f"Calling {function_name} with arguments {kwargs}")
    try:
        if function_name in callable_registry:
            function_to_call = callable_registry[function_name]
            
            if asyncio.iscoroutinefunction(function_to_call):
                # If it's a coroutine function, await it
                result = await function_to_call(**kwargs)
            else:
                # If it's a regular function, run it in a thread to avoid blocking
                result = await asyncio.to_thread(function_to_call, **kwargs)
            
            return json.dumps(result) if not isinstance(result, str) else result
        else:
            raise ValueError(f"Function {function_name} not found in registry")
    except Exception as e:
        logging.error(f"Error executing function {function_name}: {str(e)}", exc_info=True)
        return json.dumps({"error": str(e)})

@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(3))
async def anthropic_chat_completion_request(messages=None, anthropic_token=None, tools=None, model="claude-3-opus-20240229"):
    """
    Make an asynchronous request to Anthropic's chat completion API.
    """
    client = AsyncAnthropic(api_key=anthropic_token)
    
    if tools:
        anthropic_tools = []
        for tool in tools:
            if 'function' in tool:
                anthropic_tools.append({
                    "name": tool['function']['name'],
                    "description": tool['function']['description'],
                    "input_schema": tool['function']['parameters'],
                })
            else:
                # If the tool is already in Anthropic format, use it as is
                anthropic_tools.append(tool)
        
        function_names = [tool['name'] for tool in anthropic_tools]
    else:
        anthropic_tools = None

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=messages,
            tools=anthropic_tools,
            system=SYSTEM_PROMPT
        )
        return response
    except Exception as e:
        logging.error("Unable to generate Anthropic ChatCompletion response: %s", e)
        raise

async def ai(username="anonymous", query="help", anthropic_token="", history=None):
    text_content = ""
    
    if not anthropic_token:
        raise ValueError("Anthropic token is required")
    
    if history is None:
        history = []

    messages = history

    logging.info(f"Initial length of messages: {len(messages)}")
    total_characters = sum(len(message['content']) for message in messages if 'content' in message and message['content'] is not None)
    logging.info(f"Total characters in all messages: {total_characters}")

    max_function_calls = 6
    function_call_count = 0
    
    while function_call_count < max_function_calls:
        spinner = Halo(text='Calling the model...', spinner='dots')
        spinner.start()
        
        chat_response = await anthropic_chat_completion_request(messages=messages, anthropic_token=anthropic_token, tools=tools)
        if not chat_response:
            spinner.stop()
            return False, {"error": "Failed to get a response from Anthropic"}
        
        logging.info(f"Anthropic response: {chat_response}")
        
        function_calls = []

        for content_item in chat_response.content:
            if isinstance(content_item, TextBlock):
                text_content += content_item.text
            elif isinstance(content_item, ToolUseBlock):    
                function_calls.append({
                    "name": content_item.name,
                    "arguments": content_item.input,
                    "id": content_item.id
                })

        logging.info(f"Extracted function calls: {function_calls}")
        logging.info(f"Extracted text content: {text_content}")

        if not function_calls:
            # AI provided a direct response without calling any functions
            spinner.stop()
            return True, {"response": text_content.strip()}
        spinner.stop()

        async def execute_function(func_call):
            print_formatted_text(FormattedText([('class:bold', f"Executing function: {func_call['name']}")]), style=custom_style)

            result = await execute_function_by_name(func_call["name"], **func_call["arguments"])
            return {"id": func_call["id"], "result": result}

        function_results = await asyncio.gather(*[execute_function(func_call) for func_call in function_calls])

        # Update messages with function calls and results
        new_message_content = []
        if text_content.strip():
            new_message_content.append({
                "type": "text",
                "text": text_content.strip()
            })

        for func_call in function_calls:
            func_call["arguments"].pop("spinner", None)
            new_message_content.append({
                "type": "tool_use",
                "id": func_call["id"],
                "name": func_call["name"],
                "input": func_call["arguments"]
            })

        if new_message_content:
            messages.append({
                "role": "assistant",
                "content": new_message_content
            })

        for func_call, result in zip(function_calls, function_results):
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": func_call["id"],
                        "content": result["result"]
                    }
                ]
            })

        function_call_count += len(function_calls)

    # Formulate final response using the tool results
    final_response = await anthropic_chat_completion_request(messages=messages, anthropic_token=anthropic_token, tools=tools)
    if not final_response:
        return False, {"error": "Failed to get a final response from Anthropic"}
    
    final_text_content = ""
    for content_item in final_response.content:
        if isinstance(content_item, TextBlock):
            final_text_content += content_item.text
    
    if not final_text_content:
        return False, {"error": "No text content in Anthropic final response"}
    
    return True, {"response": final_text_content.strip()}