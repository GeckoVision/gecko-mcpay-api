"""Make the skill root importable so tests can `import voices...` and
`import bot_state` exactly as the bot does at runtime (cwd-relative)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
