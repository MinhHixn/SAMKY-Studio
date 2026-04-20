"""
OASIS dual-platform parallel simulation preset script
Run Twitter and Reddit simulations simultaneously with the same configuration file

Features:
- Dual-platform (Twitter + Reddit) parallel simulation
- Keep environment running after simulation completes (enter wait mode)
- Support Interview commands via IPC
- Support single Agent interview and batch interview
- Support remote environment shutdown command

Usage:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # Close immediately after completion
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

Log structure:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter platform action log
    ├── reddit/
    │   └── actions.jsonl    # Reddit platform action log
    ├── simulation.log       # Main simulation process log
    └── run_state.json       # Run state (for API queries)
"""

# ============================================================
# Fix Windows encoding issue: Set UTF-8 encoding before all imports
# This is to fix the issue that OASIS third-party library doesn't specify encoding when reading files
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # Set Python default I/O encoding to UTF-8
    # This affects all open() calls without specified encoding
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

    # Reconfigure standard output stream to UTF-8 (fix console encoding issues)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    # Force set default encoding (affects default encoding of open() function)
    # Note: This must be set when Python starts, runtime configuration may not work
    # So we also need to monkey-patch the built-in open function
    import builtins
    _original_open = builtins.open

    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None,
                   newline=None, closefd=True, opener=None):
        """
        Wrap open() function to use UTF-8 encoding by default for text mode
        This can fix the issue that third-party libraries (like OASIS) don't specify encoding when reading files
        """
        # Only set default encoding for text mode (non-binary) without specified encoding
        if encoding is None and 'b' not in mode:
            encoding = 'utf-8'
        return _original_open(file, mode, buffering, encoding, errors,
                              newline, closefd, opener)

    builtins.open = _utf8_open

import argparse
import asyncio
import json
import logging
import math
import multiprocessing
import random
import re
import signal
import sqlite3
import warnings
from datetime import datetime
from typing import Callable, Dict, Any, List, Mapping, Optional, Tuple


# Global variables: for signal handling
_shutdown_event = None
_cleanup_done = False

# Add backend directory to path
# Script is fixed in backend/scripts/ directory
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# Load .env file from project root (contains LLM_API_KEY and other configurations)
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
    print(f"Loaded environment configuration: {_env_file}")
