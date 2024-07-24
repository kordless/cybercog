import os
import sys
import string
import random
from configparser import ConfigParser
from datetime import datetime

from coolname import generate_slug

import re
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import input_dialog
from prompt_toolkit.styles import Style

import logging

# Ensure the cybercog directory exists
cybercog_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(cybercog_dir, exist_ok=True)

# Constants for configuration directory and file
CONFIG_DIR = cybercog_dir
CONFIG_FILE_PATH = os.path.join(CONFIG_DIR, "cybercog_config")

# Initialize configuration parser
config = ConfigParser()

def setup_logging(log_level=logging.INFO):
    log_dir = os.path.join(cybercog_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'cybercog.log'), encoding='utf-8'),
        ]
    )
    
    return logging.getLogger(__name__)

def get_logger():
    return logging.getLogger(__name__)

logger = setup_logging()

def ensure_config_dir_exists():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def read_config():
    ensure_config_dir_exists()
    config.read(CONFIG_FILE_PATH)

def write_config():
    ensure_config_dir_exists()
    with open(CONFIG_FILE_PATH, "w") as f:
        config.write(f)

def set_config_value(section, key, value):
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, str(value))  # Convert value to string
    write_config()

def get_config_value(section, key):
    if config.has_option(section, key):
        return config.get(section, key)
    return None

def create_and_check_directory(directory_path):
    try:
        os.makedirs(directory_path, exist_ok=True)
        logger.info(f"Directory '{directory_path}' ensured to exist.")
        if os.path.isdir(directory_path):
            logger.info(f"Confirmed: The directory '{directory_path}' exists.")
        else:
            logger.error(f"Error: The directory '{directory_path}' was not found after creation attempt.")
    except Exception as e:
        logger.error(f"An error occurred while creating the directory: {e}")

def extract_urls(query):
    url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+')
    return url_pattern.findall(query)

def list_files(directory):
    file_list = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for file in files:
            if not (file.endswith(".pyc") or file.startswith(".")):
                file_path = os.path.join(root, file)
                file_list.append(file_path)
    return file_list

def random_string(size=6, chars=string.ascii_letters + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

def set_username(username):
    set_config_value("config", "username", username)
    return username

def get_username():
    username = get_config_value("config", "username")
    if username:
        print(f"You are logged in as `{username}`.")
        return username
    else:
        username = generate_slug(2)
        return set_username(username)

###############################################################################
#                               Anthropic Setup                               #
###############################################################################
import anthropic

def check_anthropic_token(anthropic_token):
    try:
        client = anthropic.Anthropic(api_key=anthropic_token)
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=10,
            temperature=0,
            system="Respond with 'Token verified' if this message is received.",
            messages=[
                {
                    "role": "user",
                    "content": "Verify token"
                }
            ]
        )
        if "Token verified" in message.content[0].text:
            print("Anthropic API token verified successfully.")
            return True
        else:
            print("Unexpected response from Anthropic API.")
            return False
    except Exception as e:
        print(f"Error verifying Anthropic API token: {str(e)}")
        return False

def get_anthropic_api_key():
    anthropic_token = os.getenv("ANTHROPIC_API_KEY") or get_config_value("config", "ANTHROPIC_API_KEY")
    if anthropic_token == "NONE":
        return None
    
    if anthropic_token and check_anthropic_token(anthropic_token):
        return anthropic_token
    
    anthropic_token = input_dialog(
        title="Anthropic API Key",
        text="Enter your Anthropic API key (Enter to skip):"
    ).run()

    if anthropic_token == '':  # User hit Enter without providing a token
        print("Anthropic token entry cancelled.")
        set_config_value("config", "ANTHROPIC_API_KEY", "NONE")
        return None

    if anthropic_token:
        if check_anthropic_token(anthropic_token):
            set_config_value("config", "ANTHROPIC_API_KEY", anthropic_token)
            return anthropic_token
        else:
            print("Invalid Anthropic token. Skipping.")
    return None

def set_anthropic_api_key(api_key):
    set_config_value("config", "ANTHROPIC_API_KEY", api_key)
import re

def format_response(response):
    if response is None:
        return FormattedText([('class:error', "No response to format.\n")])
    
    formatted_text = []
    
    # Define non-XML delimiters and their corresponding styles
    delimiters = {
        'code': ('```', '```', 'class:code'),
        'inline_code': ('`', '`', 'class:inline-code'),
        'bold': ('**', '**', 'class:bold'),
        'math': (r'\(', r'\)', 'class:math')
    }
    
    # Regex pattern to match all non-XML delimiters
    delimiter_pattern = '|'.join(f'({re.escape(start)}.*?{re.escape(end)})' for start, end, _ in delimiters.values())
    
    # Regex pattern to match XML-style tags
    xml_pattern = r'(<[a-zA-Z]+>.*?</[a-zA-Z]+>)'
    
    # Combine patterns
    pattern = f'{delimiter_pattern}|{xml_pattern}'
    pattern = re.compile(pattern, re.DOTALL)
    
    # Split the response into delimited and non-delimited parts
    parts = re.split(pattern, response)
    
    for part in parts:
        if not part:  # Skip empty parts
            continue
        
        # Check if the part is a non-XML delimiter
        for key, (start, end, style) in delimiters.items():
            if part.startswith(start) and part.endswith(end):
                content = part[len(start):-len(end)]
                if key == 'code':
                    # For code blocks, preserve existing line breaks
                    formatted_text.append((style, content))
                else:
                    # For other delimited content, strip whitespace
                    formatted_text.append((style, content.strip()))
                break
        else:
            # Check if the part is an XML-style tag
            xml_match = re.match(r'<([a-zA-Z]+)>(.*?)</\1>', part, re.DOTALL)
            if xml_match:
                tag, content = xml_match.groups()
                formatted_text.append((f'class:{tag}', content.strip()))
            else:
                # Non-delimited content
                lines = part.split('\n')
                for i, line in enumerate(lines):
                    if line.strip():  # Skip empty lines
                        if line.startswith('#'):
                            # Handle headers
                            level = len(line.split()[0])
                            formatted_text.append(('class:header', line[level:].strip()))
                        else:
                            formatted_text.append(('', line.rstrip()))
                    
                    # Add a newline after each line, except for the last one
                    if i < len(lines) - 1:
                        formatted_text.append(('', '\n'))
    
    # Ensure the entire response ends with a newline
    if formatted_text and not formatted_text[-1][1].endswith('\n'):
        formatted_text.append(('', '\n'))
    
    return FormattedText(formatted_text)

# Styles
custom_style = Style.from_dict({
    'code': '#ansicyan',
    'header': '#ansigreen bold',
    'thinking': '#ansiblue italic',
    'bold': 'bold',
    'inline-code': '#ansiyellow',
    'error': '#ansired bold',
    'warning': '#ansiyellow',
    'success': '#ansigreen',
    'math': '#ansimagenta',
    'emoji': '#ansibrightmagenta',
    'username': '#ansigreen bold',
    'model': '#ansiyellow bold',
    'path': '#ansicyan',
    'instruction': '#ansibrightgreen',
})

# Initialize configuration
read_config()