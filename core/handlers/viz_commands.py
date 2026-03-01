"""
Data Visualization Commands - generate interactive HTML charts from data files.

Commands included:
- /viz <file> - Auto-detect data and generate visualization
- /viz <file> --type <chart_type> - Specify chart type
- /viz <file> --x <col> --y <col> - Specify columns
- /viz <file> --type <chart_type> --x <col> --y <col> - Full specification

Supported chart types: line, bar, scatter, pie
Supported data formats: CSV, JSON
Output: HTML files saved to ./viz_output/ directory
"""

import os
import json
import csv
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from modules.im import MessageContext
from .error_handler import handle_error, format_user_error

logger = logging.getLogger(__name__)

# Try to import plotly, provide helpful error if not available
try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logger.warning("plotly not installed. Visualization commands will not work.")


# Chart type mapping with descriptions
CHART_TYPES = {
    "line": {
        "name": "Line Chart",
        "description": "Show trends over time or ordered categories",
        "icon": "📈",
    },
    "bar": {
        "name": "Bar Chart",
        "description": "Compare values across categories",
        "icon": "📊",
    },
    "scatter": {
        "name": "Scatter Plot",
        "description": "Show relationships between two variables",
        "icon": "🔵",
    },
    "pie": {
        "name": "Pie Chart",
        "description": "Show proportions of a whole",
        "icon": "🥧",
    },
}


