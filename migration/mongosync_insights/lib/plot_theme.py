"""
Shared Plotly styling for Mongosync Insights.
Mirrors design tokens from templates/_theme_vars.html.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import plotly.graph_objects as go
import plotly.io as pio

FONT_FAMILY = "Euclid Circular A, Helvetica Neue, Helvetica, Arial, sans-serif"

COLORWAY = [
    "#00684A",
    "#016BF8",
    "#00A35C",
    "#0498EC",
    "#FFC010",
    "#DB3030",
    "#889397",
    "#00ED64",
]

THEME_LIGHT = {
    "paper_bgcolor": "#FFFFFF",
    "plot_bgcolor": "#F9FBFA",
    "text": "#1F2937",
    "text_secondary": "#415058",
    "grid": "rgba(0, 30, 43, 0.08)",
    "line": "rgba(0, 30, 43, 0.15)",
    "accent": "#016BF8",
    "section_text": "#1A3C4A",
    "section_bg": "rgba(1, 107, 248, 0.12)",
    "section_border": "#016BF8",
    "table_header_fill": "#00684A",
    "table_header_color": "#FFFFFF",
    "table_cell_fill": "#F9FBFA",
    "table_cell_color": "#1F2937",
    "legend_bg": "rgba(255, 255, 255, 0.92)",
    "legend_border": "#D9E0E3",
}

THEME_DARK = {
    "paper_bgcolor": "#132C37",
    "plot_bgcolor": "#1A3642",
    "text": "#F9FBFA",
    "text_secondary": "#C1C7C6",
    "grid": "rgba(255, 255, 255, 0.08)",
    "line": "rgba(255, 255, 255, 0.12)",
    "accent": "#0498EC",
    "section_text": "#F9FBFA",
    "section_bg": "rgba(4, 152, 236, 0.18)",
    "section_border": "#0498EC",
    "table_header_fill": "#00593F",
    "table_header_color": "#F9FBFA",
    "table_cell_fill": "#1A3642",
    "table_cell_color": "#F9FBFA",
    "legend_bg": "rgba(19, 44, 55, 0.92)",
    "legend_border": "#36505B",
}


def theme_tokens(*, dark: bool = False) -> Dict[str, str]:
    """Return color/style tokens for the requested theme."""
    return THEME_DARK if dark else THEME_LIGHT


def section_label_style(*, dark: bool = False) -> Dict[str, Any]:
    """Annotation kwargs for section group labels."""
    tokens = theme_tokens(dark=dark)
    return dict(
        showarrow=False,
        font=dict(size=11, color=tokens["section_text"]),
        bgcolor=tokens["section_bg"],
        bordercolor=tokens["section_border"],
        borderwidth=1,
        borderpad=4,
    )


def no_data_text_style(*, dark: bool = False) -> Dict[str, Any]:
    """Textfont kwargs for NO DATA placeholders."""
    tokens = theme_tokens(dark=dark)
    return dict(size=30, color=tokens["text_secondary"])


def register_mi_template() -> None:
    """Register a reusable Plotly template (light baseline)."""
    tokens = theme_tokens(dark=False)
    pio.templates["mongodb_insights"] = go.layout.Template(
        layout=dict(
            colorway=COLORWAY,
            font=dict(family=FONT_FAMILY, size=12, color=tokens["text"]),
            paper_bgcolor=tokens["paper_bgcolor"],
            plot_bgcolor=tokens["plot_bgcolor"],
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor=tokens["paper_bgcolor"],
                font_size=12,
                font_color=tokens["text"],
                bordercolor=tokens["line"],
            ),
            margin=dict(l=48, r=24, t=56, b=40),
            xaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor=tokens["grid"],
                zeroline=False,
                linecolor=tokens["line"],
                tickfont=dict(color=tokens["text_secondary"]),
                title=dict(font=dict(color=tokens["text"])),
            ),
            yaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor=tokens["grid"],
                zeroline=False,
                linecolor=tokens["line"],
                tickfont=dict(color=tokens["text_secondary"]),
                title=dict(font=dict(color=tokens["text"])),
            ),
        )
    )


def apply_mi_theme(
    fig,
    *,
    title: Optional[str] = None,
    height: Optional[int] = None,
    width: Optional[int] = None,
    showlegend: bool = False,
    dark: bool = False,
    **layout_overrides: Any,
) -> None:
    """
    Apply Mongosync Insights styling to a Plotly figure.
    Call after all traces and annotations are added.
    """
    tokens = theme_tokens(dark=dark)

    layout: Dict[str, Any] = dict(
        font=dict(family=FONT_FAMILY, size=12, color=tokens["text"]),
        colorway=COLORWAY,
        paper_bgcolor=tokens["paper_bgcolor"],
        plot_bgcolor=tokens["plot_bgcolor"],
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=tokens["paper_bgcolor"],
            font_size=12,
            font_color=tokens["text"],
            bordercolor=tokens["line"],
        ),
        showlegend=showlegend,
    )

    if title is not None:
        layout["title"] = dict(
            text=title,
            font=dict(size=16, color=tokens["text"]),
            x=0.02,
            xanchor="left",
        )

    if height is not None:
        layout["height"] = height
    if width is not None:
        layout["width"] = width

    layout.update(layout_overrides)
    fig.update_layout(**layout)

    for key in fig.layout:
        if not (key.startswith("xaxis") or key.startswith("yaxis")):
            continue
        axis = fig.layout[key]
        if getattr(axis, "visible", None) is False:
            continue

        axis_updates: Dict[str, Any] = {}
        if getattr(axis, "showgrid", None) is not False:
            axis_updates.update(
                showgrid=True,
                gridwidth=1,
                gridcolor=tokens["grid"],
            )
        if getattr(axis, "zeroline", None) is not False:
            axis_updates["zeroline"] = False
        if getattr(axis, "showticklabels", None) is not False or axis_updates:
            axis_updates.update(
                linecolor=tokens["line"],
                tickfont=dict(color=tokens["text_secondary"]),
            )
        if axis_updates:
            axis.update(axis_updates)
        if getattr(axis, "title", None) is not None:
            title_font = {}
            if getattr(axis.title, "font", None) is not None:
                title_font = (
                    axis.title.font.to_plotly_json()
                    if hasattr(axis.title.font, "to_plotly_json")
                    else dict(axis.title.font)
                )
            title_font["color"] = tokens["text"]
            axis.title.font = title_font

    fig.update_traces(
        selector=dict(type="scatter"),
        line=dict(width=2),
    )
    fig.update_traces(
        selector=dict(type="scattergl"),
        line=dict(width=2),
    )
    fig.update_traces(
        selector=dict(type="bar"),
        marker=dict(line=dict(width=0)),
    )

    fig.update_traces(
        selector=dict(type="table"),
        header=dict(
            fill_color=tokens["table_header_fill"],
            font=dict(color=tokens["table_header_color"], size=12),
            line=dict(color=tokens["line"], width=1),
        ),
        cells=dict(
            fill_color=tokens["table_cell_fill"],
            font=dict(color=tokens["table_cell_color"], size=11),
            line=dict(color=tokens["line"], width=1),
        ),
    )

    # Refresh section-label annotations if present (server-side light default).
    for annotation in fig.layout.annotations or []:
        if getattr(annotation, "bordercolor", None) in (
            THEME_LIGHT["section_border"],
            THEME_DARK["section_border"],
            "#016BF8",
            "#0498EC",
        ):
            annotation.font.color = tokens["section_text"]
            annotation.bgcolor = tokens["section_bg"]
            annotation.bordercolor = tokens["section_border"]

    # Normalize NO DATA placeholder text color.
    for trace in fig.data:
        if getattr(trace, "mode", None) == "text" and getattr(trace, "textfont", None):
            text = trace.text
            if text == "NO DATA" or text == ["NO DATA"] or (
                isinstance(text, (list, tuple)) and text and text[0] == "NO DATA"
            ):
                trace.textfont.color = tokens["text_secondary"]