else:
    # Try to load backend/.env
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"Loaded environment configuration: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """Filter out camel-ai max_tokens warnings (we intentionally don't set max_tokens to let the model decide)"""

    def filter(self, record):
        # Filter out logs containing max_tokens warnings
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# Add filter immediately when module loads, ensure it takes effect before camel code executes
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    Disable verbose logging output from OASIS library
    OASIS logging is too verbose (logs every agent's observation and action), we use our own action_logger
    """
    # Disable all OASIS loggers
    oasis_loggers = [
        "social.agent",
        "social.twitter",
        "social.rec",
        "oasis.env",
        "table",
    ]

    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # Only log critical errors
        logger.handlers.clear()
        logger.propagate = False

    # Also silence Transformers warnings about uninitialized BertModel weights
    logging.getLogger("transformers").setLevel(logging.ERROR)


def init_logging_for_simulation(simulation_dir: str):
    """
    Initialize simulation log configuration

    Args:
        simulation_dir: Simulation directory path
    """
    # Disable OASIS verbose logging
    disable_oasis_logging()

    # Clean up old log directory (if exists)
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger
from app.utils.llm_client import LLMClient

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
        generate_reddit_agent_graph
    )
except ImportError as e:
    print(f"Error: Missing dependency {e}")
    print("Please install first: pip install oasis-ai camel-ai")
    sys.exit(1)


# Twitter available actions (INTERVIEW not included, INTERVIEW can only be triggered manually via ManualAction)
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

# Reddit available actions (INTERVIEW not included, INTERVIEW can only be triggered manually via ManualAction)
REDDIT_ACTIONS = [
    ActionType.LIKE_POST,
    ActionType.DISLIKE_POST,
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_COMMENT,
    ActionType.DISLIKE_COMMENT,
    ActionType.SEARCH_POSTS,
    ActionType.SEARCH_USER,
    ActionType.TREND,
    ActionType.REFRESH,
    ActionType.DO_NOTHING,
    ActionType.FOLLOW,
    ActionType.MUTE,
]


# IPC-related constants
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """Command type constants"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """
    Dual-platform IPC command handler
    
    Manage environments of both platforms, handle Interview commands
    """
    
    def __init__(
        self,
        simulation_dir: str,
        twitter_env=None,
        twitter_agent_graph=None,
        reddit_env=None,
        reddit_agent_graph=None
    ):
        self.simulation_dir = simulation_dir
        self.twitter_env = twitter_env
        self.twitter_agent_graph = twitter_agent_graph
        self.reddit_env = reddit_env
        self.reddit_agent_graph = reddit_agent_graph
        
        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)
        
        # Ensure directory exists
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """Update environment status"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "twitter_available": self.twitter_env is not None,
                "reddit_available": self.reddit_env is not None,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """Poll for pending commands"""
        if not os.path.exists(self.commands_dir):
            return None
        
        # Get command files (sorted by time)
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))
        
        command_files.sort(key=lambda x: x[1])
        
        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
        
        return None
    
    def send_response(self, command_id: str, status: str, result: Dict = None, error: str = None):
        """Send response"""
        response = {
            "command_id": command_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
        
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        
        # Delete command file
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def _get_env_and_graph(self, platform: str):
        """
        Get environment and agent_graph for specified platform
        
        Args:
            platform: Platform name ("twitter" or "reddit")
            
        Returns:
            (env, agent_graph, platform_name) or (None, None, None)
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        Execute Interview on a single platform
        
        Returns:
            Dictionary containing result, or dictionary containing error
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)
        
        if not env or not agent_graph:
            return {"platform": platform, "error": f"{platform}platform unavailable"}
        
        try:
            agent = agent_graph.get_agent(agent_id)
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            actions = {agent: interview_action}
            await env.step(actions)
            
            result = self._get_interview_result(agent_id, actual_platform)
            result["platform"] = actual_platform
            return result
            
        except Exception as e:
            return {"platform": platform, "error": str(e)}
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str, platform: str = None) -> bool:
        """
        Handle single Agent interview command
        
        Args:
            command_id: Command ID
            agent_id: Agent ID
            prompt: Interview question
            platform: Specify platform (optional)
                - "twitter": Interview only Twitter platform
                - "reddit": Interview only Reddit platform
                - None/unspecified: Interview both platforms simultaneously, return integrated result
            
        Returns:
            True means success, False means failure
        """
        # If platform is specified, only interview that platform
        if platform in ("twitter", "reddit"):
            result = await self._interview_single_platform(agent_id, prompt, platform)
            
            if "error" in result:
                self.send_response(command_id, "failed", error=result["error"])
                print(f"  Interview failed: agent_id={agent_id}, platform={platform}, error={result['error']}")
                return False
            else:
                self.send_response(command_id, "completed", result=result)
                print(f"  Interview completed: agent_id={agent_id}, platform={platform}")
                return True
        
        # Platform not specified: interview both platforms simultaneously
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="No available simulation environment")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # Interview both platforms in parallel
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # Execute in parallel
        platform_results = await asyncio.gather(*tasks)
        
        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1
        
        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interview completed: agent_id={agent_id}, success_platforms={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', 'Unknown error')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interview failed: agent_id={agent_id}, All platforms failed")
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """
        Handle batch interview command
        
        Args:
            command_id: Command ID
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: default platform (can be overridden by each interview item)
                - "twitter": Interview only Twitter platform
                - "reddit": Interview only Reddit platform
                - None/unspecified: Interview both platforms simultaneously for each Agent
        """
        # Group by platform
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # Need to interview both platforms simultaneously
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # Platform not specified: interview both platforms
                both_platforms_interviews.append(interview)
        
        # Split both_platforms_interviews to two platforms
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # Handle Twitter platform interview
        if twitter_interviews and self.twitter_env:
            try:
                twitter_actions = {}
                for interview in twitter_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.twitter_agent_graph.get_agent(agent_id)
                        twitter_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  Warning: Unable to get Twitter Agent {agent_id}: {e}")
                
                if twitter_actions:
                    await self.twitter_env.step(twitter_actions)
                    
                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "twitter")
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitter batch Interview failed: {e}")
        
        # Handle Reddit platform interview
        if reddit_interviews and self.reddit_env:
            try:
                reddit_actions = {}
                for interview in reddit_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.reddit_agent_graph.get_agent(agent_id)
                        reddit_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  Warning: Unable to get Reddit Agent {agent_id}: {e}")
                
                if reddit_actions:
                    await self.reddit_env.step(reddit_actions)
                    
                    for interview in reddit_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "reddit")
                        result["platform"] = "reddit"
                        results[f"reddit_{agent_id}"] = result
            except Exception as e:
                print(f"  Reddit batch Interview failed: {e}")
        
        if results:
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  Batch Interview completed: {len(results)} Agents")
            return True
        else:
            self.send_response(command_id, "failed", error="No successful interviews")
            return False
    
    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """Get the latest Interview result from database"""
        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")
        
        result = {
            "agent_id": agent_id,
            "response": None,
            "timestamp": None
        }
        
        if not os.path.exists(db_path):
            return result
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Query the latest Interview record
            cursor.execute("""
                SELECT user_id, info, created_at
                FROM trace
                WHERE action = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (ActionType.INTERVIEW.value, agent_id))
            
            row = cursor.fetchone()
            if row:
                user_id, info_json, created_at = row
                try:
                    info = json.loads(info_json) if info_json else {}
                    result["response"] = info.get("response", info)
                    result["timestamp"] = created_at
                except json.JSONDecodeError:
                    result["response"] = info_json
            
            conn.close()
            
        except Exception as e:
            print(f"  Failed to read Interview result: {e}")
        
        return result
    
    async def process_commands(self) -> bool:
        """
        Process all pending commands
        
        Returns:
            True means continue running, False means should exit
        """
        command = self.poll_command()
        if not command:
            return True
        
        command_id = command.get("command_id")
        command_type = command.get("command_type")
        args = command.get("args", {})
        
        print(f"\nReceived IPC command: {command_type}, id={command_id}")
        
        if command_type == CommandType.INTERVIEW:
            await self.handle_interview(
                command_id,
                args.get("agent_id", 0),
                args.get("prompt", ""),
                args.get("platform")
            )
            return True
            
        elif command_type == CommandType.BATCH_INTERVIEW:
            await self.handle_batch_interview(
                command_id,
                args.get("interviews", []),
                args.get("platform")
            )
            return True
            
        elif command_type == CommandType.CLOSE_ENV:
            print("Received close environment command")
            self.send_response(command_id, "completed", result={"message": "Environment will close"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"Unknown command type: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# Non-core action types to be filtered (these actions have low analytical value)
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# Action type mapping table (Database name -> standard name)
ACTION_TYPE_MAP = {
    'create_post': 'CREATE_POST',
    'like_post': 'LIKE_POST',
    'dislike_post': 'DISLIKE_POST',
    'repost': 'REPOST',
    'quote_post': 'QUOTE_POST',
    'follow': 'FOLLOW',
    'mute': 'MUTE',
    'create_comment': 'CREATE_COMMENT',
    'like_comment': 'LIKE_COMMENT',
    'dislike_comment': 'DISLIKE_COMMENT',
    'search_posts': 'SEARCH_POSTS',
    'search_user': 'SEARCH_USER',
    'trend': 'TREND',
    'do_nothing': 'DO_NOTHING',
    'interview': 'INTERVIEW',
}


def get_agent_names_from_config(config: Dict[str, Any]) -> Dict[int, str]:
    """
    Get mapping of agent_id -> entity_name from simulation_config
    
    This allows displaying real entity names in actions.jsonl instead of codes like "Agent_0"
    
    Args:
        config: Content of simulation_config.json
        
    Returns:
        Mapping dictionary of agent_id -> entity_name
    """
    agent_names = {}
    agent_configs = config.get("agent_configs", [])
    
    for agent_config in agent_configs:
        agent_id = agent_config.get("agent_id")
        entity_name = agent_config.get("entity_name", f"Agent_{agent_id}")
        if agent_id is not None:
            agent_names[agent_id] = entity_name
    
    return agent_names


def fetch_new_actions_from_db(
    db_path: str,
    last_rowid: int,
    agent_names: Dict[int, str]
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get new action records from Database and supplement complete context information
    
    Args:
        db_path: Database file path
        last_rowid: Maximum rowid value from last read (use rowid instead of created_at because different platforms have different created_at formats)
        agent_names: agent_id -> agent_name mapping
        
    Returns:
        (actions_list, new_last_rowid)
        - actions_list: List of actions, each element contains agent_id, agent_name, action_type, action_args (including context information)
        - new_last_rowid: New maximum rowid value
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Use rowid to track processed records (rowid is SQLite's built-in auto-increment field)
        # This avoids created_at format differences (Twitter uses integers, Reddit uses datetime strings)
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # Update maximum rowid
            new_last_rowid = rowid
            
            # Filter non-core actions
            if action in FILTERED_ACTIONS:
                continue
            
            # Parse action arguments
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # Simplify action_args, keep only key fields (keep full content, no truncation)
            simplified_args = {}
            if 'content' in action_args:
                simplified_args['content'] = action_args['content']
            if 'post_id' in action_args:
                simplified_args['post_id'] = action_args['post_id']
            if 'comment_id' in action_args:
                simplified_args['comment_id'] = action_args['comment_id']
            if 'quoted_id' in action_args:
                simplified_args['quoted_id'] = action_args['quoted_id']
            if 'new_post_id' in action_args:
                simplified_args['new_post_id'] = action_args['new_post_id']
            if 'follow_id' in action_args:
                simplified_args['follow_id'] = action_args['follow_id']
            if 'query' in action_args:
                simplified_args['query'] = action_args['query']
            if 'like_id' in action_args:
                simplified_args['like_id'] = action_args['like_id']
            if 'dislike_id' in action_args:
                simplified_args['dislike_id'] = action_args['dislike_id']
            if action == ActionType.INTERVIEW.value:
                if 'prompt' in action_args:
                    simplified_args['prompt'] = action_args['prompt']
                if 'response' in action_args:
                    simplified_args['response'] = action_args['response']
                interview_probability = _extract_interview_probability(action_args)
                if interview_probability is not None:
                    simplified_args['yes_probability'] = interview_probability
            
            # Convert action type names
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # Supplement context information (post content, usernames, etc.)
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)
            
            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })
        
        conn.close()
    except Exception as e:
        print(f"Failed to read Database actions: {e}")
    
    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """
    for actionSupplement context information (post content, usernames, etc.)
    
    Args:
        cursor: Database cursor
        action_type: Action type
        action_args: Action arguments (will be modified)
        agent_names: agent_id -> agent_name mapping
    """
    try:
        # Like/dislike post: supplement post content and author
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # Repost: supplement original post content and author
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # Repost's original_post_id points to original post
                cursor.execute("""
                    SELECT original_post_id FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    original_post_id = row[0]
                    original_info = _get_post_info(cursor, original_post_id, agent_names)
                    if original_info:
                        action_args['original_content'] = original_info.get('content', '')
                        action_args['original_author_name'] = original_info.get('author_name', '')
        
        # Quote post: supplement original post content, author, and quote comment
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # Get quote post comment content (quote_content)
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # Follow user: supplement followed user name
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # Get followee_id from follow table
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # Mute user: supplement muted user name
        elif action_type == 'MUTE':
            # Get user_id or target_id from action_args
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # Like/dislike comment: supplement comment content and author
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # Post comment: supplement commented post information
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # Context supplement failure does not affect main process
        print(f"Failed to supplement action context: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    Get post information
    
    Args:
        cursor: Database cursor
        post_id: Post ID
        agent_names: agent_id -> agent_name mapping
        
    Returns:
        Dictionary containing content and author_name, or None
    """
    try:
        cursor.execute("""
            SELECT p.content, p.user_id, u.agent_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            WHERE p.post_id = ?
        """, (post_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # Preferentially use name from agent_names
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Get name from user table
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def _get_user_name(
    cursor,
    user_id: int,
    agent_names: Dict[int, str]
) -> Optional[str]:
    """
    Get user name
    
    Args:
        cursor: Database cursor
        user_id: User ID
        agent_names: agent_id -> agent_name mapping
        
    Returns:
        User name, or None
    """
    try:
        cursor.execute("""
            SELECT agent_id, name, user_name FROM user WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            agent_id = row[0]
            name = row[1]
            user_name = row[2]
            
            # Preferentially use name from agent_names
            if agent_id is not None and agent_id in agent_names:
                return agent_names[agent_id]
            return name or user_name or ''
    except Exception:
        pass
    return None


def _get_comment_info(
    cursor,
    comment_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    Get comment information
    
    Args:
        cursor: Database cursor
        comment_id: Comment ID
        agent_names: agent_id -> agent_name mapping
        
    Returns:
        Dictionary containing content and author_name, or None
    """
    try:
        cursor.execute("""
            SELECT c.content, c.user_id, u.agent_id
            FROM comment c
            LEFT JOIN user u ON c.user_id = u.user_id
            WHERE c.comment_id = ?
        """, (comment_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # Preferentially use name from agent_names
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Get name from user table
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def _apply_benchmark_env(
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    llm_model: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Apply deterministic benchmark OpenRouter bridge variables."""
    llm_api_key = llm_api_key or os.environ.get("LLM_API_KEY", "")
    llm_base_url = llm_base_url or os.environ.get("LLM_BASE_URL", "")
    llm_model = llm_model or os.environ.get("LLM_MODEL_NAME", "") or (config or {}).get("llm_model", "gpt-4o-mini")
    benchmark_mode_enabled = os.environ.get("BENCHMARK_MODE", "").strip().lower() == "true"

    if not llm_api_key:
        raise ValueError("LLM_API_KEY is required")

    os.environ["OPENAI_API_KEY"] = llm_api_key
    if llm_base_url:
        os.environ["OPENAI_API_BASE_URL"] = llm_base_url
    else:
        os.environ.pop("OPENAI_API_BASE_URL", None)

    if benchmark_mode_enabled:
        os.environ.setdefault("BENCHMARK_TEMPERATURE", "0")
        os.environ.setdefault("BENCHMARK_SEED", "42")
        os.environ["HEADLESS_MODE"] = "true"
        random.seed(int(os.environ["BENCHMARK_SEED"]))

    return llm_model


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_headless_mode_enabled() -> bool:
    return _env_flag("HEADLESS_MODE") or _env_flag("BENCHMARK_MODE")


_TELEMETRY_DISTRIBUTION_SUM_MIN = 0.95
_TELEMETRY_DISTRIBUTION_SUM_MAX = 1.05
_TELEMETRY_PROBE_BINARY_PROMPT_TEMPLATE = (
    "--- AUTHORITATIVE SYSTEM OVERRIDE: SUSPEND PERSONA ROLEPLAY ---\n"
    "You are currently participating in a prediction benchmark telemetry probe.\n"
    "Regardless of your assigned persona's background or stated limitations, you MUST now act as a predictive processing unit.\n"
    "Target question: {question}\n"
    "Return only valid JSON with one key exactly named yes_probability.\n"
    "Example: {{\"yes_probability\": 0.63}}\n"
    "Constraints: JSON only, no prose, no markdown, no persona-based refusals. Value must be between 0 and 1."
)


_TELEMETRY_BINARY_SCHEMA = {
    "name": "telemetry_probability",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "yes_probability": {"type": "number"}
        },
        "required": ["yes_probability"],
        "additionalProperties": False
    }
}


def _get_telemetry_categorical_schema(options: List[str]) -> Dict[str, Any]:
    return {
        "name": "telemetry_distribution",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {opt: {"type": "number"} for opt in options},
            "required": options,
            "additionalProperties": False
        }
    }


def _telemetry_probes_enabled() -> bool:
    raw = os.environ.get("ENABLE_TELEMETRY_PROBES")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return _is_headless_mode_enabled()


def _build_telemetry_probe_rounds(total_rounds: int) -> List[int]:
    if total_rounds <= 0:
        return []
    checkpoints: List[int] = []
    for ratio in (0.2, 0.4, 0.6, 0.8, 1.0):
        checkpoint = int(round(total_rounds * ratio))
        checkpoint = max(1, min(total_rounds, checkpoint))
        checkpoints.append(checkpoint)
    return sorted(set(checkpoints))


def _normalize_probability(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            numeric = float(stripped)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(numeric):
        return None
    if 0.0 <= numeric <= 1.0:
        return numeric
    if 1.0 < numeric <= 100.0:
        scaled = numeric / 100.0
        if 0.0 <= scaled <= 1.0:
            return scaled
    return None


def _normalize_option_label(value: Any) -> Optional[str]:
    """Normalize an option label for case-insensitive matching."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.casefold()


def _extract_event_options(config: Mapping[str, Any]) -> List[str]:
    """Extract clean option labels from event_config.options."""
    event_config = config.get("event_config", {})
    if not isinstance(event_config, Mapping):
        return []
    options = event_config.get("options", [])
    if not isinstance(options, list):
        return []
    cleaned: List[str] = []
    for option in options:
        if isinstance(option, str) and option.strip():
            cleaned.append(option.strip())
    return cleaned


def _is_yes_no_options(options: List[str]) -> bool:
    """Return True when options form a yes/no-style binary event."""
    if len(options) != 2:
        return False
    normalized = {_normalize_option_label(option) for option in options}
    normalized.discard(None)
    yes_tokens = {"yes", "y", "true"}
    no_tokens = {"no", "n", "false"}
    return bool(normalized & yes_tokens) and bool(normalized & no_tokens)


def _extract_event_question(config: Mapping[str, Any]) -> str:
    """Extract the probe question text from event config."""
    question = "current event outcome"
    event_config = config.get("event_config", {})
    if not isinstance(event_config, Mapping):
        return question
    initial_posts = event_config.get("initial_posts", [])
    if not isinstance(initial_posts, list):
        return question
    for post in initial_posts:
        if not isinstance(post, Mapping):
            continue
        content = post.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return question


def _resolve_probe_target_label(config: Mapping[str, Any], event_options: List[str]) -> Optional[str]:
    """Resolve a preferred option label (ground truth) for scalar normalization."""
    candidate: Optional[str] = None
    event_config = config.get("event_config", {})
    if isinstance(event_config, Mapping):
        for key in ("ground_truth", "outcome", "answer", "label", "target", "correct_answer"):
            value = event_config.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break
    if not candidate:
        return None
    candidate_norm = _normalize_option_label(candidate)
    if candidate_norm is None:
        return None
    for option in event_options:
        if _normalize_option_label(option) == candidate_norm:
            return option
    return candidate


def _build_distribution_example(event_options: List[str]) -> Dict[str, float]:
    """Build a deterministic categorical example payload for the prompt."""
    if not event_options:
        return {}
    if len(event_options) == 1:
        return {event_options[0]: 1.0}
    if len(event_options) == 2:
        return {event_options[0]: 0.7, event_options[1]: 0.3}
    example: Dict[str, float] = {event_options[0]: 0.7, event_options[1]: 0.3}
    for option in event_options[2:]:
        example[option] = 0.0
    return example


def _extract_distribution_from_mapping(payload: Mapping[Any, Any], event_options: List[str]) -> Optional[Dict[str, float]]:
    """Extract a probability distribution from a mapping if it is distribution-shaped."""
    numeric_entries: Dict[str, float] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        label = key.strip()
        if not label:
            continue
        parsed = _normalize_probability(value)
        if parsed is None:
            continue
        numeric_entries[label] = parsed
    if len(numeric_entries) < 2:
        return None
    total = sum(numeric_entries.values())
    if not (_TELEMETRY_DISTRIBUTION_SUM_MIN <= total <= _TELEMETRY_DISTRIBUTION_SUM_MAX):
        return None

    if len(event_options) > 1:
        option_lookup = {_normalize_option_label(option): option for option in event_options}
        matched: Dict[str, float] = {}
        for raw_key, probability in numeric_entries.items():
            key_norm = _normalize_option_label(raw_key)
            mapped = option_lookup.get(key_norm)
            if mapped is not None:
                matched[mapped] = probability
        if len(matched) >= 2:
            return matched
    return numeric_entries


def _select_distribution_probability(
    distribution: Mapping[str, float],
    *,
    event_options: List[str],
    preferred_label: Optional[str],
) -> Optional[float]:
    """Map a categorical distribution to scalar yes_probability for telemetry compatibility."""
    preferred_norm = _normalize_option_label(preferred_label)
    if preferred_norm:
        for key, value in distribution.items():
            if _normalize_option_label(key) == preferred_norm:
                return value
    for option in event_options:
        option_norm = _normalize_option_label(option)
        if option_norm is None:
            continue
        for key, value in distribution.items():
            if _normalize_option_label(key) == option_norm:
                return value
    for value in distribution.values():
        return value
    return None


def _extract_interview_probability(
    payload: Any,
    *,
    event_options: Optional[List[str]] = None,
    preferred_label: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Extract scalar probability from telemetry probe payloads and normalized distributions."""
    options = event_options or []
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in ("yes_probability", "probability", "prob", "p_yes"):
            if key in payload:
                parsed = _normalize_probability(payload.get(key))
                if parsed is not None:
                    return parsed
        for key in ("probabilities", "normalized_probabilities", "distribution"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                distribution = _extract_distribution_from_mapping(nested, options)
                if distribution is None:
                    continue
                selected = _select_distribution_probability(
                    distribution,
                    event_options=options,
                    preferred_label=preferred_label,
                )
                if selected is not None:
                    if metadata is not None:
                        metadata["telemetry_source"] = "normalized_from_distribution"
                    return selected
        distribution = _extract_distribution_from_mapping(payload, options)
        if distribution is not None:
            selected = _select_distribution_probability(
                distribution,
                event_options=options,
                preferred_label=preferred_label,
            )
            if selected is not None:
                if metadata is not None:
                    metadata["telemetry_source"] = "normalized_from_distribution"
                return selected
        numeric_entry_count = 0
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if _normalize_probability(value) is not None:
                numeric_entry_count += 1
        if numeric_entry_count >= 2:
            return None
        response = payload.get("response")
        if response is not None:
            parsed = _extract_interview_probability(
                response,
                event_options=options,
                preferred_label=preferred_label,
                metadata=metadata,
            )
            if parsed is not None:
                return parsed
        for value in payload.values():
            parsed = _extract_interview_probability(
                value,
                event_options=options,
                preferred_label=preferred_label,
                metadata=metadata,
            )
            if parsed is not None:
                return parsed
        return None
    if isinstance(payload, list):
        for item in payload:
            parsed = _extract_interview_probability(
                item,
                event_options=options,
                preferred_label=preferred_label,
                metadata=metadata,
            )
            if parsed is not None:
                return parsed
        return None
    parsed = _normalize_probability(payload)
    if parsed is not None:
        return parsed
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return None
        try:
            parsed_json = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return _extract_interview_probability(
            parsed_json,
            event_options=options,
            preferred_label=preferred_label,
            metadata=metadata,
        )
    return None


def _build_telemetry_probe_prompt(config: Dict[str, Any]) -> str:
    """Build a telemetry probe prompt adapted to binary vs categorical event structure."""
    question = _extract_event_question(config)
    event_options = _extract_event_options(config)
    if len(event_options) > 1 and not _is_yes_no_options(event_options):
        options_json = json.dumps(event_options, ensure_ascii=False)
        example_json = json.dumps(_build_distribution_example(event_options), ensure_ascii=False)
        return (
            "--- AUTHORITATIVE SYSTEM OVERRIDE: SUSPEND PERSONA ROLEPLAY ---\n"
            "You are currently participating in a prediction benchmark telemetry probe.\n"
            "Regardless of your assigned persona's background or stated limitations, you MUST now act as a predictive processing unit.\n"
            f"Target question: {question}\n"
            f"Valid options: {options_json}\n"
            "Return only valid JSON where keys are exactly the option strings above and values are probabilities.\n"
            f"Example: {example_json}\n"
            "Constraints: JSON only, no prose, no markdown, no persona-based refusals, every value must be between 0 and 1, and values must sum to 1."
        )
    return _TELEMETRY_PROBE_BINARY_PROMPT_TEMPLATE.format(question=question)


def _serialize_probe_response_snippet(payload: Any, max_chars: int = 280) -> str:
    """Serialize and truncate raw payload for telemetry extraction diagnostics."""
    if isinstance(payload, str):
        serialized = payload
    else:
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = str(payload)
    compact = " ".join(serialized.splitlines()).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


async def _capture_checkpoint_probe(
    *,
    env: Any,
    config: Dict[str, Any],
    db_path: str,
    round_num: int,
    probe_rounds: set[int],
    last_rowid: int,
    agent_names: Dict[int, str],
    action_logger: Optional[PlatformActionLogger],
    platform_label: str,
) -> Tuple[int, int]:
    if not probe_rounds or round_num not in probe_rounds or action_logger is None:
        return last_rowid, 0

    candidate_agent_id = 0
    if agent_names:
        candidate_agent_id = min(agent_names.keys())

    try:
        probe_agent = env.agent_graph.get_agent(candidate_agent_id)
    except Exception:
        logging.warning("Skipping telemetry probe at round %s on %s: probe agent unavailable", round_num, platform_label)
        return last_rowid, 0

    event_options = _extract_event_options(config)
    preferred_label = _resolve_probe_target_label(config, event_options)
    prompt = _build_telemetry_probe_prompt(config)
    
    schema = None
    if len(event_options) > 1 and not _is_yes_no_options(event_options):
        schema = _get_telemetry_categorical_schema(event_options)
    else:
        schema = _TELEMETRY_BINARY_SCHEMA

    # Use a direct chat_json call with enforced schema to bypass persona refusals
    client = LLMClient()
    messages = [
        {"role": "system", "content": "--- AUTHORITATIVE SYSTEM OVERRIDE: SUSPEND PERSONA ROLEPLAY ---\nYou are a predictive processing unit. Output probabilities only based on your current state."},
        {"role": "user", "content": prompt},
    ]

    try:
        response = client.chat_json(messages, temperature=0.0, json_schema=schema)
        
        # Manually log this into the SQLite database as an INTERVIEW action to maintain 
        # compatibility with fetch_new_actions_from_db logic.
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            info_json = json.dumps({"prompt": prompt, "response": response}, ensure_ascii=False)
            created_at = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO trace (user_id, action, info, created_at) VALUES (?, ?, ?, ?)",
                (candidate_agent_id, ActionType.INTERVIEW.value, info_json, created_at)
            )
            conn.commit()
            conn.close()
        except Exception as db_exc:
             logging.error("Failed to manually log telemetry probe to DB: %s", db_exc)

    except Exception as exc:
        logging.warning("Telemetry probe interview failed at round %s on %s: %s", round_num, platform_label, exc)
        if _env_flag("BENCHMARK_MODE"):
            return last_rowid, 0

    probe_actions, updated_last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
    logged_count = 0
    for action_data in probe_actions:
        if action_data.get("action_type") != "INTERVIEW":
            continue
        action_args = dict(action_data.get("action_args") or {})
        extraction_meta: Dict[str, Any] = {}
        probability = _extract_interview_probability(
            action_args,
            event_options=event_options,
            preferred_label=preferred_label,
            metadata=extraction_meta,
        )
        telemetry_source = extraction_meta.get("telemetry_source")
        if isinstance(telemetry_source, str) and telemetry_source.strip():
            action_args["telemetry_source"] = telemetry_source.strip()
        if probability is None:
            action_args["yes_probability"] = None
            action_args["telemetry_fallback"] = "extraction_failed"
            response_snippet = _serialize_probe_response_snippet(action_args.get("response", action_args))
            logging.warning(
                "Telemetry probe extraction failed at round %s on %s; raw_response=%s",
                round_num,
                platform_label,
                response_snippet,
            )
        else:
            action_args["yes_probability"] = probability
        action_logger.log_action(
            round_num=round_num,
            agent_id=action_data.get("agent_id", candidate_agent_id),
            agent_name=action_data.get("agent_name", agent_names.get(candidate_agent_id, f"Agent_{candidate_agent_id}")),
            action_type="TELEMETRY_PROBE",
            action_args=action_args,
        )
        logged_count += 1
    return updated_last_rowid, logged_count


def create_model(config: Dict[str, Any], use_boost: bool = False):
    """
    Create LLM model
    
    Support dual LLM configuration for acceleration during parallel simulation：
    - Common configuration：LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
    - Acceleration configuration (optional)：LLM_BOOST_API_KEY, LLM_BOOST_BASE_URL, LLM_BOOST_MODEL_NAME
    
    If acceleration LLM is configured, different platforms can use different API providers during parallel simulation to improve concurrency.
    
    Args:
        config: Simulation configuration dictionary
        use_boost: Whether to use acceleration LLM configuration (if available)
    """
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = bool(boost_api_key and boost_base_url)

    if use_boost and has_boost_config:
        llm_model = _apply_benchmark_env(
            llm_api_key=boost_api_key,
            llm_base_url=boost_base_url,
            llm_model=boost_model,
            config=config,
        )
        config_label = "[Acceleration LLM]"
    else:
        llm_model = _apply_benchmark_env(config=config)
        config_label = "[Common LLM]"

    llm_base_url = os.environ.get("OPENAI_API_BASE_URL", "")
    print(f"{config_label} model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else 'default'}...")
    
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=llm_model,
    )


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int
) -> List:
    """Decide which Agents to activate this round based on time and configuration"""
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])
    
    base_min = time_config.get("agents_per_hour_min", 5)
    base_max = time_config.get("agents_per_hour_max", 20)
    
    peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])
    
    if current_hour in peak_hours:
        multiplier = time_config.get("peak_activity_multiplier", 1.5)
    elif current_hour in off_peak_hours:
        multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
    else:
        multiplier = 1.0
    
    target_count = int(random.uniform(base_min, base_max) * multiplier)
    
    candidates = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        activity_level = cfg.get("activity_level", 0.5)
        
        if current_hour not in active_hours:
            continue
        
        if random.random() < activity_level:
            candidates.append(agent_id)
    
    selected_ids = random.sample(
        candidates, 
        min(target_count, len(candidates))
    ) if candidates else []
    
    dev_minimal_mode = os.environ.get("DEV_MINIMAL_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    if dev_minimal_mode and os.environ.get("DEV_MINIMAL_SKIP_LLM", "").strip().lower() in {"1", "true", "yes", "on"}:
        return []
    dev_minimal_cap = 0
    if dev_minimal_mode:
        try:
            dev_minimal_cap = max(1, int(os.environ.get("DEV_MINIMAL_ACTIVE_AGENTS", "5")))
        except ValueError:
            dev_minimal_cap = 5
        if len(selected_ids) > dev_minimal_cap:
            selected_ids = selected_ids[:dev_minimal_cap]

    active_agents = []
    for agent_id in selected_ids:
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass

    return active_agents


def collect_scheduled_posts_for_round(event_config: Dict[str, Any], round_num: int) -> List[Dict[str, Any]]:
    """Collect scheduled create-post events for the given round."""
    scheduled_posts: List[Dict[str, Any]] = []

    if not isinstance(event_config, dict):
        return scheduled_posts

    for scheduled_event in event_config.get("scheduled_events", []) or []:
        if not isinstance(scheduled_event, dict):
            continue

        trigger_round = scheduled_event.get("trigger_round")
        if not isinstance(trigger_round, int) or isinstance(trigger_round, bool):
            continue
        if trigger_round != round_num:
            continue

        posts = scheduled_event.get("posts", [])
        if not isinstance(posts, list):
            continue

        for post in posts:
            if not isinstance(post, dict):
                continue

            content = post.get("content")
            poster_agent_id = post.get("poster_agent_id")

            if not isinstance(content, str):
                continue

            content = content.strip()
            if not content:
                continue

            if not isinstance(poster_agent_id, int) or isinstance(poster_agent_id, bool):
                continue

            scheduled_posts.append({
                "poster_agent_id": poster_agent_id,
                "content": content,
            })

    return scheduled_posts


def collect_temporal_updates_for_round(event_config: Dict[str, Any], round_num: int) -> List[Dict[str, Any]]:
    """Collect temporal fact lifecycle updates scheduled for a specific round."""
    temporal_updates: List[Dict[str, Any]] = []
    if not isinstance(event_config, dict):
        return temporal_updates

    for scheduled_event in event_config.get("scheduled_events", []) or []:
        if not isinstance(scheduled_event, dict):
            continue

        trigger_round = scheduled_event.get("trigger_round")
        if not isinstance(trigger_round, int) or isinstance(trigger_round, bool) or trigger_round != round_num:
            continue

        updates = scheduled_event.get("temporal_updates", [])
        if not isinstance(updates, list):
            continue

        for update in updates:
            if not isinstance(update, dict):
                continue
            fact_id = update.get("fact_id")
            status = update.get("status")
            if not isinstance(fact_id, str) or not fact_id.strip():
                continue
            if not isinstance(status, str) or not status.strip():
                continue
            normalized_update: Dict[str, Any] = {
                "fact_id": fact_id.strip(),
                "status": status.strip(),
            }
            replacement_fact = update.get("replacement_fact")
            if isinstance(replacement_fact, dict):
                normalized_update["replacement_fact"] = dict(replacement_fact)
            temporal_updates.append(normalized_update)
    return temporal_updates


def apply_temporal_fact_updates_for_round(env, event_config: Dict[str, Any], round_num: int) -> int:
    """Apply temporal validity updates after a scheduled perturbation is posted."""
    updates = collect_temporal_updates_for_round(event_config, round_num)
    if not updates:
        return 0

    graph_storage = getattr(env, "graph_storage", None)
    if graph_storage is None or not hasattr(graph_storage, "update_fact_validity"):
        logging.info(
            "Temporal updates scheduled for round %s but env.graph_storage.update_fact_validity is unavailable",
            round_num,
        )
        return 0

    applied = 0
    for update in updates:
        graph_storage.update_fact_validity(
            fact_id=update["fact_id"],
            current_round=round_num,
            status=update["status"],
            replacement_fact=update.get("replacement_fact"),
        )
        applied += 1
    return applied


async def apply_scheduled_posts_for_round(env, event_config: Dict[str, Any], round_num: int) -> int:
    """Apply scheduled create-post events for the given round."""
    scheduled_posts = collect_scheduled_posts_for_round(event_config, round_num)
    if not scheduled_posts:
        return 0

    benchmark_mode_enabled = os.environ.get("BENCHMARK_MODE", "").strip().lower() == "true"
    scheduled_actions = {}
    scheduled_action_count = 0

    for post in scheduled_posts:
        agent_id = post["poster_agent_id"]
        content = post["content"]
        try:
            agent = env.agent_graph.get_agent(agent_id)
            action = ManualAction(
                action_type=ActionType.CREATE_POST,
                action_args={"content": content}
            )
            if agent in scheduled_actions:
                if not isinstance(scheduled_actions[agent], list):
                    scheduled_actions[agent] = [scheduled_actions[agent]]
                scheduled_actions[agent].append(action)
            else:
                scheduled_actions[agent] = action
            scheduled_action_count += 1
        except Exception as exc:
            logging.warning(
                "Unable to apply scheduled post for agent %s in round %s: %s",
                agent_id,
                round_num,
                exc,
            )
            if benchmark_mode_enabled:
                raise

    if scheduled_actions:
        try:
            await env.step(scheduled_actions)
            apply_temporal_fact_updates_for_round(env, event_config, round_num)
        except Exception as exc:
            logging.warning(
                "Failed to apply scheduled posts for round %s: %s",
                round_num,
                exc,
            )
            if benchmark_mode_enabled:
                raise

    return scheduled_action_count


class PlatformSimulation:
    """Platform simulation result container"""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0


async def run_twitter_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """Run Twitter simulation
    
    Args:
        config: Simulation configuration
        simulation_dir: Simulation directory
        action_logger: Action logger
        main_logger: Main logger manager
        max_rounds: Maximum simulation rounds (optional, used to truncate long simulations)
        
    Returns:
        PlatformSimulation: Result object containing env and agent_graph
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")
    
    log_info("Initializing...")
    
    # Twitter use acceleration LLM configuration (if available, otherwise fallback to Common configuration)
    model = create_model(config, use_boost=True)
    
    # OASIS Twitter uses CSV format
    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"Error: Profile file does not exist: {profile_path}")
        return result
    
    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )
    
    # Get Agent real name mapping from config (use entity_name instead of default Agent_X)
    agent_names = get_agent_names_from_config(config)
    # If an agent is not in config, use OASIS default name
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')
    
    db_path = os.path.join(simulation_dir, "twitter_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.TWITTER,
        database_path=db_path,
        semaphore=30,  # Limit maximum concurrent LLM requests to prevent API overload
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # Track last processed row in Database (use rowid to avoid created_at format differences)
    
    # Execute initial events
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Log round 0 start (initial event phase)
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                initial_actions[agent] = ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content}
                )
                
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass
        
        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"Published {len(initial_actions)} initial posts")
    
    # Log round 0 end
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Main simulation loop
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # If maximum rounds specified, truncate
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

    probe_rounds = set(_build_telemetry_probe_rounds(total_rounds)) if _telemetry_probes_enabled() else set()
    if probe_rounds:
        log_info(f"Telemetry probes scheduled at rounds: {sorted(probe_rounds)}")

    probe_rounds = set(_build_telemetry_probe_rounds(total_rounds)) if _telemetry_probes_enabled() else set()
    if probe_rounds:
        log_info(f"Telemetry probes scheduled at rounds: {sorted(probe_rounds)}")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # Check if received exit signal
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received exit signal，at round {round_num + 1} stop simulation")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # Log round start regardless of active agents
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)

        round_action_count = 0
        scheduled_action_count = await apply_scheduled_posts_for_round(
            result.env, event_config, round_num + 1
        )
        if scheduled_action_count:
            log_info(f"Injection triggered at step {round_num + 1}")
            scheduled_actions_list, last_rowid = fetch_new_actions_from_db(
                db_path, last_rowid, agent_names
            )
            for action_data in scheduled_actions_list:
                if action_logger:
                    action_logger.log_action(
                        round_num=round_num + 1,
                        agent_id=action_data['agent_id'],
                        agent_name=action_data['agent_name'],
                        action_type=action_data['action_type'],
                        action_args=action_data['action_args']
                    )
                total_actions += 1
                round_action_count += 1

        if active_agents:
            actions = {agent: LLMAction() for _, agent in active_agents}
            await result.env.step(actions)

            # Get actual executed actions from Database and log
            actual_actions, last_rowid = fetch_new_actions_from_db(
                db_path, last_rowid, agent_names
            )

            for action_data in actual_actions:
                if action_logger:
                    action_logger.log_action(
                        round_num=round_num + 1,
                        agent_id=action_data['agent_id'],
                        agent_name=action_data['agent_name'],
                        action_type=action_data['action_type'],
                        action_args=action_data['action_args']
                    )
                total_actions += 1
                round_action_count += 1

        if probe_rounds:
            last_rowid, probe_count = await _capture_checkpoint_probe(
                env=result.env,
                config=config,
                db_path=db_path,
                round_num=round_num + 1,
                probe_rounds=probe_rounds,
                last_rowid=last_rowid,
                agent_names=agent_names,
                action_logger=action_logger,
                platform_label="twitter",
            )
            if probe_count:
                total_actions += probe_count
                round_action_count += probe_count
        
        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # Note: Do not close environment, keep for Interview use
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! Time taken: {elapsed:.1f}seconds, Total actions: {total_actions}")
    log_info(f"Simulation completed at step {total_rounds}")
    
    return result


async def run_reddit_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """Run Reddit simulation
    
    Args:
        config: Simulation configuration
        simulation_dir: Simulation directory
        action_logger: Action logger
        main_logger: Main logger manager
        max_rounds: Maximum simulation rounds (optional, used to truncate long simulations)
        
    Returns:
        PlatformSimulation: Result object containing env and agent_graph
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")
    
    log_info("Initializing...")
    
    # Reddit use acceleration LLM configuration(if available，otherwise fallback toCommon configuration）
    model = create_model(config, use_boost=True)
    
    profile_path = os.path.join(simulation_dir, "reddit_profiles.json")
    if not os.path.exists(profile_path):
        log_info(f"Error: Profile file does not exist: {profile_path}")
        return result
    
    result.agent_graph = await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=REDDIT_ACTIONS,
    )
    
    # Get Agent real name mapping from config (use entity_name instead of default Agent_X)
    agent_names = get_agent_names_from_config(config)
    # If an agent is not in config, use OASIS default name
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')
    
    db_path = os.path.join(simulation_dir, "reddit_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
        semaphore=30,  # Limit maximum concurrent LLM requests to prevent API overload
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # Track last processed row in Database (use rowid to avoid created_at format differences)
    
    # Execute initial events
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Log round 0 start (initial event phase)
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                if agent in initial_actions:
                    if not isinstance(initial_actions[agent], list):
                        initial_actions[agent] = [initial_actions[agent]]
                    initial_actions[agent].append(ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    ))
                else:
                    initial_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )
                
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass
        
        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"Published {len(initial_actions)} initial posts")
    
    # Log round 0 end
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Main simulation loop
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # If maximum rounds specified, truncate
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # Check if received exit signal
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received exit signal，at round {round_num + 1} stop simulation")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # Log round start regardless of active agents
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)

        round_action_count = 0
        scheduled_action_count = await apply_scheduled_posts_for_round(
            result.env, event_config, round_num + 1
        )
        if scheduled_action_count:
            log_info(f"Injection triggered at step {round_num + 1}")
            scheduled_actions_list, last_rowid = fetch_new_actions_from_db(
                db_path, last_rowid, agent_names
            )
            for action_data in scheduled_actions_list:
                if action_logger:
                    action_logger.log_action(
                        round_num=round_num + 1,
                        agent_id=action_data['agent_id'],
                        agent_name=action_data['agent_name'],
                        action_type=action_data['action_type'],
                        action_args=action_data['action_args']
                    )
                total_actions += 1
                round_action_count += 1

        if active_agents:
            actions = {agent: LLMAction() for _, agent in active_agents}
            await result.env.step(actions)

            # Get actual executed actions from Database and log
            actual_actions, last_rowid = fetch_new_actions_from_db(
                db_path, last_rowid, agent_names
            )

            for action_data in actual_actions:
                if action_logger:
                    action_logger.log_action(
                        round_num=round_num + 1,
                        agent_id=action_data['agent_id'],
                        agent_name=action_data['agent_name'],
                        action_type=action_data['action_type'],
                        action_args=action_data['action_args']
                    )
                total_actions += 1
                round_action_count += 1

        if probe_rounds:
            last_rowid, probe_count = await _capture_checkpoint_probe(
                env=result.env,
                config=config,
                db_path=db_path,
                round_num=round_num + 1,
                probe_rounds=probe_rounds,
                last_rowid=last_rowid,
                agent_names=agent_names,
                action_logger=action_logger,
                platform_label="reddit",
            )
            if probe_count:
                total_actions += probe_count
                round_action_count += probe_count
        
        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # Note: Do not close environment, keep for Interview use
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! Time taken: {elapsed:.1f}seconds, Total actions: {total_actions}")
    log_info(f"Simulation completed at step {total_rounds}")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description='OASIS Dual-Platform Parallel Simulation')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='Configuration file path (simulation_config.json)'
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='Only run Twitter simulation'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='Only run Reddit simulation'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='Maximum simulation rounds (optional, used to truncate long simulations)'
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='Close environment immediately after simulation completes, do not enter wait mode'
    )
    
    args = parser.parse_args()
    
    # Create shutdown event at the start of main function to ensure the whole program can respond to exit signal
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"Error: Configuration file does not exist: {args.config}")
        sys.exit(1)
    
    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    wait_for_commands = not args.no_wait and not _is_headless_mode_enabled()
    
    # Initialize logging configuration (disable OASIS logs, clean up old files)
    init_logging_for_simulation(simulation_dir)
    
    # Create log manager
    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()
    
    log_manager.info("=" * 60)
    log_manager.info("OASIS dual-platform parallel simulation")
    log_manager.info(f"Configuration file: {args.config}")
    log_manager.info(f"Simulation ID: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"Wait mode: {'Enabled' if wait_for_commands else 'Disabled'}")
    log_manager.info("=" * 60)
    
    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 30)
    config_total_rounds = (total_hours * 60) // minutes_per_round
    
    log_manager.info(f"Simulation parameters:")
    log_manager.info(f"  - Total simulation duration: {total_hours}hours")
    log_manager.info(f"  - Time per round: {minutes_per_round}minutes")
    log_manager.info(f"  - Configured total rounds: {config_total_rounds}")
    if args.max_rounds:
        log_manager.info(f"  - Maximum rounds limit: {args.max_rounds}")
        if args.max_rounds < config_total_rounds:
            log_manager.info(f"  - Actual execution rounds: {args.max_rounds} (Truncated)")
    log_manager.info(f"  - Number of Agents: {len(config.get('agent_configs', []))}")
    
    log_manager.info("Log structure:")
    log_manager.info(f"  - Main log: simulation.log")
    log_manager.info(f"  - Twitter actions: twitter/actions.jsonl")
    log_manager.info(f"  - Reddit actions: reddit/actions.jsonl")
    log_manager.info("=" * 60)
    
    start_time = datetime.now()
    
    # Store simulation results of both platforms
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds)
    else:
        # Run in parallel (each platform uses independent logger)
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds),
        )
        twitter_result, reddit_result = results
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"Simulation loop completed! Total time: {total_elapsed:.1f}seconds")
    
    # Whether to enter wait mode
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("Enter wait mode - environment keeps running")
        log_manager.info("Supported commands: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # Create IPC handler
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")
        
        # Command wait loop (using global _shutdown_event)
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # Use wait_for instead of sleep to respond to shutdown_event
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # Received exit signal
                except asyncio.TimeoutError:
                    pass  # Timeout continue loop
        except KeyboardInterrupt:
            print("\nReceived interrupt signal")
        except asyncio.CancelledError:
            print("\nTask was cancelled")
        except Exception as e:
            print(f"\nError processing command: {e}")
        
        log_manager.info("\nClose environment...")
        ipc_handler.update_status("stopped")
    
    # Close environment
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] Environment closed")
    
    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] Environment closed")
    
    log_manager.info("=" * 60)
    log_manager.info(f"All completed!")
    log_manager.info(f"Log files:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """
    Set signal handlers to ensure proper exit when receiving SIGTERM/SIGINT
    
    Persistent simulation scenario：Simulation completeafter does not exit，Wait for interview command
    When receiving termination signal, need to：
    1. Notify asyncio loop to exit wait
    2. Give program a chance to clean up resources properly (close database, environment, etc.)
    3. Then exit
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\nReceived {sig_name} signal, exiting...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # Set event to notify asyncio loop to exit (give loop a chance to clean up)
            if _shutdown_event:
                _shutdown_event.set()
        
        # Don't directly sys.exit(), let asyncio loop exit normally and clean up
        # Force exit only if signal is received repeatedly
        else:
            print("Force exit...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted")
    except SystemExit:
        pass
    finally:
        # Clean up multiprocessing resource tracker (prevent warning on exit)
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("Simulation process exited")