class VizCommands:
    """Handles data visualization operations"""

    # Output directory for generated HTML files
    OUTPUT_DIR = "viz_output"

    def __init__(self, controller):
        """Initialize with reference to main controller"""
        self.controller = controller
        self.config = controller.config
        self.im_client = controller.im_client
        self.error_handler = controller.error_handler

    def _get_channel_context(self, context: MessageContext) -> MessageContext:
        """Get context for channel messages (no thread)"""
        if self.config.platform == "slack":
            return MessageContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_id=None,
                platform_specific=context.platform_specific,
            )
        return context

    def _ensure_output_dir(self, base_path: str) -> str:
        """Ensure output directory exists and return absolute path"""
        output_dir = os.path.join(base_path, self.OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def _parse_csv(self, file_path: str) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, str]]:
        """
        Parse CSV file and return columns, data, and column types.

        Returns:
            Tuple of (column_names, row_data, column_types)
            column_types maps column name to 'numeric', 'datetime', or 'string'
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            # Try to detect delimiter
            sample = f.read(1024)
            f.seek(0)

            # Sniff delimiter
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ','

            reader = csv.DictReader(f, delimiter=delimiter)
            columns = reader.fieldnames or []
            rows = list(reader)

            # Detect column types
            column_types = {}
            for col in columns:
                col_type = self._detect_column_type([row.get(col, '') for row in rows if col in row])
                column_types[col] = col_type

            return columns, rows, column_types

    def _parse_json(self, file_path: str) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, str]]:
        """
        Parse JSON file and return columns, data, and column types.

        Supports:
        - Array of objects: [{"col1": 1, "col2": "a"}, ...]
        - Single object: {"col1": [1,2,3], "col2": ["a","b","c"]}

        Returns:
            Tuple of (column_names, row_data, column_types)
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Handle array of objects
        if isinstance(data, list):
            if not data:
                return [], [], {}
            # Get all unique keys
            columns = list(set().union(*[row.keys() for row in data if isinstance(row, dict)]))
            rows = [row for row in data if isinstance(row, dict)]
        # Handle single object with arrays
        elif isinstance(data, dict):
            columns = list(data.keys())
            # Find max length
            max_len = max(len(v) if isinstance(v, list) else 1 for v in data.values())
            # Convert to rows
            rows = []
            for i in range(max_len):
                row = {}
                for col, val in data.items():
                    if isinstance(val, list):
                        row[col] = val[i] if i < len(val) else None
                    else:
                        row[col] = val if i == 0 else None
                rows.append(row)
        else:
            return [], [], {}

        # Detect column types
        column_types = {}
        for col in columns:
            col_type = self._detect_column_type([row.get(col, '') for row in rows if col in row])
            column_types[col] = col_type

        return columns, rows, column_types

    def _detect_column_type(self, values: List[Any]) -> str:
        """Detect if column is numeric, datetime, or string"""
        if not values:
            return 'string'

        # Filter out empty values
        non_empty = [v for v in values if v not in (None, '', 'NA', 'N/A', 'null')]
        if not non_empty:
            return 'string'

        # Check for numeric
        numeric_count = 0
        for v in non_empty[:10]:  # Check first 10 values
            try:
                float(v)
                numeric_count += 1
            except (ValueError, TypeError):
                pass

        if numeric_count == len(non_empty[:10]):
            return 'numeric'

        # Check for datetime
        datetime_count = 0
        for v in non_empty[:10]:
            try:
                # Try parsing as datetime
                if isinstance(v, str):
                    datetime.fromisoformat(v.replace('Z', '+00:00'))
                    datetime_count += 1
            except Exception:
                pass

        if datetime_count >= len(non_empty[:10]) * 0.7:  # 70% match
            return 'datetime'

        return 'string'

    def _auto_select_columns(
        self,
        columns: List[str],
        column_types: Dict[str, str],
        chart_type: str,
        rows: List[Dict]
    ) -> Tuple[Optional[str], Optional[List[str]]]:
        """
        Auto-select x and y columns based on data types and chart type.

        Returns:
            Tuple of (x_column, y_columns_list)
        """
        numeric_cols = [c for c in columns if column_types.get(c) == 'numeric']
        datetime_cols = [c for c in columns if column_types.get(c) == 'datetime']
        string_cols = [c for c in columns if column_types.get(c) == 'string']

        # For pie chart, need one string (labels) and one numeric (values)
        if chart_type == 'pie':
            if string_cols and numeric_cols:
                return string_cols[0], [numeric_cols[0]]
            return None, None

        # For line chart, prefer datetime x and numeric y
        if chart_type == 'line':
            if datetime_cols and numeric_cols:
                return datetime_cols[0], numeric_cols[:3]  # Up to 3 series
            elif string_cols and numeric_cols:
                return string_cols[0], numeric_cols[:3]
            elif len(numeric_cols) >= 2:
                return numeric_cols[0], numeric_cols[1:3]
            return None, None

        # For bar chart, prefer string x and numeric y
        if chart_type == 'bar':
            if string_cols and numeric_cols:
                return string_cols[0], [numeric_cols[0]]
            elif numeric_cols:
                return numeric_cols[0], [numeric_cols[1]] if len(numeric_cols) > 1 else None
            return None, None

        # For scatter chart, need two numeric columns
        if chart_type == 'scatter':
            if len(numeric_cols) >= 2:
                return numeric_cols[0], [numeric_cols[1]]
            return None, None

        return None, None

    def _generate_html(
        self,
        fig,
        title: str,
        file_info: Dict[str, Any],
        chart_type: str
    ) -> str:
        """Generate complete HTML with embedded plotly chart"""
        # Get plotly HTML
        plot_html = fig.to_html(include_plotlyjs='cdn', full_html=False)

        # Create styled HTML wrapper
        html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 2em;
            margin-bottom: 10px;
        }}
        .header .subtitle {{
            opacity: 0.9;
            font-size: 0.9em;
        }}
        .chart-container {{
            padding: 30px;
        }}
        .info {{
            background: #f8f9fa;
            padding: 20px 30px;
            border-top: 1px solid #e9ecef;
        }}
        .info h3 {{
            color: #495057;
            margin-bottom: 10px;
            font-size: 1.1em;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .info-item {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .info-item label {{
            display: block;
            font-size: 0.8em;
            color: #6c757d;
            margin-bottom: 5px;
        }}
        .info-item value {{
            font-weight: 600;
            color: #212529;
        }}
        .footer {{
            background: #343a40;
            color: #dee2e6;
            padding: 20px 30px;
            text-align: center;
            font-size: 0.9em;
        }}
        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}
        .deploy-section {{
            background: #e7f5ff;
            border: 2px dashed #339af0;
            border-radius: 8px;
            padding: 20px;
            margin-top: 15px;
        }}
        .deploy-section h4 {{
            color: #1971c2;
            margin-bottom: 10px;
        }}
        .deploy-section code {{
            background: #f1f3f5;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Monaco', 'Consolas', monospace;
        }}
        .deploy-section pre {{
            background: #f1f3f5;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            margin-top: 10px;
        }}
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.5em;
            }}
            .chart-container, .info {{
                padding: 15px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="subtitle">Generated by Vibe Remote</div>
        </div>
        <div class="chart-container">
            {plot_html}
        </div>
        <div class="info">
            <h3>Chart Information</h3>
            <div class="info-grid">
                <div class="info-item">
                    <label>Chart Type</label>
                    <value>{chart_type_name}</value>
                </div>
                <div class="info-item">
                    <label>Data Source</label>
                    <value>{file_name}</value>
                </div>
                <div class="info-item">
                    <label>Rows</label>
                    <value>{row_count}</value>
                </div>
                <div class="info-item">
                    <label>Generated</label>
                    <value>{timestamp}</value>
                </div>
            </div>
            <div class="deploy-section">
                <h4>Deploy to Cloudflare Pages</h4>
                <p>To publish this visualization, deploy this folder to Cloudflare Pages:</p>
                <pre>cd {output_dir}
npx wrangler pages deploy . --project-name my-viz</pre>
            </div>
        </div>
        <div class="footer">
            <p>Generated with <a href="https://github.com/anthropics/claude-code">Vibe Remote</a></p>
        </div>
    </div>
</body>
</html>"""

        return html_template.format(
            title=title,
            plot_html=plot_html,
            chart_type_name=CHART_TYPES.get(chart_type, {}).get('name', chart_type.title()),
            file_name=file_info.get('name', 'Unknown'),
            row_count=file_info.get('rows', 0),
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            output_dir=self.OUTPUT_DIR,
        )

    def _create_chart(
        self,
        chart_type: str,
        rows: List[Dict],
        x_col: str,
        y_cols: List[str],
        title: str
    ):
        """Create plotly figure based on chart type"""
        # Extract data
        x_values = [row.get(x_col, '') for row in rows]

        if chart_type == 'line':
            fig = go.Figure()
            for y_col in y_cols:
                y_values = []
                for row in rows:
                    try:
                        y_values.append(float(row.get(y_col, 0)))
                    except (ValueError, TypeError):
                        y_values.append(0)
                fig.add_trace(go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode='lines+markers',
                    name=y_col,
                    line=dict(width=2),
                    marker=dict(size=6)
                ))

        elif chart_type == 'bar':
            fig = go.Figure()
            y_col = y_cols[0] if y_cols else x_col
            y_values = []
            for row in rows:
                try:
                    y_values.append(float(row.get(y_col, 0)))
                except (ValueError, TypeError):
                    y_values.append(0)

            # Use x_values as labels if x_col is different from y_col
            if x_col != y_col:
                fig.add_trace(go.Bar(
                    x=x_values,
                    y=y_values,
                    name=y_col,
                    marker=dict(color='#667eea')
                ))
            else:
                fig.add_trace(go.Bar(
                    x=list(range(len(y_values))),
                    y=y_values,
                    name=y_col,
                    marker=dict(color='#667eea')
                ))

        elif chart_type == 'scatter':
            y_col = y_cols[0] if y_cols else x_col
            y_values = []
            x_numeric = []
            for row in rows:
                try:
                    x_numeric.append(float(row.get(x_col, 0)))
                except (ValueError, TypeError):
                    x_numeric.append(0)
                try:
                    y_values.append(float(row.get(y_col, 0)))
                except (ValueError, TypeError):
                    y_values.append(0)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_numeric,
                y=y_values,
                mode='markers',
                name=f'{x_col} vs {y_col}',
                marker=dict(
                    size=10,
                    color='#667eea',
                    opacity=0.7
                )
            ))

        elif chart_type == 'pie':
            y_col = y_cols[0] if y_cols else x_col
            y_values = []
            for row in rows:
                try:
                    y_values.append(float(row.get(y_col, 0)))
                except (ValueError, TypeError):
                    y_values.append(0)

            fig = go.Figure()
            fig.add_trace(go.Pie(
                labels=x_values,
                values=y_values,
                hole=0.3,
                textinfo='label+percent'
            ))

        else:
            # Default to line chart
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_values,
                y=y_values if y_cols else list(range(len(x_values))),
                mode='lines+markers',
            ))

        # Update layout
        fig.update_layout(
            title=dict(
                text=title,
                x=0.5,
                xanchor='center',
                font=dict(size=20)
            ),
            hovermode='x unified',
            template='plotly_white',
            margin=dict(l=40, r=40, t=60, b=40),
        )

        # Update axes based on chart type
        if chart_type in ['line', 'scatter', 'bar']:
            fig.update_xaxes(title_text=x_col)
            if y_cols and chart_type != 'bar':
                fig.update_yaxes(title_text=', '.join(y_cols))
            elif y_cols:
                fig.update_yaxes(title_text=y_cols[0])

        return fig

    def _parse_viz_args(self, args: str) -> Dict[str, Any]:
        """
        Parse visualization command arguments.

        Supports:
        - <file>
        - <file> --type <chart_type>
        - <file> --x <col> --y <col>
        - <file> --type <chart_type> --x <col> --y <col>

        Returns:
            Dict with 'file', 'type', 'x', 'y' keys
        """
        parts = args.strip().split()
        if not parts:
            return {}

        result = {'file': parts[0], 'type': None, 'x': None, 'y': []}

        i = 1
        while i < len(parts):
            if parts[i] == '--type' and i + 1 < len(parts):
                result['type'] = parts[i + 1].lower()
                i += 2
            elif parts[i] == '--x' and i + 1 < len(parts):
                result['x'] = parts[i + 1]
                i += 2
            elif parts[i] == '--y' and i + 1 < len(parts):
                result['y'].append(parts[i + 1])
                i += 2
            else:
                i += 1

        return result

    async def handle_viz(self, context: MessageContext, args: str = ""):
        """Handle /viz command - generate data visualization"""
        try:
            formatter = self.im_client.formatter

            # Check if plotly is available
            if not PLOTLY_AVAILABLE:
                error_msg = format_user_error(
                    "Plotly is not installed. Install it with: pip install plotly",
                    formatter
                )
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Parse arguments
            parsed = self._parse_viz_args(args)
            if not parsed.get('file'):
                lines = [
                    formatter.format_bold("Usage:"),
                    formatter.format_code_inline("/viz <file>"),
                    "",
                    formatter.format_bold("Options:"),
                    formatter.format_text("--type <chart_type> - line, bar, scatter, pie"),
                    formatter.format_text("--x <column> - X axis column"),
                    formatter.format_text("--y <column> - Y axis column (can use multiple times)"),
                    "",
                    formatter.format_bold("Examples:"),
                    formatter.format_code_inline("/viz data.csv"),
                    formatter.format_code_inline("/viz data.csv --type line"),
                    formatter.format_code_inline("/viz data.csv --type bar --x category --y value"),
                ]
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, formatter.format_message(*lines)
                )
                return

            # Get file path
            file_arg = parsed['file']
            cwd = self.controller.get_cwd(context)

            # Expand path
            expanded = os.path.expanduser(file_arg)
            if not os.path.isabs(expanded):
                file_path = os.path.join(cwd, expanded)
            else:
                file_path = expanded

            file_path = os.path.abspath(file_path)

            # Check if file exists
            if not os.path.exists(file_path):
                error_msg = self.error_handler.handle_path_error(
                    file_path, "read data file", formatter
                )
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Get file extension
            file_ext = Path(file_path).suffix.lower()
            file_name = Path(file_path).name

            # Parse data based on file type
            try:
                if file_ext == '.csv':
                    columns, rows, column_types = self._parse_csv(file_path)
                elif file_ext == '.json':
                    columns, rows, column_types = self._parse_json(file_path)
                else:
                    # Try CSV first, then JSON
                    try:
                        columns, rows, column_types = self._parse_csv(file_path)
                    except Exception:
                        columns, rows, column_types = self._parse_json(file_path)

                if not rows:
                    error_msg = format_user_error(
                        f"No data found in {file_name}. Ensure the file has valid data.",
                        formatter
                    )
                    channel_context = self._get_channel_context(context)
                    await self.im_client.send_message(channel_context, error_msg)
                    return

            except Exception as e:
                error_msg = handle_error(e, formatter, f"Parsing {file_name}")
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Determine chart type
            chart_type = parsed.get('type')
            if not chart_type:
                # Auto-detect best chart type
                if self._detect_column_type([row.get(columns[0], '') for row in rows if columns[0] in row]) == 'datetime':
                    chart_type = 'line'
                elif len(columns) == 2 and self._detect_column_type([row.get(columns[1], '') for row in rows if len(columns) > 1 and columns[1] in row]) == 'numeric':
                    chart_type = 'pie' if len(rows) < 20 else 'bar'
                else:
                    chart_type = 'bar'

            # Validate chart type
            if chart_type not in CHART_TYPES:
                valid_types = ', '.join(CHART_TYPES.keys())
                error_msg = format_user_error(
                    f"Invalid chart type '{chart_type}'. Valid types: {valid_types}",
                    formatter
                )
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Determine columns
            x_col = parsed.get('x')
            y_cols = parsed.get('y', [])

            if not x_col or not y_cols:
                auto_x, auto_y = self._auto_select_columns(columns, column_types, chart_type, rows)
                if not x_col:
                    x_col = auto_x
                if not y_cols:
                    y_cols = auto_y or []

            # Validate columns
            if x_col and x_col not in columns:
                error_msg = format_user_error(
                    f"Column '{x_col}' not found in data. Available columns: {', '.join(columns)}",
                    formatter
                )
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            for y_col in y_cols:
                if y_col not in columns:
                    error_msg = format_user_error(
                        f"Column '{y_col}' not found in data. Available columns: {', '.join(columns)}",
                        formatter
                    )
                    channel_context = self._get_channel_context(context)
                    await self.im_client.send_message(channel_context, error_msg)
                    return

            # If still no columns selected, use first available
            if not x_col and columns:
                x_col = columns[0]
            if not y_cols and len(columns) > 1:
                y_cols = [columns[1]]
            elif not y_cols and columns:
                y_cols = [columns[0]]

            # Create chart
            chart_info = CHART_TYPES.get(chart_type, {})
            title = f"{chart_info.get('icon', '')} {chart_info.get('name', chart_type.title())} - {file_name}"

            try:
                fig = self._create_chart(chart_type, rows, x_col, y_cols, title)
            except Exception as e:
                error_msg = handle_error(e, formatter, "Creating chart")
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Generate output filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = Path(file_path).stem
            output_filename = f"{base_name}_{chart_type}_{timestamp}.html"

            # Ensure output directory exists
            output_dir = self._ensure_output_dir(cwd)
            output_path = os.path.join(output_dir, output_filename)

            # Generate and save HTML
            try:
                html_content = self._generate_html(
                    fig,
                    title,
                    {'name': file_name, 'rows': len(rows)},
                    chart_type
                )
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
            except Exception as e:
                error_msg = handle_error(e, formatter, "Saving HTML")
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Send success message
            chart_emoji = chart_info.get('icon', '📊')
            lines = [
                f"{chart_emoji} {formatter.format_bold('Visualization Generated')}",
                "",
                f"{formatter.format_bold('Chart Type')}: {chart_info.get('name', chart_type)}",
                f"{formatter.format_bold('Data File')}: {formatter.format_code_inline(file_name)}",
                f"{formatter.format_bold('Rows')}: {formatter.format_code_inline(str(len(rows)))}",
                f"{formatter.format_bold('X Axis')}: {formatter.format_code_inline(x_col)}",
                f"{formatter.format_bold('Y Axis')}: {formatter.format_code_inline(', '.join(y_cols))}",
                "",
                f"{formatter.format_bold('Output')}: {formatter.format_code_inline(output_path)}",
                "",
                formatter.format_text("Open the HTML file in your browser to view the interactive chart."),
                formatter.format_text("To deploy to Cloudflare Pages, see instructions in the HTML file."),
            ]

            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, formatter.format_message(*lines)
            )

            logger.info(f"Generated visualization: {output_path}")

        except Exception as e:
            logger.error(f"Error in handle_viz: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = handle_error(e, self.im_client.formatter, "Generating visualization")
            await self.im_client.send_message(channel_context, error_msg)
