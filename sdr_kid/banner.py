from pyfiglet import Figlet
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


TAGLINES = [
    "Radio waves are magic you can measure.",
    "Every antenna is a telescope for invisible light.",
    "The sky is loud — you just needed the right ears.",
    "Engineers turn 'I wonder' into 'I built it'.",
]


def render_banner(console: Console) -> None:
    fig = Figlet(font="slant")
    title = fig.renderText("SDR  Kid")
    text = Text(title, style="bold cyan")
    tag = Text(TAGLINES[0], style="italic magenta")
    inside = Text.assemble(text, "\n", Align.center(tag).renderable)
    panel = Panel(
        Align.center(inside),
        border_style="bright_blue",
        title="[bold yellow]a Software Defined Radio playground[/]",
        subtitle="[dim]press Ctrl+C anytime to stop a mode[/]",
    )
    console.print(panel)
