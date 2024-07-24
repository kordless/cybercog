# Test header
# This is a test modification of the main.py file

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import json
import traceback
import asyncio

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import FormattedText, PygmentsTokens
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.clipboard import ClipboardData

from util import get_anthropic_api_key
from util import get_username
from util import format_response
from util import get_logger
from util import custom_style

from halo import Halo

from aifunc import ai

# Ensure the cybercog directory exists
cybercog_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(cybercog_dir, exist_ok=True)

# Setup logging
logger = get_logger()

# User
username = get_username()

# Key bindings
bindings = KeyBindings()

# Intercept Ctrl+V
@bindings.add('c-v')
def _(event):
    print("system> Use mouse right-click to paste.")
    clipboard_data = event.app.clipboard.get_data()
    if isinstance(clipboard_data, ClipboardData):
        event.current_buffer.insert_text(clipboard_data.text)

# Build history and session
history_file = os.path.join(cybercog_dir, 'cybercog_history')
history = FileHistory(history_file)
session = PromptSession(history=history, key_bindings=bindings)

def custom_exception_handler(loop, context):
    # Extract the exception
    exception = context.get("exception")
    
    if exception:
        logger.error(f"Caught exception: {exception}")
    else:
        logger.error(f"Caught error: {context['message']}")

    # Log the exception and prevent the program from crashing
    print(f"Unhandled exception: {exception}")
    print("Press ENTER to continue...")

    # Optionally: Handle specific exceptions
    if isinstance(exception, OSError) and exception.winerror == 10038:
        print("Handled WinError 10038")
    else:
        loop.default_exception_handler(context)

async def process_shell_query(username, query, anthropic_token, conversation_history):
    try:
        success, results = await ai(username=username, query=query, anthropic_token=anthropic_token, history=conversation_history)
        
        logger.debug(f"AI response: {results}")

        if success:
            if "response" in results and results["response"] is not None:
                return True, {"explanation": results["response"]}
            elif "function_call" in results:
                try:
                    function_call = results["function_call"]
                    arguments = json.loads(function_call.arguments)
                    function_response = f"Function call: {function_call.name}\nArguments: {json.dumps(arguments, indent=2)}"
                    return True, {"explanation": function_response}
                except json.JSONDecodeError:
                    function_response = f"Function call: {function_call.name}\nArguments (raw): {function_call.arguments}"
                    return True, {"explanation": function_response}
            else:
                error_msg = "An unexpected response format was received."
                print(results)
                print_formatted_text(FormattedText([('class:error', f"system> Error: {error_msg}")]), style=custom_style)
                return False, {"error": error_msg}
        else:
            if "error" in results:
                error_message = results["error"]
                print_formatted_text(FormattedText([('class:error', f"system> Error: {error_message}")]), style=custom_style)
                logger.error(f"Error: {error_message}")
            else:
                error_message = "An unknown error occurred."
                print_formatted_text(FormattedText([('class:error', f"system> Error: {error_message}")]), style=custom_style)
            return False, {"error": error_message}
    except Exception as e:
        error_message = f"Error: {str(e)}"
        print_formatted_text(FormattedText([('class:error', f"system> {error_message}")]), style=custom_style)
        logger.error(error_message)
        logger.error(traceback.format_exc())
        return False, {"error": error_message}

async def main(anthropic_token):
    conversation_history = []  # Initialize conversation history

    while True:
        try:
            current_path = os.getcwd().replace(os.path.expanduser('~'), '~')
            
            prompt_text = [
                ('class:username', f"{username}@"),
                ('class:model', "anthropic "),
                ('class:path', f"{current_path} $ ")
            ]

            question = await session.prompt_async(FormattedText(prompt_text), style=custom_style)

            # Check if the question is empty (user just hit enter)
            if question.strip() == "":
                continue
            
            if question.strip().lower() in ['quit', 'exit']:
                print("system> Bye!")
                return
            
            conversation_history.append({"role": "user", "content": question})
            
            success, results = await process_shell_query(username, question, anthropic_token, conversation_history)
            
            if success and "explanation" in results:
                formatted_response = format_response(results['explanation'])
                print_formatted_text(formatted_response, style=custom_style)
                conversation_history.append({"role": "assistant", "content": results["explanation"]})
            elif not success and "error" in results:
                # Error messages are now handled in process_shell_query, so we don't need to print them here
                pass
            else:
                print_formatted_text(FormattedText([('class:error', "system> An unexpected error occurred.")]), style=custom_style)

        except Exception as e:
            print_formatted_text(FormattedText([('class:error', f"system> Error: {str(e)}")]), style=custom_style)
            logger.error(f"Error: {str(e)}")
            logger.error(traceback.format_exc())

def entry_point():
    # Clear the screen
    os.system('cls' if os.name == 'nt' else 'clear')

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(custom_exception_handler)

    try:
        anthropic_token = get_anthropic_api_key()
        if not anthropic_token:
            raise ValueError("Anthropic API token is not set")
        
        main_task = loop.create_task(main(anthropic_token=anthropic_token))
        loop.run_until_complete(main_task)
    except ValueError as e:
        print_formatted_text(FormattedText([('class:error', f"Error: {str(e)}")]), style=custom_style)
        print_formatted_text(FormattedText([('class:error', "Exiting the program...")]), style=custom_style)
    except KeyboardInterrupt:
        print("system> KeyboardInterrupt received, shutting down...")
    except Exception as e:
        print_formatted_text(FormattedText([('class:error', f"Unexpected error: {str(e)}")]), style=custom_style)
    finally:
        try:
            # Cancel all running tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            
            # Only wait for pending tasks if there are any
            if pending:
                loop.run_until_complete(asyncio.wait(pending, timeout=5))
            
            # Close the loop
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except RuntimeError as e:
            print_formatted_text(FormattedText([('class:warning', f"Runtime error during cleanup: {str(e)}")]), style=custom_style)
        except Exception as e:
            print_formatted_text(FormattedText([('class:error', f"Error during cleanup: {str(e)}")]), style=custom_style)
        
        print_formatted_text(FormattedText([('class:success', "system> Shutdown complete.")]), style=custom_style)

if __name__ == "__main__":
    entry_point()
    